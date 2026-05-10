import csv
import hashlib
import io
import re
import zipfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal
from xml.etree import ElementTree

from ..etl.categorize import CategoryRule
from ..etl.normalize import normalize_merchant, parse_clp_amount
from ..etl.pipeline import prepare_batch_for_staging
from ..models import CanonicalTx

FileSourceType = Literal["ofx", "qif", "csv", "xlsx", "pdf"]
FileParser = Callable[[Path], Iterable[CanonicalTx]]

PLANNED_DROP_EXTENSIONS: Mapping[str, FileSourceType] = {
    ".ofx": "ofx",
    ".qif": "qif",
    ".csv": "csv",
    ".xlsx": "xlsx",
    ".pdf": "pdf",
}

FILE_LOADERS: dict[str, FileParser] = {}
_DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y%m%d", "%d/%m/%y")


@dataclass(frozen=True)
class FileLoadResult:
    source_path: str
    source_type: FileSourceType
    content_sha256: str
    transactions: list[CanonicalTx]


class FileLoaderError(ValueError):
    error_code = "FILE_LOADER_ERROR"
    exit_code = 2

    def __init__(self, message: str, *, details: dict[str, object] | None = None):
        super().__init__(message)
        self.details = details or {}


class FileLoaderUnsupportedError(FileLoaderError):
    error_code = "FILE_LOADER_UNSUPPORTED"


class FileLoaderAmbiguousError(FileLoaderError):
    error_code = "FILE_LOADER_AMBIGUOUS"


class FileLoaderCorruptError(FileLoaderError):
    error_code = "FILE_LOADER_CORRUPT"


class FileLoaderTemporaryError(FileLoaderError):
    error_code = "FILE_LOADER_TEMPORARY"
    exit_code = 5


def register_file_loader(extension: str, parser: FileParser) -> None:
    normalized = _normalize_extension(extension)
    if normalized not in PLANNED_DROP_EXTENSIONS:
        raise FileLoaderUnsupportedError(
            f"Unsupported drop file extension: {normalized}",
            details={
                "extension": normalized,
                "supported_extensions": sorted(PLANNED_DROP_EXTENSIONS),
            },
        )
    FILE_LOADERS[normalized] = parser


def detect_source_type(path: str | Path) -> FileSourceType:
    candidate = Path(path)
    extension = _normalize_extension(candidate.suffix)
    source_type = PLANNED_DROP_EXTENSIONS.get(extension)
    if source_type is None:
        raise FileLoaderUnsupportedError(
            f"Unsupported drop file extension: {extension or '<none>'}",
            details={
                "path": str(candidate),
                "extension": extension,
                "supported_extensions": sorted(PLANNED_DROP_EXTENSIONS),
            },
        )
    return source_type


def load_drop_file_for_staging(
    input_path: str | Path,
    *,
    rules: Iterable[CategoryRule] = (),
    loaders: Mapping[str, FileParser] | None = None,
) -> FileLoadResult:
    path = Path(input_path)
    source_type = detect_source_type(path)
    extension = _normalize_extension(path.suffix)
    registry = (
        {_normalize_extension(ext): parser for ext, parser in loaders.items()}
        if loaders is not None
        else FILE_LOADERS
    )
    parser = registry.get(extension)
    if parser is None:
        raise FileLoaderUnsupportedError(
            f"Loader for {extension} is not implemented yet",
            details={
                "path": str(path),
                "extension": extension,
                "source_type": source_type,
            },
        )
    return load_file_for_staging(
        path,
        source_type=source_type,
        parser=parser,
        rules=rules,
    )


def load_file_for_staging(
    input_path: str | Path,
    *,
    source_type: FileSourceType,
    parser: FileParser,
    rules: Iterable[CategoryRule] = (),
) -> FileLoadResult:
    path = Path(input_path)
    if not path.is_file():
        raise FileLoaderUnsupportedError(
            f"Drop input is not a readable file: {path}",
            details={"path": str(path)},
        )

    try:
        content = path.read_bytes()
    except OSError as exc:
        raise FileLoaderTemporaryError(
            f"Could not read drop file: {path}",
            details={"path": str(path), "exception_type": type(exc).__name__},
        ) from exc

    content_sha256 = hashlib.sha256(content).hexdigest()
    try:
        parsed = list(parser(path))
    except FileLoaderError:
        raise
    except ValueError as exc:
        raise FileLoaderCorruptError(
            str(exc),
            details={"path": str(path), "exception_type": type(exc).__name__},
        ) from exc
    except OSError as exc:
        raise FileLoaderTemporaryError(
            str(exc),
            details={"path": str(path), "exception_type": type(exc).__name__},
        ) from exc

    if not parsed:
        raise FileLoaderAmbiguousError(
            "No transactions could be extracted from drop file",
            details={"path": str(path), "source_type": source_type},
        )

    normalized = [
        replace(
            tx,
            source_type=source_type,
            source_file=tx.source_file or str(path),
            source_ref=tx.source_ref or path.name,
            content_sha256=tx.content_sha256 or content_sha256,
        )
        for tx in parsed
    ]
    prepared = prepare_batch_for_staging(normalized, rules=rules)
    return FileLoadResult(
        source_path=str(path),
        source_type=source_type,
        content_sha256=content_sha256,
        transactions=prepared,
    )


def _normalize_extension(extension: str) -> str:
    if not extension:
        return ""
    lowered = extension.lower()
    return lowered if lowered.startswith(".") else f".{lowered}"


def parse_ofx_file(path: Path) -> list[CanonicalTx]:
    text = path.read_text(encoding="utf-8", errors="replace")
    blocks = re.findall(
        r"<STMTTRN>(.*?)(?=<STMTTRN>|</BANKTRANLIST>|</OFX>)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not blocks:
        raise FileLoaderCorruptError(
            "OFX file does not contain STMTTRN transactions",
            details={"path": str(path)},
        )

    account_alias, account_review = _ofx_account_alias(text)
    transactions: list[CanonicalTx] = []
    for block in blocks:
        amount_raw = _required_tag(block, "TRNAMT", path)
        posted_raw = _required_tag(block, "DTPOSTED", path)
        amount, direction = _parse_signed_amount(amount_raw)
        merchant = _tag(block, "NAME") or _tag(block, "MEMO") or ""
        review_reasons = []
        if account_review:
            review_reasons.append(account_review)
        if not merchant:
            merchant = "OFX SIN COMERCIO"
            review_reasons.append("missing_merchant")
        transactions.append(
            CanonicalTx(
                source_type="ofx",
                source_ref=_tag(block, "FITID"),
                event_date=_parse_date(posted_raw),
                posted_date=_parse_date(posted_raw),
                amount=amount,
                direction=direction,
                account_alias=account_alias,
                merchant_raw=merchant,
                merchant_norm=normalize_merchant(merchant),
                tx_type=_tx_type_from_direction(direction),
                category_guess=_tag(block, "SIC"),
                parser_name="ofx_file",
                needs_review=bool(review_reasons),
                review_reason=";".join(review_reasons) or None,
            )
        )
    return transactions


def parse_qif_file(path: Path) -> list[CanonicalTx]:
    text = path.read_text(encoding="utf-8", errors="replace")
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("!"):
            continue
        if line == "^":
            if current:
                records.append(current)
                current = {}
            continue
        current[line[:1]] = line[1:].strip()
    if current:
        records.append(current)
    if not records:
        raise FileLoaderCorruptError(
            "QIF file does not contain transactions",
            details={"path": str(path)},
        )

    transactions: list[CanonicalTx] = []
    for record in records:
        amount, direction = _parse_signed_amount(_required_record(record, "T", path))
        tx_date = _parse_date(_required_record(record, "D", path))
        merchant = record.get("P") or record.get("M") or "QIF SIN COMERCIO"
        review_reasons = []
        if "P" not in record and "M" not in record:
            review_reasons.append("missing_merchant")
        transactions.append(
            CanonicalTx(
                source_type="qif",
                source_ref=record.get("N"),
                event_date=tx_date,
                posted_date=tx_date,
                amount=amount,
                direction=direction,
                account_alias="QIF_IMPORT",
                merchant_raw=merchant,
                merchant_norm=normalize_merchant(merchant),
                tx_type=_tx_type_from_direction(direction),
                category_guess=record.get("L"),
                parser_name="qif_file",
                needs_review=bool(review_reasons),
                review_reason=";".join(review_reasons) or None,
            )
        )
    return transactions


def parse_csv_file(path: Path) -> list[CanonicalTx]:
    text = path.read_text(encoding="utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise FileLoaderCorruptError(
            "CSV file is missing a header row",
            details={"path": str(path)},
        )
    rows = [_normalize_row(row) for row in reader]
    return _rows_to_transactions(
        rows,
        default_source_type="csv",
        parser_name="csv_file",
    )


def parse_xlsx_file(path: Path) -> list[CanonicalTx]:
    rows = _read_xlsx_rows(path)
    return _rows_to_transactions(
        rows,
        default_source_type="xlsx",
        parser_name="xlsx_file",
    )


def parse_pdf_file(path: Path) -> list[CanonicalTx]:
    text = _extract_pdf_text(path)
    rows = _text_table_rows(text, source_type="pdf")
    transactions = _rows_to_transactions(
        rows,
        default_source_type="pdf",
        parser_name="pdf_file",
    )
    content_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    return [
        replace(
            tx,
            content_sha256=content_sha256,
            raw_text="",
            needs_review=True,
            review_reason=_append_review_reason(
                tx.review_reason,
                "pdf_review_required",
            ),
        )
        for tx in transactions
    ]


def _rows_to_transactions(
    rows: list[dict[str, str]],
    *,
    default_source_type: FileSourceType,
    parser_name: str,
) -> list[CanonicalTx]:
    if not rows:
        raise FileLoaderCorruptError(
            f"{default_source_type.upper()} file does not contain data rows",
            details={"source_type": default_source_type},
        )
    transactions: list[CanonicalTx] = []
    for row in rows:
        date_raw = _first_value(row, "date", "fecha", "posted_date", "event_date")
        amount_raw = _first_value(row, "amount", "monto", "importe")
        merchant = _first_value(
            row,
            "merchant",
            "comercio",
            "descripcion",
            "description",
            "payee",
        )
        if date_raw is None or amount_raw is None:
            raise FileLoaderCorruptError(
                "File row is missing required date or amount columns",
                details={"source_type": default_source_type},
            )

        direction_hint = _first_value(row, "direction", "tipo", "cargo_abono")
        amount, direction = _parse_signed_amount(amount_raw, direction_hint)
        account_alias = _first_value(row, "account_alias", "account", "cuenta")
        review_reasons = []
        if not account_alias:
            account_alias = f"{default_source_type.upper()}_IMPORT"
            review_reasons.append("missing_account_alias")
        if not merchant:
            merchant = f"{default_source_type.upper()} SIN COMERCIO"
            review_reasons.append("missing_merchant")

        transactions.append(
            CanonicalTx(
                source_type=default_source_type,
                source_ref=_first_value(row, "source_ref", "id", "fitid"),
                event_date=_parse_date(date_raw),
                posted_date=_parse_date(date_raw),
                amount=amount,
                direction=direction,
                account_alias=account_alias,
                merchant_raw=merchant,
                merchant_norm=normalize_merchant(merchant),
                tx_type=_tx_type_from_direction(direction),
                category_guess=_first_value(row, "category", "categoria"),
                subcategory_guess=_first_value(row, "subcategory", "subcategoria"),
                tags=_split_tags(_first_value(row, "tags", "etiquetas")),
                parser_name=parser_name,
                needs_review=bool(review_reasons),
                review_reason=";".join(review_reasons) or None,
            )
        )
    return transactions


def _ofx_account_alias(text: str) -> tuple[str, str | None]:
    account = _tag(text, "ACCTID")
    if not account:
        return "OFX_IMPORT", "missing_account_alias"
    cleaned = re.sub(r"\W+", "_", account).strip("_")
    return f"OFX_{cleaned or 'IMPORT'}", None


def _tag(text: str, name: str) -> str | None:
    match = re.search(rf"<{name}>([^\r\n<]+)", text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


def _required_tag(text: str, name: str, path: Path) -> str:
    value = _tag(text, name)
    if not value:
        raise FileLoaderCorruptError(
            f"OFX transaction is missing {name}",
            details={"path": str(path), "tag": name},
        )
    return value


def _required_record(record: dict[str, str], key: str, path: Path) -> str:
    value = record.get(key)
    if not value:
        raise FileLoaderCorruptError(
            f"QIF transaction is missing {key}",
            details={"path": str(path), "field": key},
        )
    return value


def _parse_signed_amount(
    raw: str,
    direction_hint: str | None = None,
) -> tuple[Decimal, Literal["debit", "credit"]]:
    negative = raw.strip().startswith("-") or raw.strip().startswith("(")
    amount = _parse_absolute_amount(raw)
    direction = _parse_direction(direction_hint) if direction_hint else None
    if direction is None:
        direction = "debit" if negative else "credit"
    return amount, direction


def _parse_absolute_amount(raw: str) -> Decimal:
    cleaned = raw.strip()
    negative_chars = "-()"
    for char in negative_chars:
        cleaned = cleaned.replace(char, "")
    try:
        if "." in cleaned and len(cleaned.rsplit(".", 1)[1]) == 2:
            value = Decimal(cleaned.replace(",", "").replace("$", "").strip())
            if value <= 0:
                raise ValueError("amount must be positive")
            return value.quantize(Decimal("0.01"))
    except InvalidOperation:
        pass
    return parse_clp_amount(cleaned)


def _parse_direction(raw: str | None) -> Literal["debit", "credit"] | None:
    if raw is None:
        return None
    value = normalize_merchant(raw)
    if value in {"DEBIT", "DEBITO", "CARGO", "EGRESO", "COMPRA"}:
        return "debit"
    if value in {"CREDIT", "CREDITO", "ABONO", "INGRESO", "DEPOSITO"}:
        return "credit"
    return None


def _tx_type_from_direction(
    direction: Literal["debit", "credit"],
) -> Literal["purchase", "transfer_in"]:
    return "purchase" if direction == "debit" else "transfer_in"


def _parse_date(raw: str) -> date:
    value = raw.strip()
    if len(value) >= 8 and value[:8].isdigit():
        value = value[:8]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    try:
        serial = int(value)
    except ValueError as exc:
        raise FileLoaderCorruptError(
            f"Unsupported date format: {raw}",
            details={"value": raw},
        ) from exc
    return date(1899, 12, 30) + timedelta(days=serial)


def _normalize_row(row: Mapping[str, str | None]) -> dict[str, str]:
    return {
        _normalize_header(key): (value or "").strip()
        for key, value in row.items()
        if key is not None
    }


def _normalize_header(value: str) -> str:
    return normalize_merchant(value).lower().replace(" ", "_")


def _first_value(row: Mapping[str, str], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value:
            return value
    return None


def _split_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in re.split(r"[;,]", raw) if item.strip()]


def _append_review_reason(existing: str | None, reason: str) -> str:
    parts = [part for part in (existing or "").split(";") if part]
    if reason not in parts:
        parts.append(reason)
    return ";".join(parts)


def _extract_pdf_text(path: Path) -> str:
    text = ""
    try:
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
            if text.strip():
                return text
    except Exception:
        text = ""

    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return path.read_bytes().decode("latin-1", errors="ignore")


def _text_table_rows(text: str, *, source_type: FileSourceType) -> list[dict[str, str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    table_start = next(
        (
            index
            for index, line in enumerate(lines)
            if "fecha" in normalize_merchant(line).lower()
            and "monto" in normalize_merchant(line).lower()
        ),
        None,
    )
    if table_start is None:
        raise FileLoaderCorruptError(
            "PDF text does not contain a supported transaction table",
            details={"source_type": source_type},
        )
    header = lines[table_start]
    delimiter = ";" if header.count(";") >= 2 else ","
    table_lines = []
    for line in lines[table_start:]:
        if line.startswith("%") and line != header:
            break
        if line.count(delimiter) >= 1:
            table_lines.append(line)
    table = "\n".join(table_lines)
    reader = csv.DictReader(io.StringIO(table), delimiter=delimiter)
    if reader.fieldnames is None:
        raise FileLoaderCorruptError(
            "PDF transaction table is missing headers",
            details={"source_type": source_type},
        )
    return [_normalize_row(row) for row in reader]


def _read_xlsx_rows(path: Path) -> list[dict[str, str]]:
    try:
        with zipfile.ZipFile(path) as archive:
            shared_strings = _xlsx_shared_strings(archive)
            sheet_xml = archive.read("xl/worksheets/sheet1.xml")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise FileLoaderCorruptError(
            "XLSX file is missing workbook parts",
            details={"path": str(path), "exception_type": type(exc).__name__},
        ) from exc

    root = ElementTree.fromstring(sheet_xml)
    rows: list[list[str]] = []
    for row in root.findall(".//{*}row"):
        values: list[str] = []
        for cell in row.findall("{*}c"):
            index = _xlsx_column_index(cell.attrib.get("r", ""))
            while len(values) <= index:
                values.append("")
            values[index] = _xlsx_cell_value(cell, shared_strings)
        rows.append(values)
    if not rows:
        return []
    headers = [_normalize_header(value) for value in rows[0]]
    return [
        {
            headers[index]: value.strip()
            for index, value in enumerate(row)
            if index < len(headers) and headers[index]
        }
        for row in rows[1:]
        if any(value.strip() for value in row)
    ]


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        raw = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ElementTree.fromstring(raw)
    strings: list[str] = []
    for item in root.findall(".//{*}si"):
        strings.append("".join(node.text or "" for node in item.findall(".//{*}t")))
    return strings


def _xlsx_cell_value(cell: ElementTree.Element, shared_strings: list[str]) -> str:
    if cell.attrib.get("t") == "s":
        raw_index = cell.findtext("{*}v")
        if raw_index is None:
            return ""
        index = int(raw_index)
        return shared_strings[index] if index < len(shared_strings) else ""
    if cell.attrib.get("t") == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//{*}t"))
    return cell.findtext("{*}v") or ""


def _xlsx_column_index(reference: str) -> int:
    letters = "".join(char for char in reference if char.isalpha())
    if not letters:
        return 0
    value = 0
    for char in letters.upper():
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value - 1


register_file_loader(".ofx", parse_ofx_file)
register_file_loader(".qif", parse_qif_file)
register_file_loader(".csv", parse_csv_file)
register_file_loader(".xlsx", parse_xlsx_file)
register_file_loader(".pdf", parse_pdf_file)
