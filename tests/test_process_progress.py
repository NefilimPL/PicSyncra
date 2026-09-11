"""Tests for the durable process-progress persistence gate."""

from picsyncra.web.process_progress import ProcessProgressGate


def test_progress_gate_coalesces_percent_only_updates():
    """Removing the 500 ms interval would make this test persist too often."""
    gate = ProcessProgressGate(min_interval_seconds=0.5)

    assert gate.should_persist("job-1", stage="images", status="running", now=0.0)
    assert not gate.should_persist("job-1", stage="images", status="running", now=0.1)
    assert not gate.should_persist("job-1", stage="images", status="running", now=0.49)
    assert gate.should_persist("job-1", stage="images", status="running", now=0.5)


def test_progress_gate_persists_stage_status_and_force():
    """Removing any bypass condition would lose a meaningful job transition."""
    gate = ProcessProgressGate(min_interval_seconds=0.5)

    assert gate.should_persist("job-1", stage="validate", status="running", now=0.0)
    assert gate.should_persist("job-1", stage="images", status="running", now=0.1)
    assert gate.should_persist("job-1", stage="images", status="failed", now=0.2)
    assert gate.should_persist(
        "job-1", stage="images", status="failed", now=0.21, force=True
    )


def test_progress_gate_forget_isolates_reused_job_ids():
    """Removing forget would let an old job suppress a new job's first snapshot."""
    gate = ProcessProgressGate(min_interval_seconds=0.5)

    assert gate.should_persist("job-1", stage="images", status="running", now=0.0)
    gate.forget("job-1")
    assert gate.should_persist("job-1", stage="images", status="running", now=0.1)
