"""The first run profile on real documents (ADR 0038 D5).

Contract QA children read documents the owner selects from the chat's project.
The profile has its own operator switch and pinned route. It may run in any
active project the owner owns; the project's inference-tier floor and privilege
flag apply at every effect, and the route is refused where it does not satisfy
them.

Granted to children: reading the selected documents, and the run's own working
notes. Bundled helpers and persistent skill workspaces are not granted here
until the conditions in ADR 0035 D8c and D8d are met.

The delivered answer's quotations are checked against the selected documents by
the Citation Engine's local stages. No judge model is called for a run: every
model call in a run is a priced, reserved effect, and a judge call is not one.
A quotation those stages cannot match is reported as unverified.
"""

from app.autonomous.orchestration.contracts import PhaseTools
from app.autonomous.orchestration.profiles import (
    RouteSettings,
    RunLimits,
    RunProfile,
    register_profile,
)
from app.config import Settings

PROFILE = "contract_qa_documents_v1"


def _route(settings: Settings) -> RouteSettings:
    return RouteSettings(
        enabled=settings.orchestration_documents_enabled,
        provider=settings.orchestration_documents_provider,
        model=settings.orchestration_documents_model,
        budget_usd=settings.orchestration_documents_budget_usd,
        minimum_tier=settings.orchestration_documents_minimum_tier,
        timeout_seconds=settings.orchestration_documents_timeout_seconds,
    )


DOCUMENTS_PROFILE = register_profile(
    RunProfile(
        id=PROFILE,
        title="Contract Questions on your documents",
        summary="Splits a request into Contract QA tasks on documents you select from this matter.",
        reads="Only the documents you select for this run. No other matter files or live sources.",
        root_skill="contract-questions-orchestrator",
        child_skill="contract-qa",
        documents="selected",
        project_scope="owned",
        child_tools=PhaseTools(analysis=("read_document", "read_note", "save_note")),
        # Sized for contracts rather than one short packet. A child re-sends
        # what it has read on each turn, so the input ceiling bounds how much
        # of the selection one task can hold. These are review point 6.
        limits=RunLimits(
            max_input_bytes=262_144,
            child_turn_limit=5,
            document_read_chars=40_000,
            deadline_seconds=7200,
        ),
        evidence="citations",
        route=_route,
        switch="LQ_AI_ORCHESTRATION_DOCUMENTS_ENABLED",
        composer=True,
    )
)
