"""Write the tracked, deterministic v1 workflow error-catalog contract."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workflow_api.error_catalog import render_catalog

DEFAULT_OUTPUT = Path("tests/contracts/v1/workflow_api_error_catalog.json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail without writing when the output differs from the catalog.",
    )
    args = parser.parse_args()
    rendered = render_catalog()
    if args.check:
        if not args.output.exists() or args.output.read_text() != rendered:
            parser.exit(1, f"error catalog is out of date: {args.output}\n")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered)


if __name__ == "__main__":
    main()
