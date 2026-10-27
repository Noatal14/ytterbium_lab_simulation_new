"""Operational capacity authority for individual simulations (not campaigns).

Family JSON and generated TypeScript expose this policy as checked contracts.
Storage metadata limits and transport envelope limits are separate safeguards;
particle identity/state capacity must derive from this module, never from them.
"""
from types import MappingProxyType

PARTICLE_MINIMUM = 1
PARTICLE_DEFAULT = 200
PARTICLE_MAXIMUM_BY_MODE = MappingProxyType({"local": 1_000, "zeus": 50_000})
PARTICLE_MAXIMUM = max(PARTICLE_MAXIMUM_BY_MODE.values())
STATE_COMPONENTS = 6
STATE_COMPONENT_BYTES = 8  # float64 SI position and velocity
SELECTED_STATE_BYTES_MAXIMUM = PARTICLE_MAXIMUM * STATE_COMPONENTS * STATE_COMPONENT_BYTES
# Bounded NPY metadata, distinct from the raw matrix payload.
SELECTED_STATE_FILE_BYTES_MAXIMUM = SELECTED_STATE_BYTES_MAXIMUM + 64 * 1024


def particle_policy() -> dict:
    """Fresh contract projection; callers cannot mutate the authority."""
    return {"minimum": PARTICLE_MINIMUM, "default": PARTICLE_DEFAULT,
            "maximum_by_execution_mode": dict(PARTICLE_MAXIMUM_BY_MODE)}


def particle_count_allowed(count: object, mode: str) -> bool:
    return (type(count) is int and mode in PARTICLE_MAXIMUM_BY_MODE
            and PARTICLE_MINIMUM <= count <= PARTICLE_MAXIMUM_BY_MODE[mode])
