"""ORM models for the LQ.AI backend.

Each model corresponds to a table in docs/db-schema.md. The migration in
api/alembic/versions/ is the authoritative DDL — these models reflect what
the migration produces and are the read/write surface for application code.

Import side-effect: importing this module registers every model with the
declarative base, so Alembic's autogenerate (when used) sees them.
"""

from __future__ import annotations

from app.models.audit import AuditLog
from app.models.chat import Chat, Message
from app.models.document import Document, DocumentChunk
from app.models.enhance_prompt import EnhancePromptInteraction
from app.models.file import File
from app.models.inference import InferenceRoutingLog
from app.models.knowledge import KnowledgeBase, KnowledgeBaseFile
from app.models.organization_profile import OrganizationProfile
from app.models.playbook import Playbook, PlaybookExecution, PlaybookPosition
from app.models.project import Project, ProjectFile, ProjectSkill
from app.models.project_knowledge_base import ProjectKnowledgeBase
from app.models.saved_prompt import SavedPrompt
from app.models.slack_workspace import SlackWorkspace
from app.models.tabular import TabularExecution
from app.models.team import Team, TeamMember
from app.models.user import User, UserSession
from app.models.user_export import UserExportJob
from app.models.user_skill import UserSkill
from app.models.work_product import WorkProductAttribution

__all__ = [
    "AuditLog",
    "Chat",
    "Document",
    "DocumentChunk",
    "EnhancePromptInteraction",
    "File",
    "InferenceRoutingLog",
    "KnowledgeBase",
    "KnowledgeBaseFile",
    "Message",
    "OrganizationProfile",
    "Playbook",
    "PlaybookExecution",
    "PlaybookPosition",
    "Project",
    "ProjectFile",
    "ProjectKnowledgeBase",
    "ProjectSkill",
    "SavedPrompt",
    "SlackWorkspace",
    "TabularExecution",
    "Team",
    "TeamMember",
    "User",
    "UserExportJob",
    "UserSession",
    "UserSkill",
    "WorkProductAttribution",
]
