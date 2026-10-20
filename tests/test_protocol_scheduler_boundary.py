"""The hermetic scheduler follows PBS directives, preserving submitted bytes."""
from test_mot_2d_receiver_protocol_chain import _scheduler_array


def test_scalar_tmpdir_array_default_is_still_scalar():
    raw = b'#!/bin/bash\nRUN_TMP="/tmp/${USER}_${PBS_JOBID}_${PBS_ARRAY_INDEX:-0}"\npython -m scalar\n'
    assert not _scheduler_array(['/usr/local/bin/qsub'], raw)
    assert _scheduler_array(['/usr/local/bin/qsub', '-J', '0-2:1'], raw)
    assert _scheduler_array(['/usr/local/bin/qsub'], b'#PBS -J 0-2:1\n'+raw)
