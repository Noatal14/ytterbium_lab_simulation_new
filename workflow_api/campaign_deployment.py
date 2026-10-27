"""Explicit normal-campaign deployment, independent of TEST ONLY policy."""
from pathlib import PurePosixPath
from typing import Any, Mapping

SCIENTIFIC_CHECKOUT = "ytterbium_lab_simulation_new"
ISOLATED_CHECKOUT = "ytterbium_lab_simulation_ui_test"
ACCEPTANCE_CHECKOUT = "ytterbium_lab_simulation_ui_acceptance"


def normal_checkout(manifest: Mapping[str, Any]) -> str:
    if "execution_checkout" not in manifest:
        return SCIENTIFIC_CHECKOUT
    if (manifest.get("execution_checkout") != ISOLATED_CHECKOUT
            or manifest.get("kind") != "mot_2d_s0_campaign"
            or "acceptance" in manifest):
        raise ValueError("Invalid campaign deployment binding.")
    return ISOLATED_CHECKOUT


def campaign_checkout_paths(username: str) -> frozenset[PurePosixPath]:
    """Syntax allowlist only; authenticate the manifest before any mutation."""
    home = PurePosixPath("/home") / username
    return frozenset(home / name for name in (
        SCIENTIFIC_CHECKOUT, ISOLATED_CHECKOUT, ACCEPTANCE_CHECKOUT,
    ))


def render_normal_deployment(manifest: Mapping[str, Any], rendered: bytes) -> bytes:
    """Bind the existing renderer to its explicit target; fail on template drift."""
    if normal_checkout(manifest) == SCIENTIFIC_CHECKOUT:
        return rendered
    text = rendered.decode("utf-8")
    substitutions = {
        '${HOME}/' + SCIENTIFIC_CHECKOUT: '${HOME}/' + ISOLATED_CHECKOUT,
        '${HOME}/venvs/atomsmltr/bin/activate': '${HOME}/venvs/atomsmltr-ui-test/bin/activate',
    }
    for original, replacement in substitutions.items():
        if text.count(original) != 1:
            raise ValueError("Campaign deployment template differs from its reviewed form.")
        text = text.replace(original, replacement, 1)
    return text.encode("utf-8")
