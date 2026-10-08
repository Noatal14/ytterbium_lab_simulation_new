from pathlib import Path

import pytest

from workflow_api.repository_paths import (
    MAX_REPOSITORY_PATH_BYTES,
    canonical_repo_relative,
    resolve_repo_relative,
)


ALLOWED = "data/particle_states/after_zeeman"


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "repo"
    source = root / ALLOWED / "profile"
    source.mkdir(parents=True)
    state = source / "state.npy"
    state.write_bytes(b"state")
    return root, source, state


def test_canonicalizes_trusted_absolute_and_relative_paths(repository):
    root, source, state = repository
    expected = f"{ALLOWED}/profile/state.npy"
    assert canonical_repo_relative(root, state, allowed_root=ALLOWED, require="file") == expected
    assert canonical_repo_relative(root, expected, allowed_root=ALLOWED, require="file") == expected
    assert resolve_repo_relative(root, expected, allowed_root=ALLOWED, require="file") == state
    assert resolve_repo_relative(
        root, f"{ALLOWED}/profile", allowed_root=ALLOWED, require="dir"
    ) == source


@pytest.mark.parametrize(
    "value",
    [
        "",
        ".",
        "/data/particle_states/after_zeeman/profile/state.npy",
        "data/particle_states/after_zeeman/../outside.npy",
        "data/particle_states/after_zeeman/profile/./state.npy",
        "data//particle_states/after_zeeman/profile/state.npy",
        "data/particle_states/after_zeeman/profile/state.npy/",
        "data\\particle_states\\after_zeeman\\profile\\state.npy",
        "data/particle_states/after_zeeman/profile/state.npy\x00",
        "data/particle_states/after_zeeman/profile/state.npy\n",
    ],
)
def test_rejects_noncanonical_stored_identities(repository, value):
    root, _, _ = repository
    with pytest.raises(ValueError):
        resolve_repo_relative(root, value, allowed_root=ALLOWED, require="file")


def test_rejects_oversized_identity(repository):
    root, _, _ = repository
    value = "a" * (MAX_REPOSITORY_PATH_BYTES + 1)
    with pytest.raises(ValueError):
        resolve_repo_relative(root, value, allowed_root=ALLOWED, require="file")


def test_rejects_sibling_prefix_and_paths_outside_allowlist(repository):
    root, _, _ = repository
    sibling = root / "data/particle_states/after_zeeman-old/state.npy"
    sibling.parent.mkdir(parents=True)
    sibling.write_bytes(b"state")
    for value in (
        "data/particle_states/after_zeeman-old/state.npy",
        "data/particle_states/outside.npy",
    ):
        with pytest.raises(ValueError):
            resolve_repo_relative(root, value, allowed_root=ALLOWED, require="file")
    with pytest.raises(ValueError):
        canonical_repo_relative(root, sibling, allowed_root=ALLOWED, require="file")


@pytest.mark.parametrize("link_target", ["directory", "file"])
def test_rejects_symlink_components_and_final_symlink(repository, link_target):
    root, source, state = repository
    if link_target == "directory":
        link = root / ALLOWED / "linked-profile"
        link.symlink_to(source, target_is_directory=True)
        value = f"{ALLOWED}/linked-profile/state.npy"
    else:
        link = source / "linked-state.npy"
        link.symlink_to(state)
        value = f"{ALLOWED}/profile/linked-state.npy"
    with pytest.raises(ValueError, match="symbolic link"):
        resolve_repo_relative(root, value, allowed_root=ALLOWED, require="file")
    with pytest.raises(ValueError, match="symbolic link"):
        canonical_repo_relative(root, link, allowed_root=ALLOWED, require="file")


def test_rejects_missing_paths_and_wrong_kinds(repository):
    root, source, state = repository
    with pytest.raises(ValueError):
        resolve_repo_relative(
            root, f"{ALLOWED}/profile/missing.npy", allowed_root=ALLOWED, require="file"
        )
    with pytest.raises(ValueError, match="not a dir"):
        canonical_repo_relative(root, state, allowed_root=ALLOWED, require="dir")
    with pytest.raises(ValueError, match="not a file"):
        canonical_repo_relative(root, source, allowed_root=ALLOWED, require="file")


def test_rejects_invalid_allowed_root(repository):
    root, _, state = repository
    for allowed in ("/data/particle_states", "data/../particle_states"):
        with pytest.raises(ValueError):
            canonical_repo_relative(root, state, allowed_root=allowed, require="file")
