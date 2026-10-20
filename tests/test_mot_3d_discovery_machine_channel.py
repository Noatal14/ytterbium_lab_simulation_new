"""Canonical progress is bounded internally; receiver errors still propagate."""
import sys

import pytest
from studies import mot_3d_campaign
from workflow_api import mot_3d_discovery_transition_remote as receiver


def test_preparation_progress_never_leaks_machine_stdout(monkeypatch, capsys):
    def prepare(campaign, manifest):
        print('Merged canonical trials.')
        print('JSON summary saved to: selection.json')
    monkeypatch.setattr(mot_3d_campaign, 'prepare_preliminary_check', prepare)
    captured = receiver._prepare_preliminary('campaign', {})
    assert captured == 'Merged canonical trials.\nJSON summary saved to: selection.json\n'
    assert capsys.readouterr().out == ''


def test_preparation_exception_propagates_and_restores_stdout(monkeypatch, capsys):
    original = sys.stdout
    def prepare(campaign, manifest):
        print('Preparing canonical artifacts')
        raise ValueError('Invalid frozen artifact')
    monkeypatch.setattr(mot_3d_campaign, 'prepare_preliminary_check', prepare)
    with pytest.raises(ValueError, match='Invalid frozen artifact'):
        receiver._prepare_preliminary('campaign', {})
    assert sys.stdout is original
    assert capsys.readouterr().out == ''


def test_preparation_diagnostics_are_bounded(monkeypatch, capsys):
    def prepare(campaign, manifest):
        print('x' * (64 * 1024 + 1))
    monkeypatch.setattr(mot_3d_campaign, 'prepare_preliminary_check', prepare)
    with pytest.raises(ValueError, match='exceeded their bound'):
        receiver._prepare_preliminary('campaign', {})
    assert capsys.readouterr().out == ''
