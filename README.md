# GitHub Issue Snapshot Connector

A small Python connector that snapshots a GitHub repository's **open issues** into a local SQLite database and reads them back later without calling the GitHub API again. Pull requests are excluded, and repeated imports are idempotent (no duplicates).

## Prerequisites & Dependencies

- Python 3.9+
- [`requests`](https://pypi.org/project/requests/) – GitHub REST API calls
- [`pytest`](https://pypi.org/project/pytest/) – test runner
- [`responses`](https://pypi.org/project/responses/) – mocks HTTP calls so tests never hit the network

## Local Setup

```bash
git clone <your-repo-url>
cd <your-repo-folder>

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

Optional: set `GITHUB_TOKEN` to raise GitHub's rate limit (60/hr unauthenticated, 5,000/hr with a token).

```bash
export GITHUB_TOKEN=ghp_your_token_here
```

## Run Commands

```bash
# Import open issues (PRs excluded) into issues.db
python cli.py import --owner psf --repo requests

# Read the stored issues (no network call)
python cli.py read --owner psf --repo requests

# Use a custom database file
python cli.py import --owner psf --repo requests --db my_issues.db
python cli.py read   --owner psf --repo requests --db my_issues.db
```

It can also be imported directly:

```python
from connector import import_issues, read_issues

import_issues("psf", "requests")
issues = read_issues("psf", "requests")
```

## Test Commands

```bash
pytest -v
```

All tests use mocked HTTP responses; no real internet requests are made.

## Example Inputs and Outputs

**Import**

```bash
python cli.py import --owner octo --repo demo
```

```json
{
  "status": "success",
  "imported": 2,
  "repository": "octo/demo"
}
```

**Read**

```bash
python cli.py read --owner octo --repo demo
```

```json
[
  {
    "issue_number": 1,
    "title": "Bug one",
    "url": "https://github.com/octo/demo/issues/1"
  },
  {
    "issue_number": 3,
    "title": "Bug three",
    "url": "https://github.com/octo/demo/issues/3"
  }
]
```

**Error (written to stderr, exit code 1)**

```json
{
  "status": "error",
  "error": "RepositoryNotFoundError",
  "message": "Repository 'octo/nope' not found (404)."
}
```

## AI & Tools Used

> Edit this section so it matches what you actually used. The entries below are a template.

| Tool | How it was used |
|------|-----------------|
| **Claude** | Code generation for `connector.py`, `cli.py`, and `test_connector.py`; drafting this README and `Architecture.MD`. |
| **ChatGPT** | *(Fill in, e.g. debugging SQLite upsert syntax, reviewing error handling.)* |
| **Gemini** | *(Fill in, e.g. test-writing ideas, cross-checking GitHub API behavior.)* |

## Unfamiliar Problem Solved: Pull Requests in the Issues Endpoint

GitHub's `GET /repos/{owner}/{repo}/issues` endpoint returns **both issues and pull requests**, because GitHub treats every PR as an issue internally. A naive import would therefore store PRs as issues and inflate the counts.

AI assistance helped identify that PR entries in the response carry an extra `pull_request` key that real issues lack. The connector filters on it:

```python
issues.extend(item for item in items if "pull_request" not in item)
```

**Verification:** `test_import_and_read_issues` mocks a response containing two issues and one pull request. It asserts that `import_issues` reports exactly 2 imported records and that `read_issues` returns only the two real issues.

## Project Layout

```
connector.py        # API + database core logic
cli.py              # argparse command-line wrapper
test_connector.py   # pytest suite (mocked HTTP)
requirements.txt
README.md
Architecture.MD
```
