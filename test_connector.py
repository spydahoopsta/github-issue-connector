"""Unit tests for connector.py. No real network requests are made."""

import sqlite3

import pytest
import requests
import responses

import connector

API_URL = "https://api.github.com/repos/octo/demo/issues"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Skip retry backoff delays so tests run instantly."""
    monkeypatch.setattr(connector.time, "sleep", lambda _seconds: None)


def _issue(number: int, title: str) -> dict:
    return {
        "number": number,
        "title": title,
        "html_url": f"https://github.com/octo/demo/issues/{number}",
    }


def _pull_request(number: int, title: str) -> dict:
    item = _issue(number, title)
    item["html_url"] = f"https://github.com/octo/demo/pull/{number}"
    item["pull_request"] = {"url": f"https://api.github.com/repos/octo/demo/pulls/{number}"}
    return item


@responses.activate
def test_import_and_read_issues(tmp_path):
    db = str(tmp_path / "issues.db")
    responses.add(
        responses.GET,
        API_URL,
        json=[_issue(1, "Bug one"), _pull_request(2, "A PR"), _issue(3, "Bug three")],
        status=200,
    )

    result = connector.import_issues("octo", "demo", db_path=db)

    assert result == {"status": "success", "imported": 2, "repository": "octo/demo"}
    assert connector.read_issues("octo", "demo", db_path=db) == [
        {"issue_number": 1, "title": "Bug one", "url": "https://github.com/octo/demo/issues/1"},
        {"issue_number": 3, "title": "Bug three", "url": "https://github.com/octo/demo/issues/3"},
    ]


@responses.activate
def test_repeated_import_no_duplicates(tmp_path):
    db = str(tmp_path / "issues.db")
    responses.add(responses.GET, API_URL, json=[_issue(1, "Old 1"), _issue(2, "Old 2")])
    connector.import_issues("octo", "demo", db_path=db)

    responses.replace(responses.GET, API_URL, json=[_issue(1, "New 1"), _issue(2, "New 2")])
    connector.import_issues("octo", "demo", db_path=db)

    with sqlite3.connect(db) as conn:
        (count,) = conn.execute("SELECT COUNT(*) FROM issues").fetchone()
    assert count == 2
    titles = [i["title"] for i in connector.read_issues("octo", "demo", db_path=db)]
    assert titles == ["New 1", "New 2"]


@responses.activate
def test_api_failure(tmp_path):
    db = str(tmp_path / "issues.db")
    responses.add(responses.GET, API_URL, json={"message": "Not Found"}, status=404)

    with pytest.raises(connector.RepositoryNotFoundError):
        connector.import_issues("octo", "demo", db_path=db)
    assert connector.read_issues("octo", "demo", db_path=db) == []


@responses.activate
def test_rate_limit_error(tmp_path):
    responses.add(
        responses.GET,
        API_URL,
        json={"message": "rate limit"},
        status=403,
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"},
    )
    with pytest.raises(connector.RateLimitError):
        connector.import_issues("octo", "demo", db_path=str(tmp_path / "i.db"))


@responses.activate
def test_server_error_is_retried_then_succeeds(tmp_path):
    db = str(tmp_path / "issues.db")
    responses.add(responses.GET, API_URL, status=500)
    responses.add(responses.GET, API_URL, json=[_issue(1, "Recovered")])

    result = connector.import_issues("octo", "demo", db_path=db)
    assert result["imported"] == 1
    assert len(responses.calls) == 2


@responses.activate
def test_network_failure_raises(tmp_path):
    responses.add(responses.GET, API_URL, body=requests.ConnectionError("boom"))
    with pytest.raises(connector.NetworkError):
        connector.import_issues("octo", "demo", db_path=str(tmp_path / "i.db"))
    assert len(responses.calls) == connector.MAX_RETRIES


@responses.activate
def test_pagination_is_followed(tmp_path):
    db = str(tmp_path / "issues.db")
    page2 = API_URL + "?page=2"
    responses.add(
        responses.GET,
        API_URL,
        json=[_issue(1, "Page one")],
        headers={"Link": f'<{page2}>; rel="next"'},
    )
    responses.add(responses.GET, page2, json=[_issue(2, "Page two")])

    result = connector.import_issues("octo", "demo", db_path=db)
    assert result["imported"] == 2
