"""Human-readable summaries and deterministic headless PNG charts."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from app.analytics.charts import chart_data
from app.analytics.metrics import compute
from app.reports.formatting import PRECISION, display_amount
from app.reports.paths import output_path


def render_summary(snapshot: dict[str, Any], filters: dict[str, Any] | None = None) -> str:
    result = compute(snapshot, filters)
    metadata = result["metadata"]
    lines = [
        "Relatório analítico local",
        f"Período: {metadata['start_date'] or 'sem dados'} "
        f"a {metadata['end_date_inclusive'] or 'sem dados'}; regime: {metadata['basis']}.",
        f"Revisão: {metadata['revision']}; origem: snapshot do domínio.",
    ]
    for row in result["totals_by_currency"]:
        lines.append(
            f"{row['currency']}: receitas {display_amount(row['income_minor'], row['currency'])}; "
            f"despesas líquidas {display_amount(row['expense_minor'], row['currency'])}; "
            f"resultado {display_amount(row['net_minor'], row['currency'])}; "
            f"{row['transaction_count']} movimentações distintas."
        )
    if not result["totals_by_currency"]:
        lines.append("Nenhuma movimentação na população filtrada.")
    lines.append(
        "Transferências não compõem consumo. Reembolsos reduzem despesas. "
        "Moedas não foram convertidas."
    )
    if filters:
        import json

        lines.append(
            "Filtros: " + json.dumps(metadata["filters"], ensure_ascii=False, sort_keys=True)
        )
    if any(b["balance_minor"] is None for b in result["balances"]):
        lines.append("Há contas sem saldo inicial informado; o saldo total permanece desconhecido.")
    lines.append(
        "Exportação analítica; conexão online, pivôs nativos "
        "e recálculo Excel ainda não verificados."
    )
    return "\n".join(lines)


def render_chart(
    snapshot: dict[str, Any],
    output_dir: str | Path,
    filters: dict[str, Any] | None = None,
    kind: str = "monthly",
    filename: str | None = None,
    style: str | None = None,
) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    if kind in {"bar", "column", "line", "doughnut", "combination"}:
        style = style or kind
        kind = {"line": "monthly", "combination": "budgets"}.get(kind, "categories")
    if style not in {None, "bar", "column", "line", "doughnut", "combination"}:
        raise ValueError("Unsupported local chart style; specify supported data axes")
    data = chart_data(snapshot, filters, kind)
    kind = data["kind"]
    target = output_path(
        output_dir,
        filename,
        ".png",
        snapshot,
        {**(filters or {}), "chart_kind": kind, "chart_style": style},
    )
    series = data["series"]
    height = max(3.5, 3.5 * len(series))
    fig, axes = plt.subplots(
        max(1, len(series)), 1, figsize=(11, height), squeeze=False, layout="constrained"
    )
    fig.set_facecolor("#f7f8fa")
    titles = {
        "monthly": "Despesas mensais",
        "annual": "Despesas anuais",
        "categories": "Composição por categoria",
        "pareto": "Pareto de despesas",
        "budgets": "Orçamento x realizado",
        "heatmap": "Calendário de gastos",
        "distribution": "Distribuição de gastos",
        "cashflow": "Fluxo de caixa programado",
    }
    for index, row in enumerate(series):
        ax = axes[index, 0]
        divisor = (
            Decimal(10 ** PRECISION.get(row["currency"], 0))
            if row["value_unit"] == "minor_units"
            else Decimal(1)
        )
        values = [
            float(Decimal(str(v)) / divisor) if v is not None else float("nan")
            for v in row["values"]
        ]
        labels = row["labels"]
        positions = list(range(len(labels)))
        if style == "doughnut":
            if any(value < 0 for value in values):
                plt.close(fig)
                raise ValueError(
                    "Doughnut composition requires nonnegative values; use bars for net refunds"
                )
            if not any(values):
                ax.text(0.5, 0.5, "Sem valores positivos para composição", ha="center", va="center")
                ax.set_axis_off()
            else:
                if len(values) > 8:
                    labels = labels[:8] + ["Demais categorias"]
                    values = values[:8] + [sum(values[8:])]
                wedges, _ = ax.pie(
                    values,
                    startangle=90,
                    wedgeprops={"width": 0.38, "edgecolor": "white"},
                    colors=plt.get_cmap("Blues")(
                        [0.35 + i * 0.6 / max(1, len(values) - 1) for i in range(len(values))]
                    ),
                )
                ax.legend(wedges, labels, loc="center left", bbox_to_anchor=(1, 0.5), frameon=False)
                ax.set_aspect("equal")
        elif kind == "heatmap":
            from datetime import date

            import numpy as np

            dates = [date.fromisoformat(label) for label in labels]
            if dates:
                first = min(dates)
                first_monday = first.toordinal() - first.weekday()
                width = (max(dates).toordinal() - first_monday) // 7 + 1
                matrix = np.full((7, width), np.nan)
                for day, value in zip(dates, values, strict=True):
                    matrix[day.weekday(), (day.toordinal() - first_monday) // 7] = value
                picture = ax.imshow(matrix, aspect="auto", cmap="Blues")
                fig.colorbar(picture, ax=ax, label=row["currency"])
                ax.set_yticks(range(7), ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"])
                ax.set_xlabel(f"Semanas a partir de {date.fromordinal(first_monday)}")
        elif style == "bar":
            ax.barh(positions, values, color="#225b81", height=0.65)
            ax.set_yticks(positions, labels)
            ax.set_xlabel(row["currency"])
            ax.invert_yaxis()
        elif style == "line" or kind in {"monthly", "annual", "cashflow"} and style != "column":
            ax.plot(positions, values, marker="o", color="#225b81", linewidth=2)
            ax.axhline(0, color="#94a3b8", linewidth=0.7)
        else:
            ax.bar(positions, values, color="#225b81", width=0.65)
            if kind == "budgets":
                limits = [
                    float(Decimal(r["limit_minor"]) / divisor)
                    if r.get("limit_minor") is not None
                    else float("nan")
                    for r in row["rows"]
                ]
                ax.plot(positions, limits, color="#c56a24", marker="D", label="Limite informado")
                ax.legend()
            if kind == "pareto":
                secondary = ax.twinx()
                secondary.plot(
                    positions,
                    [
                        float(Decimal(r["pareto_cumulative_rate"]) * 100)
                        if r["pareto_cumulative_rate"] is not None
                        else float("nan")
                        for r in row["rows"]
                    ],
                    color="#c56a24",
                    marker="o",
                )
                secondary.set_ylabel("Participação acumulada (%)")
        if kind != "heatmap" and style not in {"bar", "doughnut"}:
            ax.set_xticks(positions, labels, rotation=30, ha="right")
            ax.set_ylabel(
                row["currency"] if row["value_unit"] == "minor_units" else "Movimentações"
            )
            ax.grid(axis="y", alpha=0.2)
        ax.set_title(f"{titles[kind]} · {row['currency']}", loc="left", fontweight="bold")
        ax.spines[["top", "right"]].set_visible(False)
    if not series:
        axes[0, 0].text(0.5, 0.5, "Sem dados na população filtrada", ha="center", va="center")
        axes[0, 0].set_axis_off()
    metadata = data["metadata"]
    fig.supxlabel(
        f"Revisão {metadata['revision']} · {metadata['basis']} · "
        "fonte: snapshot do domínio · moedas separadas",
        fontsize=9,
    )
    fig.savefig(
        target, format="png", dpi=140, metadata={"Software": "OUR_FINANCES analytical export"}
    )
    plt.close(fig)
    return target
