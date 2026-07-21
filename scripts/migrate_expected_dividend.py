#!/usr/bin/env python3
"""Migrate account summary records from ``daily_dividend`` to ``expected_dividend``.

Usage:
    python -m scripts.migrate_expected_dividend --data-root <data-root>
"""

import argparse
import json
import os
from pathlib import Path
import tempfile


def migrate_summaries(data_root: str | Path) -> int:
    """Migrate legacy dividend keys below *data_root* and return changed file count.

    All summaries below ``<data-root>`` are touched.
    When both keys exist, the already-migrated ``expected_dividend`` value wins.
    """
    root = Path(data_root)
    changed_files = 0

    for summary_path in root.rglob("summary.json"):
        with summary_path.open("r", encoding="utf-8") as source:
            records = json.load(source)

        if not isinstance(records, list):
            raise ValueError(f"summary JSON must contain a list: {summary_path}")

        changed = False
        for record in records:
            if not isinstance(record, dict) or "daily_dividend" not in record:
                continue
            record.setdefault("expected_dividend", record["daily_dividend"])
            del record["daily_dividend"]
            changed = True

        if changed:
            _write_json_atomically(summary_path, records)
            changed_files += 1

    return changed_files


def _write_json_atomically(path: Path, data: list) -> None:
    """Write JSON to a sibling temporary file, then replace the original."""
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as destination:
            json.dump(data, destination, indent=4, ensure_ascii=False)
            destination.write("\n")
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        required=True,
        type=Path,
        help="Root containing account directories with summary.json files",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if not args.data_root.is_dir():
        print(f"Data root does not exist or is not a directory: {args.data_root}")
        return 2

    try:
        changed_files = migrate_summaries(args.data_root)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Migration failed: {error}")
        return 1

    print(f"Migrated {changed_files} summary file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
