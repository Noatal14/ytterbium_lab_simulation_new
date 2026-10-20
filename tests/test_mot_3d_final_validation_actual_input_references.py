"""Final-validation accepts exact references from real production/freeze writers."""
import copy
import json

import pytest

from tests.test_mot_3d_final_input_actual_writer import _produce
from tests.test_mot_3d_final_input_results import _json
from workflow_api.mot_3d_final_input_results import validate_final_input_result_bytes
from workflow_api.mot_3d_final_validation_results import (
    _input_producer_references, FinalValidationResultError,
)


@pytest.mark.parametrize('acceptance', [False, True])
@pytest.mark.parametrize('absolute_identity', [False, True])
def test_real_producer_references_remain_valid_after_sealing(tmp_path, monkeypatch, acceptance, absolute_identity):
    manifest, locked, submission, files, project, campaign = _produce(
        tmp_path, monkeypatch, acceptance, absolute_identity,
    )
    sealed = validate_final_input_result_bytes(
        _json(manifest), _json(locked), _json(submission), files,
        project_directory=project.as_posix(), campaign_absolute_path=campaign.as_posix(),
    )
    original_files = dict(files)
    row = sealed.input_manifest['ensembles'][0]
    metadata = json.loads(files[row['metadata_path'][len(campaign.as_posix())+1:]])
    replicate = json.loads(files[row['replicate_path'][len(campaign.as_posix())+1:]])
    kwargs = dict(zeeman_path=row['zeeman_path'], logical_root=campaign.relative_to(project).as_posix(), campaign_absolute_path=campaign.as_posix())
    assert _input_producer_references(metadata, replicate, **kwargs) == metadata['design']['ensemble_dir']
    # All aliases below name existing-looking data but are not producer identities
    # for the sealed row. No normalization, suffix search or path relocation.
    for key, value in [
        ('directory', '../after_zeeman'),
        ('directory', metadata['design']['ensemble_dir']+'/.'),
        ('source', 'foreign/'+row['zeeman_path'].split('/')[-1]),
        ('source', '/wrong-root/'+row['zeeman_path'].split('/')[-1]),
        ('source', row['zeeman_path'].replace('/', '\\')),
        ('source', row['zeeman_path'].replace('/after_zeeman/', '/after_zeeman/../after_zeeman/')),
        ('source', row['zeeman_path'].replace('seed3035', 'seed3036')),
        ('replicate', row['zeeman_path']),
        ('replicate', '../'+row['zeeman_path'].split('/')[-1]),
    ]:
        changed_metadata, changed_replicate = copy.deepcopy(metadata), copy.deepcopy(replicate)
        if key == 'directory': changed_metadata['design']['ensemble_dir'] = value
        elif key == 'source': changed_metadata['source_zeeman_ensemble'] = value
        else: changed_replicate['replicate']['ensemble_file'] = value
        with pytest.raises(FinalValidationResultError, match='manifest_mismatch'):
            _input_producer_references(changed_metadata, changed_replicate, **kwargs)

    assert files == original_files
