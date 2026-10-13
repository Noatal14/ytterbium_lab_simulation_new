import hashlib
import json
from pathlib import Path

from workflow_api.run_records import validate_record


FIXTURES = Path(__file__).parent / "fixtures"


def test_individual_run_v1_golden_shape_remains_strictly_readable():
    path = FIXTURES / "individual_runs" / "v1_records.json"
    raw = path.read_bytes()
    records = json.loads(raw)

    assert set(records) == {"run", "configuration", "inputs", "status"}
    for kind, record in records.items():
        validate_record(kind, record)
    assert hashlib.sha256(raw).hexdigest() == (
        "f848c2eabc72650fc1c8e954be47cb7344497eeebe9d67d8d79a5ea9453e77a9"
    )


def test_campaign_v1_golden_bytes_are_frozen():
    expected = {
        "mot_2d_v1.json": "6c69b310469262688b2e00f1b0bfe39d3301ba3eec5261ffed410158467ce941",
        "mot_3d_v1.json": "7a82271d0389110551f84621eebb605c061c646d757229ea5594ac929450b648",
    }
    root = FIXTURES / "campaign_manifests"
    assert {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in expected
    } == expected
