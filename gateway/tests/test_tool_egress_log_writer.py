import pytest

from app.tool_egress_log import (
    NullToolEgressLogWriter,
    RecordingToolEgressLogWriter,
    ToolEgressLogRow,
)


@pytest.mark.unit
async def test_recording_writer_captures_rows() -> None:
    writer = RecordingToolEgressLogWriter()
    row = ToolEgressLogRow(provider="echo-test", tool="echo", tier=4, bytes_out=2, bytes_in=2)
    await writer.write(row)
    assert len(writer.rows) == 1
    assert writer.rows[0].provider == "echo-test"


@pytest.mark.unit
async def test_null_writer_is_noop() -> None:
    writer = NullToolEgressLogWriter()
    await writer.write(ToolEgressLogRow(provider="x", tool="echo", tier=4))  # no raise


@pytest.mark.unit
async def test_row_defaults_to_not_refused_not_anonymized() -> None:
    row = ToolEgressLogRow(provider="x", tool="echo", tier=4)
    assert row.refused is False
    assert row.anonymization_applied is False
