"""Structural regression tests for the public studies command surface."""

import ast
import importlib.util
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STUDIES = ROOT / "studies"
MODULE_PATTERN = re.compile(r"studies(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+")


def _module_references(path):
    text = path.read_text(encoding="utf-8")
    references = set(MODULE_PATTERN.findall(text))
    tree = ast.parse(text, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("studies"):
                references.add(node.module)
        elif isinstance(node, ast.Import):
            references.update(
                alias.name
                for alias in node.names
                if alias.name.startswith("studies")
            )
    return references


def test_studies_root_contains_only_campaign_managers():
    assert {path.name for path in STUDIES.glob("*.py")} == {
        "__init__.py",
        "mot_2d_s0_campaign.py",
        "mot_3d_campaign.py",
    }


def test_all_studies_module_references_resolve():
    references = set()
    for path in STUDIES.rglob("*.py"):
        references.update(_module_references(path))
    for path in (ROOT / "workflow_api").rglob("*.py"):
        references.update(_module_references(path))

    missing = sorted(
        module for module in references if importlib.util.find_spec(module) is None
    )
    assert not missing, f"Unresolved studies module references: {missing}"
