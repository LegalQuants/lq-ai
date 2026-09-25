"""Shared API/worker assembly, closed to sample execution and disabled by default."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.autonomous.orchestration.checkpoints import CheckpointRuntime
from app.autonomous.orchestration.demo import demo_effects, demonstration_policy
from app.autonomous.orchestration.executor import OrchestrationExecutor
from app.autonomous.orchestration.policy import CurrentPolicy, OperatorPolicy
from app.autonomous.orchestration.store import OrchestrationStore
from app.config import Settings
from app.errors import Forbidden
from app.skills.registry import MutableSkillRegistry


class DemonstrationService:
    def __init__(
        self,
        settings: Settings,
        skills: MutableSkillRegistry,
        sessions: async_sessionmaker[AsyncSession],
    ) -> None:
        self.settings, self.skills = settings, skills
        self.store = OrchestrationStore(
            sessions,
            check_policy=CurrentPolicy(
                skills=skills,
                operator=self.policy,
            ),
            deployment_children=settings.orchestration_deployment_children,
        )

    def policy(self) -> OperatorPolicy | None:
        if not self.settings.orchestration_demo_enabled:
            return None
        capacity = self.settings.orchestration_deployment_children
        if capacity is None:
            raise Forbidden(message="The operator must configure shared child capacity")
        return demonstration_policy(self.skills, deployment_children=capacity)

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
            demo_effects(self.store, self.skills),
            CheckpointRuntime(
                self.settings.database_url, deployment_children=policy.deployment_children
            ),
        )
