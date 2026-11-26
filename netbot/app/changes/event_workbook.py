"""Read only the supported Wi-Fi columns of an event workbook."""
from collections import Counter
from dataclasses import dataclass, field
from io import BytesIO
import posixpath
import re
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile
from zlib import error as ZipDataError

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from app.core.errors import InvalidInput, PayloadTooLarge

_SHEET = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_HEADERS = {"evento": "event", "wifi / ssid": "ssid"}
_CELL = re.compile(r"([A-Z]+)([1-9][0-9]*)")


@dataclass
class EventWifiRow:
    number: int
    event: str
    ssid: str
    errors: list[str] = field(default_factory=list)


def _xml(archive, path):
    limit = 4 * 1024 * 1024
    with archive.open(path) as member:
        content = member.read(limit + 1)
    if len(content) > limit:
        raise PayloadTooLarge("Una sección del Excel supera el tamaño admitido.")
    text = content.decode("utf-8-sig")
    if "\x00" in text:
        raise InvalidInput("El Excel contiene XML no admitido.")
    try:
        return ElementTree.fromstring(text, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except DefusedXmlException:
        raise InvalidInput("El Excel contiene XML no admitido.") from None


def _sheet(archive):
    workbook = _xml(archive, "xl/workbook.xml")
    history = [
        sheet for sheet in workbook.findall(f"{_SHEET}sheets/{_SHEET}sheet")
        if sheet.get("name", "").strip().casefold() in {"histórico", "historico"}
    ]
    if len(history) != 1:
        raise InvalidInput("El Excel debe contener una hoja Histórico.")
    relations = _xml(archive, "xl/_rels/workbook.xml.rels")
    relation = next(item for item in relations if item.get("Id") == history[0].get(_REL_ID))
    if relation.get("TargetMode") == "External" or not relation.get("Type", "").endswith("/worksheet"):
        raise ValueError()
    target = relation.attrib["Target"]
    path = posixpath.normpath(target.lstrip("/") if target.startswith("/") else f"xl/{target}")
    if not path.startswith("xl/worksheets/"):
        raise ValueError()
    return _xml(archive, path)


def _cell_text(cell, strings):
    value = cell.findtext(f"{_SHEET}v", "")
    if cell.get("t") == "s":
        index = int(value)
        if index < 0:
            raise ValueError()
        return strings[index].strip()
    if cell.get("t") == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{_SHEET}t")).strip()
    return value.strip()


def _rows(sheet, strings, max_rows):
    records = iter(sheet.findall(f"{_SHEET}sheetData/{_SHEET}row"))
    header = next(records)
    columns = {}
    for cell in header.findall(f"{_SHEET}c"):
        name = _HEADERS.get(_cell_text(cell, strings).casefold())
        if name:
            column = _CELL.fullmatch(cell.attrib["r"]).group(1)
            if name in columns.values() or column in columns:
                raise InvalidInput("El encabezado de Histórico contiene columnas duplicadas.")
            columns[column] = name
    if set(columns.values()) != set(_HEADERS.values()):
        raise InvalidInput("Histórico requiere las columnas Evento y WiFi / SSID.")

    rows = []
    for record in records:
        values = {}
        formulas = set()
        for cell in record.findall(f"{_SHEET}c"):
            reference = _CELL.fullmatch(cell.attrib["r"])
            if reference is None:
                raise ValueError()
            name = columns.get(reference.group(1))
            if name is None:
                continue
            if name in values:
                raise ValueError()
            values[name] = _cell_text(cell, strings)
            if cell.find(f"{_SHEET}f") is not None:
                formulas.add(name)
        ssid = values.get("ssid", "")
        if not ssid and "ssid" not in formulas:
            continue
        if len(rows) >= max_rows:
            raise PayloadTooLarge("El Excel supera el número máximo de filas Wi-Fi.")
        row = EventWifiRow(int(record.attrib["r"]), values.get("event", ""), ssid)
        if formulas:
            row.errors.append("Usa valores, sin fórmulas, en Evento y WiFi / SSID.")
        if not row.event:
            row.errors.append("Indica el evento.")
        rows.append(row)

    if not rows:
        raise InvalidInput("Histórico no contiene filas con SSID.")
    numbers = {row.number for row in rows}
    if len(numbers) != len(rows) or min(numbers) < 2 or max(numbers) > 1048576:
        raise ValueError()
    counts = Counter((row.event.casefold(), row.ssid.casefold()) for row in rows if not row.errors)
    for row in rows:
        if counts[row.event.casefold(), row.ssid.casefold()] > 1:
            row.errors.append("El SSID se repite para el mismo evento en el Excel.")
    return sorted(rows, key=lambda row: row.number)


def parse_event_workbook(content: bytes, *, max_bytes: int, max_rows: int) -> list[EventWifiRow]:
    if len(content) > max_bytes:
        raise PayloadTooLarge("El Excel supera el tamaño máximo permitido.")
    try:
        with ZipFile(BytesIO(content)) as archive:
            sheet = _sheet(archive)
            strings = []
            if "xl/sharedStrings.xml" in archive.namelist():
                table = _xml(archive, "xl/sharedStrings.xml")
                strings = [
                    "".join(node.text or "" for node in item.iter(f"{_SHEET}t"))
                    for item in table.findall(f"{_SHEET}si")
                ]
            return _rows(sheet, strings, max_rows)
    except (BadZipFile, ParseError, KeyError, IndexError, ValueError, AttributeError,
            RuntimeError, StopIteration, ZipDataError):
        raise InvalidInput("El archivo no es un Excel XLSX válido con la estructura esperada.") from None
