"""Mutable config holder for hot-reload (D0.5).

Mirrors the C1 atomic-swap pattern (``api/app/skills/registry.py``)
adapted for the gateway's :class:`GatewayConfig`. The router and every
admin handler that reads config goes through :meth:`MutableConfigHolder.current`
(a single Python attribute fetch — atomic under CPython's GIL). The
write side serializes through ``_lock`` so concurrent reload attempts
do not race on the file or on the in-memory swap.

Hot-reload triggers (D0.5):

* **Explicit alias write** — ``PATCH``/``POST``/``DELETE`` on the admin
  alias endpoints write the file (atomically) and call
  :meth:`reload_from_disk` in-process.
* **SIGHUP** — operator-driven external trigger (mirrors C1's skill
  reload signal). The handler re-reads from disk; on validation failure
  it logs WARNING and KEEPS the old snapshot.

Validation is performed by re-running ``load_config`` (the same path
used at startup). If the new config does not validate, the holder
keeps the prior snapshot and surfaces a :class:`ConfigReloadError` so
callers can react. **The gateway never silently transitions to a
malformed config.**

In-flight requests are unaffected: each request resolves its alias
chain against the snapshot it captured at dispatch start. The Router
reads the current snapshot exactly once per ``chat_completion`` call;
a reload happening mid-call leaves that call on the old config and
the next call sees the new one.
"""

from __future__ import annotations

import logging
import signal
import threading
from pathlib import Path

from app.config import GatewayConfig, check_gateway_auth_configured
from app.config_loader import ConfigLoadError, load_config

logger = logging.getLogger(__name__)


class ConfigReloadError(RuntimeError):
    """Raised when a hot-reload from disk fails validation.

    The holder retains the prior snapshot; callers should surface a
    422 (or appropriate 4xx) without crashing the process.
    """


class MutableConfigHolder:
    """Thin holder for the loaded :class:`GatewayConfig`.

    The lifespan handler builds the initial config and wraps it; the
    router and admin endpoints read via :meth:`current`. Writes go
    through :meth:`replace` (in-process swap with a known-good config)
    or :meth:`reload_from_disk` (re-read + re-validate against the
    backing file).
    """

    def __init__(
        self,
        initial: GatewayConfig,
        *,
        config_path: Path,
    ) -> None:
        self._config = initial
        self._config_path = config_path
        # ``_lock`` protects the *write side*. Reads do not take the
        # lock; they read ``_config`` once and operate on the snapshot.
        self._lock = threading.Lock()

    @property
    def config_path(self) -> Path:
        """The disk path the holder reads from on hot-reload."""

        return self._config_path

    def current(self) -> GatewayConfig:
        """Return the live :class:`GatewayConfig` snapshot.

        A single attribute fetch — atomic under CPython's GIL.
        Callers that need a stable view across multiple reads (e.g.,
        the router building a candidate list) should call this once
        and pass the snapshot down rather than re-reading.
        """

        return self._config

    def replace(self, new_config: GatewayConfig) -> GatewayConfig:
        """Atomically swap in ``new_config``; return the prior snapshot.

        The caller is responsible for having validated ``new_config``
        already (typically by going through :func:`load_config`). Used
        by the alias-CRUD admin handlers after they have written the
        new YAML to disk and re-loaded it.
        """

        with self._lock:
            old = self._config
            self._config = new_config
            return old

    def reload_from_disk(self) -> GatewayConfig:
        """Re-read the backing YAML file, validate, and atomically swap.

        On success: the new config replaces the live snapshot and is
        returned.
        On validation failure: the prior snapshot is retained and
        :class:`ConfigReloadError` is raised. The handler logs
        WARNING with enough context for an operator to fix the file.

        Used both by the SIGHUP handler and by the admin alias-write
        endpoints (after they write the file). Holding ``_lock`` for
        the entire reload prevents two concurrent reloads from racing
        on the file read and producing a torn snapshot.
        """

        with self._lock:
            try:
                new_config = load_config(self._config_path)
            except ConfigLoadError as exc:
                logger.warning(
                    "gateway config hot-reload failed; keeping prior snapshot: %s",
                    exc,
                )
                raise ConfigReloadError(str(exc)) from exc
            # gateway#F5: reject a reload that would enable auth with no key
            # configured, so a hot-reload can't drop the gateway into the
            # fail-open state. Keep the prior snapshot on rejection.
            auth_misconfig = check_gateway_auth_configured(new_config)
            if auth_misconfig is not None:
                logger.warning(
                    "gateway config hot-reload rejected; keeping prior snapshot: %s",
                    auth_misconfig,
                )
                raise ConfigReloadError(auth_misconfig)
            old = self._config
            self._config = new_config
        # Log outside the lock to keep the critical section minimal.
        logger.info(
            "gateway config reloaded: %d → %d providers, %d → %d aliases",
            len(old.providers),
            len(new_config.providers),
            len(old.model_aliases),
            len(new_config.model_aliases),
        )
        return new_config


def install_sighup_reload(holder: MutableConfigHolder) -> None:
    """Wire SIGHUP to atomically reload the gateway config.

    Mirrors the C1 :func:`app.skills.install_sighup_reload` shape.
    SIGHUP is unavailable on Windows; this function is a no-op there
    (with a debug log so operators on Windows know not to expect it).

    The handler is deliberately small — it delegates to
    :meth:`MutableConfigHolder.reload_from_disk` and never raises
    out of the signal handler. A failed reload keeps the prior
    snapshot and emits a WARNING; the gateway continues to serve.
    """

    sighup = getattr(signal, "SIGHUP", None)
    if sighup is None:
        logger.debug("SIGHUP not available on this platform; gateway config reload disabled")
        return

    def _handler(_signum: int, _frame: object) -> None:
        logger.info("SIGHUP received — reloading gateway config from %s", holder.config_path)
        try:
            holder.reload_from_disk()
        except ConfigReloadError:
            # Already logged inside reload_from_disk; never raise out
            # of a signal handler.
            return
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(
                "unexpected error during SIGHUP config reload; keeping prior snapshot: %s",
                exc,
                exc_info=True,
            )

    signal.signal(sighup, _handler)


__all__ = [
    "ConfigReloadError",
    "MutableConfigHolder",
    "install_sighup_reload",
]
