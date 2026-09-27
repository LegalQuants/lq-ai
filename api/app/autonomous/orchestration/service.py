"""Shared API/worker assembly for the bounded model-backed demonstration."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.autonomous.orchestration.chat_demo import PROFILE, chat_policy
from app.autonomous.orchestration.checkpoints import CheckpointRuntime
from app.autonomous.orchestration.effects import GuardedEffects
from app.autonomous.orchestration.executor import OrchestrationExecutor
from app.autonomous.orchestration.inference import InferenceRoutes
from app.autonomous.orchestration.policy import CurrentPolicy, OperatorPolicy
from app.autonomous.orchestration.store import OrchestrationStore
from app.clients.gateway import GatewayClient, get_gateway_client
from app.config import Settings
from app.errors import Forbidden
from app.skills.registry import MutableSkillRegistry


class ModelDemoGateway:
    """Match the disclosed demo timeout without changing ordinary chat clients.

    Configuration reads reuse the application client. Each bounded inference
    owns and closes its transport, including cancellation and uncertain outcomes.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def get_admin_config(self) -> dict[str, Any]:
        return await get_gateway_client().get_admin_config()

    async def chat_completion(self, request: Any, *, configuration_revision: str) -> Any:
        gateway = GatewayClient(
            self.settings.lq_ai_gateway_url,
            self.settings.lq_ai_gateway_key,
            timeout=self.settings.orchestration_chat_timeout_seconds,
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
        if profile != PROFILE:
            raise Forbidden(message="Unknown orchestration profile")
        self.store = OrchestrationStore(
            sessions,
            check_policy=CurrentPolicy(
                skills=skills,
                operator=self.policy,
            ),
            deployment_children=settings.orchestration_deployment_children,
        )

    def policy(self) -> OperatorPolicy | None:
        if not self.settings.orchestration_chat_enabled:
            return None
        return chat_policy(self.skills, self.settings)

    def require_policy(self) -> OperatorPolicy:
        policy = self.policy()
        if policy is None:
            raise Forbidden(message="The orchestration demonstration is disabled")
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
            model_demo=True,
            policy=self.policy,
        )

    def effects(self) -> GuardedEffects:
        gateway = self.gateway or ModelDemoGateway(self.settings)
        return GuardedEffects(
            self.store,
            skills=self.skills,
            gateway=gateway,
            inference=InferenceRoutes(gateway=gateway, operator=self.policy),
        )

    def for_profile(self, profile: str) -> "DemonstrationService":
        return DemonstrationService(
            self.settings, self.skills, self.store.sessions, profile=profile, gateway=self.gateway
        )
