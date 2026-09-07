from studies import submit_3d_mot_overnight_pipeline as pipeline


def test_pipeline_generates_all_stages_and_dependency_submissions(tmp_path, monkeypatch):
    submitted = []
    monkeypatch.setattr(pipeline, "run_merge", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "run_selection", lambda *args, **kwargs: None)

    def fake_submit(path, dependency=None):
        submitted.append((path, dependency))
        return f"job{len(submitted)}"

    monkeypatch.setattr(pipeline, "_submit", fake_submit)

    final_job = pipeline.submit_pipeline(tmp_path)

    assert final_job == "job9"
    assert len(list(tmp_path.glob("*.pbs"))) == 9
    assert submitted[1][1] == "job1"
    assert submitted[2][1] == "job2"
    assert submitted[4][1] == "job4"
    assert submitted[-1][1] == "job2:job8"
    generated = "\n".join(path.read_text() for path, _ in submitted)
    assert "studies.merge_3d_mot_blue_scan_shards" in generated
    assert "studies.scan_3d_mot_green_trap" in generated
    assert "studies.scan_3d_mot_gradient" in generated
