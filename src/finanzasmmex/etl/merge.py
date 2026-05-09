import logging
from dataclasses import replace
from datetime import date, timedelta

from rapidfuzz import fuzz

from ..models import CanonicalTx
from ..staging.repo import StagingRepo

logger = logging.getLogger(__name__)


def merge_scraped_txs(
    repo: StagingRepo, scraped_txs: list[CanonicalTx], window_days: int = 14
) -> list[CanonicalTx]:
    """
    Merge scraped transactions into staging.db, enriching existing ones if found.
    """
    merged_results = []

    for scraped in scraped_txs:
        # 1. Search for candidates in staging.db within a time window
        scraped_date = _tx_date(scraped)
        date_from = scraped_date - timedelta(days=window_days)
        date_to = scraped_date + timedelta(days=window_days)

        candidates = repo.list_txs(
            account_alias=scraped.account_alias,
            since=date_from.isoformat(),
            until=date_to.isoformat(),
        )

        best_match: CanonicalTx | None = None
        best_score = 0.0

        for candidate in candidates:
            # Match amount exactly
            if candidate.amount != scraped.amount:
                continue

            # Match direction
            if candidate.direction != scraped.direction:
                continue

            # Match merchant similarity
            name_a = (candidate.merchant_norm or candidate.merchant_raw).upper()
            name_b = scraped.merchant_raw.upper()

            score = fuzz.token_set_ratio(name_a, name_b)

            # Use a higher threshold for automated merging
            if score >= 80.0 and score > best_score:
                best_match = candidate
                best_score = score

        if best_match:
            logger.info(
                "Matched scraped tx with existing: %s (score %s)",
                best_match.tx_uid,
                best_score,
            )
            enriched = _enrich_tx(best_match, scraped)
            merged_results.append(enriched)
        else:
            logger.info(f"No match found for scraped tx: {scraped.merchant_raw}")
            merged_results.append(scraped)

    return merged_results


def _enrich_tx(existing: CanonicalTx, scraped: CanonicalTx) -> CanonicalTx:
    """Enrich an existing transaction with data from a scraped one."""

    # Priority for date:
    # We want to keep the date that determines the FITID if it's already set.
    # But if the scraped date is more 'official' (extract date), we might want it.
    # Rule: If we have an event_date, we can safely update posted_date.
    # If we ONLY have posted_date, changing it changes the FITID.

    new_posted_date = existing.posted_date
    if existing.event_date or existing.booking_date:
        # Safe to update posted_date as it won't break FITID
        new_posted_date = scraped.posted_date

    return replace(
        existing,
        posted_date=new_posted_date,
        source_ref=f"{existing.source_ref or ''}|{scraped.source_ref or ''}".strip("|"),
    )


def _tx_date(tx: CanonicalTx) -> date:
    tx_date = tx.posted_date or tx.booking_date or tx.event_date
    if tx_date is None:
        raise ValueError("Cannot merge scraped transaction without a date")
    return tx_date
