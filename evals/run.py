"""Coleta evidência para revisão humana; não emite vereditos semânticos."""

import argparse
import asyncio
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.agent.contracts import ConversationTurn, Interpretation
from app.agent.prompts import INTERPRET_INSTRUCTIONS
from app.ai.llm import interpret
from app.config import Settings
from app.providers import ProviderFailure

ROOT = Path(__file__).resolve().parent


def load_cases(split: str, case_ids: Sequence[str] = ()) -> list[dict[str, Any]]:
    filename = "cases.jsonl" if split == "regression" else "heldout.jsonl"
    cases = [
        json.loads(line) for line in (ROOT / filename).read_text(encoding="utf-8").splitlines()
    ]
    return [case for case in cases if not case_ids or case["id"] in case_ids]


async def collect(
    settings: Settings,
    cases: Sequence[dict[str, Any]],
    *,
    repetitions: int = 4,
) -> list[dict[str, Any]]:
    """O chamador precisa autorizar inferência paga antes de chamar esta função."""
    if not 1 <= repetitions <= 8:
        raise ValueError("Use entre uma e oito repetições")
    fixture = json.loads((ROOT / "fixtures.json").read_text(encoding="utf-8"))
    prompt_hash = hashlib.sha256(
        (
            INTERPRET_INSTRUCTIONS + json.dumps(Interpretation.model_json_schema(), sort_keys=True)
        ).encode()
    ).hexdigest()
    evidence: list[dict[str, Any]] = []
    for case in cases:
        if case.get("fictional") is not True:
            raise ValueError("Somente fixtures fictícias são aceitas neste coletor")
        context = {**fixture, **case.get("context_override", {})}
        history = [ConversationTurn.model_validate(turn) for turn in case.get("history", [])]
        input_hash = hashlib.sha256(
            json.dumps(
                {
                    "text": case["text"],
                    "context": context,
                    "history": case.get("history", []),
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        for attempt in range(1, repetitions + 1):
            row: dict[str, Any] = {
                "case_id": case["id"],
                "pool": case["pool"],
                "attempt": attempt,
                "model": settings.openai_model,
                "fictional": True,
                "prompt_hash": prompt_hash,
                "input_hash": input_hash,
                "at": datetime.now(UTC).isoformat(),
                "semantic_status": "awaiting_human_review",
            }
            try:
                result = await interpret(settings, case["text"], context, history=history)
                row.update(
                    {
                        "output": result.model_dump(),
                        "operations": result.to_operations(),
                        "usage": result.usage.model_dump() if result.usage else None,
                        "schema_valid": True,
                    }
                )
            except ProviderFailure as exc:
                row.update({"error": exc.reason, "status_code": exc.status_code})
            evidence.append(row)
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Autoriza chamadas pagas")
    parser.add_argument("--split", choices=["regression", "capability"], default="regression")
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--repetitions", type=int, default=4)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cases = load_cases(args.split, args.case_id)
    if not args.live:
        print(json.dumps({"live": False, "cases": len(cases), "provider_calls": 0}))
        return
    if args.output is None:
        parser.error("--live exige --output para registrar evidência")
    if not cases:
        parser.error("Nenhum caso selecionado")
    evidence = asyncio.run(collect(Settings(), cases, repetitions=args.repetitions))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in evidence),
        encoding="utf-8",
    )
    print(json.dumps({"cases": len(cases), "attempts": len(evidence), "review": "pending"}))


if __name__ == "__main__":
    main()
