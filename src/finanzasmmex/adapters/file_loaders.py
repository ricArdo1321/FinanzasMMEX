import hashlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from ..etl.categorize import CategoryRule
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
