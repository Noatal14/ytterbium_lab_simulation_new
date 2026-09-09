from studies import submit_sequential_reoptimization as pipeline


def test_pipeline_submits_four_ordered_scan_stages(tmp_path, monkeypatch):
    submitted = []

    def fake_submit(path, dependency=None):
        submitted.append((path, dependency))
        return f"job{len(submitted)}"

    monkeypatch.setattr(pipeline, "_submit", fake_submit)
    assert pipeline.submit_pipeline(tmp_path) == "job8"
    assert [dependency for _, dependency in submitted] == [
        None, "job1", "job2", "job3", "job4", "job5", "job6", "job7"
    ]
    generated = "\n".join(path.read_text() for path, _ in submitted)
    assert "studies.scan_3d_mot_sequential_geometry" in generated
    assert "--geometry-point-file" in generated
    assert "studies.scan_3d_mot_blue_slower" in generated
    assert "studies.scan_3d_mot_gradient" in generated
    assert "studies.scan_3d_mot_green_trap" in generated
    assert generated.count("--max-atoms 900") == 4
    assert generated.count("--num-shards 3") == 4
    assert generated.count("--npools 200") == 4
