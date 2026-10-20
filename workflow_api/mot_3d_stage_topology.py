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
    t_max_s: float = MOT_3D_TIMESTEP_POLICY["t_max_s"]
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


@dataclass(frozen=True)
class ClosureScientificDesign:
    input_ensembles: int = 4
    particles_per_ensemble: int = 750
    recoil_seeds: tuple[int, ...] = (42001, 42002, 42003)
    t_max_s: float = MOT_3D_TIMESTEP_POLICY["t_max_s"]
    selection_seed: int = 71_001
    bootstrap_replicates: int = 10_000
    bootstrap_seed: int = 72_001
    solver: str = MOT_3D_TIMESTEP_POLICY["solver"]
    dt_s: float = MOT_3D_TIMESTEP_POLICY["search_dt_s"]


@dataclass(frozen=True)
class FinalistSelectionScientificDesign:
    input_ensembles: int = 20
    recoil_seeds: tuple[int, ...] = (43001, 43002, 43003)
    t_max_s: float = MOT_3D_TIMESTEP_POLICY["t_max_s"]
    bootstrap_replicates: int = 10_000
    bootstrap_seed: int = 82_001
    solver: str = MOT_3D_TIMESTEP_POLICY["solver"]
    dt_s: float = MOT_3D_TIMESTEP_POLICY["search_dt_s"]


@dataclass(frozen=True)
class FinalValidationScientificDesign:
    input_ensembles: int = 20
    recoil_seeds: tuple[int, ...] = (44001, 44002, 44003)
    t_max_s: float = MOT_3D_TIMESTEP_POLICY["t_max_s"]
    npools: int = 200
    bootstrap_replicates: int = 20_000
    bootstrap_seed: int = 92_001
    solver: str = MOT_3D_TIMESTEP_POLICY["solver"]
    dt_s: float = MOT_3D_TIMESTEP_POLICY["sealed_final_validation_dt_s"]


PRELIMINARY_CHECK_TOPOLOGY = SelectionStageTopology(
    stage="preliminary_check", candidates_per_family=12
)
PRELIMINARY_SCIENTIFIC_DESIGN = PreliminaryScientificDesign()
REFINEMENT_TOPOLOGY = SelectionStageTopology(
    stage="refinement", candidates_per_family=16
)
REFINEMENT_SCIENTIFIC_DESIGN = RefinementScientificDesign()
CLOSURE_TOPOLOGY = SelectionStageTopology(stage="closure", candidates_per_family=16)
CLOSURE_SCIENTIFIC_DESIGN = ClosureScientificDesign()
FINALIST_SELECTION_TOPOLOGY = SelectionStageTopology(
    stage="finalist_selection", candidates_per_family=3
)
FINALIST_SELECTION_SCIENTIFIC_DESIGN = FinalistSelectionScientificDesign()
FINAL_VALIDATION_TOPOLOGY = SelectionStageTopology(
    stage="final_validation",
    candidates_per_family=1,
    merge_memory_gb=8,
    merge_walltime="02:00:00",
)
FINAL_VALIDATION_SCIENTIFIC_DESIGN = FinalValidationScientificDesign()


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
