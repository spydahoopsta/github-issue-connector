# Architecture

## Interface

Two reusable, import-friendly functions in `connector.py`:

- `import_issues(owner, repo, db_path="issues.db") -> dict` – fetches open issues from GitHub, upserts them into SQLite, and returns a JSON-compatible summary: `{"status": "success", "imported": 2, "repository": "owner/repo"}`.
- `read_issues(owner, repo, db_path="issues.db") -> list[dict]` – reads stored issues for `owner/repo` from SQLite only (no network) and returns `[{"issue_number": 1, "title": "...", "url": "..."}]`.

Failures raise subclasses of `GitHubConnectorError`, each with a `to_dict()` method that yields a JSON-compatible error object.

## Main Components

| File | Responsibility |
|------|----------------|
| `connector.py` | GitHub API client (retries, error mapping, pagination, PR filtering), SQLite schema and upsert, read query |
| `cli.py` | `argparse` parsing, JSON printing, exit codes. Contains no business logic |
| `test_connector.py` | pytest + `responses` tests with a temporary DB; no real network |

## Data Flow

```
GitHub REST API  →  Python JSON parser  →  SQLite upsert  →  Reader query  →  JSON output
 (paginated)        (drop pull_request      (ON CONFLICT      (SELECT by       (dict / list
                     items)                  DO UPDATE)        repository)      / CLI print)
```

## Database Schema

```sql
CREATE TABLE IF NOT EXISTS issues (
    repository   TEXT    NOT NULL,
    issue_number INTEGER NOT NULL,
    title        TEXT,
    url          TEXT,
    PRIMARY KEY (repository, issue_number)
);
```

The composite primary key `(repository, issue_number)` lets one table hold many repositories and makes re-imports idempotent via:

```sql
INSERT INTO issues (...) VALUES (...)
ON CONFLICT(repository, issue_number)
DO UPDATE SET title=excluded.title, url=excluded.url;
```

## Configuration & Error Handling

- **Database path:** configurable through the `db_path` argument (CLI: `--db`), defaulting to `issues.db`.
- **Authentication (optional):** `GITHUB_TOKEN` environment variable adds a bearer token for higher rate limits.
- **HTTP errors:** 404 → `RepositoryNotFoundError`; other non-200 → `GitHubAPIError`.
- **Rate limiting:** 429, or 403 with `X-RateLimit-Remaining: 0` → `RateLimitError` (includes reset time).
- **Network retry logic:** connection errors, timeouts, and 5xx responses are retried up to 3 times with linear backoff, then raise `NetworkError` / `GitHubAPIError`. 4xx responses are not retried.
- **Pagination:** follows the `Link: rel="next"` header so repos with more than 100 open issues are fully imported.
- **CLI:** known errors print structured JSON to stderr; unexpected errors print a standard message; both exit with status 1.

## Design Tradeoffs

- **SQLite vs PostgreSQL/Redis:** SQLite is zero-config, ships with Python, and persists to a single file, which suits a local snapshot tool. The cost is no concurrent multi-writer scaling or network access.
- **Composite primary key:** gives simple, idempotent upserts without a separate dedupe step or surrogate id. The cost is that rows are keyed by repository string, so renamed repositories appear as new ones.
- **Snapshot semantics:** the import upserts open issues but does not delete rows for issues that have since closed. This keeps the logic simple; pruning stale rows would be a natural extension.
- **Raise vs return errors:** exceptions keep the success path clean and let callers choose how to handle failures; the CLI converts them to JSON.
