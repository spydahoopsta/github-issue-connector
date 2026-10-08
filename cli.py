"""Command-line interface for the GitHub Issue Snapshot Connector.

Usage:
    python cli.py import --owner <owner> --repo <repo> [--db <db_path>]
    python cli.py read   --owner <owner> --repo <repo> [--db <db_path>]
"""

from __future__ import annotations

import argparse
import json
import sys

import connector


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="GitHub Issue Snapshot Connector CLI"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("import", "Fetch open issues from GitHub and store them in SQLite"),
        ("read", "Read stored issues from SQLite (no network call)"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--owner", required=True, help="GitHub owner or organisation")
        p.add_argument("--repo", required=True, help="Repository name")
        p.add_argument("--db", default=connector.DEFAULT_DB_PATH, help="SQLite path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "import":
            result = connector.import_issues(args.owner, args.repo, args.db)
        else:
            result = connector.read_issues(args.owner, args.repo, args.db)
        print(json.dumps(result, indent=2))
        return 0
    except connector.GitHubConnectorError as exc:
        print(json.dumps(exc.to_dict(), indent=2), file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - last-resort handler for the demo
        print(f"Error: an unexpected error occurred: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
