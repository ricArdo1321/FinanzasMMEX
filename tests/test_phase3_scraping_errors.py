import json

import pytest

from finanzasmmex.cli import main


class _NoopClick:
    def click(self) -> None:
        return None


class _FakePage:
    url = "https://example.test"

    def __init__(self, content: str = "") -> None:
        self._content = content

    def goto(self, _url: str) -> None:
        return None

    def content(self) -> str:
        return self._content

    def get_by_role(self, *_args, **_kwargs) -> _NoopClick:
        return _NoopClick()

    def wait_for_selector(self, *_args, **_kwargs):
        raise TimeoutError("selector missing")


def _payload(stdout: str) -> dict:
    return json.loads(stdout)


def test_be_scraper_login_failure_raises_typed_error_without_stdout_or_save(
    monkeypatch, capsys
) -> None:
    from finanzasmmex.adapters.be_scraping import BancoEstadoScraper
    from finanzasmmex.adapters.scraping_base import ScrapingLoginError

    scraper = BancoEstadoScraper(vault=None)
    monkeypatch.setattr(scraper, "_is_logged_in", lambda _page: False)
    monkeypatch.setattr(
        scraper, "wait_for_user_login", lambda *_args, **_kwargs: False
    )
    monkeypatch.setattr(
        scraper,
        "save_storage_state",
        lambda _context: pytest.fail("storage_state must not be saved"),
    )

    with pytest.raises(ScrapingLoginError):
        scraper._execute_scrape(_FakePage(), object(), since=None)

    captured = capsys.readouterr()
    assert captured.out == ""


def test_cmr_scraper_captcha_raises_typed_challenge_error(monkeypatch) -> None:
    from finanzasmmex.adapters.cmr_scraping import CMRScraper
    from finanzasmmex.adapters.scraping_base import ScrapingChallengeError

    scraper = CMRScraper(vault=None)
    monkeypatch.setattr(scraper, "_is_logged_in", lambda _page: True)

    with pytest.raises(ScrapingChallengeError, match="CAPTCHA"):
        scraper._execute_scrape(_FakePage("CAPTCHA requerido"), object(), since=None)


def test_be_scraper_missing_movements_table_raises_structure_error(
    monkeypatch,
) -> None:
    from finanzasmmex.adapters.be_scraping import BancoEstadoScraper
    from finanzasmmex.adapters.scraping_base import ScrapingStructureError

    scraper = BancoEstadoScraper(vault=None)
    monkeypatch.setattr(scraper, "_is_logged_in", lambda _page: True)

    with pytest.raises(ScrapingStructureError, match="movements table"):
        scraper._execute_scrape(_FakePage(), object(), since=None)


def test_login_be_failure_returns_credentials_error(monkeypatch, capsys) -> None:
    from finanzasmmex.adapters.be_scraping import BancoEstadoScraper

    monkeypatch.setattr(
        BancoEstadoScraper,
        "run_headful",
        lambda self, action_fn: action_fn(object(), object()),
    )
    monkeypatch.setattr(
        BancoEstadoScraper,
        "wait_for_user_login",
        lambda self, page, login_url, indicator: False,
    )
    monkeypatch.setattr(
        BancoEstadoScraper,
        "save_storage_state",
        lambda self, context: pytest.fail("storage_state must not be saved"),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["finanzasmmex", "login", "--source", "be"],
    )

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 3
    payload = _payload(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "CREDENTIALS_REQUIRED"


def test_scraping_be_structure_error_returns_temporary_failure(
    monkeypatch, tmp_path, capsys
) -> None:
    import finanzasmmex.cli as cli
    from finanzasmmex.adapters.scraping_base import ScrapingStructureError

    def raise_structure_error(**_kwargs):
        raise ScrapingStructureError("BancoEstado movements table not found")

    monkeypatch.setattr(cli, "run_scraping_be", raise_structure_error)
    monkeypatch.setattr(
        "sys.argv",
        [
            "finanzasmmex",
            "run",
            "--source",
            "scraping-be",
            "--db",
            str(tmp_path / "staging.db"),
            "--schema",
            "src/finanzasmmex/staging/schema.sql",
            "--ofx-output",
            str(tmp_path / "out.ofx"),
            "--report-output",
            str(tmp_path / "report.html"),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 5
    payload = _payload(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "SCRAPING_STRUCTURE_CHANGED"
