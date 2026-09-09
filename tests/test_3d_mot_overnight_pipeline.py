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
    assert generated.count("--max-atoms 900") == 4
    assert generated.count("python -u -m studies.scan_3d_mot_") == 4
    assert 'exec > "${LOG_STEM}.out" 2> "${LOG_STEM}.err"' in generated
    assert "data/validation/mot_3d/logs" in generated


def test_pbs_header_creates_distinct_live_logs_for_array_shards():
    header = pipeline._header("mot3d_test", array=True)

    assert 'LOG_SUFFIX="${PBS_ARRAY_INDEX:-single}"' in header
    assert "${PBS_JOBNAME}_${PBS_JOBID}_${LOG_SUFFIX}" in header
    assert "#PBS -j oe" not in header
