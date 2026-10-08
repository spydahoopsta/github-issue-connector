"""GitHub Issue Snapshot Connector.

Imports open issues (excluding pull requests) from a GitHub repository into a
local SQLite database and reads them back without touching the GitHub API.

Public API:
    import_issues(owner, repo, db_path="issues.db") -> dict
    read_issues(owner, repo, db_path="issues.db") -> list[dict]
"""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import closing
from typing import Any

import requests

DEFAULT_DB_PATH = "issues.db"
GITHUB_API_URL = "https://api.github.com/repos/{owner}/{repo}/issues"
REQUEST_TIMEOUT = 10  # seconds
MAX_RETRIES = 3
RETRY_BACKOFF = 1.0  # seconds; multiplied by attempt number


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #
class GitHubConnectorError(Exception):
    """Base class for all connector errors."""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible description of the error."""
        return {"status": "error", "error": type(self).__name__, "message": str(self)}


class RepositoryNotFoundError(GitHubConnectorError):
    """The repository does not exist or is not accessible (HTTP 404)."""


class RateLimitError(GitHubConnectorError):
    """GitHub API rate limit exceeded (HTTP 403/429 with no quota left)."""


class GitHubAPIError(GitHubConnectorError):
    """Any other non-successful HTTP response from GitHub."""


class NetworkError(GitHubConnectorError):
    """The request could not be completed (DNS, connection, timeout)."""


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #
def _connect(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a SQLite connection and make sure the ``issues`` table exists."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS issues (
            repository   TEXT    NOT NULL,
            issue_number INTEGER NOT NULL,
            title        TEXT,
            url          TEXT,
            PRIMARY KEY (repository, issue_number)
        )
        """
    )
    conn.commit()
    return conn


# --------------------------------------------------------------------------- #
# GitHub API
# --------------------------------------------------------------------------- #
def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-issue-snapshot-connector",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get_with_retry(url: str, params: dict[str, Any] | None) -> requests.Response:
    """GET ``url`` retrying network failures and 5xx responses."""
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.get(
                url, params=params, headers=_headers(), timeout=REQUEST_TIMEOUT
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_error = exc
        except requests.RequestException as exc:  # other non-retryable failure
            raise NetworkError(f"Request failed: {exc}") from exc
        else:
            if response.status_code < 500:
                return response
            last_error = GitHubAPIError(
                f"GitHub returned HTTP {response.status_code}"
            )
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF * attempt)

    if isinstance(last_error, GitHubAPIError):
        raise last_error
    raise NetworkError(
        f"Network failure after {MAX_RETRIES} attempts: {last_error}"
    ) from last_error


def _check_response(response: requests.Response, owner: str, repo: str) -> None:
    """Translate HTTP error statuses into custom exceptions."""
    status = response.status_code
    if status == 200:
        return
    if status == 404:
        raise RepositoryNotFoundError(f"Repository '{owner}/{repo}' not found (404).")
    if status in (403, 429) and (
        response.headers.get("X-RateLimit-Remaining") == "0" or status == 429
    ):
        reset = response.headers.get("X-RateLimit-Reset", "unknown")
        raise RateLimitError(f"GitHub API rate limit exceeded (resets at {reset}).")
    raise GitHubAPIError(f"GitHub API returned HTTP {status}.")


def _fetch_open_issues(owner: str, repo: str) -> list[dict[str, Any]]:
    """Fetch all open issues (not PRs) for a repo, following pagination."""
    url: str | None = GITHUB_API_URL.format(owner=owner, repo=repo)
    params: dict[str, Any] | None = {"state": "open", "per_page": 100}
    issues: list[dict[str, Any]] = []

    while url:
        response = _get_with_retry(url, params)
        _check_response(response, owner, repo)
        try:
            items = response.json()
        except ValueError as exc:
            raise GitHubAPIError("GitHub returned invalid JSON.") from exc
        # The issues endpoint also returns PRs; they carry a "pull_request" key.
        issues.extend(item for item in items if "pull_request" not in item)
        url = response.links.get("next", {}).get("url")
        params = None  # the "next" URL already embeds the query string
    return issues


# --------------------------------------------------------------------------- #
# Public functions
# --------------------------------------------------------------------------- #
def import_issues(owner: str, repo: str, db_path: str = DEFAULT_DB_PATH) -> dict:
    """Import open issues from GitHub into SQLite (idempotent upsert).

    Pull requests are excluded. Existing rows are updated in place, so running
    the import repeatedly never creates duplicates.

    Args:
        owner: GitHub user or organisation name.
        repo: Repository name.
        db_path: Path to the SQLite database file.

    Returns:
        ``{"status": "success", "imported": <count>, "repository": "owner/repo"}``

    Raises:
        RepositoryNotFoundError: the repository returned HTTP 404.
        RateLimitError: GitHub's rate limit was hit.
        GitHubAPIError: any other HTTP error or malformed response.
        NetworkError: connection failure or timeout (after retries).
    """
    repository = f"{owner}/{repo}"
    issues = _fetch_open_issues(owner, repo)
    rows = [
        (repository, issue["number"], issue.get("title"), issue.get("html_url"))
        for issue in issues
    ]

    with closing(_connect(db_path)) as conn:
        with conn:  # single transaction
            conn.executemany(
                """
                INSERT INTO issues (repository, issue_number, title, url)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(repository, issue_number)
                DO UPDATE SET title=excluded.title, url=excluded.url
                """,
                rows,
            )

    return {"status": "success", "imported": len(rows), "repository": repository}


def read_issues(owner: str, repo: str, db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    """Read stored issues for ``owner/repo`` from SQLite (no GitHub call).

    Returns:
        A list of ``{"issue_number": int, "title": str, "url": str}`` dicts
        ordered by issue number.
    """
    repository = f"{owner}/{repo}"
    with closing(_connect(db_path)) as conn:
        cursor = conn.execute(
            "SELECT issue_number, title, url FROM issues "
            "WHERE repository = ? ORDER BY issue_number",
            (repository,),
        )
        return [
            {"issue_number": number, "title": title, "url": url}
            for number, title, url in cursor.fetchall()
        ]
