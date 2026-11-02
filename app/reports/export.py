"""CSV and auditable XLSX analytical exports built from the same filtered facts.

This creates a fresh local workbook. It never opens/rewrites a sophisticated
online workbook and does not claim native pivot or slicer preservation.
"""

from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.analytics.forecast import forecast
from app.analytics.metrics import compute
from app.analytics.query import facts
from app.analytics.reports import ReportDefinition
from app.reports.paths import output_path, safe_text
from app.spreadsheets.pivots import build_pivot_spec


def export_csv(
    snapshot: dict[str, Any],
    output_dir: str | Path,
    filters: dict[str, Any] | None = None,
    filename: str | None = None,
) -> Path:
    rows, f = facts(snapshot, filters)
    target = output_path(output_dir, filename, ".csv", snapshot, filters)
    columns = [
        "workspace_id",
        "revision",
        "basis",
        "transaction_id",
        "allocation_id",
        "date",
        "currency",
        "type",
        "status",
        "category_id",
        "category",
        "area_id",
        "project_id",
        "account_id",
        "amount_minor",
        "expense_minor",
        "income_minor",
        "net_minor",
    ]
    with target.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            enriched = {
                **row,
                "workspace_id": snapshot["workspace_id"],
                "revision": snapshot.get("revision", 0),
                "basis": f.basis,
            }
            writer.writerow({key: safe_text(enriched.get(key)) for key in columns})
    return target


def export_xlsx(
    snapshot: dict[str, Any],
    output_dir: str | Path,
    filters: dict[str, Any] | None = None,
    filename: str | None = None,
) -> Path:
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, LineChart, Reference
    from openpyxl.comments import Comment
    from openpyxl.formatting.rule import ColorScaleRule
    from openpyxl.styles import Alignment, Font, PatternFill, Protection
    from openpyxl.utils import get_column_letter
    from openpyxl.workbook.properties import CalcProperties
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.worksheet.table import Table, TableStyleInfo

    rows, f = facts(snapshot, filters)
    analytics = compute(snapshot, filters)
    target = output_path(output_dir, filename, ".xlsx", snapshot, filters)
    wb = Workbook()
    wb.remove(wb.worksheets[0])
    wb.calculation = CalcProperties(calcId=0, fullCalcOnLoad=True, forceFullCalc=True)
    wb.properties.creator = "OUR_FINANCES"
    wb.properties.title = "Exportação analítica local"
    chart: BarChart | LineChart
    source = (
        f"Source: domain_snapshot; revision {snapshot.get('revision', 0)}; "
        f"as_of {snapshot.get('as_of', analytics['metadata']['end_date'])}"
    )

    def sheet(
        name: str,
        columns: list[str],
        data: list[list[Any]],
        table_name: str | None = None,
        *,
        manual: bool = False,
    ) -> Any:
        ws = wb.create_sheet(name)
        ws.append(columns)
        for cell in ws[1]:
            cell.font = Font(name="Aptos", bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="183B56")
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        ws.row_dimensions[1].height = 30
        for row in data:
            row = [
                Decimal(v)
                if isinstance(v, str)
                and (
                    header.endswith("_minor")
                    or header.endswith("_rate")
                    or header in {"share", "pareto_cumulative_rate"}
                )
                else v
                for header, v in zip(columns, row, strict=True)
            ]
            ws.append(
                [
                    safe_text(v)
                    if not isinstance(v, (list, dict))
                    else safe_text(json.dumps(v, ensure_ascii=False, default=str))
                    for v in row
                ]
            )
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.font = Font(name="Aptos", size=11, color="0000FF")
                cell.comment = Comment(
                    source + f"; {name}!{cell.coordinate}; materialized analytical metrics "
                    "are engine data, not recalculating formulas",
                    "OUR_FINANCES",
                )
                if isinstance(cell.value, (int, float)):
                    cell.number_format = '#,##0;[Red](#,##0);"—"'
                if manual:
                    cell.protection = Protection(locked=False)
        ws.freeze_panes = "A2"
        ws.sheet_view.showGridLines = False
        ws.auto_filter.ref = ws.dimensions
        for index, header in enumerate(columns, 1):
            ws.column_dimensions[get_column_letter(index)].width = min(45, max(16, len(header) + 3))
        if table_name and data:
            table = Table(
                displayName=table_name, ref=f"A1:{get_column_letter(len(columns))}{len(data) + 1}"
            )
            table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
            ws.add_table(table)
        if not manual:
            ws.protection.sheet = True
            ws.protection.autoFilter = False
            ws.protection.sort = False
            ws.protection.selectLockedCells = False
        ws.print_options.horizontalCentered = True
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_setup.orientation = "landscape"
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.print_title_rows = "1:1"
        return ws

    def formula(
        ws: Any, address: str, value: str, *, cross_sheet: bool = False, percent: bool = False
    ) -> None:
        cell = ws[address]
        cell.value = value
        cell.font = Font(name="Aptos", size=11, color="006100" if cross_sheet else "000000")
        cell.comment = Comment(
            "Trusted formula template; Excel recalculation on open is required. Source: " + source,
            "OUR_FINANCES",
        )
        cell.number_format = "0.0%" if percent else '#,##0.00;[Red](#,##0.00);"—"'

    metadata = analytics["metadata"]
    introduction = [
        ["Tipo", "EXPORTAÇÃO ANALÍTICA LOCAL"],
        ["Revisão", snapshot.get("revision", 0)],
        ["Workspace", snapshot["workspace_id"]],
        ["Período inicial", metadata["start_date"]],
        ["Período final", metadata["end_date"]],
        ["Regime", f.basis],
        ["Origem", "Snapshot do domínio; fatos e métricas materializados identificados"],
        ["Unidade financeira", "Unidades mínimas da moeda original; nenhuma conversão cambial"],
        ["Filtros", metadata["filters"]],
        ["Objetos locais", "Tabelas Excel, gráficos editáveis e fórmulas confiáveis"],
        ["Pivôs e segmentações", "PENDENTES: publicação e verificação nos destinos online"],
        ["Recálculo", "Fórmulas recalculam ao abrir no Excel; resultado em cache não verificado"],
        ["Legenda", "Azul: dados/inputs; preto: fórmulas; verde: referência entre abas"],
        ["Edição", "Use Entrada_Alteracoes; domínio exige prévia, revisão-base e confirmação"],
        ["Abas manuais", "Arquivo novo; nenhuma pasta existente foi regravada"],
    ]
    intro = sheet("Inicio", ["Campo", "Valor"], introduction)
    intro.column_dimensions["B"].width = 105
    for row in intro.iter_rows(min_row=2):
        row[1].alignment = Alignment(wrap_text=True, vertical="top")
        intro.row_dimensions[row[0].row].height = 32

    ids = {row["transaction_id"] for row in rows}
    txs = [tx for tx in snapshot.get("transactions", []) if str(tx["id"]) in ids]
    tx_columns = [
        "id",
        "revision",
        "type",
        "description",
        "currency",
        "amount_minor",
        "occurrence_date",
        "competence_date",
        "settlement_date",
        "status",
        "account_id",
        "to_account_id",
        "refund_of",
        "source",
    ]
    sheet(
        "Lancamentos", tx_columns, [[tx.get(c) for c in tx_columns] for tx in txs], "Transactions"
    )
    fact_columns = [
        "transaction_id",
        "allocation_id",
        "date",
        "month",
        "year",
        "currency",
        "type",
        "category_id",
        "category",
        "area_id",
        "project_id",
        "account_id",
        "amount_minor",
        "expense_minor",
        "income_minor",
        "net_minor",
    ]
    allocations = sheet(
        "Rateios", fact_columns, [[r.get(c) for c in fact_columns] for r in rows], "Facts"
    )
    category_columns = ["id", "name", "parent_id", "area_id", "active", "aliases"]
    sheet(
        "Categorias",
        category_columns,
        [[c.get(k) for k in category_columns] for c in snapshot.get("categories", [])],
        "Categories",
    )

    # Exact positions are fixed before formulas are generated.
    budget_columns = [
        "id",
        "name",
        "currency",
        "basis",
        "start_date",
        "end_date",
        "limit_minor",
        "budget_actual_minor",
        "remaining_minor",
        "deviation_minor",
        "consumed_rate",
        "thresholds_reached",
        "coverage_note",
        "actual_minor",
    ]
    budgets = sheet(
        "Orcamentos",
        budget_columns,
        [[r.get(c) for c in budget_columns] for r in analytics["budgets"]],
        "Budgets",
    )
    for index, _ in enumerate(analytics["budgets"], 2):
        formula(budgets, f"I{index}", f'=IF(G{index}="","",G{index}-H{index})')
        formula(budgets, f"J{index}", f'=IF(G{index}="","",H{index}-G{index})')
        formula(
            budgets,
            f"K{index}",
            f'=IF(OR(G{index}="",G{index}=0),"",H{index}/G{index})',
            percent=True,
        )
    if analytics["budgets"]:
        budgets.conditional_formatting.add(
            f"K2:K{len(analytics['budgets']) + 1}",
            ColorScaleRule(  # type: ignore[no-untyped-call]
                start_type="num",
                start_value=0,
                start_color="E4F0E6",
                end_type="num",
                end_value=1,
                end_color="F8D7DA",
            ),
        )
        for currency_index, currency in enumerate(
            sorted({r["currency"] for r in analytics["budgets"]})
        ):
            indexes = [
                i for i, row in enumerate(analytics["budgets"], 2) if row["currency"] == currency
            ]
            chart = BarChart()
            chart.title = f"{currency} · limite efetivo x realizado"
            chart.y_axis.title = f"{currency} (minor units)"
            chart.add_data(
                Reference(budgets, min_col=7, max_col=8, min_row=min(indexes), max_row=max(indexes))
            )
            chart.set_categories(
                Reference(budgets, min_col=2, min_row=min(indexes), max_row=max(indexes))
            )
            budgets.add_chart(chart, f"P{2 + 17 * currency_index}")

    balances = analytics["balances"]
    balance_columns = [
        "account_id",
        "name",
        "currency",
        "opening_balance_minor",
        "recorded_change_minor",
        "balance_minor",
        "coverage",
    ]
    balance_ws = sheet(
        "Contas_Cartoes",
        balance_columns,
        [[r.get(c) for c in balance_columns] for r in balances],
        "Accounts",
    )
    for index, _ in enumerate(balances, 2):
        formula(balance_ws, f"F{index}", f'=IF(D{index}="","",D{index}+E{index})')
    goal_columns = [
        "id",
        "name",
        "currency",
        "target_minor",
        "contributed_minor",
        "remaining_minor",
        "progress_rate",
        "deadline",
        "required_daily_minor",
    ]
    goals = sheet(
        "Metas_Projetos",
        goal_columns,
        [[r.get(c) for c in goal_columns] for r in analytics["goals"]],
        "Goals",
    )
    for index, _ in enumerate(analytics["goals"], 2):
        formula(goals, f"F{index}", f'=IF(D{index}="","",MAX(0,D{index}-E{index}))')
        formula(
            goals,
            f"G{index}",
            f'=IF(OR(D{index}="",D{index}=0),"",E{index}/D{index})',
            percent=True,
        )

    panel_columns = [
        "currency",
        "period",
        "income_minor",
        "expense_minor",
        "net_minor",
        "expense_transaction_count",
        "ticket_minor",
        "saving_rate",
        "incomplete_period",
        "rolling_3_month_mean_minor",
        "year_change_rate",
    ]
    for family, name, field, table_name in [
        ("monthly", "Painel_Mensal", "month", "Monthly"),
        ("annual", "Painel_Anual", "year", "Annual"),
    ]:
        selected = analytics[family]
        ws = sheet(
            name,
            panel_columns,
            [
                [
                    r["currency"],
                    r[field],
                    r["income_minor"],
                    r["expense_minor"],
                    None,
                    r["expense_transaction_count"],
                    r["ticket_minor"],
                    None,
                    r.get("incomplete_period"),
                    r.get("rolling_3_month_mean_minor"),
                    r.get("year_change_rate"),
                ]
                for r in selected
            ],
            table_name,
        )
        for index, _ in enumerate(selected, 2):
            # Recalculate additive metrics directly from the exported allocation source.
            if rows:
                formula(
                    ws,
                    f"C{index}",
                    f"=SUMIFS(Facts[income_minor],Facts[currency],A{index},Facts[{field}],B{index})",
                    cross_sheet=True,
                )
                formula(
                    ws,
                    f"D{index}",
                    f"=SUMIFS(Facts[expense_minor],Facts[currency],A{index},Facts[{field}],B{index})",
                    cross_sheet=True,
                )
            formula(ws, f"E{index}", f"=C{index}-D{index}")
            formula(ws, f"H{index}", f'=IF(C{index}=0,"",E{index}/C{index})', percent=True)
        # Separate native charts per currency; no cross-currency sum is drawn.
        for currency_index, currency in enumerate(sorted({r["currency"] for r in selected})):
            indexes = [
                index for index, row in enumerate(selected, 2) if row["currency"] == currency
            ]
            if indexes:
                chart = LineChart() if family == "monthly" else BarChart()
                chart.title = f"{currency} · despesas · unidades mínimas"
                chart.y_axis.title = f"{currency} (minor units)"
                chart.add_data(
                    Reference(ws, min_col=4, min_row=min(indexes), max_row=max(indexes)),
                    titles_from_data=False,
                )
                chart.set_categories(
                    Reference(ws, min_col=2, min_row=min(indexes), max_row=max(indexes))
                )
                chart.height, chart.width = 8, 18
                ws.add_chart(chart, f"M{2 + currency_index * 17}")

    composition_columns = [
        "currency",
        "category_id",
        "category",
        "expense_minor",
        "transaction_count",
        "allocation_count",
        "ticket_minor",
        "share",
        "pareto_cumulative_rate",
    ]
    composition = sheet(
        "Composicao",
        composition_columns,
        [[r.get(c) for c in composition_columns] for r in analytics["categories"]],
        "Composition",
    )
    for index, row in enumerate(analytics["categories"], 2):
        currency = str(row["currency"]).replace('"', '""')
        formula(
            composition,
            f"H{index}",
            f'=IF(SUMIF(A:A,"{currency}",D:D)=0,"",D{index}/SUMIF(A:A,"{currency}",D:D))',
            percent=True,
        )
    for currency_index, currency in enumerate(
        sorted({r["currency"] for r in analytics["categories"]})
    ):
        indexes = [
            i for i, row in enumerate(analytics["categories"], 2) if row["currency"] == currency
        ]
        chart = BarChart()
        chart.type = "bar"
        chart.title = f"{currency} · composição"
        chart.add_data(
            Reference(composition, min_col=4, min_row=min(indexes), max_row=max(indexes))
        )
        chart.set_categories(
            Reference(composition, min_col=3, min_row=min(indexes), max_row=max(indexes))
        )
        composition.add_chart(chart, f"K{2 + 17 * currency_index}")

    if snapshot.get("as_of") or snapshot.get("generated_at"):
        projection = forecast(snapshot, {"filters": filters or {}})
    elif metadata["end_date"]:
        projection = forecast(snapshot, {"start_date": metadata["end_date"]})
    else:
        projection = {"items": [], "monthly": [], "net_worth": [], "debts": [], "metadata": {}}
    cash_columns = [
        "id",
        "source",
        "date",
        "currency",
        "type",
        "amount_minor",
        "income_minor",
        "expense_minor",
        "net_minor",
        "account_id",
        "description",
    ]
    cash = sheet(
        "Fluxo_Caixa",
        cash_columns,
        [[r.get(c) for c in cash_columns] for r in projection["items"]],
        "Cashflow",
    )
    for index, _ in enumerate(projection["items"], 2):
        formula(cash, f"I{index}", f"=G{index}-H{index}")
    cash_month_columns = [
        "currency",
        "month",
        "income_minor",
        "expense_minor",
        "net_minor",
        "commitment_count",
    ]
    cash_month = sheet(
        "Caixa_Projetado_Mensal",
        cash_month_columns,
        [[r.get(c) for c in cash_month_columns] for r in projection["monthly"]],
        "MonthlyCashflow",
    )
    for index, _ in enumerate(projection["monthly"], 2):
        formula(cash_month, f"E{index}", f"=C{index}-D{index}")
    for currency_index, currency in enumerate(
        sorted({r["currency"] for r in projection["monthly"]})
    ):
        indexes = [
            i for i, row in enumerate(projection["monthly"], 2) if row["currency"] == currency
        ]
        chart = LineChart()
        chart.title = f"{currency} · caixa programado"
        chart.add_data(Reference(cash_month, min_col=5, min_row=min(indexes), max_row=max(indexes)))
        chart.set_categories(
            Reference(cash_month, min_col=2, min_row=min(indexes), max_row=max(indexes))
        )
        cash_month.add_chart(chart, f"H{2 + 17 * currency_index}")
    cash_actual = compute(snapshot, {**(filters or {}), "basis": "cash"})
    cash_daily_columns = [
        "currency",
        "date",
        "income_minor",
        "expense_minor",
        "net_minor",
        "transaction_count",
    ]
    sheet(
        "Caixa_Realizado",
        cash_daily_columns,
        [[r.get(c) for c in cash_daily_columns] for r in cash_actual["daily"]],
        "ActualCashflow",
    )
    wealth_columns = [
        "currency",
        "assets_minor",
        "liabilities_minor",
        "net_worth_minor",
        "unknown_values",
        "coverage",
        "as_of_dates",
    ]
    sheet(
        "Patrimonio",
        wealth_columns,
        [[r.get(c) for c in wealth_columns] for r in projection["net_worth"]],
        "Wealth",
    )
    sheet(
        "Dividas",
        ["liability_id", "currency", "rate", "rate_period", "coverage", "schedule"],
        [
            [
                r.get(c)
                for c in ["liability_id", "currency", "rate", "rate_period", "coverage", "schedule"]
            ]
            for r in projection["debts"]
        ],
        "Debts",
    )
    sheet(
        "Cenarios",
        ["Estado", "Descrição"],
        [
            [
                "Separado do realizado",
                "Cenários são calculados explicitamente pelo motor com premissas informadas; "
                "nenhum cenário presumido no export.",
            ]
        ],
    )
    report = ReportDefinition(filters=f)
    native_spec = build_pivot_spec(snapshot, report)
    sheet(
        "Tabelas_Dinamicas",
        ["Estado", "Especificação"],
        [["PENDENTE: objeto nativo online", native_spec]],
    )
    sheet(
        "Analises_Salvas",
        ["id", "name", "revision", "definition"],
        [[r.get("id"), r.get("name"), r.get("revision"), r] for r in snapshot.get("reports", [])],
        "SavedReports",
    )

    manual_columns = [
        "id",
        "workspace_id",
        "entity",
        "operation",
        "entity_id",
        "base_revision",
        "values_json",
        "status",
    ]
    entry = sheet(
        "Entrada_Alteracoes",
        manual_columns,
        [
            [
                None,
                snapshot["workspace_id"],
                None,
                None,
                None,
                snapshot.get("revision", 0),
                None,
                "requires_preview_and_confirmation",
            ]
        ],
        "ManualEntries",
        manual=True,
    )
    for row in entry.iter_rows(min_row=2, max_row=501, max_col=len(manual_columns)):
        for cell in row:
            cell.protection = Protection(locked=False)
    for column, choices in [("C", '"transaction,category,budget"'), ("D", '"create,update"')]:
        validation = DataValidation(type="list", formula1=choices, allow_blank=True)
        validation.errorTitle, validation.error = "Valor inválido", "Selecione um valor da lista."
        validation.showErrorMessage = True
        entry.add_data_validation(validation)
        validation.add(f"{column}2:{column}501")
    sheet("Manual_Livre", ["Notas próprias (preservadas em futuros conectores)"], [], manual=True)
    check_columns = [
        "currency",
        "engine_income_minor",
        "engine_expense_minor",
        "sheet_income_minor",
        "sheet_expense_minor",
        "income_matches",
        "expense_matches",
    ]
    checks = sheet(
        "Conferencias",
        check_columns,
        [
            [r["currency"], r["income_minor"], r["expense_minor"], None, None, None, None]
            for r in analytics["totals_by_currency"]
        ],
        "Checks",
    )
    for index, _ in enumerate(analytics["totals_by_currency"], 2):
        formula(
            checks,
            f"D{index}",
            f"=SUMIF(Facts[currency],A{index},Facts[income_minor])",
            cross_sheet=True,
        )
        formula(
            checks,
            f"E{index}",
            f"=SUMIF(Facts[currency],A{index},Facts[expense_minor])",
            cross_sheet=True,
        )
        formula(checks, f"F{index}", f"=B{index}=D{index}")
        formula(checks, f"G{index}", f"=C{index}=E{index}")
    sheet(
        "Configuracao",
        ["Chave", "Valor"],
        [[key, value] for key, value in metadata.items()]
        + [
            ["native_pivots_verified", False],
            ["formula_cache_verified", False],
            ["workbook_type", "local_analytical_export"],
            ["forecast_metadata", projection.get("metadata", {})],
        ],
    )
    # Return-to-index links are trusted fixed workbook references.
    for ws in wb.worksheets[1:]:
        ws.sheet_properties.tabColor = "225B81"
    if rows:
        allocations.conditional_formatting.add(
            f"N2:N{len(rows) + 1}",
            ColorScaleRule(  # type: ignore[no-untyped-call]
                start_type="min", start_color="E4F0E6", end_type="max", end_color="B6CFDF"
            ),
        )
    wb.save(target)
    return target
