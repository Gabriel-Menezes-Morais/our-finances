"""Propostas tipadas, sem identidade, autorização ou efeitos de persistência."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, strict=True)


class ConversationTurn(Contract):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=12000)


class ImageInput(Contract):
    """Imagem já baixada pelo adaptador autorizado; URLs externas não são aceitas."""

    data: bytes = Field(max_length=8 * 1024 * 1024)
    mime_type: Literal["image/jpeg", "image/png", "image/webp"]


class Allocation(Contract):
    amount_minor: int
    category_id: str | None = None
    area_id: str | None = None
    project_id: str | None = None


class TransactionPayload(Contract):
    type: str | None = None
    amount_minor: int | None = None
    currency: str | None = None
    occurrence_date: str | None = None
    competence_date: str | None = None
    settlement_date: str | None = None
    status: str | None = None
    description: str | None = None
    account_id: str | None = None
    to_account_id: str | None = None
    refund_of: str | None = None
    allocations: list[Allocation] | None = None
    tags: list[str] | None = None
    installment_count: int | None = None
    first_due_date: str | None = None
    variability: str | None = None
    necessity: str | None = None
    responsible_id: str | None = None
    fx_rate: str | None = None
    fx_date: str | None = None
    fx_source: str | None = None


class QueryFilters(Contract):
    start_date: str | None = None
    end_date: str | None = None
    area_id: str | None = None
    category_id: str | None = None
    project_id: str | None = None
    account_id: str | None = None
    responsible_id: str | None = None
    tag_id: str | None = None
    type: str | None = None
    status: str | None = None
    currency: str | None = None
    category_ids: list[str] | None = None
    area_ids: list[str] | None = None
    project_ids: list[str] | None = None
    account_ids: list[str] | None = None
    responsible_ids: list[str] | None = None
    tag_ids: list[str] | None = None
    types: list[str] | None = None
    statuses: list[str] | None = None
    currencies: list[str] | None = None
    basis: Literal["cash", "accrual", "occurrence"] | None = None

    def to_analytics_filters(self) -> dict[str, object]:
        values: dict[str, object] = self.model_dump(exclude_none=True)
        for singular, plural in {
            "category_id": "category_ids",
            "area_id": "area_ids",
            "project_id": "project_ids",
            "account_id": "account_ids",
            "responsible_id": "responsible_ids",
            "tag_id": "tag_ids",
            "type": "types",
            "status": "statuses",
            "currency": "currencies",
        }.items():
            if singular in values:
                value = values.pop(singular)
                values.setdefault(plural, [value])
        if values.get("basis") == "accrual":
            values["basis"] = "competence"
        return values


Dimension = Literal[
    "currency",
    "date",
    "month",
    "year",
    "category_id",
    "category",
    "area_id",
    "project_id",
    "account_id",
    "responsible_id",
    "type",
    "status",
    "fixed",
    "essential",
    "variability",
    "necessity",
]
Metric = Literal[
    "expense_minor",
    "income_minor",
    "net_minor",
    "transaction_count",
    "expense_transaction_count",
    "allocation_count",
    "ticket_minor",
    "median_ticket_minor",
    "min_ticket_minor",
    "max_ticket_minor",
    "saving_rate",
    "expense_income_ratio",
]
Chart = Literal[
    "monthly",
    "annual",
    "categories",
    "category",
    "pareto",
    "budgets",
    "budget",
    "heatmap",
    "distribution",
    "cashflow",
    "bar",
    "column",
    "line",
    "combination",
    "scatter",
    "waterfall",
    "doughnut",
]


class CategoryReduction(Contract):
    category_id: str
    fraction: str


class ExtraordinaryExpense(Contract):
    date: str
    amount_minor: int
    currency: str
    description: str | None = None


class ScenarioAssumptions(Contract):
    name: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    horizon_days: int | None = None
    include_recurrences: bool | None = None
    filters: QueryFilters | None = None
    income_minor: int | None = None
    income_change_rate: str | None = None
    category_reductions: list[CategoryReduction] | None = None
    extra_expenses_minor: int | None = None
    extraordinary_expenses: list[ExtraordinaryExpense] | None = None

    def to_analytics_assumptions(self) -> dict[str, object]:
        values: dict[str, object] = self.model_dump(exclude_none=True)
        if self.category_reductions is not None:
            values["category_reductions"] = {
                row.category_id: row.fraction for row in self.category_reductions
            }
        if self.filters is not None:
            values["filters"] = self.filters.to_analytics_filters()
        return values

    @model_validator(mode="after")
    def unique_categories(self) -> Self:
        if self.income_minor is not None and self.income_change_rate is not None:
            raise ValueError("Specify absolute income or income change, not both")
        ids = [item.category_id for item in self.category_reductions or []]
        if len(ids) != len(set(ids)):
            raise ValueError("Category reductions must have distinct category IDs")
        return self


class OperationFlags(Contract):
    ai: bool | None = None
    audio: bool | None = None
    excel: bool | None = None
    sheets: bool | None = None
    schedules: bool | None = None
    mutations: bool | None = None


class ActionPayload(TransactionPayload):
    """Campos do catálogo fechado. Cada operação é revalidada pelo domínio."""

    id: str | None = None
    target_id: str | None = None
    name: str | None = None
    parent_id: str | None = None
    area_id: str | None = None
    category_id: str | None = None
    project_id: str | None = None
    aliases: list[str] | None = None
    opening_balance_minor: int | None = None
    opening_date: str | None = None
    closing_day: int | None = None
    due_day: int | None = None
    period: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    thresholds: list[str] | None = None
    carryover: bool | None = None
    basis: Literal["cash", "accrual"] | None = None
    target_minor: int | None = None
    deadline: str | None = None
    goal_id: str | None = None
    frequency: Literal["day", "week", "month", "year"] | None = None
    interval: int | None = None
    next_date: str | None = None
    timezone: str | None = None
    exceptions: list[str] | None = None
    template: TransactionPayload | None = None
    paused: bool | None = None
    value_minor: int | None = None
    as_of: str | None = None
    rate: str | None = None
    rate_period: Literal["month", "year"] | None = None
    payment_minor: int | None = None
    months: int | None = None
    kind: str | None = None
    next_run: str | None = None
    destination: str | None = None
    rows: list[Dimension] | None = None
    columns: list[Dimension] | None = None
    metrics: list[Metric] | None = None
    filters: QueryFilters | None = None
    chart: Chart | None = None
    order_by: str | None = None
    limit: int | None = None
    assumptions: ScenarioAssumptions | None = None
    flags: OperationFlags | None = None
    through_date: str | None = None
    clear_fields: list[
        Literal[
            "parent_id",
            "area_id",
            "category_id",
            "project_id",
            "responsible_id",
            "amount_minor",
            "value_minor",
            "deadline",
            "end_date",
            "settlement_date",
            "opening_balance_minor",
            "rate",
            "payment_minor",
            "months",
        ]
    ] = Field(default_factory=list)

    @model_validator(mode="after")
    def clear_fields_are_unambiguous(self) -> Self:
        if any(getattr(self, name) is not None for name in self.clear_fields):
            raise ValueError("A cleared field cannot also specify a value")
        return self


Operation = Literal[
    "configure_workspace",
    "duplicate_report",
    "duplicate_scenario",
    "create_area",
    "update_area",
    "archive_area",
    "merge_area",
    "create_category",
    "update_category",
    "archive_category",
    "merge_category",
    "create_project",
    "update_project",
    "archive_project",
    "create_tag",
    "update_tag",
    "archive_tag",
    "create_account",
    "update_account",
    "archive_account",
    "create_budget",
    "update_budget",
    "archive_budget",
    "create_goal",
    "update_goal",
    "archive_goal",
    "create_contribution",
    "create_recurrence",
    "update_recurrence",
    "archive_recurrence",
    "create_asset",
    "update_asset",
    "archive_asset",
    "create_liability",
    "update_liability",
    "archive_liability",
    "create_schedule",
    "update_schedule",
    "archive_schedule",
    "create_report",
    "update_report",
    "archive_report",
    "create_scenario",
    "update_scenario",
    "archive_scenario",
    "create_transaction",
    "update_transaction",
    "cancel_transaction",
    "refund_transaction",
    "settle_card",
    "generate_recurrences",
    "set_operations",
    "undo",
    "reclassify_transactions",
]


class ProposedAction(Contract):
    operation: Operation
    payload: ActionPayload

    def to_operation(self) -> dict[str, object]:
        payload = self.payload.model_dump(exclude_none=True, exclude={"clear_fields"})
        if (
            self.operation in {"create_report", "update_report"}
            and self.payload.filters is not None
        ):
            payload["filters"] = self.payload.filters.to_analytics_filters()
        for field in self.payload.clear_fields:
            payload[field] = None
        if self.payload.assumptions is not None:
            payload["assumptions"] = self.payload.assumptions.to_analytics_assumptions()
        return {"operation": self.operation, "payload": payload}


class QueryRequest(Contract):
    kind: Literal[
        "summary",
        "list",
        "budget",
        "status",
        "report",
        "pivot",
        "chart",
        "export",
        "forecast",
        "scenario",
    ]
    entity: (
        Literal[
            "transactions",
            "areas",
            "categories",
            "projects",
            "tags",
            "accounts",
            "budgets",
            "goals",
            "recurrences",
            "assets",
            "liabilities",
            "schedules",
            "reports",
            "scenarios",
        ]
        | None
    ) = None
    filters: QueryFilters = Field(default_factory=QueryFilters)
    report_id: str | None = None
    name: str | None = None
    rows: list[Dimension] | None = None
    columns: list[Dimension] | None = None
    metrics: list[Metric] | None = None
    chart: Chart | None = None
    format: Literal["text", "csv", "xlsx", "png", "html", "audio"] | None = None
    destination: Literal["telegram", "excel", "sheets", "both"] | None = None
    months: int | None = None
    assumptions: ScenarioAssumptions | None = None


class ModelUsage(Contract):
    input_tokens: int
    output_tokens: int
    total_tokens: int


class Interpretation(Contract):
    answer: str = Field(max_length=6000)
    explanation: str = Field(max_length=3000)
    question: str | None = Field(default=None, max_length=2000)
    needs_clarification: bool
    actions: list[ProposedAction] = Field(max_length=12)
    query: QueryRequest | None = None
    _usage: ModelUsage | None = PrivateAttr(default=None)

    @property
    def usage(self) -> ModelUsage | None:
        return self._usage

    def with_usage(self, usage: ModelUsage) -> Self:
        result = self.model_copy(deep=True)
        result._usage = usage
        return result

    @model_validator(mode="after")
    def clarification_is_non_mutating(self) -> Self:
        if self.needs_clarification and (not self.question or self.actions or self.query):
            raise ValueError("Clarification requires a question and no executable proposal")
        if not self.needs_clarification and self.question:
            raise ValueError("Question requires clarification state")
        return self

    def to_operations(self) -> list[dict[str, object]]:
        return [action.to_operation() for action in self.actions]
