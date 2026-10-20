"""Read-only selection of canonical and historical smoke submission receipts."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat

MAX_RECEIPT_BYTES = 16_384


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate smoke receipt field.')
        result[key] = value
    return result


def _metadata(path: Path):
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _fingerprint(metadata):
    return (metadata.st_dev, metadata.st_ino, metadata.st_mode, metadata.st_nlink,
            metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)


def _receipt_identity(path: Path) -> str:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_RECEIPT_BYTES:
        raise ValueError('Unsafe smoke receipt.')
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
                         | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or _fingerprint(opened) != _fingerprint(before):
            raise ValueError('Smoke receipt changed during inspection.')
        raw = stream.read(MAX_RECEIPT_BYTES + 1)
        if _fingerprint(os.fstat(stream.fileno())) != _fingerprint(before):
            raise ValueError('Smoke receipt changed during inspection.')
    after = path.lstat()
    if _fingerprint(after) != _fingerprint(before) or len(raw) != before.st_size:
        raise ValueError('Smoke receipt changed during inspection.')
    value = json.loads(raw, object_pairs_hook=_unique,
                       parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Non-finite smoke receipt.')))
    if not isinstance(value, dict):
        raise ValueError('Smoke receipt must be an object.')
    # Canonical serialization preserves scalar types (False is not numeric 0).
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def resolve_smoke_receipt(campaign: str | Path) -> Path:
    """Select a receipt without migrating, copying or creating any state.

    Callers retain their exact receipt schema, submission-key and job checks.
    An unresolved pending record in either namespace requires reconciliation.
    """
    campaign = Path(campaign)
    campaign_metadata = campaign.lstat()
    if not stat.S_ISDIR(campaign_metadata.st_mode):
        raise ValueError('Unsafe smoke campaign directory.')
    receipts = []
    for namespace in ('.mot_ui', '.workflow'):
        directory = campaign
        for part in (namespace, 'submissions'):
            directory /= part
            metadata = _metadata(directory)
            if metadata is not None and not stat.S_ISDIR(metadata.st_mode):
                raise ValueError('Unsafe smoke receipt parent.')
        pending = directory / 'smoke.pending.json'
        if _metadata(pending) is not None:
            raise ValueError('Unresolved smoke submission intent.')
        receipt = directory / 'smoke.json'
        if _metadata(receipt) is not None:
            receipts.append((receipt, _receipt_identity(receipt)))
    if not receipts:
        raise FileNotFoundError('No smoke submission receipt.')
    if any(identity != receipts[0][1] for _, identity in receipts[1:]):
        raise ValueError('Conflicting smoke submission receipts.')
    return receipts[0][0]
