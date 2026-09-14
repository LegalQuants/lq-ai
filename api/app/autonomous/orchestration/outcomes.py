"""Bounded internal delivery for the demonstration; no implied verification."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.autonomous.orchestration.contracts import Snapshot, TaskText


class TopicOutcome(Snapshot):
    status: Literal["completed", "empty", "failed"]
    summary: TaskText
    findings: Annotated[tuple[TaskText, ...], Field(max_length=8)]
    verification: Literal["unverified"] = "unverified"
    failure_code: Literal["invalid_output", "execution_failed"] | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.status == "completed" and not self.findings:
            raise ValueError("completed topics require findings; use empty otherwise")
        if self.status != "completed" and self.findings:
            raise ValueError("empty or failed topics cannot claim findings")
        if (self.status == "failed") != (self.failure_code is not None):
            raise ValueError("only failed topics carry a failure code")
        return self


class CollectedTopic(Snapshot):
    session_id: UUID
    topic: TaskText
    outcome: TopicOutcome


class DemonstrationResult(Snapshot):
    kind: Literal["orchestration_demonstration"] = "orchestration_demonstration"
    verification: Literal["unverified"] = "unverified"
    coverage: Literal["complete", "partial", "empty", "failed"]
    summary: Annotated[str, Field(min_length=1, max_length=16384)]
    topics: Annotated[tuple[CollectedTopic, ...], Field(min_length=1, max_length=4)]


def topic_coverage(
    topics: tuple[CollectedTopic, ...],
) -> Literal["complete", "partial", "empty", "failed"]:
    statuses = {topic.outcome.status for topic in topics}
    if statuses == {"failed"}:
        return "failed"
    if "failed" in statuses:
        return "partial"
    if statuses == {"empty"}:
        return "empty"
    return "complete"
