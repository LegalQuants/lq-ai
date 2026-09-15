"""Shared library for the skill golden harness (DE-231).

Loads acceptance fixtures and structural golden snapshots from
``skills/<skill>/acceptance/`` and evaluates a skill's markdown output
against the snapshot's *structural* expectations — section presence and
count ranges — never wording.

Snapshot semantics (schema_version 1) are documented in
``tests/golden/README.md``. In one paragraph:

* ``required_sections`` — headings (##-####, matched case-insensitively
  by normalized prefix) that MUST be present in the output.
* ``metrics`` — named counters with inclusive ``min``/``max`` ranges
  (``max: null`` = unbounded). Kinds: ``section_items`` (subsection
  headings or, failing that, top-level bullets under a named section;
  a missing section counts 0), ``regex_count`` (case-insensitive match
  count), ``citation_count`` (clause/section reference heuristic),
  ``blockquote_lines`` (lines starting with ``>``), ``table_rows``
  (markdown table body rows).
* ``min_chars`` / ``max_chars`` — output length bounds.

Snapshots carry ``status: provisional`` until a maintainer calibrates
them against a live run (`LQ_GOLDEN_RECORD=1` writes observed sidecars
for that review). Provisional ranges derive from each skill's SKILL.md
output contract and test-plan.md calibration bands — they are NOT
observed values.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = REPO_ROOT / "skills"

#: The 10 starter skills DE-231 covers (== the skills shipping a
#: test-plan.md). Pinned like api/tests' EXPECTED_PATHS: adding an
#: acceptance/ dir to another skill must update this set deliberately.
GOLDEN_SKILLS: frozenset[str] = frozenset(
    {
        "action-items-from-client-alert",
        "comms-improver",
        "contract-qa",
        "dpa-checklist-review",
        "enhance-prompt",
        "msa-review-commercial-purchase",
        "msa-review-saas",
        "nda-review",
        "skill-creator",
        "vendor-privacy-policy-first-pass",
    }
)

#: Minimum fixtures per skill (DE-231 acceptance: 3-5 per skill).
MIN_FIXTURES_PER_SKILL = 3

SNAPSHOT_SCHEMA_VERSION = 1
VALID_SNAPSHOT_STATUSES = frozenset({"provisional", "calibrated"})
VALID_METRIC_KINDS = frozenset(
    {"section_items", "regex_count", "citation_count", "blockquote_lines", "table_rows"}
)

# Same shape as api/app/skills/loader.py's frontmatter regex.
_FRONTMATTER_RE = re.compile(
    r"\A---\s*\r?\n(?P<yaml>.*?)\r?\n---\s*\r?\n(?P<body>.*)\Z",
    re.DOTALL,
)

# ATX headings, levels 1-4. Skill output contracts use ##/### sections.
_HEADING_RE = re.compile(r"^(?P<hashes>#{1,4})\s+(?P<title>.+?)\s*$", re.MULTILINE)

# Clause/section reference heuristic for ``citation_count``: the forms
# the starter skills' output contracts use for citations to the source
# document ("Section 4.2", "§ 7", "[§4.2(b), p. 7]", "Clause 3",
# "Article 28(3)", "45 CFR §164.504").
_CITATION_RE = re.compile(
    r"§\s*\d|\bsections?\s+\d|\bclauses?\s+\d|\barticles?\s+\d|\bsec\.\s*\d|\bpara(?:graph)?s?\s+\d",
    re.IGNORECASE,
)

_BULLET_RE = re.compile(r"^(?:[-*+]|\d+[.)])\s+\S", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\|.+\|\s*$", re.MULTILINE)
_TABLE_RULE_RE = re.compile(r"^\|[\s:|-]+\|\s*$")


class GoldenFormatError(ValueError):
    """A fixture or snapshot file does not match the documented format."""


# ---------------------------------------------------------------------------
# Fixture + snapshot models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Fixture:
    """One anonymized synthetic input document + how to send it."""

    skill: str
    fixture_id: str
    path: Path
    description: str
    synthetic_notice: str
    prompt: str
    document: str
    skill_inputs: dict[str, Any] = field(default_factory=dict)
    model: str | None = None

    @property
    def message_content(self) -> str:
        """The chat-message body: instruction + the fixture document."""

        return f"{self.prompt.rstrip()}\n\n---\n\n{self.document.strip()}\n"


@dataclass(frozen=True)
class MetricSpec:
    """One counted structural expectation with an inclusive range."""

    metric_id: str
    kind: str
    min: int
    max: int | None  # None = unbounded
    section: str | None = None  # for section_items
    pattern: str | None = None  # for regex_count


@dataclass(frozen=True)
class Snapshot:
    """Structural golden snapshot for one fixture."""

    skill: str
    fixture_id: str
    path: Path
    status: str
    provenance: str
    required_sections: tuple[str, ...]
    metrics: tuple[MetricSpec, ...]
    min_chars: int
    max_chars: int | None


@dataclass(frozen=True)
class GoldenPair:
    """A fixture and its snapshot, paired by file stem."""

    skill: str
    fixture_id: str
    fixture_path: Path
    snapshot_path: Path


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_fixture(path: Path) -> Fixture:
    """Parse a ``fixtures/<id>.md`` file (YAML frontmatter + document body)."""

    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise GoldenFormatError(f"{path}: missing YAML frontmatter delimiters")
    try:
        meta = yaml.safe_load(match.group("yaml"))
    except yaml.YAMLError as exc:
        raise GoldenFormatError(f"{path}: frontmatter is not valid YAML: {exc}") from exc
    if not isinstance(meta, dict):
        raise GoldenFormatError(f"{path}: frontmatter must be a YAML mapping")

    for key in ("fixture", "skill", "description", "synthetic", "prompt"):
        if not isinstance(meta.get(key), str) or not meta[key].strip():
            raise GoldenFormatError(f"{path}: frontmatter key {key!r} missing or empty")

    skill_inputs = meta.get("skill_inputs") or {}
    if not isinstance(skill_inputs, dict):
        raise GoldenFormatError(f"{path}: skill_inputs must be a mapping")

    model = meta.get("model")
    if model is not None and not isinstance(model, str):
        raise GoldenFormatError(f"{path}: model must be a string when present")

    return Fixture(
        skill=meta["skill"],
        fixture_id=meta["fixture"],
        path=path,
        description=meta["description"],
        synthetic_notice=meta["synthetic"],
        prompt=meta["prompt"],
        document=match.group("body"),
        skill_inputs=skill_inputs,
        model=model,
    )


def load_snapshot(path: Path) -> Snapshot:
    """Parse a ``snapshots/<id>.golden.json`` file."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GoldenFormatError(f"{path}: not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise GoldenFormatError(f"{path}: snapshot must be a JSON object")

    if raw.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise GoldenFormatError(
            f"{path}: schema_version must be {SNAPSHOT_SCHEMA_VERSION}, "
            f"got {raw.get('schema_version')!r}"
        )
    status = raw.get("status")
    if status not in VALID_SNAPSHOT_STATUSES:
        raise GoldenFormatError(
            f"{path}: status must be one of {sorted(VALID_SNAPSHOT_STATUSES)}, got {status!r}"
        )
    provenance = raw.get("provenance")
    if not isinstance(provenance, str) or not provenance.strip():
        raise GoldenFormatError(f"{path}: provenance missing or empty")

    assertions = raw.get("assertions")
    if not isinstance(assertions, dict):
        raise GoldenFormatError(f"{path}: assertions must be an object")

    required_sections = assertions.get("required_sections", [])
    if not isinstance(required_sections, list) or not all(
        isinstance(s, str) and s.strip() for s in required_sections
    ):
        raise GoldenFormatError(f"{path}: required_sections must be a list of nonempty strings")

    metrics: list[MetricSpec] = []
    for entry in assertions.get("metrics", []):
        metrics.append(_parse_metric(path, entry))

    min_chars = assertions.get("min_chars", 0)
    max_chars = assertions.get("max_chars")
    if not isinstance(min_chars, int) or min_chars < 0:
        raise GoldenFormatError(f"{path}: min_chars must be a non-negative integer")
    if max_chars is not None and (not isinstance(max_chars, int) or max_chars < min_chars):
        raise GoldenFormatError(f"{path}: max_chars must be null or an integer >= min_chars")

    return Snapshot(
        skill=str(raw.get("skill", "")),
        fixture_id=str(raw.get("fixture", "")),
        path=path,
        status=status,
        provenance=provenance,
        required_sections=tuple(required_sections),
        metrics=tuple(metrics),
        min_chars=min_chars,
        max_chars=max_chars,
    )


def _parse_metric(path: Path, entry: Any) -> MetricSpec:
    if not isinstance(entry, dict):
        raise GoldenFormatError(f"{path}: each metric must be an object, got {entry!r}")
    metric_id = entry.get("id")
    kind = entry.get("kind")
    if not isinstance(metric_id, str) or not metric_id.strip():
        raise GoldenFormatError(f"{path}: metric id missing or empty")
    if kind not in VALID_METRIC_KINDS:
        raise GoldenFormatError(
            f"{path}: metric {metric_id!r} kind must be one of "
            f"{sorted(VALID_METRIC_KINDS)}, got {kind!r}"
        )
    lo = entry.get("min", 0)
    hi = entry.get("max")
    if not isinstance(lo, int) or lo < 0:
        raise GoldenFormatError(f"{path}: metric {metric_id!r} min must be a non-negative integer")
    if hi is not None and (not isinstance(hi, int) or hi < lo):
        raise GoldenFormatError(f"{path}: metric {metric_id!r} max must be null or >= min")

    section = entry.get("section")
    pattern = entry.get("pattern")
    if kind == "section_items" and (not isinstance(section, str) or not section.strip()):
        raise GoldenFormatError(f"{path}: metric {metric_id!r} (section_items) needs 'section'")
    if kind == "regex_count":
        if not isinstance(pattern, str) or not pattern:
            raise GoldenFormatError(f"{path}: metric {metric_id!r} (regex_count) needs 'pattern'")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise GoldenFormatError(
                f"{path}: metric {metric_id!r} pattern does not compile: {exc}"
            ) from exc

    return MetricSpec(
        metric_id=metric_id,
        kind=kind,
        min=lo,
        max=hi,
        section=section if isinstance(section, str) else None,
        pattern=pattern if isinstance(pattern, str) else None,
    )


def discover_pairs(skills_dir: Path = SKILLS_DIR) -> list[GoldenPair]:
    """Find every fixture/snapshot pair under ``skills/*/acceptance/``.

    Pairing is by file stem: ``fixtures/<id>.md`` ↔
    ``snapshots/<id>.golden.json``. Unpaired files raise — a fixture
    without expectations (or vice versa) is a broken contribution, and
    the keyless inventory test surfaces it before any live run.
    """

    pairs: list[GoldenPair] = []
    problems: list[str] = []
    for acceptance in sorted(skills_dir.glob("*/acceptance")):
        skill = acceptance.parent.name
        fixtures = {p.stem: p for p in sorted((acceptance / "fixtures").glob("*.md"))}
        snapshots = {
            p.name.removesuffix(".golden.json"): p
            for p in sorted((acceptance / "snapshots").glob("*.golden.json"))
        }
        for stem in sorted(fixtures.keys() | snapshots.keys()):
            if stem not in fixtures:
                problems.append(f"{skill}: snapshot {stem!r} has no fixtures/{stem}.md")
                continue
            if stem not in snapshots:
                problems.append(f"{skill}: fixture {stem!r} has no snapshots/{stem}.golden.json")
                continue
            pairs.append(
                GoldenPair(
                    skill=skill,
                    fixture_id=stem,
                    fixture_path=fixtures[stem],
                    snapshot_path=snapshots[stem],
                )
            )
    if problems:
        raise GoldenFormatError("unpaired acceptance files: " + "; ".join(problems))
    return pairs


# ---------------------------------------------------------------------------
# Markdown structure extraction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SectionSpan:
    level: int
    title: str
    body_start: int
    body_end: int


def _normalize_heading(text: str) -> str:
    """Lowercase, strip markdown emphasis/trailing colon, collapse spaces."""

    cleaned = re.sub(r"[*_`]", "", text).strip().rstrip(":").lower()
    return re.sub(r"\s+", " ", cleaned)


def parse_sections(markdown: str) -> list[SectionSpan]:
    """All ATX headings (levels 1-4) with their body spans."""

    matches = list(_HEADING_RE.finditer(markdown))
    sections: list[SectionSpan] = []
    for i, m in enumerate(matches):
        level = len(m.group("hashes"))
        body_start = m.end()
        body_end = len(markdown)
        for later in matches[i + 1 :]:
            if len(later.group("hashes")) <= level:
                body_end = later.start()
                break
        sections.append(
            SectionSpan(
                level=level,
                title=m.group("title"),
                body_start=body_start,
                body_end=body_end,
            )
        )
    return sections


def find_section(markdown: str, name: str) -> SectionSpan | None:
    """First heading whose normalized title starts with normalized ``name``.

    Prefix matching tolerates dynamic suffixes ("NDA Review: Meridian…").
    """

    target = _normalize_heading(name)
    for section in parse_sections(markdown):
        if _normalize_heading(section.title).startswith(target):
            return section
    return None


def count_section_items(markdown: str, name: str) -> int:
    """Items under the named section: child headings, else top-level bullets.

    A missing section counts 0 (skills legitimately omit empty severity
    sections — "do not pad"). Use ``required_sections`` to assert
    presence separately.
    """

    section = find_section(markdown, name)
    if section is None:
        return 0
    body = markdown[section.body_start : section.body_end]
    child_headings = sum(
        1 for m in _HEADING_RE.finditer(body) if len(m.group("hashes")) > section.level
    )
    if child_headings:
        return child_headings
    return len(_BULLET_RE.findall(body))


def count_regex(markdown: str, pattern: str) -> int:
    return len(re.findall(pattern, markdown, re.IGNORECASE | re.MULTILINE))


def count_citations(markdown: str) -> int:
    return len(_CITATION_RE.findall(markdown))


def count_blockquote_lines(markdown: str) -> int:
    return sum(1 for line in markdown.splitlines() if line.lstrip().startswith(">"))


def count_table_rows(markdown: str) -> int:
    """Markdown table body rows (pipe rows minus header/rule rows)."""

    rows = [r for r in _TABLE_ROW_RE.findall(markdown) if not _TABLE_RULE_RE.match(r.strip())]
    # Subtract one header row per table: a table = a rule row preceded by
    # a header row; count rule rows as headers consumed.
    rules = sum(1 for r in _TABLE_ROW_RE.findall(markdown) if _TABLE_RULE_RE.match(r.strip()))
    return max(len(rows) - rules, 0)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Failure:
    """One structural expectation the output missed."""

    check: str
    expected: str
    observed: str


@dataclass(frozen=True)
class EvalResult:
    passed: bool
    failures: tuple[Failure, ...]
    observed: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "failures": [
                {"check": f.check, "expected": f.expected, "observed": f.observed}
                for f in self.failures
            ],
            "observed": self.observed,
        }


def _metric_value(markdown: str, spec: MetricSpec) -> int:
    if spec.kind == "section_items":
        assert spec.section is not None  # validated at load
        return count_section_items(markdown, spec.section)
    if spec.kind == "regex_count":
        assert spec.pattern is not None  # validated at load
        return count_regex(markdown, spec.pattern)
    if spec.kind == "citation_count":
        return count_citations(markdown)
    if spec.kind == "blockquote_lines":
        return count_blockquote_lines(markdown)
    if spec.kind == "table_rows":
        return count_table_rows(markdown)
    raise GoldenFormatError(f"unknown metric kind {spec.kind!r}")  # pragma: no cover


def evaluate(snapshot: Snapshot, markdown: str) -> EvalResult:
    """Structurally compare a skill's output against its golden snapshot."""

    failures: list[Failure] = []
    observed: dict[str, Any] = {
        "total_chars": len(markdown),
        "sections": [s.title for s in parse_sections(markdown)],
    }

    if len(markdown) < snapshot.min_chars:
        failures.append(
            Failure(
                check="min_chars",
                expected=f">= {snapshot.min_chars}",
                observed=str(len(markdown)),
            )
        )
    if snapshot.max_chars is not None and len(markdown) > snapshot.max_chars:
        failures.append(
            Failure(
                check="max_chars",
                expected=f"<= {snapshot.max_chars}",
                observed=str(len(markdown)),
            )
        )

    missing = [name for name in snapshot.required_sections if find_section(markdown, name) is None]
    observed["missing_sections"] = missing
    for name in missing:
        failures.append(
            Failure(check=f"required_section:{name}", expected="present", observed="missing")
        )

    metrics_observed: dict[str, int] = {}
    for spec in snapshot.metrics:
        value = _metric_value(markdown, spec)
        metrics_observed[spec.metric_id] = value
        hi = "unbounded" if spec.max is None else str(spec.max)
        if value < spec.min or (spec.max is not None and value > spec.max):
            failures.append(
                Failure(
                    check=f"metric:{spec.metric_id}",
                    expected=f"{spec.min}..{hi}",
                    observed=str(value),
                )
            )
    observed["metrics"] = metrics_observed

    return EvalResult(passed=not failures, failures=tuple(failures), observed=observed)
