"""Durable Telegram ingress, recoverable jobs and owner-scoped local runtime."""

from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter
from aiogram.types import CallbackQuery, Message, Update

from app.agent.orchestrator import Orchestrator, Reply
from app.audio.elevenlabs import transcribe_audio
from app.audio.formats import validate_audio, validate_image
from app.config import Settings
from app.db import Database
from app.domain import DomainError, FinanceService
from app.jobs.scheduler import Scheduler
from app.jobs.store import DurableStore
from app.observability import event
from app.providers import ProviderFailure
from app.spreadsheets.imports import confirmed_commands, parse_csv, parse_xlsx, preview_changes
from app.telegram.delivery import deliver


class Runtime:
    def __init__(
        self, settings: Settings, *, database: Database | None = None, bot: Bot | None = None
    ) -> None:
        if settings.telegram_owner_user_id is None:
            raise ValueError("Proprietário Telegram precisa ser vinculado antes de iniciar.")
        self.settings = settings
        self.owner_id = settings.telegram_owner_user_id
        settings.report_directory.mkdir(parents=True, exist_ok=True)
        if database is None:
            (Path(__file__).resolve().parents[1] / "data").mkdir(exist_ok=True)
        self.database = database or Database(settings.database_url.get_secret_value())
        self.database.initialize()
        self.service = FinanceService(self.database, self.owner_id)
        # Resolve the authenticated owner's workspace before the very first
        # ingress/reply job is scoped. A NULL-scoped first job would never be
        # claimed by the worker's mandatory workspace filter.
        self.service.snapshot()
        self.store = DurableStore(self.database)
        self.orchestrator = Orchestrator(settings, self.service, self.store)
        self.bot = bot
        self.worker_id = str(uuid4())
        self.running = True
        self.last_poll: str | None = None
        self.last_worker: str | None = None
        self.last_schedule_check = 0.0

    def is_authorized(self, update: Update) -> bool:
        callback = update.callback_query
        message = update.message
        if callback:
            sender = callback.from_user
            callback_message = callback.message
            return bool(
                sender.id == self.owner_id
                and not sender.is_bot
                and callback_message
                and callback_message.chat.type == "private"
                and callback_message.chat.id == self.owner_id
            )
        return bool(
            message
            and message.from_user
            and not message.from_user.is_bot
            and message.from_user.id == self.owner_id
            and message.chat.type == "private"
            and message.chat.id == self.owner_id
        )

    def ingest(self, update: Update) -> bool:
        if not self.is_authorized(update):
            return False
        source = "telegram:" + str(self.bot.id if self.bot else self.owner_id)
        row = self.store.persist_inbound(
            source, str(update.update_id), self.owner_id, update.model_dump(mode="json")
        )
        if row["status"] != "processed":
            self.store.enqueue(
                "telegram_inbound",
                {"event_id": row["id"]},
                dedupe_key="inbound:" + row["id"],
                workspace_id=self.service.workspace_id,
            )
        return True

    def recover(self) -> None:
        source = "telegram:" + str(self.bot.id if self.bot else self.owner_id)
        for row in self.store.pending_inbounds(source):
            self.store.enqueue(
                "telegram_inbound",
                {"event_id": row["id"]},
                dedupe_key="inbound:" + row["id"],
                workspace_id=self.service.workspace_id,
            )

    async def poll(self) -> None:
        if self.bot is None:
            raise RuntimeError("Bot não configurado.")
        if (await self.bot.get_webhook_info()).url:
            raise RuntimeError("Webhook ativo; polling não foi iniciado.")
        offset: int | None = None
        while self.running:
            try:
                updates = await self.bot.get_updates(
                    offset=offset, timeout=20, allowed_updates=["message", "callback_query"]
                )
                for update in updates:
                    # Offset advances only after durable persistence/enqueue, never before.
                    self.ingest(update)
                    offset = update.update_id + 1
                self.last_poll = datetime.now(UTC).isoformat()
            except TelegramRetryAfter as exc:
                await asyncio.sleep(min(exc.retry_after, 30))
            except TelegramNetworkError:
                event("telegram_poll", "retry", reason="network")
                await asyncio.sleep(5)

    async def worker(self) -> None:
        self.recover()
        while self.running:
            now = asyncio.get_running_loop().time()
            if now - self.last_schedule_check >= 30:
                try:
                    Scheduler(self.service, self.store).tick()
                except Exception as exc:
                    reason = exc.code if isinstance(exc, DomainError) else type(exc).__name__
                    event("schedule", "retry", reason=reason)
                self.last_schedule_check = now
            worked = await self.run_one_job()
            if not worked:
                await asyncio.sleep(self.settings.worker_poll_seconds)

    async def run_one_job(self) -> bool:
        kinds = [
            "telegram_inbound",
            "telegram_delivery",
            "publish_snapshot",
            "scheduled_report",
            "scheduled_notice",
        ]
        job = self.store.claim(
            self.worker_id,
            kinds=kinds,
            lease_seconds=300,
            workspace_id=self.service.snapshot()["workspace_id"],
        )
        if job is None:
            self.last_worker = datetime.now(UTC).isoformat()
            return False
        uncertain = False
        try:
            if job["kind"] == "telegram_inbound":
                await self.process_inbound(job["payload"]["event_id"])
            elif job["kind"] == "telegram_delivery":
                if self.bot is None:
                    raise ProviderFailure("telegram_not_configured")
                payload = job["payload"]
                self.orchestrator.authorize(payload["owner_id"], payload["chat_id"])
                files = [Path(path) for path in payload.get("files", [])]
                if payload.get("artifacts"):
                    files = []
                    for artifact in payload["artifacts"]:
                        name = Path(artifact["name"]).name
                        target = self.settings.report_directory / name
                        content = base64.b64decode(artifact["content"], validate=True)
                        if len(content) > self.settings.max_audio_bytes:
                            raise ProviderFailure("invalid_cached_artifact_size")
                        # Cache bytes in the durable job so a stateless PaaS restart
                        # cannot lose an already queued XLSX, chart or narrated reply.
                        target.write_bytes(content)
                        files.append(target)
                reply = Reply(
                    text=payload["text"],
                    confirmation_token=payload.get("confirmation_token"),
                    files=files,
                )
                # Delivery is at-most-once on ambiguous transport failures. Financial
                # confirmations remain idempotent independently from message delivery.
                uncertain = True
                await deliver(
                    self.bot, self.owner_id, self.owner_id, reply, self.settings.report_directory
                )
                uncertain = False
            elif job["kind"] == "publish_snapshot":
                # No account credentials: retain actual pending state, never mark a
                # Microsoft/Google projection as published without external evidence.
                self.store.fail(
                    job["id"],
                    self.worker_id,
                    job["fence"],
                    "spreadsheet_not_connected",
                    retry_seconds=3600,
                )
                return True
            elif job["kind"] in {"scheduled_report", "scheduled_notice"}:
                payload = job["payload"]
                snapshot = self.service.snapshot()
                if (
                    payload.get("owner_id") != self.owner_id
                    or payload.get("workspace_id") != snapshot["workspace_id"]
                ):
                    raise PermissionError("Rotina de outro espaço não autorizada.")
                if snapshot.get("operations", {}).get("schedules"):
                    self.store.fail(
                        job["id"],
                        self.worker_id,
                        job["fence"],
                        "schedules_paused",
                        retry_seconds=3600,
                    )
                    return True
                if job["kind"] == "scheduled_notice":
                    reply = Reply(payload["text"])
                elif payload.get("kind") in {"reminder", "subscription"}:
                    reply = Reply(
                        "Lembrete: "
                        + payload.get("name", "Compromisso financeiro")
                        + "\nHorário programado: "
                        + payload["scheduled_at"]
                    )
                else:
                    reply = await self.orchestrator.answer_query(
                        self._summary_query(payload.get("kind", "summary"))
                    )
                self.enqueue_reply(reply, "schedule:" + job["id"])
            self.store.complete(job["id"], self.worker_id, job["fence"])
            event("job", "completed", correlation_id=job["id"], attempts=job["attempts"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            reason = exc.reason if isinstance(exc, ProviderFailure) else type(exc).__name__
            self.store.fail(
                job["id"],
                self.worker_id,
                job["fence"],
                reason,
                retry_seconds=min(3600, 15 * 2 ** min(job["attempts"], 7)),
                uncertain=uncertain,
            )
            event(
                "job",
                "uncertain" if uncertain else "retry",
                correlation_id=job["id"],
                reason=reason,
                attempts=job["attempts"],
            )
        self.last_worker = datetime.now(UTC).isoformat()
        return True

    @staticmethod
    def _summary_query(kind: str) -> Any:
        from app.agent.contracts import QueryRequest

        return QueryRequest.model_validate({"kind": "budget" if kind == "budget" else "summary"})

    def enqueue_reply(self, reply: Reply, source: str) -> None:
        files = list(reply.files)
        if reply.audio:
            path = self.settings.report_directory / ("audio-" + str(uuid4()) + ".mp3")
            path.write_bytes(reply.audio)
            files.append(path)
        artifacts = []
        for path in files:
            path = path.resolve()
            if not path.is_relative_to(self.settings.report_directory.resolve()):
                raise PermissionError("Arquivo não autorizado para entrega.")
            content = path.read_bytes()
            if len(content) > self.settings.max_audio_bytes:
                raise ProviderFailure("artifact_delivery_limit_exceeded")
            artifacts.append(
                {"name": path.name, "content": base64.b64encode(content).decode("ascii")}
            )
        self.store.enqueue(
            "telegram_delivery",
            {
                "owner_id": self.owner_id,
                "chat_id": self.owner_id,
                "text": reply.text,
                "confirmation_token": reply.confirmation_token,
                "files": [str(path.resolve()) for path in files],
                "artifacts": artifacts,
            },
            dedupe_key="reply:" + source,
            workspace_id=self.service.workspace_id,
        )

    async def process_inbound(self, event_id: str) -> None:
        row = self.store.get_inbound(event_id)
        if row is None or row["status"] == "processed":
            return
        if self.store.get_job_by_key("reply:" + event_id):
            self.store.mark_inbound(event_id, "processed")
            return
        update = Update.model_validate(row["payload"])
        if not self.is_authorized(update):
            self.store.mark_inbound(event_id, "failed")
            return
        try:
            if update.callback_query:
                reply = await self.handle_callback(update.callback_query)
            elif update.message:
                reply = await self.handle_message(update.message, event_id)
            else:
                reply = Reply("Tipo de mensagem não suportado.")
            if reply.followup_query:
                try:
                    followup = await self.orchestrator.answer_query(reply.followup_query)
                    reply.text += "\n\n" + followup.text
                    reply.files.extend(followup.files)
                    reply.audio = followup.audio
                except Exception:
                    reply.text += (
                        "\n\nA alteração foi salva, mas a análise solicitada não foi gerada. "
                        "Peça a análise novamente; não repita o lançamento."
                    )
        except DomainError as exc:
            reply = Reply("Pedido não aplicado: " + str(exc))
        except ProviderFailure as exc:
            reply = Reply("Não processei o pedido: " + exc.reason + ". Nenhuma alteração aplicada.")
        self.enqueue_reply(reply, event_id)
        self.store.mark_inbound(event_id, "processed")

    async def handle_callback(self, callback: CallbackQuery) -> Reply:
        if callback.message is None or callback.message.chat.type != "private":
            raise PermissionError("Confirmação exige a conversa privada vinculada.")
        self.orchestrator.authorize(callback.from_user.id, callback.message.chat.id)
        data = callback.data or ""
        operation, _, token = data.partition(":")
        if operation not in {"confirm", "cancel"}:
            return Reply("Botão desconhecido ou antigo.")
        if self.bot:
            try:
                await self.bot.answer_callback_query(callback.id)
            except Exception:
                # Expired spinner acknowledgement does not authorize or prevent a
                # separately validated, unexpired financial confirmation.
                pass
        return self.orchestrator.confirm(
            token, self.owner_id, self.owner_id, cancel=operation == "cancel"
        )

    async def download(self, file_id: str, size: int | None) -> bytes:
        if self.bot is None or size is None or not 0 < size <= self.settings.max_audio_bytes:
            raise ProviderFailure("invalid_media_size")
        buffer = BytesIO()
        await self.bot.download(file_id, destination=buffer)
        data = buffer.getvalue()
        if len(data) > self.settings.max_audio_bytes:
            raise ProviderFailure("media_too_large")
        return data

    async def handle_message(self, message: Message, event_id: str) -> Reply:
        assert message.from_user is not None
        self.orchestrator.authorize(message.from_user.id, message.chat.id)
        text = message.text or message.caption or ""
        images = []
        flags = self.service.snapshot().get("operations", {})
        if (message.voice or message.audio) and flags.get("audio"):
            return Reply("Processamento de áudio pausado. Você pode enviar texto.")
        if message.voice or message.audio:
            if self.settings.app_mode != "connected":
                return Reply("Áudio requer modo conectado e chave ElevenLabs configurada.")
            audio = message.voice or message.audio
            assert audio is not None
            data = await self.download(audio.file_id, audio.file_size)
            validate_audio(
                data,
                max_bytes=self.settings.max_audio_bytes,
                duration=audio.duration,
                max_seconds=self.settings.max_audio_seconds,
            )
            async with httpx.AsyncClient() as client:
                transcript = await transcribe_audio(
                    self.settings, data, "telegram.ogg", client=client
                )
            self.store.record_usage(self.owner_id, "elevenlabs_stt", units=audio.duration)
            text = (text + "\n" + transcript).strip()
        elif message.photo:
            photo = message.photo[-1]
            data = await self.download(photo.file_id, photo.file_size)
            images = [validate_image(data)]
            text = text or "Interprete este comprovante; peça os campos financeiros que faltarem."
        elif message.document:
            document = message.document
            if document.mime_type in {"image/jpeg", "image/png", "image/webp"}:
                data = await self.download(document.file_id, document.file_size)
                images = [validate_image(data)]
                text = text or "Interprete este comprovante e proponha os lançamentos."
            elif (document.file_name or "").lower().endswith((".csv", ".xlsx")):
                data = await self.download(document.file_id, document.file_size)
                try:
                    return self.import_proposal(data, document.file_name or "import.csv")
                except (ValueError, DomainError):
                    return Reply(
                        "Não importei o arquivo. Verifique cabeçalhos, valores em centavos, "
                        "IDs de conta/categoria e a revisão-base. Fórmulas, macros e links "
                        "externos não são aceitos. Use a aba Entrada_Alteracoes do XLSX exportado."
                    )
            else:
                return Reply(
                    "Por enquanto, envie comprovantes como foto, JPEG, PNG ou WebP. "
                    "Importação de planilha exige prévia e confirmação; nenhum dado desse arquivo "
                    "foi lançado."
                )
        if not text and not images:
            return Reply("Envie texto, áudio ou foto de comprovante. Use /ajuda para exemplos.")
        if flags.get("ai") and not text.startswith("/"):
            return Reply(
                "IA pausada. Consultas por /resumo, /status e /exportar continuam disponíveis."
            )
        return await self.orchestrator.handle(
            text, actor_id=self.owner_id, chat_id=self.owner_id, event_id=event_id, images=images
        )

    def import_proposal(self, data: bytes, filename: str) -> Reply:
        from hashlib import sha256

        snapshot = self.service.snapshot()
        parser = parse_xlsx if filename.lower().endswith(".xlsx") else parse_csv
        changes = parser(data, snapshot)
        preview = preview_changes(snapshot, changes)
        commands = confirmed_commands(snapshot, preview, preview["preview_hash"])
        if not commands:
            return Reply("O arquivo não contém alterações novas para confirmar.")
        if len(commands) > 100:
            return Reply(
                "Divida a importação em arquivos de até 100 alterações. Nada foi importado."
            )
        actions: list[dict[str, object]] = []
        for command in commands:
            values = dict(command["values"])
            if command.get("entity_id"):
                values["id"] = command["entity_id"]
            actions.append(
                {
                    "operation": command["operation"] + "_" + command["entity"],
                    "payload": values,
                }
            )
        return self.orchestrator.propose(
            actions,
            self.owner_id,
            self.owner_id,
            explanation=f"Importar {len(actions)} alterações verificadas. O lote é atômico.",
            idempotency_key="import:" + sha256(data).hexdigest(),
        )

    def close(self) -> None:
        self.running = False
        self.database.close()
