from pathlib import Path

import studies.submit_angled_donut_reoptimization as pipeline


def test_corrected_donut_pipeline_uses_isolated_outputs_and_three_shards(
    monkeypatch, tmp_path
):
    submitted = []

    def fake_submit(path, dependency=None):
        submitted.append((Path(path), dependency))
        return f"job-{len(submitted)}"

    monkeypatch.setattr(pipeline, "_submit", fake_submit)
    pipeline.submit_pipeline(tmp_path)

    generated = "\n".join(path.read_text() for path, _ in submitted)
    assert "polarization_corrected_900" in generated
    assert "--profiles angled_donut" in generated
    assert "--profile angled_donut" in generated
    assert "--max-atoms 900" in generated
    assert "--num-shards 3" in generated
    assert "#PBS -J 0-2" in generated
    assert "ncpus=200" in generated
    assert "green_scan_force_corrected_900" in generated
    assert len(submitted) == 7
    assert submitted[-1][1] == "job-6"
