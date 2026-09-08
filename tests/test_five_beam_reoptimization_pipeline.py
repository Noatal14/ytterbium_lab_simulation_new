from studies import submit_five_beam_reoptimization as pipeline


def test_corrected_five_beam_pipeline_generates_serial_dependency_graph(
    tmp_path, monkeypatch
):
    submitted = []

    def fake_submit(path, dependency=None):
        submitted.append((path, dependency))
        return f"job{len(submitted)}"

    monkeypatch.setattr(pipeline, "_submit", fake_submit)
    final_job = pipeline.submit_pipeline(tmp_path)

    assert final_job == "job7"
    assert len(list(tmp_path.glob("*.pbs"))) == 7
    assert submitted[0][1] is None
    for index in range(1, 7):
        assert submitted[index][1] == f"job{index}"
    generated = "\n".join(path.read_text() for path, _ in submitted)
    assert generated.count("--max-atoms 900") == 3
    assert "force_corrected_900" in generated
    assert "--profiles five_beam_gravity" in generated
    assert "--profile five_beam_gravity" in generated
