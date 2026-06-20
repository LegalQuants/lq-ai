from app.skills.schema import LQAIFrontmatter, SkillFrontmatter, derive_summary


def test_frontmatter_parses_tool_usage():
    fm = LQAIFrontmatter.model_validate({"tool_usage": ["courtlistener"]})
    assert fm.tool_usage == ["courtlistener"]


def test_frontmatter_tool_usage_absent_is_none():
    assert LQAIFrontmatter.model_validate({}).tool_usage is None


def test_derive_summary_carries_tool_usage():
    front = SkillFrontmatter.model_validate(
        {"name": "x", "description": "d", "lq_ai": {"tool_usage": ["courtlistener"]}}
    )
    summary = derive_summary("x", front)
    assert summary.tool_usage == ["courtlistener"]
