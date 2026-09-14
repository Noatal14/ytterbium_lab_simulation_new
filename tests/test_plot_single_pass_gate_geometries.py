from graphs_scripts.plot_single_pass_gate_geometries import plot_geometries


def test_plot_single_pass_gate_geometries_writes_png(tmp_path):
    output = tmp_path / "gate_geometries.png"
    assert plot_geometries(output) == output
    assert output.exists()
    assert output.stat().st_size > 0
