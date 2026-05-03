from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from finanzasmmex.models import CanonicalTx
from finanzasmmex.writer.ofx_export import render_ofx, write_ofx


def make_tx() -> CanonicalTx:
    return CanonicalTx(
        owner="ricardo",
        source_type="email",
        content_sha256="abc",
        posted_date=date(2026, 5, 2),
        amount=Decimal("12340.00"),
        direction="debit",
        account_alias="BE_Ricardo_1234",
        merchant_raw="COMERCIO DEMO",
        merchant_norm="COMERCIO DEMO",
        tx_type="purchase",
        parser_name="be_email_v1",
        parser_version="1.0",
        fitid_synthetic="fitid-demo",
    )


def test_render_ofx_uses_fitid_and_signed_debit_amount() -> None:
    ofx = render_ofx([make_tx()])

    assert "<FITID>fitid-demo" in ofx
    assert "<TRNAMT>-12340.00" in ofx
    assert "<NAME>COMERCIO DEMO" in ofx
    assert "finanza.mmb" not in ofx


def test_render_ofx_requires_fitid() -> None:
    with pytest.raises(ValueError):
        render_ofx([replace(make_tx(), fitid_synthetic=None)])


def test_write_ofx_creates_parent_directories(tmp_path) -> None:
    path = write_ofx([make_tx()], tmp_path / "reports" / "demo.ofx")

    assert path.is_file()
    assert "<OFX>" in path.read_text(encoding="utf-8")


def test_write_ofx_rejects_mmex_database_paths(tmp_path) -> None:
    with pytest.raises(ValueError, match="MMEX database"):
        write_ofx([make_tx()], tmp_path / "finanza.mmb")


def test_write_ofx_requires_ofx_suffix(tmp_path) -> None:
    with pytest.raises(ValueError, match="\\.ofx"):
        write_ofx([make_tx()], tmp_path / "demo.txt")
