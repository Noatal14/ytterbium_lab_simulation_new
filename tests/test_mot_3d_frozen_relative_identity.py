"""Frozen worker identities stay exact while containment uses the Zeus root."""
from pathlib import PurePosixPath

import pytest

from workflow_api.mot_3d_preliminary_results import (
    PreliminaryResultError, _frozen_input_absolute_path,
)


@pytest.mark.parametrize('root', ['ytterbium_lab_simulation_new', 'ytterbium_lab_simulation_ui_acceptance'])
def test_relative_and_absolute_frozen_identity_resolve_to_same_trusted_path(root):
    project = PurePosixPath('/home/tal.noa') / root
    relative = 'data/optimization/mot_2d/ui_acceptance/source/states.npy'
    assert _frozen_input_absolute_path(relative, project) == project / relative
    assert _frozen_input_absolute_path(str(project / relative), project) == project / relative


@pytest.mark.parametrize('path', [
    '../data/x.npy', 'data/../x.npy', 'data//x.npy', 'data/./x.npy',
    'data/x.npy/', '', './data/x.npy', 'jobs/x.npy', 'data\\x.npy',
    '/home/other/ytterbium_lab_simulation_new/data/x.npy',
    '/home/tal.noa/ytterbium_lab_simulation_ui_acceptance/data/x.npy',
])
def test_noncanonical_or_escaping_frozen_identity_rejected(path):
    with pytest.raises(PreliminaryResultError, match='particle_selection_mismatch'):
        _frozen_input_absolute_path(path, PurePosixPath('/home/tal.noa/ytterbium_lab_simulation_new'))
