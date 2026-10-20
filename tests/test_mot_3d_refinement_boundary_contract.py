"""The canonical boundary rejection remains explicit; success fixtures stay interior."""
import pytest

from studies.mot_3d.discovery.optimize import _seed_parameters
from studies.mot_3d.refinement.select import select_from_summary


def test_boundary_nominal_rejects_clipped_duplicate_without_changing_policy():
    summary = {'family':'single_pass', 'ranked_candidates':[
        {'candidate_id':f'single_pass_{worker:02d}', 'mean_usable_fraction':1.0,
         'parameters':_seed_parameters('single_pass', worker)}
        for worker in range(2)
    ]}
    assert summary['ranked_candidates'][0]['parameters']['blue_crossing_z_offset_m'] == -0.05
    with pytest.raises(ValueError, match='Duplicate refinement point generated for crossing_z_upstream'):
        select_from_summary('single_pass', summary)
