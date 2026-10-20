"""Only bounded canonical completion progress is excluded from machine stdout."""
import pytest
from workflow_api import mot_3d_preliminary_transition_remote as core
from workflow_api import mot_3d_final_validation_results as results


@pytest.mark.parametrize('acceptance', [False, True])
def test_completion_internal_progress_preserves_only_caller_envelope(monkeypatch, capsys, acceptance):
    sentinel = object()
    def validate(**kwargs):
        assert kwargs == {'acceptance': acceptance}
        print('JSON summary saved to: /temporary/recomputation/summary.json')
        return sentinel
    monkeypatch.setattr(results, 'validate_final_validation_result_bytes', validate)
    assert core._validate_completion_results(acceptance=acceptance) is sentinel
    print('{"lifecycle":"ready_to_advance"}')
    assert capsys.readouterr().out == '{"lifecycle":"ready_to_advance"}\n'


@pytest.mark.parametrize('failure', ['exception', 'overflow'])
def test_completion_internal_diagnostics_fail_closed(monkeypatch, capsys, failure):
    def validate(**kwargs):
        print('partial internal diagnostics')
        if failure == 'exception':
            raise RuntimeError('canonical validation failed')
        print('x' * (64 * 1024))
    monkeypatch.setattr(results, 'validate_final_validation_result_bytes', validate)
    with pytest.raises((RuntimeError, ValueError)):
        core._validate_completion_results()
    assert capsys.readouterr().out == ''
