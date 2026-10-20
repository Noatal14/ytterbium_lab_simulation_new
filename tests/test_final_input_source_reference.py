from pathlib import Path

import pytest

from studies.mot_3d_campaign import _matches_generated_zeeman_reference


def test_production_basename_resolves_in_declared_input_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    expected = tmp_path / 'after_zeeman' / 'production_seed3035.npy'
    assert _matches_generated_zeeman_reference(expected.name, expected)
    assert _matches_generated_zeeman_reference(str(expected), expected)
    assert _matches_generated_zeeman_reference('after_zeeman/production_seed3035.npy', expected)


@pytest.mark.parametrize('reference', [None, '', '../production_seed3035.npy',
    'foreign/production_seed3035.npy', 'production_seed3036.npy', 3035])
def test_foreign_or_invalid_references_are_rejected(tmp_path, monkeypatch, reference):
    monkeypatch.chdir(tmp_path)
    expected = tmp_path / 'after_zeeman' / 'production_seed3035.npy'
    assert not _matches_generated_zeeman_reference(reference, expected)
