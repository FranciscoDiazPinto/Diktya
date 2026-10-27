"""CSV de propuestas locales. No persiste el archivo ni envía su contenido al LLM."""
import csv
import io
from collections import Counter

from pydantic import ValidationError
from app.core.errors import InvalidInput, PayloadTooLarge
from .schemas import VlanReservationCreate
from .csv_schemas import CsvRow

COLUMNS = ("parent_interface", "tag", "event_name", "purpose", "ssid")


def parse_csv(content: bytes, *, max_bytes: int, max_rows: int) -> list[CsvRow]:
    if len(content) > max_bytes:
        raise PayloadTooLarge("El CSV supera el tamaño máximo permitido.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InvalidInput("El CSV debe estar codificado en UTF-8.") from None
    if not text.strip() or "\x00" in text:
        raise InvalidInput("El CSV está vacío o contiene caracteres no admitidos.")
    reader = None
    # Identificar separador por encabezados, sin adivinar a partir de los datos.
    for delimiter in (",", ";"):
        candidate = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
        try:
            header = [name.strip() for name in next(candidate)]
        except (StopIteration, csv.Error):
            continue
        if len(header) == len(COLUMNS) and set(header) == set(COLUMNS):
            reader = candidate
            break
    if reader is None:
        raise InvalidInput("Encabezados requeridos, sin columnas adicionales ni contraseñas: " + ", ".join(COLUMNS))
    rows = []
    try:
        while True:
            row_number = reader.line_num + 1
            try:
                cells = next(reader)
            except StopIteration:
                break
            if not cells or all(not cell.strip() for cell in cells):
                continue
            if len(rows) >= max_rows:
                raise PayloadTooLarge("El CSV supera el número máximo de filas permitido.")
            if len(cells) != len(header):
                rows.append(CsvRow(row_number=row_number, errors=["La cantidad de columnas no coincide con el encabezado."]))
                continue
            values = dict(zip(header, (cell.strip() for cell in cells)))
            errors = []
            if not values["tag"].isascii() or not values["tag"].isdecimal():
                errors.append("tag debe ser un entero entre 1 y 4094.")
            if not 1 <= len(values["ssid"].encode("utf-8")) <= 32:
                errors.append("ssid debe ocupar entre 1 y 32 bytes UTF-8.")
            try:
                data = VlanReservationCreate.model_validate(values)
            except ValidationError as exc:
                # No devolver los inputs ni representaciones crudas de errores.
                fields = sorted({str(error["loc"][0]) for error in exc.errors()})
                errors.append("Campos inválidos: " + ", ".join(fields) + ".")
                data = None
            rows.append(CsvRow(row_number=row_number, data=data if not errors else None, errors=errors))
    except csv.Error:
        raise InvalidInput("El CSV tiene comillas inválidas o un campo demasiado largo.") from None
    if not rows:
        raise InvalidInput("El CSV no contiene filas de datos.")
    keys = Counter((r.data.parent_interface, r.data.tag) for r in rows if r.data)
    ssids = Counter(r.data.ssid for r in rows if r.data)
    for row in rows:
        if row.data:
            if keys[row.data.parent_interface, row.data.tag] > 1:
                row.errors.append("La VLAN se repite en el archivo.")
            if ssids[row.data.ssid] > 1:
                row.errors.append("El SSID se repite en el archivo.")
    return rows
