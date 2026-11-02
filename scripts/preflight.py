"""Testes reais só com --live; saída contém apenas metadados seguros."""

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.ai.llm import probe_openai
from app.audio.elevenlabs import probe_elevenlabs
from app.config import PROJECT_ROOT, Settings


async def run(audio_path: Path | None) -> int:
    settings = Settings()
    openai_result = await probe_openai(settings)
    results = [openai_result]
    if audio_path is not None:
        async with httpx.AsyncClient(follow_redirects=False) as client:
            results.append(await probe_elevenlabs(settings, audio_path.read_bytes(), client=client))
    receipt = {
        "tested_at": datetime.now(UTC).isoformat(),
        "openai_model": settings.openai_model,
        "elevenlabs_stt_model": settings.elevenlabs_stt_model,
        "audio_test_performed": audio_path is not None,
        "results": [asdict(result) for result in results],
    }
    destination = PROJECT_ROOT / "data" / "sandbox" / "providers-preflight.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    history = destination.with_suffix(".jsonl")
    with history.open("a", encoding="utf-8") as log:
        log.write(json.dumps(receipt) + "\n")
    destination.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0 if all(result.ok for result in results) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Valida APIs sem expor credenciais.")
    parser.add_argument("--live", action="store_true", help="Autoriza chamadas reais de teste.")
    parser.add_argument(
        "--audio", type=Path, help="Amostra sintética para STT, sem dados pessoais."
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("Use --live somente quando houver autorização para testes reais.")
    if args.audio is not None and not args.audio.is_file():
        parser.error("Arquivo de áudio não encontrado.")
    try:
        code = asyncio.run(run(args.audio))
    except Exception:
        # Nunca incluir traceback/str(exc), pois erros de SDK podem carregar inputs.
        print("Preflight não concluído: erro local inesperado; nenhuma credencial foi exibida.")
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
