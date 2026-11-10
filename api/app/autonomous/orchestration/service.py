"""Shared API/worker assembly for governed runs, one profile at a time.

A service is bound to one registry profile (ADR 0038 D3). Its operator policy,
pinned route, limits and executor all come from that profile and the operator's
settings for it. ``for_profile`` returns the service for a retained run's own
profile, so a run is never driven under another profile's policy.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Importing the profile modules registers the shipped profiles.
from app.autonomous.orchestration import new_harness as _new_harness  # noqa: F401
from app.autonomous.orchestration.chat_demo import PROFILE
from app.autonomous.orchestration.checkpoints import CheckpointRuntime
from app.autonomous.orchestration.effects import GuardedEffects
from app.autonomous.orchestration.executor import OrchestrationExecutor
from app.autonomous.orchestration.inference import InferenceRoutes
from app.autonomous.orchestration.policy import CurrentPolicy, OperatorPolicy
from app.autonomous.orchestration.profiles import (
    RunProfile,
    operator_policy,
    registered_profiles,
    require_profile,
)
from app.autonomous.orchestration.store import OrchestrationStore
from app.clients.gateway import GatewayClient, get_gateway_client
from app.config import Settings
from app.errors import Forbidden
from app.skills.registry import MutableSkillRegistry


class ModelDemoGateway:
    """Match a profile's disclosed attempt timeout without changing ordinary chat clients.

    Configuration reads reuse the application client. Each bounded inference
    owns and closes its transport, including cancellation and uncertain outcomes.
    """

    def __init__(self, settings: Settings, *, timeout_seconds: int | None = None) -> None:
        self.settings = settings
        self.timeout_seconds = timeout_seconds

    async def get_admin_config(self) -> dict[str, Any]:
        return await get_gateway_client().get_admin_config()

    async def chat_completion(self, request: Any, *, configuration_revision: str) -> Any:
        gateway = GatewayClient(
            self.settings.lq_ai_gateway_url,
            self.settings.lq_ai_gateway_key,
            timeout=self.timeout_seconds or self.settings.orchestration_chat_timeout_seconds,
        )
        try:
            return await gateway.chat_completion(
                request, configuration_revision=configuration_revision
            )
        finally:
            await gateway.aclose()


class DemonstrationService:
    def __init__(
        self,
        settings: Settings,
        skills: MutableSkillRegistry,
        sessions: async_sessionmaker[AsyncSession],
        *,
        profile: str = PROFILE,
        gateway: Any = None,
    ) -> None:
        self.settings, self.skills = settings, skills
        self.profile, self.gateway = profile, gateway
        self.run_profile: RunProfile = require_profile(profile)
        on_delivered = None
        if self.run_profile.evidence == "citations":
            from app.autonomous.orchestration.evidence import verify_delivered_answer

            on_delivered = verify_delivered_answer
        self.store = OrchestrationStore(
            sessions,
            check_policy=CurrentPolicy(
                skills=skills,
                operator=self.policy,
            ),
            deployment_children=settings.orchestration_deployment_children,
            on_delivered=on_delivered,
        )

    def policy(self) -> OperatorPolicy | None:
        return operator_policy(self.run_profile, self.skills, self.settings)

    def require_policy(self) -> OperatorPolicy:
        policy = self.policy()
        if policy is None:
            raise Forbidden(message="This run profile is disabled by the operator")
        return policy

    def executor(self) -> OrchestrationExecutor:
        policy = self.require_policy()
        assert policy.deployment_children is not None
        return OrchestrationExecutor(
            self.store,
            self.effects(),
            CheckpointRuntime(
                self.settings.database_url, deployment_children=policy.deployment_children
            ),
            profile=self.run_profile,
            policy=self.policy,
        )

    def effects(self) -> GuardedEffects:
        gateway = self.gateway or ModelDemoGateway(
            self.settings,
            timeout_seconds=self.run_profile.route(self.settings).timeout_seconds,
        )
        return GuardedEffects(
            self.store,
            skills=self.skills,
            gateway=gateway,
            inference=InferenceRoutes(gateway=gateway, operator=self.policy),
        )

    def for_profile(self, profile: str) -> "DemonstrationService":
        if profile == self.profile:
            return self
        return DemonstrationService(
            self.settings, self.skills, self.store.sessions, profile=profile, gateway=self.gateway
        )

    def enabled_profiles(self) -> tuple[str, ...]:
        """Profiles whose operator switch is on. A misconfigured one is not enabled."""
        enabled = []
        for profile in registered_profiles():
            try:
                if operator_policy(profile, self.skills, self.settings) is not None:
                    enabled.append(profile.id)
            except Forbidden:
                continue
        return tuple(enabled)
