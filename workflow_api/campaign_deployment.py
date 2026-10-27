"""Explicit normal-campaign deployment, independent of TEST ONLY policy."""
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

DEPLOYMENTS = json.loads((Path(__file__).parent / "specifications/deployments_v1.json").read_text())
SCIENTIFIC_CHECKOUT = DEPLOYMENTS["historical"]["checkout"]
ISOLATED_CHECKOUT = DEPLOYMENTS["test"]["checkout"]
ACCEPTANCE_CHECKOUT = DEPLOYMENTS["acceptance"]["checkout"]
TEAM_CHECKOUT = DEPLOYMENTS["team"]["checkout"]


def environment_for_checkout(checkout: str) -> str:
    for deployment in DEPLOYMENTS.values():
        if checkout == deployment["checkout"]:
            return deployment["environment"]
    raise ValueError("Unsupported Zeus checkout.")


def normal_checkout(manifest: Mapping[str, Any]) -> str:
    if "execution_checkout" not in manifest:
        return SCIENTIFIC_CHECKOUT
    if (manifest.get("execution_checkout") not in (ISOLATED_CHECKOUT, TEAM_CHECKOUT)
            or manifest.get("kind") not in ("mot_2d_s0_campaign", "mot_3d_campaign_v2")
            or "acceptance" in manifest):
        raise ValueError("Invalid campaign deployment binding.")
    return manifest["execution_checkout"]


def campaign_checkout_paths(username: str) -> frozenset[PurePosixPath]:
    """Syntax allowlist only; authenticate the manifest before any mutation."""
    home = PurePosixPath("/home") / username
    return frozenset(home / deployment["checkout"] for deployment in DEPLOYMENTS.values())


def render_normal_deployment(manifest: Mapping[str, Any], rendered: bytes) -> bytes:
    """Bind the existing renderer to its explicit target; fail on template drift."""
    checkout = normal_checkout(manifest)
    if checkout == SCIENTIFIC_CHECKOUT:
        return rendered
    text = rendered.decode("utf-8")
    prefix = "~/" if manifest.get("kind") == "mot_3d_campaign_v2" else "${HOME}/"
    environment = environment_for_checkout(checkout)
    substitutions = {
        prefix + SCIENTIFIC_CHECKOUT: prefix + checkout,
        prefix + 'venvs/atomsmltr/bin/activate': prefix + f'venvs/{environment}/bin/activate',
    }
    for original, replacement in substitutions.items():
        if text.count(original) != 1:
            raise ValueError("Campaign deployment template differs from its reviewed form.")
        text = text.replace(original, replacement, 1)
    return text.encode("utf-8")
