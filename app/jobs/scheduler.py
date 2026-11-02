"""Persisted schedules with one catch-up notice, owner binding and dedupe keys."""

from __future__ import annotations

import calendar
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.analytics import compute
from app.domain import DomainError, FinanceService
from app.formatting import format_money
from app.jobs.store import DurableStore
from app.observability import event


def next_run(
    previous: str,
    frequency: str,
    interval: int,
    timezone: str,
    now: datetime,
    anchor_day: int | None = None,
) -> str:
    if not 1 <= interval <= 365:
        raise ValueError("Intervalo inválido.")
    current = datetime.fromisoformat(previous)
    if current.tzinfo is None or now.tzinfo is None:
        raise ValueError("Horário exige fuso explícito.")
    local = current.astimezone(ZoneInfo(timezone))
    original_day = anchor_day or local.day
    for _ in range(10000):
        if frequency in {"day", "week"}:
            local += timedelta(days=interval * (7 if frequency == "week" else 1))
        elif frequency in {"month", "year"}:
            count = (
                local.year * 12 + local.month - 1 + interval * (12 if frequency == "year" else 1)
            )
            year, month = divmod(count, 12)
            month += 1
            local = local.replace(
                year=year, month=month, day=min(original_day, calendar.monthrange(year, month)[1])
            )
        else:
            raise ValueError("Periodicidade desconhecida.")
        if local > now:
            return local.astimezone(UTC).isoformat()
    raise ValueError("Rotina antiga demais; ajuste o próximo horário.")


class Scheduler:
    def __init__(self, service: FinanceService, store: DurableStore) -> None:
        self.service = service
        self.store = store

    def tick(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        snapshot = self.service.snapshot()
        if snapshot.get("operations", {}).get("schedules"):
            return 0
        enqueued = 0
        for schedule in self.store.due_schedules(now.isoformat()):
            if (
                schedule["owner_id"] != self.service.owner_id
                or schedule["workspace_id"] != snapshot["workspace_id"]
            ):
                continue
            kind = schedule.get("kind", "summary")
            if kind not in {"summary", "budget", "reminder", "subscription"}:
                continue
            payload: dict[str, Any] = {
                "kind": kind,
                "owner_id": self.service.owner_id,
                "workspace_id": snapshot["workspace_id"],
                "schedule_id": schedule["id"],
                "scheduled_at": schedule["next_run"],
                "name": schedule.get("name", "Rotina"),
            }
            self.store.enqueue(
                "scheduled_report",
                payload,
                dedupe_key=f"schedule:{schedule['id']}:{schedule['next_run']}",
                workspace_id=snapshot["workspace_id"],
            )
            following = next_run(
                schedule["next_run"],
                schedule.get("frequency", "month"),
                schedule.get("interval", 1),
                schedule.get("timezone", snapshot["timezone"]),
                now,
                anchor_day=schedule.get("anchor_day"),
            )
            self.store.advance_schedule(schedule["id"], schedule["next_run"], following)
            enqueued += 1
        if not snapshot.get("operations", {}).get("mutations"):
            today = now.astimezone(ZoneInfo(snapshot["timezone"])).date().isoformat()
            due = [
                row
                for row in snapshot.get("recurrences", [])
                if row.get("active", True)
                and not row.get("paused")
                and row.get("next_date", "9999") <= today
            ]
            if due:
                fingerprint = ":".join(sorted(row["id"] + row["next_date"] for row in due))
                from hashlib import sha256

                key = "recurrences:" + sha256(fingerprint.encode()).hexdigest()
                try:
                    self.service.execute(
                        "generate_recurrences", {"through_date": today}, idempotency_key=key
                    )
                except DomainError as exc:
                    event("recurrence", "failed", reason=exc.code)
                    self.store.enqueue(
                        "scheduled_notice",
                        {
                            "owner_id": self.service.owner_id,
                            "workspace_id": snapshot["workspace_id"],
                            "text": "Uma recorrência não foi lançada: " + str(exc),
                        },
                        dedupe_key="recurrence-error:" + key,
                        workspace_id=snapshot["workspace_id"],
                    )
        refreshed = self.service.snapshot()
        budget_day = now.astimezone(ZoneInfo(refreshed["timezone"])).date()
        budgets = {row["id"]: row for row in refreshed.get("budgets", [])}
        for budget in compute(
            refreshed,
            {
                "start_date": budget_day.isoformat(),
                "end_date": (budget_day + timedelta(days=1)).isoformat(),
            },
        )["budgets"]:
            if budget["no_limit"] or (budget["zero_limit"] and budget["budget_actual_minor"] == 0):
                continue
            for threshold in budget["thresholds_reached"]:
                definition = budgets[budget["id"]]
                key = (
                    f"budget-alert:{budget['id']}:{definition.get('revision', 0)}:"
                    f"{budget['start_date']}:{threshold}"
                )
                self.store.enqueue(
                    "scheduled_notice",
                    {
                        "owner_id": self.service.owner_id,
                        "workspace_id": refreshed["workspace_id"],
                        "text": (
                            "Alerta de orçamento: "
                            + budget["name"]
                            + "\nGasto no período: "
                            + format_money(budget["budget_actual_minor"], budget["currency"])
                            + "\nLimite: "
                            + format_money(budget["limit_minor"], budget["currency"])
                            + "\nPeríodo: "
                            + budget["start_date"]
                            + " até "
                            + budget["end_date"]
                            + " (fim exclusivo)."
                        ),
                    },
                    dedupe_key=key,
                    workspace_id=refreshed["workspace_id"],
                )
        return enqueued
