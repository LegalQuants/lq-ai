"""CLI for journaled stack migrations (ADR 0037)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any, NoReturn

from app.ops.models import JournalEntry
from app.ops.service import MigrationService
from app.ops.state import (
    COMPONENT,
    MIGRATION_ID,
    TOOL_VERSION,
    OpsPaths,
    inspect_object_store,
    utc_now,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.ops.migrate")
    parser.add_argument(
        "--actor",
        choices=("cli", "launcher", "helm-job"),
        default=os.environ.get("LQ_AI_OPS_ACTOR", "cli"),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "status"):
        command = subparsers.add_parser(name)
        command.add_argument("--json", action="store_true", dest="as_json")
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--yes", action="store_true")
    apply_parser.add_argument("--only", choices=(MIGRATION_ID,))
    apply_parser.add_argument("--json", action="store_true", dest="as_json")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("migration_id", nargs="?", choices=(MIGRATION_ID,))
    verify_parser.add_argument("--json", action="store_true", dest="as_json")
    rollback_parser = subparsers.add_parser("rollback")
    rollback_parser.add_argument("migration_id", choices=(MIGRATION_ID,))
    rollback_parser.add_argument("--yes", action="store_true")
    rollback_parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _emit(value: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(value, sort_keys=True, indent=2))


def _fail(
    service: MigrationService,
    phase: str,
    exc: Exception,
    *,
    exit_code: int,
    as_json: bool,
) -> NoReturn:
    detection = inspect_object_store(service.paths.object_store)
    service.journal.append(
        JournalEntry(
            timestamp=utc_now(),
            migration_id=MIGRATION_ID,
            component=COMPONENT,
            phase=phase,
            state="failed",
            actor=service.actor,
            tool_version=TOOL_VERSION,
            deployment_id=detection.deployment_id,
            layout=detection.layout,
            error=str(exc),
        )
    )
    _emit({"status": "failed", "phase": phase, "error": str(exc)}, as_json=as_json)
    raise SystemExit(exit_code)


async def _run(args: argparse.Namespace) -> int:
    service = MigrationService(OpsPaths.from_environment(), actor=args.actor)
    as_json = bool(getattr(args, "as_json", False))
    if args.command == "status":
        _emit(service.status(), as_json=as_json)
        return 0
    if args.command == "plan":
        try:
            plan = await service.plan()
        except Exception as exc:
            _fail(service, "plan", exc, exit_code=21, as_json=as_json)
        _emit({"status": "planned", "plan": plan.to_dict()}, as_json=as_json)
        if plan.action == "conflict":
            return 21
        if not plan.preflight_passed:
            return 20
        if plan.action in {"apply", "verify"}:
            return 10
        return 0
    if args.command == "apply":
        try:
            result = await service.apply()
        except Exception as exc:
            _fail(service, "apply", exc, exit_code=30, as_json=as_json)
        _emit(result, as_json=as_json)
        return 0
    if args.command == "verify":
        try:
            result = await service.verify()
        except Exception as exc:
            _fail(service, "verify", exc, exit_code=40, as_json=as_json)
        _emit(result, as_json=as_json)
        return 0
    if args.command == "rollback":
        if not args.yes and sys.stdin.isatty():
            answer = input(
                "Restore the migration snapshot and replace the object-store volume? [y/N] "
            )
            if answer.strip().lower() not in {"y", "yes"}:
                _emit({"status": "cancelled"}, as_json=as_json)
                return 50
        try:
            result = service.rollback()
        except Exception as exc:
            _fail(service, "rollback", exc, exit_code=50, as_json=as_json)
        _emit(result, as_json=as_json)
        return 0
    raise AssertionError(f"unknown command: {args.command}")


def main() -> None:
    raise SystemExit(asyncio.run(_run(_parser().parse_args())))


if __name__ == "__main__":
    main()
