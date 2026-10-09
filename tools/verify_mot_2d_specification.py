"""Explicit verification entry point; this tool never rewrites specifications."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from workflow_api.mot_2d_specification import (
    load_mot_2d_specification,
    render_typescript_specification,
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--emit-typescript",
        action="store_true",
        help="print the deterministic TS artifact to stdout; never writes a file",
    )
    args = parser.parse_args()
    spec = load_mot_2d_specification()
    print(
        (
            render_typescript_specification()
            if args.emit_typescript
            else f"verified {spec['spec_version']}"
        ),
        end="" if args.emit_typescript else "\n",
    )
