"""Closed, non-scientific topology shared by 3D selection-stage workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from lab_setup.mot_3d_timestep_policy import MOT_3D_TIMESTEP_POLICY


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


@dataclass(frozen=True)
class PreliminaryScientificDesign:
    input_ensembles: int = 4
    particles_per_ensemble: int = 150
    recoil_seeds: tuple[int, ...] = (41001, 41002, 41003)
    t_max_s: float = 0.1
    selection_seed: int = 51001
    bootstrap_replicates: int = 10_000
    bootstrap_seed: int = 52_001
    solver: str = MOT_3D_TIMESTEP_POLICY["solver"]
    dt_s: float = MOT_3D_TIMESTEP_POLICY["search_dt_s"]


@dataclass(frozen=True)
class RefinementScientificDesign:
    particles_per_ensemble: int = 750
    selection_seed: int = 61_001
    bootstrap_seed: int = 62_001


PRELIMINARY_CHECK_TOPOLOGY = SelectionStageTopology(
    stage="preliminary_check", candidates_per_family=12
)
PRELIMINARY_SCIENTIFIC_DESIGN = PreliminaryScientificDesign()
REFINEMENT_TOPOLOGY = SelectionStageTopology(
    stage="refinement", candidates_per_family=16
)
REFINEMENT_SCIENTIFIC_DESIGN = RefinementScientificDesign()


def public_chain(
    jobs: Mapping[str, Mapping[str, str | None]] | None = None,
    *,
    topology: SelectionStageTopology = PRELIMINARY_CHECK_TOPOLOGY,
) -> dict[str, object]:
    jobs = jobs or {}
    return {
        "dependency": topology.dependency,
        "families": [
            {
                "id": family,
                "array_job_id": jobs.get(family, {}).get("array"),
                "merge_job_id": jobs.get(family, {}).get("merge"),
            }
            for family in FAMILIES
        ],
    }
