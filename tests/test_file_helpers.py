import json
from pathlib import Path

import numpy as np
import pytest

from utils import file_helpers


def test_json_publication_preserves_lf_values_and_atomic_replace(monkeypatch, tmp_path):
    target = tmp_path / "spaced directory" / "campaign.json"
    target.parent.mkdir()
    target.write_bytes(b'{"previous":true}')
    values = {"parameters": [1.3, -1.0, 4e-5], "seed": np.int64(3031)}
    native_open = file_helpers.os.fdopen
    native_replace = file_helpers.os.replace
    newlines = []
    published = []

    def open_text(fd, *args, **kwargs):
        newlines.append(kwargs.get("newline"))
        return native_open(fd, *args, **kwargs)

    def replace(source, destination):
        raw = Path(source).read_bytes()
        assert b"\r\n" not in raw
        assert target.read_bytes() == b'{"previous":true}'
        published.append(json.loads(raw))
        return native_replace(source, destination)

    monkeypatch.setattr(file_helpers.os, "fdopen", open_text)
    monkeypatch.setattr(file_helpers.os, "replace", replace)
    file_helpers.save_file_json(target, values)
    expected = {"parameters": [1.3, -1.0, 4e-5], "seed": 3031}
    assert newlines == ["\n"]
    assert published == [expected]
    assert json.loads(target.read_bytes()) == expected
    assert list(target.parent.iterdir()) == [target]


def test_json_failed_replace_keeps_previous_file_and_removes_temp(monkeypatch, tmp_path):
    target = tmp_path / "campaign.json"
    target.write_bytes(b"previous")

    def fail_replace(*_args):
        raise OSError("controlled publication failure")

    monkeypatch.setattr(file_helpers.os, "replace", fail_replace)
    with pytest.raises(OSError, match="controlled publication failure"):
        file_helpers.save_file_json(target, {"seed": 3031})
    assert target.read_bytes() == b"previous"
    assert list(tmp_path.iterdir()) == [target]
