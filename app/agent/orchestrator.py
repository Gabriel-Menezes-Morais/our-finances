"""Owner-scoped proposals, confirmations and deterministic financial answers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.agent.contracts import ConversationTurn, ImageInput, Interpretation, QueryRequest
from app.ai.llm import interpret
from app.analytics import compute, forecast, pivot, scenario
from app.analytics.query import facts
from app.audio.elevenlabs import synthesize_audio
from app.config import Settings
from app.domain import DomainError, FinanceService
from app.formatting import format_money
from app.jobs.store import DurableStore
from app.providers import ProviderFailure
from app.reports.export import export_csv, export_xlsx
from app.reports.render import render_chart, render_summary


@dataclass
class Reply:
    text: str
    confirmation_token: str | None = None
    files: list[Path] = field(default_factory=list)
    audio: bytes | None = None
    followup_query: QueryRequest | None = None


def month_filters(today: date) -> dict[str, str]:
    start = today.replace(day=1)
    end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    return {"start_date": start.isoformat(), "end_date": end.isoformat()}


def safe_json(value: object, limit: int = 3000) -> str:
    result = json.dumps(value, ensure_ascii=False, default=str, indent=2)
    return result if len(result) <= limit else result[:limit] + "\n… resultado limitado."


def money(amount: int, currency: str = "BRL") -> str:
    return format_money(amount, currency)


def action_preview(actions: list[dict[str, Any]], snapshot: dict[str, Any]) -> str:
    records = {
        str(row["id"]): row
        for rows in snapshot.values()
        if isinstance(rows, list)
        for row in rows
        if isinstance(row, dict) and "id" in row
    }
    fields = {
        "id": "Registro",
        "name": "Nome",
        "type": "Tipo",
        "amount_minor": "Valor",
        "currency": "Moeda",
        "description": "Descrição",
        "occurrence_date": "Data",
        "competence_date": "Competência",
        "settlement_date": "Liquidação",
        "account_id": "Conta",
        "to_account_id": "Conta de destino",
        "category_id": "Categoria",
        "area_id": "Área",
        "project_id": "Projeto",
        "parent_id": "Categoria superior",
        "target_id": "Destino",
        "refund_of": "Compra original",
        "allocations": "Divisão",
        "opening_balance_minor": "Saldo inicial",
        "opening_date": "Data do saldo",
        "target_minor": "Objetivo",
        "value_minor": "Valor",
        "payment_minor": "Pagamento",
        "goal_id": "Meta",
        "period": "Período",
        "start_date": "Início",
        "end_date": "Fim",
        "deadline": "Prazo",
        "frequency": "Frequência",
        "next_date": "Próxima data",
        "next_run": "Próximo envio",
        "installment_count": "Parcelas",
        "first_due_date": "Primeiro vencimento",
        "closing_day": "Dia de fechamento",
        "due_day": "Dia do vencimento",
        "thresholds": "Limiares de alerta",
        "carryover": "Transportar saldo",
        "paused": "Pausado",
        "flags": "Pausas",
        "ai": "IA",
        "audio": "Áudio",
        "mutations": "Registros",
        "schedules": "Rotinas",
        "excel": "Excel",
        "sheets": "Sheets",
        "rows": "Linhas",
        "columns": "Colunas",
        "metrics": "Medidas",
        "filters": "Filtros",
        "chart": "Gráfico",
        "basis": "Regime",
        "template": "Lançamento recorrente",
        "tags": "Tags",
        "status": "Situação",
        "kind": "Modalidade",
        "interval": "Intervalo",
        "aliases": "Nomes alternativos",
        "timezone": "Fuso",
        "rate": "Taxa",
        "rate_period": "Período da taxa",
        "months": "Meses",
        "as_of": "Data de referência",
        "responsible_id": "Responsável",
        "variability": "Variabilidade",
        "necessity": "Necessidade",
        "assumptions": "Premissas",
        "exceptions": "Exceções",
    }
    nouns = {
        "area": "área",
        "category": "categoria",
        "project": "projeto",
        "tag": "tag",
        "account": "conta",
        "transaction": "lançamento",
        "budget": "limite",
        "goal": "meta",
        "contribution": "contribuição",
        "recurrence": "recorrência",
        "asset": "ativo",
        "liability": "dívida",
        "schedule": "rotina",
        "report": "análise",
        "scenario": "cenário",
        "workspace": "organização",
    }
    verbs = {
        "create": "Criar",
        "update": "Alterar",
        "archive": "Arquivar",
        "merge": "Mesclar",
        "duplicate": "Duplicar",
        "configure": "Configurar",
    }
    values = {
        "expense": "Despesa",
        "income": "Receita",
        "transfer": "Transferência",
        "refund": "Reembolso",
        "cash": "Caixa",
        "accrual": "Competência",
        "day": "Diária",
        "week": "Semanal",
        "month": "Mensal",
        "year": "Anual",
        "settled": "Liquidado",
        "pending": "Pendente",
        "cancelled": "Cancelado",
    }

    def display(value: Any, key: str, currency: str) -> str:
        if value is None:
            return "Não informado"
        if isinstance(value, bool):
            return "Sim" if value else "Não"
        if isinstance(value, int) and key.endswith("_minor"):
            return money(value, currency)
        if isinstance(value, dict):
            currency = str(value.get("currency") or currency)
            return "; ".join(
                f"{fields.get(k, k.replace('_', ' '))}: {display(v, k, currency)}"
                for k, v in value.items()
            )
        if isinstance(value, list):
            return " / ".join(display(item, key, currency) for item in value) or "Nenhum"
        if key == "id" or key.endswith("_id") or key == "refund_of":
            row = records.get(str(value), {})
            if row:
                return str(row.get("name") or row.get("description") or value)
            if isinstance(value, str) and value.startswith("$") and value[1:].isdigit():
                return f"Item {int(value[1:]) + 1} desta proposta"
        return values.get(str(value), str(value))

    lines = []
    for index, action in enumerate(actions, 1):
        payload = action.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("Proposta exige parâmetros estruturados.")
        previous = records.get(str(payload.get("id")), {})
        currency = str(payload.get("currency") or previous.get("currency") or snapshot["currency"])
        operation = str(action["operation"])
        verb, _, noun = operation.partition("_")
        label = (
            f"{verbs[verb]} {nouns[noun]}"
            if verb in verbs and noun in nouns
            else {
                "undo": "Desfazer última alteração",
                "set_operations": "Alterar pausas",
                "cancel_transaction": "Cancelar lançamento",
                "refund_transaction": "Reembolsar compra",
                "reclassify": "Reclassificar lançamentos",
                "settle_card": "Pagar cartão",
                "generate_recurrences": "Gerar ocorrências previstas",
            }.get(operation, operation.replace("_", " "))
        )
        lines.append(f"{index}. {label}\n{display(payload, '', currency)}")
    return "\n\n".join(lines)


def normalized_filters(query: QueryRequest) -> dict[str, Any]:
    filters = query.filters.model_dump(exclude_none=True)
    aliases = {
        "category_id": "category_ids",
        "area_id": "area_ids",
        "project_id": "project_ids",
        "account_id": "account_ids",
        "responsible_id": "responsible_ids",
        "tag_id": "tag_ids",
        "type": "types",
        "status": "statuses",
        "currency": "currencies",
    }
    for singular, plural in aliases.items():
        if singular in filters:
            value = filters.pop(singular)
            filters[plural] = list(dict.fromkeys([*filters.get(plural, []), value]))
    if filters.get("basis") == "accrual":
        filters["basis"] = "competence"
    return filters


class Orchestrator:
    def __init__(self, settings: Settings, service: FinanceService, store: DurableStore) -> None:
        self.settings = settings
        self.service = service
        self.store = store
        self.owner_id = service.owner_id

    def authorize(self, actor_id: int, chat_id: int) -> None:
        if actor_id != self.owner_id or chat_id != self.owner_id:
            raise PermissionError("Acesso restrito ao proprietário em conversa privada.")

    async def handle(
        self,
        text: str,
        *,
        actor_id: int,
        chat_id: int,
        event_id: str,
        images: list[ImageInput] | None = None,
    ) -> Reply:
        self.authorize(actor_id, chat_id)
        if len(text) > self.settings.max_input_characters:
            return Reply("Mensagem longa demais. Divida o pedido em partes menores.")
        command, _, argument = text.strip().partition(" ")
        command = command.lower().split("@")[0]
        if command in {"/start", "/help", "/ajuda"}:
            return Reply(
                "Our Finances — finanças pelo Telegram.\n\n"
                "Escreva ou mande áudio: ‘gastei 38,50 no almoço ontem’, "
                "‘cria a categoria Saúde’, ‘limita alimentação a 900 por mês’.\n"
                "Toda alteração pede sua confirmação.\n\n"
                "/resumo · /lancamentos · /categorias · /contas · /limites · /metas\n"
                "/agenda · /grafico · /exportar xlsx · /exportar csv · /desfazer · /status\n\n"
                "O banco local guarda os registros. Conexões Excel/Sheets e hospedagem "
                "ainda dependem da configuração combinada. Exportações são locais."
            )
        if command == "/status":
            return self.status()
        if command in {"/pausar", "/retomar"}:
            aliases = {
                "ia": "ai",
                "audio": "audio",
                "registros": "mutations",
                "excel": "excel",
                "sheets": "sheets",
                "rotinas": "schedules",
            }
            chosen = argument.strip().lower()
            if chosen == "tudo":
                flags = {value: command == "/pausar" for value in aliases.values()}
            elif chosen in aliases:
                flags = {aliases[chosen]: command == "/pausar"}
            else:
                return Reply(
                    "Use /pausar ou /retomar com ia, audio, registros, excel, sheets, "
                    "rotinas ou tudo. A mudança pede confirmação."
                )
            return self.propose(
                [{"operation": "set_operations", "payload": {"flags": flags}}],
                actor_id,
                chat_id,
                explanation="Alterar os controles operacionais selecionados.",
            )
        if command in {"/confirmar", "/cancelar"}:
            return self.confirm(argument.strip(), actor_id, chat_id, cancel=command == "/cancelar")
        if command == "/desfazer":
            return self.propose(
                [{"operation": "undo", "payload": {}}],
                actor_id,
                chat_id,
                explanation="Desfazer a última alteração reversível, preservando auditoria.",
            )
        direct: dict[str, tuple[str, str | None]] = {
            "/resumo": ("summary", None),
            "/lancamentos": ("list", "transactions"),
            "/categorias": ("list", "categories"),
            "/contas": ("list", "accounts"),
            "/limites": ("budget", None),
            "/metas": ("list", "goals"),
            "/agenda": ("list", "schedules"),
            "/grafico": ("chart", None),
        }
        if command in direct:
            kind, entity = direct[command]
            query = QueryRequest.model_validate({"kind": kind, "entity": entity})
            return await self.answer_query(query)
        if command == "/exportar":
            output_format = argument.strip().lower() or "xlsx"
            if output_format not in {"csv", "xlsx"}:
                return Reply("Use /exportar xlsx ou /exportar csv.")
            return await self.answer_query(
                QueryRequest.model_validate({"kind": "export", "format": output_format})
            )
        if command.startswith("/"):
            return Reply("Comando desconhecido. Use /ajuda ou descreva o pedido em português.")
        if self.settings.app_mode != "connected":
            return Reply(
                "Interpretação por IA está desligada no modo offline. "
                "Os comandos de consulta e exportação local continuam disponíveis."
            )
        context = self.service.context()
        timezone = context.get("timezone", self.settings.app_timezone)
        context["current_date"] = datetime.now(ZoneInfo(timezone)).date().isoformat()
        context["timezone"] = timezone
        context["transactions"] = context.get("transactions", [])[-20:]
        transaction_ids = {row["id"] for row in context["transactions"]}
        context["allocations"] = [
            row
            for row in context.get("allocations", [])
            if row.get("transaction_id") in transaction_ids
        ][:100]
        for key, value in list(context.items()):
            if isinstance(value, list) and key not in {"transactions", "allocations"}:
                context[key] = value[-100:]
        history = [
            ConversationTurn.model_validate({"role": row["role"], "content": row["text"]})
            for row in self.store.recent_turns(actor_id, limit=8)
            if row["role"] in {"user", "assistant"}
        ]
        self.store.record_turn(actor_id, "user", text)
        try:
            interpretation = await interpret(
                self.settings, text, context, history=history, images=images or []
            )
        except ProviderFailure as exc:
            return Reply(
                "Não consegui interpretar agora (" + exc.reason + "). "
                "Nenhuma alteração financeira foi feita. Você pode tentar novamente."
            )
        if interpretation.usage:
            usage = interpretation.usage
            self.store.record_usage(
                actor_id,
                "openai",
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )
        reply = await self.apply_interpretation(interpretation, actor_id, chat_id)
        self.store.record_turn(actor_id, "assistant", reply.text[:10000])
        return reply

    async def apply_interpretation(
        self, interpretation: Interpretation, actor_id: int, chat_id: int
    ) -> Reply:
        self.authorize(actor_id, chat_id)
        if interpretation.needs_clarification:
            return Reply(interpretation.question or "Pode detalhar o pedido?")
        if interpretation.actions:
            return self.propose(
                interpretation.to_operations(),
                actor_id,
                chat_id,
                explanation=interpretation.explanation,
                query=interpretation.query,
            )
        if interpretation.query:
            return await self.answer_query(interpretation.query)
        return Reply(
            interpretation.answer or "Descreva o lançamento, a organização ou a análise desejada."
        )

    def propose(
        self,
        actions: list[dict[str, object]],
        actor_id: int,
        chat_id: int,
        *,
        explanation: str = "",
        query: QueryRequest | None = None,
        idempotency_key: str | None = None,
    ) -> Reply:
        self.authorize(actor_id, chat_id)
        snapshot = self.service.snapshot()
        body = action_preview(actions, snapshot)
        token = self.store.create_pending(
            snapshot["workspace_id"],
            actor_id,
            chat_id,
            {
                "actions": actions,
                "query": query.model_dump(mode="json") if query else None,
                "idempotency_key": idempotency_key,
                "preview": body,
            },
            snapshot["revision"],
            ttl_seconds=self.settings.confirmation_ttl_seconds,
        )
        return Reply(
            "PRÉVIA — nada foi gravado ainda.\n\n"
            + explanation[:1200]
            + "\n\n"
            + body
            + f"\n\nConfirme em até {self.settings.confirmation_ttl_seconds // 60} minutos. "
            "Se estiver incorreto, cancele e envie a correção.",
            confirmation_token=token,
        )

    def confirm(self, token: str, actor_id: int, chat_id: int, *, cancel: bool = False) -> Reply:
        self.authorize(actor_id, chat_id)
        if not token or len(token) > 100:
            return Reply("Confirmação inválida. Use o botão da prévia mais recente.")
        try:
            pending = self.store.get_pending(token, actor_id, chat_id)
            if cancel:
                self.store.resolve_pending(token, actor_id, chat_id, status="cancelled")
                return Reply("Proposta cancelada. Nenhuma alteração financeira foi feita.")
            payload = pending["payload"]
            result = self.service.execute_batch(
                payload["actions"],
                idempotency_key=payload.get("idempotency_key") or "confirm:" + token,
                expected_revision=pending["expected_revision"],
            )
            self.store.resolve_pending(token, actor_id, chat_id, status="confirmed")
            text = (
                "Alteração confirmada e salva no banco.\n"
                f"{len(result['results'])} item(ns); revisão financeira {result['revision']}.\n\n"
                + str(
                    payload.get("preview")
                    or action_preview(payload["actions"], self.service.snapshot())
                )
            )
            text += "\nExcel e Sheets: conexão ainda não configurada."
            self.store.record_turn(actor_id, "assistant", text)
            query = payload.get("query")
            return Reply(text, followup_query=QueryRequest.model_validate(query) if query else None)
        except DomainError as exc:
            return Reply("Não apliquei a proposta: " + str(exc))

    def status(self) -> Reply:
        snapshot = self.service.snapshot()
        return Reply(
            "Our Finances\n"
            f"Modo: {self.settings.app_mode}\n"
            f"Revisão financeira: {snapshot['revision']}\n"
            f"Lançamentos: {len(snapshot.get('transactions', []))}\n"
            f"Categorias: {len(snapshot.get('categories', []))}\n"
            "Banco: conectado; acesso restrito ao proprietário.\n"
            "Excel / Sheets: não conectados.\n"
            "Hospedagem externa: ainda não configurada.\n"
            + "Filas: "
            + safe_json(self.store.pending_counts(), 700)
            + "\nUso registrado: "
            + safe_json(self.store.usage_summary(self.owner_id), 700)
        )

    async def answer_query(self, query: QueryRequest) -> Reply:
        snapshot = self.service.snapshot()
        filters = normalized_filters(query)
        if not filters and query.kind in {"summary", "budget", "chart"}:
            timezone = snapshot.get("timezone", self.settings.app_timezone)
            filters = month_filters(datetime.now(ZoneInfo(timezone)).date())
        if query.kind == "status":
            return self.status()
        if query.kind == "list":
            entity = query.entity or "transactions"
            rows = snapshot.get(entity, [])
            if not rows:
                return Reply("Nenhum registro encontrado em " + entity + ".")
            if entity == "transactions":
                if filters:
                    selected, _ = facts(snapshot, filters)
                    ids = {row["transaction_id"] for row in selected}
                    rows = [row for row in rows if row["id"] in ids]
            return Reply(entity + ":\n" + safe_json(rows[-20:], 11000))
        if query.kind == "export":
            function = export_csv if query.format == "csv" else export_xlsx
            path = function(snapshot, self.settings.report_directory, filters=filters or None)
            return Reply(
                "Exportação analítica local, revisão "
                + str(snapshot["revision"])
                + ". A conexão com Excel online/Sheets ainda não foi configurada.",
                files=[path],
            )
        if query.kind == "chart":
            kind: str = query.chart or "monthly"
            native_shapes = {
                "line": "monthly",
                "bar": "categories",
                "column": "categories",
                "combination": "budgets",
            }
            kind = native_shapes.get(kind, kind)
            if kind not in {
                "monthly",
                "annual",
                "categories",
                "pareto",
                "budgets",
                "heatmap",
                "distribution",
                "cashflow",
                "doughnut",
            }:
                return Reply(
                    "Esse formato depende do gráfico nativo da planilha. Posso gerar agora "
                    "evolução mensal, composição, orçamento, Pareto ou fluxo de caixa local. "
                    "A definição de análise pode ser salva enquanto a conexão fica pendente."
                )
            path = render_chart(
                snapshot,
                self.settings.report_directory,
                filters=filters or None,
                kind=kind,
                style=query.chart
                if query.chart in {"bar", "column", "line", "doughnut", "combination"}
                else None,
            )
            return Reply(render_summary(snapshot, filters or None), files=[path])
        if query.kind in {"pivot", "report"}:
            definition: dict[str, Any] = {}
            if query.report_id:
                saved: dict[str, Any] = next(
                    (row for row in snapshot.get("reports", []) if row["id"] == query.report_id), {}
                )
                if not saved:
                    return Reply("Análise salva não encontrada.")
                allowed = {
                    "id",
                    "name",
                    "rows",
                    "columns",
                    "metrics",
                    "filters",
                    "chart",
                    "sort_by",
                    "descending",
                    "max_cells",
                    "revision",
                }
                definition = {key: value for key, value in saved.items() if key in allowed}
                if saved.get("order_by"):
                    definition["sort_by"] = saved["order_by"]
                if saved.get("limit") is not None:
                    definition["max_cells"] = saved["limit"]
            definition.update(
                {
                    "name": query.name or definition.get("name", "Análise"),
                    "rows": query.rows
                    if query.rows is not None
                    else definition.get("rows", ["category"]),
                    "columns": query.columns
                    if query.columns is not None
                    else definition.get("columns", ["month"]),
                    "metrics": query.metrics
                    if query.metrics is not None
                    else definition.get("metrics", ["expense_minor"]),
                    "filters": filters or definition.get("filters", {}),
                }
            )
            result = pivot(snapshot, definition)
            note = "\nResultado calculado localmente. Pivô nativo online aguarda conexão."
            return Reply(safe_json(result, 11000) + note)
        if query.kind == "forecast":
            assumptions: dict[str, Any] = {
                "horizon_days": min(3660, (query.months or 6) * 31),
                "filters": filters,
            }
            for key in ("start_date", "end_date"):
                if key in filters:
                    assumptions[key] = filters[key]
            return Reply(
                "Projeção com premissas explícitas:\n"
                + safe_json(forecast(snapshot, assumptions), 11000)
            )
        if query.kind == "scenario":
            assumptions = query.assumptions.to_analytics_assumptions() if query.assumptions else {}
            return Reply(
                "Cenário separado dos registros reais:\n"
                + safe_json(scenario(snapshot, assumptions), 11000)
            )
        text = render_summary(snapshot, filters or None)
        if query.kind == "budget":
            result = compute(snapshot, filters or None)
            text += "\n\nLimites:\n" + safe_json(result.get("budgets", []), 7000)
        reply = Reply(text)
        if query.format == "audio":
            if snapshot.get("operations", {}).get("audio"):
                reply.text += "\n\nÁudio pausado. Use /retomar audio para preparar a reativação."
            elif not self.settings.elevenlabs_voice_id or not self.settings.elevenlabs_tts_model:
                reply.text += "\n\nPara resposta falada, falta escolher sua voz/modelo ElevenLabs."
            elif self.settings.app_mode == "connected":
                try:
                    async with httpx.AsyncClient() as client:
                        reply.audio = await synthesize_audio(
                            self.settings, text[:4500], client=client
                        )
                    self.store.record_usage(self.owner_id, "elevenlabs_tts", units=len(text[:4500]))
                except ProviderFailure as exc:
                    reply.text += "\n\nÁudio indisponível: " + exc.reason + "."
        return reply
