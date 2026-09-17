#!/usr/bin/env python3
"""Extract Pydantic model fields from Python source, as JSON.

Why a Python script inside a Node build: ``api/app/config.py`` and
``gateway/app/config.py`` are the canonical statement of what an operator can
configure, and a reference page that restates them by hand is wrong the first
time either file changes. Reading them with a regex from JavaScript would be
wrong in a quieter way -- a multi-line ``Field(...)`` call, an implicitly
concatenated description string, a ``Literal[...]`` annotation spread over three
lines. ``ast`` parses exactly what Python parses.

**Nothing is imported.** The modules are parsed, never executed, so generating
the documentation cannot pull in ``pydantic``, read an ``.env`` file, or run any
code in the repository. Stdlib only, Python 3.11+.

Usage::

    python3 gen-config-reference.py api/app/config.py gateway/app/config.py

Output (stdout)::

    {
      "files": [
        {
          "path": "api/app/config.py",
          "doc": "module docstring",
          "classes": [
            {
              "name": "Settings",
              "bases": ["BaseSettings"],
              "doc": "class docstring",
              "fields": [
                {
                  "name": "database_url",
                  "annotation": "str",
                  "default": "\"postgresql+asyncpg://...\"",
                  "description": "Async SQLAlchemy URL for Postgres.",
                  "required": false,
                  "section": "Postgres",
                  "line": 49
                }
              ]
            }
          ]
        }
      ]
    }

Every string in the output is source text or a literal the source states. The
script never infers a default, a type, or a description that is not written down
-- a field whose description is absent comes back as ``null`` so the page can
say the repository does not document it rather than invent a sentence.
"""

from __future__ import annotations

import ast
import io
import json
import re
import sys
import tokenize
from pathlib import Path
from typing import Any

# ``# ----- Postgres -----`` and ``# --- Server / auth ---`` are how both config
# files group their fields. The grouping is real documentation: it is how the
# operator's ``.env`` is laid out. It is captured so the page can keep it.
SECTION = re.compile(r"^#\s*-{2,}\s*(?P<title>.*?)\s*-{2,}\s*$")

PYDANTIC_BASES = {
    "BaseModel",
    "BaseSettings",
    "PydanticBaseSettingsSource",
}


def _comments(source: str) -> tuple[dict[int, str], dict[int, str]]:
    """Return ``(trailing, standalone)`` comment text by line number."""

    trailing: dict[int, str] = {}
    standalone: dict[int, str] = {}
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue
            line = token.start[0]
            text = token.string.lstrip("#").strip()
            # A comment that starts the line is standalone; one that follows
            # code on the same line documents that line.
            if token.line[: token.start[1]].strip():
                trailing[line] = text
            else:
                standalone[line] = text
    except tokenize.TokenError:
        pass
    return trailing, standalone


def _string_value(node: ast.AST) -> str | None:
    """The value of a string literal, including implicit concatenation."""

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _string_value(node.left)
        right = _string_value(node.right)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr):
        # An f-string cannot be evaluated without running code; report the
        # source text instead of guessing at the interpolation.
        return None
    return None


def _field_call(node: ast.AST | None) -> ast.Call | None:
    if isinstance(node, ast.Call):
        name = node.func
        if isinstance(name, ast.Name) and name.id == "Field":
            return node
        if isinstance(name, ast.Attribute) and name.attr == "Field":
            return node
    return None


def _keyword(call: ast.Call, name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _default_text(source: str, value: ast.AST | None) -> tuple[str | None, bool]:
    """``(default as source text, required)``."""

    if value is None:
        # `name: str` with no assignment -- Pydantic treats it as required.
        return None, True

    call = _field_call(value)
    if call is None:
        return ast.get_source_segment(source, value), False

    if call.args:
        first = call.args[0]
        text = ast.get_source_segment(source, first)
        # `Field(...)` -- Pydantic's explicit "required" sentinel.
        if isinstance(first, ast.Constant) and first.value is Ellipsis:
            return None, True
        return text, False

    default = _keyword(call, "default")
    if default is not None:
        if isinstance(default, ast.Constant) and default.value is Ellipsis:
            return None, True
        return ast.get_source_segment(source, default), False

    factory = _keyword(call, "default_factory")
    if factory is not None:
        return f"{ast.get_source_segment(source, factory)}()", False

    return None, True


def _constraints(source: str, value: ast.AST | None) -> dict[str, str]:
    """``ge``/``le``/``min_length``/… stated on a ``Field(...)``."""

    call = _field_call(value)
    if call is None:
        return {}
    wanted = ("ge", "gt", "le", "lt", "min_length", "max_length", "pattern")
    found = {}
    for keyword in call.keywords:
        if keyword.arg in wanted:
            found[keyword.arg] = ast.get_source_segment(source, keyword.value)
    return found


def _fields(source: str, klass: ast.ClassDef) -> list[dict[str, Any]]:
    trailing, standalone = _comments(source)
    fields: list[dict[str, Any]] = []
    section: str | None = None

    body = list(klass.body)
    for index, statement in enumerate(body):
        # Track the most recent `# ----- Section -----` banner above this point.
        for line in range(_previous_end(body, index) + 1, statement.lineno):
            match = SECTION.match((standalone.get(line) and f"# {standalone[line]}") or "")
            if match:
                section = match.group("title") or None

        if not isinstance(statement, ast.AnnAssign) or not isinstance(statement.target, ast.Name):
            continue

        name = statement.target.id
        if name.startswith("_") or name == "model_config":
            continue

        annotation = ast.get_source_segment(source, statement.annotation)
        default, required = _default_text(source, statement.value)

        description = None
        call = _field_call(statement.value)
        if call is not None:
            node = _keyword(call, "description")
            if node is not None:
                description = _string_value(node) or ast.get_source_segment(source, node)

        # Pydantic's other convention: a bare string expression on the line
        # after the field, used as its docstring. Both config files use it.
        if description is None and index + 1 < len(body):
            following = body[index + 1]
            if isinstance(following, ast.Expr):
                description = _string_value(following.value)

        # Last resort: the comment the author wrote beside or above the field.
        if description is None:
            description = trailing.get(statement.lineno)
        if description is None:
            above = []
            line = statement.lineno - 1
            while line in standalone and not SECTION.match(f"# {standalone[line]}"):
                above.insert(0, standalone[line])
                line -= 1
            if above:
                description = " ".join(above)

        fields.append(
            {
                "name": name,
                "annotation": annotation,
                "default": default,
                "required": required,
                "description": _clean(description),
                "constraints": _constraints(source, statement.value),
                "section": section,
                "line": statement.lineno,
            }
        )

    return fields


def _previous_end(body: list[ast.stmt], index: int) -> int:
    if index == 0:
        return body[0].lineno - 40
    previous = body[index - 1]
    return getattr(previous, "end_lineno", previous.lineno)


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    collapsed = " ".join(str(text).split())
    return collapsed or None


def _is_model(klass: ast.ClassDef) -> bool:
    for base in klass.bases:
        if isinstance(base, ast.Name) and base.id in PYDANTIC_BASES:
            return True
        if isinstance(base, ast.Attribute) and base.attr in PYDANTIC_BASES:
            return True
        # A model that extends another model in the same file (SkillSummary ->
        # Skill) is still a model; the name is resolved by the caller.
        if isinstance(base, ast.Name) and base.id[:1].isupper():
            return True
    return False


def parse_file(path: Path, root: Path) -> dict[str, Any]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    classes = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or not _is_model(node):
            continue
        classes.append(
            {
                "name": node.name,
                "bases": [
                    ast.get_source_segment(source, base) or "" for base in node.bases
                ],
                "doc": _clean(ast.get_docstring(node)),
                "fields": _fields(source, node),
                "line": node.lineno,
            }
        )

    return {
        "path": str(path.relative_to(root)).replace("\\", "/"),
        "doc": _clean(ast.get_docstring(tree)),
        "classes": classes,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2

    root = Path(argv[1]).resolve()
    files = []
    problems = []
    for raw in argv[2:]:
        path = (root / raw).resolve()
        if not path.is_file():
            problems.append(f"{raw} is not a file in the repository")
            continue
        try:
            files.append(parse_file(path, root))
        except SyntaxError as error:  # pragma: no cover - a broken checkout
            problems.append(f"{raw} does not parse: {error}")

    json.dump({"files": files, "problems": problems}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
