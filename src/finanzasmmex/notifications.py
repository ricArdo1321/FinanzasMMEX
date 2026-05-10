from dataclasses import dataclass
from datetime import UTC, date, datetime

from .models import CanonicalTx

NOTIFY_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class NotificationResult:
    sent: bool
    delivery: str
    needs_review_count: int
    payload: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "sent": self.sent,
            "delivery": self.delivery,
            "needs_review_count": self.needs_review_count,
            "payload": self.payload,
        }


def build_needs_review_payload(
    transactions: list[CanonicalTx],
    *,
    report_path: str | None = None,
) -> dict[str, object]:
    dates = sorted(filter(None, (_tx_date(tx) for tx in transactions)))
    by_status: dict[str, int] = {}
    for tx in transactions:
        by_status[tx.mmex_status] = by_status.get(tx.mmex_status, 0) + 1

    return {
        "event": "finanzasmmex.needs_review",
        "schema_version": NOTIFY_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "summary": {
            "count": len(transactions),
            "by_status": dict(sorted(by_status.items())),
            "oldest_date": dates[0].isoformat() if dates else None,
            "newest_date": dates[-1].isoformat() if dates else None,
        },
        "report_path": report_path,
    }


def notify_needs_review(
    transactions: list[CanonicalTx],
    *,
    report_path: str | None = None,
) -> NotificationResult:
    payload = build_needs_review_payload(transactions, report_path=report_path)
    return NotificationResult(
        sent=False,
        delivery="local_envelope",
        needs_review_count=len(transactions),
        payload=payload,
    )


def _tx_date(tx: CanonicalTx) -> date | None:
    return tx.posted_date or tx.booking_date or tx.event_date
