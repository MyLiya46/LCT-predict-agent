"""Offline reader for the target model's five-sheet forecast workbook.

The adapter uses the XLSX ZIP/XML format directly so the backend does not need
to import the model container or carry a dataframe dependency.  It is kept
strictly offline: no prediction or PG write is triggered by this module.
"""
from __future__ import annotations

import re
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

SHEETS = ("result", "预测详情", "历史数据", "白盒归因", "归因映射")
_NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_MONTH_RE = re.compile(r"^(\d{4})[-/]?(\d{1,2})(?:[-/]?(\d{1,2}))?.*$")


def normalizer(value: Any) -> str | None:
    """Normalize common Excel dates/month values to ``YYYY-MM``."""
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m")
    text = str(value).strip()
    match = _MONTH_RE.match(text)
    if match:
        month = int(match.group(2))
        if 1 <= month <= 12:
            return f"{match.group(1)}-{month:02d}"
    try:
        serial = float(text)
        if 1 <= serial <= 80000 and serial.is_integer():
            return (datetime(1899, 12, 30) + timedelta(days=serial)).strftime("%Y-%m")
    except ValueError:
        pass
    return text


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    return value


def _col_number(reference: str) -> int:
    letters = "".join(char for char in reference if char.isalpha()).upper()
    number = 0
    for char in letters:
        number = number * 26 + ord(char) - 64
    return number


class ExcelResultAdapter:
    """Read and filter forecast workbooks without inventing missing sheets."""

    normalizer = staticmethod(normalizer)

    def __init__(self, output_path: str | Path):
        self.output_path = Path(output_path)
        self._cache: dict[str, list[dict[str, Any]]] | None = None

    def _load(self) -> dict[str, list[dict[str, Any]]]:
        if self._cache is not None:
            return self._cache
        if not self.output_path.is_file():
            self._cache = {}
            return self._cache
        try:
            with zipfile.ZipFile(self.output_path) as archive:
                shared: list[str] = []
                if "xl/sharedStrings.xml" in archive.namelist():
                    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                    for item in root.findall("main:si", _NS):
                        shared.append("".join(node.text or "" for node in item.iter() if node.tag.endswith("}t") or node.tag == "t"))
                workbook = ET.fromstring(archive.read("xl/workbook.xml"))
                rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
                rel_map = {
                    item.attrib["Id"]: item.attrib["Target"]
                    for item in rels.findall(f"{{{_REL_NS}}}Relationship")
                }
                loaded: dict[str, list[dict[str, Any]]] = {}
                for sheet in workbook.findall("main:sheets/main:sheet", _NS):
                    name = sheet.attrib.get("name", "")
                    relation = sheet.attrib.get(f"{{{_NS['rel']}}}id")
                    target = rel_map.get(relation or "")
                    if not target:
                        continue
                    xml_path = target.lstrip("/")
                    if not xml_path.startswith("xl/"):
                        xml_path = "xl/" + xml_path
                    loaded[name] = self._read_sheet(archive.read(xml_path), shared)
                self._cache = loaded
        except (OSError, KeyError, ET.ParseError, zipfile.BadZipFile):
            self._cache = {}
        return self._cache

    @staticmethod
    def _read_sheet(raw: bytes, shared: list[str]) -> list[dict[str, Any]]:
        root = ET.fromstring(raw)
        matrix: list[dict[int, Any]] = []
        for row in root.findall("main:sheetData/main:row", _NS):
            values: dict[int, Any] = {}
            for cell in row.findall("main:c", _NS):
                index = _col_number(cell.attrib.get("r", "A1"))
                kind = cell.attrib.get("t")
                value_node = cell.find("main:v", _NS)
                value: Any = value_node.text if value_node is not None else ""
                if kind == "s":
                    try:
                        value = shared[int(value)]
                    except (ValueError, IndexError):
                        value = ""
                elif kind == "inlineStr":
                    value = "".join(node.text or "" for node in cell.iter() if node.tag.endswith("}t") or node.tag == "t")
                elif kind == "b":
                    value = value == "1"
                else:
                    try:
                        value = float(value) if "." in str(value) else int(value)
                    except (TypeError, ValueError):
                        pass
                values[index] = _clean(value)
            matrix.append(values)
        if not matrix:
            return []
        header = matrix[0]
        names = {index: str(value).strip() for index, value in header.items() if value is not None and str(value).strip()}
        result: list[dict[str, Any]] = []
        for values in matrix[1:]:
            row = {names[index]: value for index, value in values.items() if index in names}
            if row and any(value not in (None, "") for value in row.values()):
                result.append(row)
        return result

    def sheet_names(self) -> list[str]:
        return list(self._load().keys())

    @staticmethod
    def _first(row: dict[str, Any], candidates: tuple[str, ...]) -> Any:
        for key in candidates:
            if key in row and row[key] not in (None, ""):
                return row[key]
        return None

    @classmethod
    def _matches(cls, row: dict[str, Any], *, category: str | None, sku: str | None, channel: str | None) -> bool:
        values = {
            "category": cls._first(row, ("品类", "category", "category_name")),
            "sku": cls._first(row, ("型号", "型号-CRM最新名称", "sku", "product_mode_code", "product_mode_name")),
            "channel": cls._first(row, ("3级渠道", "channel_l3", "channel_name_l3")),
        }
        return all(
            expected is None or str(values[name] or "").strip() == str(expected).strip()
            for name, expected in (("category", category), ("sku", sku), ("channel", channel))
        )

    @staticmethod
    def _normalize_forecast_row(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        month = ExcelResultAdapter._first(row, ("预测月份", "月份", "forecast_month", "period"))
        result["预测月份"] = normalizer(month)
        horizon = ExcelResultAdapter._first(row, ("预测期", "horizon", "预测期序号"))
        if horizon is not None:
            text = str(horizon).strip()
            if text.isdigit():
                text = f"N+{int(text)}"
            match = re.search(r"(?:N\+)?0*(\d+)", text, re.IGNORECASE)
            result["预测期"] = f"N+{int(match.group(1))}" if match else text
        return result

    def extract_forecast(
        self,
        *,
        category: str | None = None,
        sku: str | None = None,
        channel: str | None = None,
        forecast_month: str | None = None,
    ) -> list[dict[str, Any]]:
        sheets = self._load()
        source_name = "预测详情" if "预测详情" in sheets else "result"
        expected_month = normalizer(forecast_month) if forecast_month else None
        rows: list[dict[str, Any]] = []
        for row in sheets.get(source_name, []):
            normalized = self._normalize_forecast_row(row)
            if not self._matches(normalized, category=category, sku=sku, channel=channel):
                continue
            if expected_month and normalized.get("预测月份") != expected_month:
                continue
            rows.append(normalized)
        return rows

    def extract_attribution(
        self,
        *,
        category: str | None = None,
        sku: str | None = None,
        channel: str | None = None,
        forecast_month: str | None = None,
    ) -> list[dict[str, Any]]:
        sheets = self._load()
        source_name = "白盒归因" if "白盒归因" in sheets else "归因映射"
        expected_month = normalizer(forecast_month) if forecast_month else None
        rows: list[dict[str, Any]] = []
        for row in sheets.get(source_name, []):
            normalized = dict(row)
            month = self._first(row, ("预测月份", "月份", "forecast_month", "period"))
            normalized["预测月份"] = normalizer(month)
            if not self._matches(normalized, category=category, sku=sku, channel=channel):
                continue
            if expected_month and normalized.get("预测月份") != expected_month:
                continue
            rows.append(normalized)
        return rows


__all__ = ["ExcelResultAdapter", "SHEETS", "normalizer"]
