from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from app.services.forecast_excel_adapter import SHEETS, ExcelResultAdapter


def _xlsx(path: Path, sheets: dict[str, list[dict[str, object]]]) -> None:
    names = list(sheets)
    workbook_sheets = "".join(
        f'<sheet name="{name}" sheetId="{idx}" r:id="rId{idx}"/>'
        for idx, name in enumerate(names, 1)
    )
    rels = "".join(
        f'<Relationship Id="rId{idx}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{idx}.xml"/>'
        for idx in range(1, len(names) + 1)
    )
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "xl/workbook.xml",
            f'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>{workbook_sheets}</sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>',
        )
        for idx, name in enumerate(names, 1):
            rows = sheets[name]
            keys = list(rows[0]) if rows else []
            xml_rows = [
                "<row>" + "".join(f'<c r="{chr(65 + col)}1" t="inlineStr"><is><t>{key}</t></is></c>' for col, key in enumerate(keys)) + "</row>"
            ]
            for row_no, row in enumerate(rows, 2):
                cells = []
                for col, key in enumerate(keys):
                    value = str(row.get(key, "")).replace("&", "&amp;").replace("<", "&lt;")
                    cells.append(f'<c r="{chr(65 + col)}{row_no}" t="inlineStr"><is><t>{value}</t></is></c>')
                xml_rows.append(f"<row>{''.join(cells)}</row>")
            archive.writestr(
                f"xl/worksheets/sheet{idx}.xml",
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + "".join(xml_rows) + "</sheetData></worksheet>",
            )


def test_five_sheet_extract_and_filters(tmp_path: Path):
    path = tmp_path / "output_AG_冰箱_2026-08.xlsx"
    _xlsx(
        path,
        {
            "result": [{"品类": "冰箱", "型号": "R-1"}],
            "预测详情": [
                {"品类": "冰箱", "型号": "R-1", "预测月份": "2026-08-01", "预测期": "1", "最终预测值": "12"},
                {"品类": "洗衣机", "型号": "W-1", "预测月份": "2026-08", "预测期": "N+2", "最终预测值": "8"},
            ],
            "历史数据": [{"品类": "冰箱", "型号": "R-1", "月份": "2026-07", "数量": "10"}],
            "白盒归因": [{"品类": "冰箱", "型号": "R-1", "月份": "2026-08", "factor_type": "price"}],
            "归因映射": [{"品类": "冰箱", "型号": "R-1", "factor_type": "fallback"}],
        },
    )
    adapter = ExcelResultAdapter(path)
    assert adapter.sheet_names() == list(SHEETS)
    forecasts = adapter.extract_forecast(category="冰箱", sku="R-1", forecast_month="2026-08")
    assert forecasts[0]["预测月份"] == "2026-08"
    assert forecasts[0]["预测期"] == "N+1"
    assert len(adapter.extract_forecast(category="洗衣机")) == 1
    assert adapter.extract_attribution(category="冰箱")[0]["预测月份"] == "2026-08"


def test_missing_sheets_are_empty(tmp_path: Path):
    path = tmp_path / "partial.xlsx"
    _xlsx(path, {"result": [{"品类": "冰箱"}]})
    adapter = ExcelResultAdapter(path)
    assert adapter.extract_attribution() == []
