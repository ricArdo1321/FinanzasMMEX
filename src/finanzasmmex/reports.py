import calendar
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from html import escape
from pathlib import Path

from .artifacts import safe_output_path
from .models import CanonicalTx
from .staging.repo import StagingRepo

MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
MONTHLY_REPORT_LIMIT = 100_000


@dataclass(frozen=True)
class Aggregate:
    key: str
    count: int
    debit: Decimal
    credit: Decimal

    @property
    def net(self) -> Decimal:
        return self.credit - self.debit

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "count": self.count,
            "debit": _money(self.debit),
            "credit": _money(self.credit),
            "net": _money(self.net),
        }


def generate_monthly_dashboard(
    repo: StagingRepo,
    *,
    month: str,
    reports_dir: str | Path,
    output_path: str | Path | None = None,
) -> dict[str, object]:
    period_start, period_end = month_bounds(month)
    transactions = repo.list_txs(
        since=period_start.isoformat(),
        until=period_end.isoformat(),
        limit=MONTHLY_REPORT_LIMIT,
    )
    summary = monthly_dashboard_summary(
        transactions,
        month=month,
        period_start=period_start,
        period_end=period_end,
    )
    path = monthly_dashboard_path(
        month=month,
        reports_dir=reports_dir,
        output_path=output_path,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_monthly_dashboard(summary), encoding="utf-8")

    return {
        "month": month,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "report_path": str(path),
        **summary,
    }


def monthly_dashboard_summary(
    transactions: list[CanonicalTx],
    *,
    month: str,
    period_start: date,
    period_end: date,
) -> dict[str, object]:
    debit_total = sum(
        (tx.amount for tx in transactions if tx.direction == "debit"),
        Decimal("0.00"),
    )
    credit_total = sum(
        (tx.amount for tx in transactions if tx.direction == "credit"),
        Decimal("0.00"),
    )
    review_txs = [tx for tx in transactions if tx.needs_review]
    status_counts: dict[str, int] = {}
    for tx in transactions:
        status_counts[tx.mmex_status] = status_counts.get(tx.mmex_status, 0) + 1

    aggregations = {
        "category": [
            item.as_dict()
            for item in _aggregate_by(
                transactions,
                lambda tx: tx.category_guess or "Sin categoria",
            )
        ],
        "tag": [
            item.as_dict()
            for item in _aggregate_by_many(
                transactions,
                lambda tx: tx.tags if tx.tags else ["Sin tag"],
            )
        ],
        "merchant": [
            item.as_dict()
            for item in _aggregate_by(
                transactions,
                lambda tx: tx.merchant_norm or tx.merchant_raw or "Sin comercio",
            )
        ],
        "account": [
            item.as_dict()
            for item in _aggregate_by(
                transactions,
                lambda tx: tx.account_alias or "Sin cuenta",
            )
        ],
    }

    return {
        "items_count": len(transactions),
        "totals": {
            "debit": _money(debit_total),
            "credit": _money(credit_total),
            "net": _money(credit_total - debit_total),
        },
        "needs_review": {
            "count": len(review_txs),
            "debit": _money(
                sum(
                    (tx.amount for tx in review_txs if tx.direction == "debit"),
                    Decimal("0.00"),
                )
            ),
            "credit": _money(
                sum(
                    (tx.amount for tx in review_txs if tx.direction == "credit"),
                    Decimal("0.00"),
                )
            ),
        },
        "mmex_status_counts": dict(sorted(status_counts.items())),
        "aggregations": aggregations,
        "dashboard": {
            "month": month,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
        },
    }


def month_bounds(month: str) -> tuple[date, date]:
    if not MONTH_RE.fullmatch(month):
        raise ValueError("--month must use YYYY-MM format")
    year_text, month_text = month.split("-")
    year = int(year_text)
    month_number = int(month_text)
    if month_number < 1 or month_number > 12:
        raise ValueError("--month must use a valid month from 01 to 12")
    last_day = calendar.monthrange(year, month_number)[1]
    return date(year, month_number, 1), date(year, month_number, last_day)


def monthly_dashboard_path(
    *,
    month: str,
    reports_dir: str | Path,
    output_path: str | Path | None = None,
) -> Path:
    month_bounds(month)
    root = Path(reports_dir).expanduser().resolve(strict=False)
    raw_path = Path(output_path) if output_path is not None else Path(
        f"dashboard_{month}.html"
    )
    path = raw_path if raw_path.is_absolute() else root / raw_path
    safe_path = safe_output_path(path, allowed_suffixes={".html", ".htm"})
    try:
        safe_path.relative_to(root)
    except ValueError as exc:
        raise ValueError("Report output must stay under the reports directory") from exc
    return safe_path


def list_monthly_dashboards(reports_dir: str | Path) -> dict[str, object]:
    root = Path(reports_dir).expanduser().resolve(strict=False)
    reports = [_report_file_to_dict(path) for path in root.glob("dashboard_*.html")]
    reports = [report for report in reports if report["month"] is not None]
    reports.sort(key=lambda report: str(report["month"]), reverse=True)
    return {
        "reports_dir": str(root),
        "count": len(reports),
        "reports": reports,
    }


def latest_monthly_dashboard(reports_dir: str | Path) -> dict[str, object]:
    data = list_monthly_dashboards(reports_dir)
    reports = data["reports"]
    assert isinstance(reports, list)
    latest = reports[0] if reports else None
    return {
        "reports_dir": data["reports_dir"],
        "report": latest,
    }


def render_monthly_dashboard(summary: dict[str, object]) -> str:
    dashboard = _expect_dict(summary["dashboard"])
    month = str(dashboard["month"])
    period_start = str(dashboard["period_start"])
    period_end = str(dashboard["period_end"])
    items_count = _expect_int(summary["items_count"])
    totals = _expect_dict(summary["totals"])
    needs_review = _expect_dict(summary["needs_review"])
    status_counts = _expect_dict(summary["mmex_status_counts"])
    aggregations = _expect_dict(summary["aggregations"])

    empty = (
        "<p class=\"empty\">Sin movimientos para este periodo.</p>"
        if items_count == 0
        else ""
    )
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>FinanzasMMEX Dashboard {escape(month)}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 32px; color: #222; }}
    h1, h2 {{ margin-bottom: 8px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 28px; }}
    th, td {{ border-bottom: 1px solid #ddd; padding: 8px; text-align: left; }}
    th {{ background: #f3f5f7; }}
    .metrics {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }}
    .metric {{ border: 1px solid #ddd; padding: 12px; }}
    .label {{ color: #555; font-size: 12px; text-transform: uppercase; }}
    .value {{ font-size: 20px; margin-top: 4px; }}
    .empty {{ padding: 16px; background: #f8f8f8; }}
  </style>
</head>
<body>
  <h1>FinanzasMMEX Dashboard {escape(month)}</h1>
  <p>{escape(period_start)} al {escape(period_end)}</p>
  <section class="metrics">
    {_metric("Movimientos", str(items_count))}
    {_metric("Debitos", str(totals["debit"]))}
    {_metric("Creditos", str(totals["credit"]))}
    {_metric("Neto", str(totals["net"]))}
  </section>
  {empty}
  <h2>Revision</h2>
  <section class="metrics">
    {_metric("Needs review", str(needs_review["count"]))}
    {_metric("Debitos en revision", str(needs_review["debit"]))}
    {_metric("Creditos en revision", str(needs_review["credit"]))}
    {_metric("Estados MMEX", str(len(status_counts)))}
  </section>
  {_status_table(status_counts)}
  {_aggregate_table("Por categoria", _expect_list(aggregations["category"]))}
  {_aggregate_table("Por tag", _expect_list(aggregations["tag"]))}
  {_aggregate_table("Por comercio", _expect_list(aggregations["merchant"]))}
  {_aggregate_table("Por cuenta", _expect_list(aggregations["account"]))}
</body>
</html>
"""


def _aggregate_by(
    transactions: list[CanonicalTx],
    key_fn: Callable[[CanonicalTx], str],
) -> list[Aggregate]:
    grouped: dict[str, tuple[int, Decimal, Decimal]] = {}
    for tx in transactions:
        _add_to_group(grouped, key_fn(tx), tx)
    return _sorted_aggregates(grouped)


def _aggregate_by_many(
    transactions: list[CanonicalTx],
    key_fn: Callable[[CanonicalTx], list[str]],
) -> list[Aggregate]:
    grouped: dict[str, tuple[int, Decimal, Decimal]] = {}
    for tx in transactions:
        for key in key_fn(tx):
            _add_to_group(grouped, key, tx)
    return _sorted_aggregates(grouped)


def _add_to_group(
    grouped: dict[str, tuple[int, Decimal, Decimal]],
    key: str,
    tx: CanonicalTx,
) -> None:
    count, debit, credit = grouped.get(key, (0, Decimal("0.00"), Decimal("0.00")))
    if tx.direction == "credit":
        credit += tx.amount
    else:
        debit += tx.amount
    grouped[key] = (count + 1, debit, credit)


def _sorted_aggregates(
    grouped: dict[str, tuple[int, Decimal, Decimal]],
) -> list[Aggregate]:
    items = [
        Aggregate(key=key, count=count, debit=debit, credit=credit)
        for key, (count, debit, credit) in grouped.items()
    ]
    return sorted(
        items,
        key=lambda item: (abs(item.net), item.count, item.key),
        reverse=True,
    )


def _report_file_to_dict(path: Path) -> dict[str, object]:
    month = _month_from_report_name(path.name)
    return {
        "month": month,
        "report_path": str(path.resolve(strict=False)),
        "filename": path.name,
        "modified_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(
            timespec="seconds"
        ),
    }


def _month_from_report_name(filename: str) -> str | None:
    prefix = "dashboard_"
    suffix = ".html"
    if not filename.startswith(prefix) or not filename.endswith(suffix):
        return None
    month = filename[len(prefix) : -len(suffix)]
    if not MONTH_RE.fullmatch(month):
        return None
    return month


def _metric(label: str, value: str) -> str:
    return (
        "<div class=\"metric\">"
        f"<div class=\"label\">{escape(label)}</div>"
        f"<div class=\"value\">{escape(value)}</div>"
        "</div>"
    )


def _status_table(status_counts: dict[str, object]) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{escape(str(status))}</td>"
        f"<td>{escape(str(count))}</td>"
        "</tr>"
        for status, count in sorted(status_counts.items())
    )
    return (
        "<h2>Estados MMEX</h2>"
        "<table><thead><tr><th>Estado</th><th>Cantidad</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _aggregate_table(title: str, rows: list[object]) -> str:
    body = "".join(_aggregate_row(row) for row in rows)
    return (
        f"<h2>{escape(title)}</h2>"
        "<table><thead><tr><th>Grupo</th><th>Cantidad</th><th>Debito</th>"
        "<th>Credito</th><th>Neto</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def _aggregate_row(row: object) -> str:
    item = _expect_dict(row)
    return (
        "<tr>"
        f"<td>{escape(str(item['key']))}</td>"
        f"<td>{escape(str(item['count']))}</td>"
        f"<td>{escape(str(item['debit']))}</td>"
        f"<td>{escape(str(item['credit']))}</td>"
        f"<td>{escape(str(item['net']))}</td>"
        "</tr>"
    )


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"


def _expect_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError("Expected dashboard dict")
    return value


def _expect_list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise TypeError("Expected dashboard list")
    return value


def _expect_int(value: object) -> int:
    if not isinstance(value, int):
        raise TypeError("Expected dashboard int")
    return value
