from pathlib import Path

_DANGEROUS_SUFFIXES = {".mmb", ".emb"}


def safe_output_path(
    output_path: str | Path,
    *,
    allowed_suffixes: set[str],
) -> Path:
    path = Path(output_path).expanduser().resolve(strict=False)
    suffix = path.suffix.lower()

    if suffix in _DANGEROUS_SUFFIXES:
        raise ValueError("Refusing to write generated artifact to MMEX database path")
    if suffix not in {item.lower() for item in allowed_suffixes}:
        allowed = ", ".join(sorted(allowed_suffixes))
        raise ValueError(f"Output path must end with one of: {allowed}")
    return path
