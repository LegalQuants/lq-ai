from app.models.project import Project


def test_project_is_sandbox_default_false() -> None:
    col = Project.__table__.c.is_sandbox
    assert col.default.arg is False
    assert col.server_default.arg.text == "false"
    assert col.nullable is False
