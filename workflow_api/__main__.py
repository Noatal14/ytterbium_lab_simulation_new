"""Read-only command line for the application workflow API."""

from __future__ import annotations

import argparse
import json

from workflow_api import (
    list_workflows,
    read_2d_campaign,
    read_3d_campaign,
)
from workflow_api.models import SCHEMA_VERSION


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Inspect simulation workflows without running or submitting jobs."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="List workflows exposed to applications.")
    inspect_parser = subparsers.add_parser(
        "inspect-2d", help="Read a fixed-s0 2D-MOT campaign manifest."
    )
    inspect_parser.add_argument("campaign")
    inspect_parser = subparsers.add_parser(
        "inspect-3d", help="Read a canonical 3D-MOT campaign manifest."
    )
    inspect_parser.add_argument("campaign")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.command == "list":
        data = [item.to_dict() for item in list_workflows()]
    elif args.command == "inspect-2d":
        data = read_2d_campaign(args.campaign).to_dict()
    else:
        data = read_3d_campaign(args.campaign).to_dict()
    payload = {"api_version": SCHEMA_VERSION, "data": data}
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
