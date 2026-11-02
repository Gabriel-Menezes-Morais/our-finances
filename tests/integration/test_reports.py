import csv
from io import StringIO
from zipfile import ZipFile

import pytest
from openpyxl import load_workbook

from app.analytics import compute
from app.analytics.charts import chart_data
from app.reports import export_csv, export_xlsx, render_chart, render_summary
from app.spreadsheets.imports import parse_xlsx


@pytest.fixture
def source():
    tx = {
        "id": "expense",
        "revision": 1,
        "type": "expense",
        "description": '=HYPERLINK("https://invalid.test","click")',
        "amount_minor": 60000,
        "currency": "BRL",
        "occurrence_date": "2026-10-20",
        "competence_date": "2026-10-20",
        "settlement_date": "2026-10-20",
        "status": "settled",
        "account_id": "bank",
    }
    return {
        "workspace_id": "w",
        "revision": 9,
        "currency": "BRL",
        "as_of": "2026-10-31",
        "transactions": [
            tx,
            {**tx, "id": "income", "type": "income", "amount_minor": 100000},
            {**tx, "id": "usd", "currency": "USD", "amount_minor": 4200},
        ],
        "categories": [
            {"id": "a", "name": '=WEBSERVICE("invalid")'},
            {"id": "b", "name": "Normal"},
        ],
        "allocations": [
            {"id": "one", "transaction_id": "expense", "category_id": "a", "amount_minor": 30000},
            {"id": "two", "transaction_id": "expense", "category_id": "b", "amount_minor": 30000},
        ],
        "budgets": [
            {
                "id": "limit",
                "name": "Orçamento",
                "amount_minor": 80000,
                "start_date": "2026-10-01",
                "period": "month",
                "currency": "BRL",
                "thresholds": ["0.8"],
            }
        ],
        "accounts": [{"id": "bank", "currency": "BRL", "opening_balance_minor": None}],
    }


def test_xlsx_real_tables_charts_formulas_metadata_and_injection(source, tmp_path):
    result = export_xlsx(source, tmp_path)
    assert result.parent == tmp_path.resolve()
    with ZipFile(result) as archive:
        names = archive.namelist()
        assert len([name for name in names if name.startswith("xl/tables/table")]) >= 8
        assert len([name for name in names if name.startswith("xl/charts/chart")]) >= 4
        assert not any("externalLinks" in name for name in names)
        workbook_xml = archive.read("xl/workbook.xml").decode()
        assert 'fullCalcOnLoad="1"' in workbook_xml
    wb = load_workbook(result, data_only=False)
    assert wb["Lancamentos"]["F2"].value == 60000
    assert wb["Lancamentos"]["F2"].data_type == "n"
    assert wb["Lancamentos"]["D2"].data_type == "s"
    assert wb["Lancamentos"]["D2"].value.startswith("'=")
    assert wb["Categorias"]["B2"].data_type == "s"
    assert (
        wb["Painel_Mensal"]["D2"].value
        == "=SUMIFS(Facts[expense_minor],Facts[currency],A2,Facts[month],B2)"
    )
    assert wb["Painel_Mensal"]["G2"].data_type == "n"
    assert wb["Orcamentos"]["I2"].value == '=IF(G2="","",G2-H2)'
    assert wb["Conferencias"]["F2"].value == "=B2=D2"
    assert wb["Contas_Cartoes"]["D2"].value is None
    assert wb["Entrada_Alteracoes"]["A2"].protection.locked is False
    assert len(wb["Entrada_Alteracoes"].data_validations.dataValidation) == 2
    assert wb["Painel_Mensal"].protection.sheet is True
    config = {row[0]: row[1] for row in wb["Configuracao"].iter_rows(min_row=2, values_only=True)}
    assert config["native_pivots_verified"] is False
    assert config["formula_cache_verified"] is False
    assert "PENDENTE" in wb["Tabelas_Dinamicas"]["A2"].value
    wb.close()
    # Exported workbook can itself be staged without treating generated formulas as edits.
    assert parse_xlsx(result.read_bytes(), source) == []


def test_csv_formula_escaped_and_amounts_reconcile(source, tmp_path):
    path = export_csv(source, tmp_path)
    rows = list(csv.DictReader(StringIO(path.read_text(encoding="utf-8-sig"))))
    assert sum(int(row["expense_minor"]) for row in rows if row["currency"] == "BRL") == 60000
    assert any(row["category"].startswith("'=") for row in rows)
    assert {row["revision"] for row in rows} == {"9"}


def test_chart_summary_and_filter_use_same_population(source, tmp_path):
    filters = {"category_ids": ["b"], "currencies": ["BRL"]}
    result = compute(source, filters)
    data = chart_data(source, filters, "category")
    assert data["series"][0]["values_minor"] == [30000]
    assert result["totals_by_currency"][0]["expense_minor"] == 30000
    summary = render_summary(source, filters)
    assert "300.00" in summary
    assert "Revisão: 9" in summary
    path = render_chart(source, tmp_path, filters, "category")
    assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    first = path.read_bytes()
    assert render_chart(source, tmp_path, filters, "category").read_bytes() == first


def test_exports_empty_snapshot_without_invalid_tables(tmp_path):
    empty = {"workspace_id": "w", "revision": 0}
    path = export_xlsx(empty, tmp_path)
    wb = load_workbook(path)
    assert len(wb["Rateios"].tables) == 0
    assert len(wb["Conferencias"].tables) == 0
    wb.close()


@pytest.mark.parametrize("filename", ["../outside.xlsx", "C:\\outside.xlsx", "sub/a.xlsx", "x.csv"])
def test_export_path_cannot_escape(source, tmp_path, filename):
    with pytest.raises(ValueError):
        export_xlsx(source, tmp_path, filename=filename)


def test_unknown_currency_precision_does_not_invent_decimal_places(tmp_path):
    source = {
        "workspace_id": "w",
        "transactions": [
            {
                "id": "jpy",
                "type": "expense",
                "amount_minor": 500,
                "currency": "JPY",
                "occurrence_date": "2026-10-01",
            },
            {
                "id": "unknown",
                "type": "expense",
                "amount_minor": 50,
                "currency": "XYZ",
                "occurrence_date": "2026-10-01",
            },
        ],
    }
    summary = render_summary(source)
    assert "JPY: receitas 0; despesas líquidas 500;" in summary
    assert "50 unidades mínimas" in summary


def test_default_export_name_is_partitioned_by_workspace(source, tmp_path):
    first = export_csv(source, tmp_path)
    second = export_csv({**source, "workspace_id": "other"}, tmp_path)
    assert first != second


def test_native_local_doughnut_draws_wedges_and_exports_png(source, tmp_path, monkeypatch):
    from matplotlib.axes import Axes

    calls = []
    original = Axes.pie

    def draw_pie(self, values, *args, **kwargs):
        calls.append(list(values))
        assert kwargs["wedgeprops"]["width"] == 0.38
        return original(self, values, *args, **kwargs)

    monkeypatch.setattr(Axes, "pie", draw_pie)
    path = render_chart(source, tmp_path, kind="doughnut")
    assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert len(calls) == 2  # Independent BRL and USD composition objects.
    assert sum(calls[0]) == 600
