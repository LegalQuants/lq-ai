"""Load ``gateway.yaml`` into a validated :class:`GatewayConfig`.

The gateway refuses to start if the config file is missing or malformed
(see ``app.main:lifespan``). This is by design: the gateway is the security
boundary, and silently coming up with empty/default config would mask
operator misconfiguration.

Environment-variable expansion
------------------------------

``gateway.yaml.example`` uses two ``${VAR}`` styles:

* ``${VAR}`` — required. Raises :class:`ConfigLoadError` if ``VAR`` is unset.
* ``${VAR:-default}`` — optional with a default literal.

Expansion runs against scalar string values *before* YAML keys are mapped to
Pydantic models, so structured fields (``true``, integers) keep their YAML
types when the default literal is e.g. ``true`` or ``8001``.

Failure mode
------------

Any failure during load (file not found, YAML parse error, missing required
env var, Pydantic validation error) raises :class:`ConfigLoadError` with a
message that names the file and the underlying cause.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.config import GatewayConfig, MCPServerConfig

__all__ = ["ConfigLoadError", "expand_env_vars", "load_config"]


class ConfigLoadError(RuntimeError):
    """Raised when ``gateway.yaml`` cannot be loaded or validated."""


# Matches ``${VAR}`` and ``${VAR:-default}`` anywhere inside a string.
# - ``VAR`` must be a typical shell-identifier (letters, digits, underscore,
#   not starting with a digit). This rejects things like ``${1}`` that aren't
#   environment variables.
_ENV_PATTERN = re.compile(
    r"""
    \$\{
        (?P<var>[A-Za-z_][A-Za-z0-9_]*)
        (?:
            :-
            (?P<default>[^}]*)
        )?
    \}
    """,
    re.VERBOSE,
)


def _expand_scalar(value: str) -> Any:
    """Substitute ``${VAR}`` placeholders inside a single string.

    If the *entire* string is a single ``${VAR:-default}`` placeholder and the
    default looks like a YAML scalar (``true``, ``false``, an integer), the
    return type follows the YAML default rules. This matters for fields like
    ``enabled: ${LOCAL_INFERENCE_ENABLED:-true}`` which must produce a bool.
    """

    match = _ENV_PATTERN.fullmatch(value)
    if match is not None:
        var = match.group("var")
        default = match.group("default")
        env_value = os.environ.get(var)
        if env_value is not None:
            raw = env_value
        elif default is not None:
            raw = default
        else:
            raise ConfigLoadError(
                f"Required environment variable {var!r} referenced in gateway.yaml is not set"
            )
        # Re-parse through YAML so ``true``/``false``/``42`` become bool/int,
        # while plain strings remain strings.
        return yaml.safe_load(raw)

    # Partial substitution (e.g., ``https://${HOST}/v1``): always returns str.
    def _replace(m: re.Match[str]) -> str:
        var = m.group("var")
        default = m.group("default")
        env_value = os.environ.get(var)
        if env_value is not None:
            return env_value
        if default is not None:
            return default
        raise ConfigLoadError(
            f"Required environment variable {var!r} referenced in gateway.yaml is not set"
        )

    return _ENV_PATTERN.sub(_replace, value)


def expand_env_vars(value: Any) -> Any:
    """Recursively expand ``${VAR}`` placeholders in a parsed-YAML structure.

    Walks dicts and lists; leaves non-string scalars alone.
    """

    if isinstance(value, str):
        return _expand_scalar(value)
    if isinstance(value, dict):
        return {key: expand_env_vars(item) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_env_vars(item) for item in value]
    return value


def load_config(path: Path, *, mcp_path: Path | None = None) -> GatewayConfig:
    """Read, expand, and validate the gateway config at ``path``.

    If ``mcp_path`` is provided and the file exists, load ``mcp_servers``
    from it, synthesize each into a ``type: mcp`` :class:`ToolProviderConfig`,
    and merge them into the returned :class:`GatewayConfig`.  The same
    ``${VAR}`` expansion is applied to the MCP yaml as to the main config.

    Raises :class:`ConfigLoadError` for any failure mode. Callers should let
    that bubble out of FastAPI's lifespan so the process exits non-zero — the
    gateway should not start without a valid config.
    """

    if not path.exists():
        raise ConfigLoadError(f"gateway config not found at {path}")
    if not path.is_file():
        raise ConfigLoadError(f"gateway config path {path} is not a regular file")

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigLoadError(f"failed to read gateway config {path}: {exc}") from exc

    try:
        parsed = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ConfigLoadError(f"gateway config {path} is not valid YAML: {exc}") from exc

    if parsed is None:
        raise ConfigLoadError(f"gateway config {path} is empty")
    if not isinstance(parsed, dict):
        raise ConfigLoadError(
            f"gateway config {path} must be a YAML mapping at the top level "
            f"(got {type(parsed).__name__})"
        )

    expanded: dict[str, Any] = expand_env_vars(parsed)

    try:
        config = GatewayConfig.model_validate(expanded)
    except ValidationError as exc:
        raise ConfigLoadError(f"gateway config {path} failed schema validation:\n{exc}") from exc

    # --- mcp.yaml merge (PR4a Task 2) ----------------------------------------

    if mcp_path is not None and mcp_path.exists():
        try:
            mcp_raw_text = mcp_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigLoadError(f"failed to read mcp config {mcp_path}: {exc}") from exc

        try:
            mcp_parsed: Any = yaml.safe_load(mcp_raw_text)
        except yaml.YAMLError as exc:
            raise ConfigLoadError(f"mcp config {mcp_path} is not valid YAML: {exc}") from exc

        if mcp_parsed is not None:
            if not isinstance(mcp_parsed, dict):
                raise ConfigLoadError(
                    f"mcp config {mcp_path} must be a YAML mapping at the top level "
                    f"(got {type(mcp_parsed).__name__})"
                )

            mcp_expanded: dict[str, Any] = expand_env_vars(mcp_parsed)
            raw_servers: Any = mcp_expanded.get("mcp_servers", [])
            if not isinstance(raw_servers, list):
                raise ConfigLoadError(
                    f"mcp config {mcp_path}: 'mcp_servers' must be a list "
                    f"(got {type(raw_servers).__name__})"
                )

            try:
                mcp_tool_providers = [
                    MCPServerConfig.model_validate(entry).to_tool_provider_config()
                    for entry in raw_servers
                ]
            except ValidationError as exc:
                raise ConfigLoadError(
                    f"mcp config {mcp_path} failed schema validation:\n{exc}"
                ) from exc

            if mcp_tool_providers:
                merged_dict = config.model_dump()
                merged_dict["tool_providers"] = (merged_dict.get("tool_providers") or []) + [
                    tp.model_dump() for tp in mcp_tool_providers
                ]
                try:
                    config = GatewayConfig.model_validate(merged_dict)
                except ValidationError as exc:
                    raise ConfigLoadError(
                        f"gateway config failed validation after merging mcp config "
                        f"{mcp_path}:\n{exc}"
                    ) from exc

    return config
