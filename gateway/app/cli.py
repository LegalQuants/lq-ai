"""Operator CLI for the LQ.AI Inference Gateway.

Subcommands:

* ``generate-master-key`` — print a fresh urlsafe-base64 master key.
  Operators store the output as ``LQ_AI_GATEWAY_MASTER_KEY``.
* ``encrypt-key`` — wrap a plaintext provider key with the master
  key and print the resulting Fernet token. Operators paste the
  token into ``gateway.yaml`` under ``api_key_encrypted:`` for the
  provider entry.

Both commands round-trip via stdin so plaintext keys never appear
in shell history. See ``docs/security/`` (M1) for operator workflow.
"""

from __future__ import annotations

import argparse
import sys

from app.secrets import MASTER_KEY_ENV, encrypt_value, generate_master_key, resolve_secret


def _cmd_generate_master_key(_args: argparse.Namespace) -> int:
    key = generate_master_key()
    print(key)
    print(
        f"\n# Set this in your environment so the gateway can decrypt "
        f"`api_key_encrypted` values:\n#   export {MASTER_KEY_ENV}={key}\n"
        f"# or mount it as a file and set {MASTER_KEY_ENV}_FILE to its path.\n",
        file=sys.stderr,
    )
    return 0


def _cmd_encrypt_key(args: argparse.Namespace) -> int:
    try:
        master_key = resolve_secret(MASTER_KEY_ENV)
    except (RuntimeError, OSError) as exc:
        print(f"error: cannot resolve {MASTER_KEY_ENV}: {exc}", file=sys.stderr)
        return 2
    if not master_key:
        print(
            f"error: {MASTER_KEY_ENV} is not set. Run `python -m app.cli "
            f"generate-master-key` first, export the result (or mount it via "
            f"{MASTER_KEY_ENV}_FILE), then re-run this command.",
            file=sys.stderr,
        )
        return 2
    if args.plaintext is not None:
        plaintext = args.plaintext
    else:
        if sys.stdin.isatty():
            try:
                import getpass

                plaintext = getpass.getpass("Provider key (input hidden): ")
            except (KeyboardInterrupt, EOFError):
                print("\naborted", file=sys.stderr)
                return 130
        else:
            plaintext = sys.stdin.read().strip()
    if not plaintext:
        print("error: empty plaintext key", file=sys.stderr)
        return 2
    token = encrypt_value(plaintext, master_key=master_key)
    print(token)
    if args.provider:
        print(
            f"\n# Paste under your `{args.provider}` provider entry in "
            f"gateway.yaml:\n#   api_key_encrypted: {token}\n",
            file=sys.stderr,
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="LQ.AI Inference Gateway operator CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_gen = sub.add_parser(
        "generate-master-key",
        help="Print a fresh urlsafe-base64 master key for LQ_AI_GATEWAY_MASTER_KEY",
    )
    p_gen.set_defaults(func=_cmd_generate_master_key)

    p_enc = sub.add_parser(
        "encrypt-key",
        help="Encrypt a provider API key for gateway.yaml under api_key_encrypted",
    )
    p_enc.add_argument(
        "--provider",
        help=(
            "Provider name (informational; included in the stderr hint). "
            "e.g., anthropic-prod, openai-prod"
        ),
    )
    p_enc.add_argument(
        "--plaintext",
        help=(
            "Plaintext key inline (avoids stdin / interactive prompt). "
            "Beware of shell history; prefer the interactive prompt."
        ),
    )
    p_enc.set_defaults(func=_cmd_encrypt_key)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
