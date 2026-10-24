"""Identical source bytes must retain identical provenance across host systems."""

import hashlib
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from studies import mot_3d_campaign


class WindowsOrderedPath(PureWindowsPath):
    """Exercise Windows' case-insensitive path ordering on every test host."""

    def rglob(self, pattern):
        return (type(self)(p.as_posix()) for p in Path(self.as_posix()).rglob(pattern))

    def read_bytes(self):
        return Path(self.as_posix()).read_bytes()


@pytest.mark.parametrize("path_type", [Path, WindowsOrderedPath])
def test_physical_source_hash_uses_portable_posix_name_order(
    tmp_path, monkeypatch, path_type
):
    monkeypatch.chdir(tmp_path)
    sources = {
        "studies/mot_3d_campaign.py": b"campaign source\n",
        "utils/RK4StCustom.py": b"mixed case solver source\n",
        "utils/__init__.py": b"package source\n",
        "utils/data_helpers.py": b"helper source\n",
        "utils/a.py": b"prefix file source\n",
        "utils/a/nested.py": b"prefix directory source\n",
        "atomsmltr/src/atomsmltr/__init__.py": b"atom source\n",
    }
    for name, contents in sources.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)
    monkeypatch.setattr(mot_3d_campaign, "CAMPAIGN_FILES", ("studies/mot_3d_campaign.py",))
    monkeypatch.setattr(mot_3d_campaign, "Path", path_type)

    expected = hashlib.sha256()
    canonical_names = sorted(sources, key=PurePosixPath)
    for name in canonical_names:
        expected.update(name.encode())
        expected.update(sources[name])
    assert mot_3d_campaign.relevant_files() == tuple(canonical_names)
    assert mot_3d_campaign._relevant_hash() == expected.hexdigest()

    # Content validation remains strict; this only canonicalizes name ordering.
    (tmp_path / "utils/RK4StCustom.py").write_bytes(b"changed solver source\n")
    assert mot_3d_campaign._relevant_hash() != expected.hexdigest()
