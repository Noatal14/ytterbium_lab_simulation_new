from studies import submit_3d_mot_preoptimization_checks as submitter


def test_preoptimization_pipeline_chains_boundary_and_finalist_repeats(
    tmp_path, monkeypatch
):
    submitted = []

    monkeypatch.setattr(
        submitter.boundary_submitter,
        "submit",
        lambda work_dir: "boundary_merge_job",
    )

    def fake_submit(path, dependency=None):
        submitted.append((path, dependency))
        return f"job{len(submitted)}"

    monkeypatch.setattr(submitter, "_submit", fake_submit)
    assert submitter.submit(tmp_path) == "job2"
    assert submitted[0][1] == "boundary_merge_job"
    assert submitted[1][1] == "job1"
    generated = submitted[0][0].read_text()
    assert "#PBS -l select=1:ncpus=200:mem=64gb" in generated
    assert "--five-beam-summary" in generated
    assert "--configurations full_donut five_beam_gravity" in generated
    assert "--repeat-seeds 42101 42102 42103 42104 42105" in generated
