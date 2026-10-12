"""Closed, non-scientific topology shared by 3D selection-stage workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


FAMILIES = ("angled_donut", "single_pass")


@dataclass(frozen=True)
class SelectionStageTopology:
    stage: str
    candidates_per_family: int
    array_tasks: int = 3
    array_ncpus: int = 200
    array_memory_gb: int = 64
    array_walltime: str = "24:00:00"
    merge_ncpus: int = 1
    merge_memory_gb: int = 4
    merge_walltime: str = "01:00:00"
    dependency: str = "afterok within each family"

    @property
    def jobs(self) -> Mapping[str, Mapping[str, str]]:
        return {
            family: {
                "array": f"jobs/{self.stage}/{family}_array.pbs",
                "merge": f"jobs/{self.stage}/{family}_merge.pbs",
            }
            for family in FAMILIES
        }


PRELIMINARY_CHECK_TOPOLOGY = SelectionStageTopology(
    stage="preliminary_check", candidates_per_family=12
)


def public_chain(
    jobs: Mapping[str, Mapping[str, str | None]] | None = None,
) -> dict[str, object]:
    jobs = jobs or {}
    return {
        "dependency": PRELIMINARY_CHECK_TOPOLOGY.dependency,
        "families": [
            {
                "id": family,
                "array_job_id": jobs.get(family, {}).get("array"),
                "merge_job_id": jobs.get(family, {}).get("merge"),
            }
            for family in FAMILIES
        ],
    }
