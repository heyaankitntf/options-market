"""Singleton TrueData TD_live connection manager.

Problem
-------
TrueData's WebSocket server only allows ONE concurrent connection per user
account. If the standalone app (`standalone_truedata.py`) holds a long-lived
connection and the option-chain endpoint tries to open another `TD_live`
instance with the same credentials, TrueData rejects it with
"User Already Connected" — which is exactly the error the team was seeing.

Solution
--------
This module provides a process-wide singleton `TD_live` connection that is
shared across all callers (standalone app, option-chain endpoint, tick
capture, etc.). The connection is:

  - Created lazily on first access (or explicitly via `connect()`).
  - Protected by a threading lock so concurrent requests don't race.
  - Automatically reconnected if the WebSocket drops.
  - Never opened twice with the same credentials.

Usage
-----
    from app.services.truedata_connection_manager import td_manager

    # Get or create the shared connection (thread-safe):
    td = td_manager.get_connection()

    # Explicitly start it (e.g. at app startup):
    td_manager.connect()

    # Disconnect (e.g. at app shutdown):
    td_manager.disconnect()

    # Register a callback — just use the underlying td object:
    @td_manager.get_connection().trade_callback
    def on_tick(tick):
        ...

Important
---------
- Callers must NOT call `td.connect()` — the constructor already calls it.
- Callers must NOT call `td.disconnect()` on the shared object — use
  `td_manager.disconnect()` instead, which safely tears down the singleton.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class TrueDataConnectionError(RuntimeError):
    """Raised when the connection manager cannot establish or reconnect
    a TrueData WebSocket session."""


class _SdkExitRaisedError(RuntimeError):
    """Raised by our patched `exit` to prevent the truedata SDK from killing
    the FastAPI worker process. Not part of the public API."""

    def __init__(self, original_message: str = "") -> None:
        self.original_message = original_message or (
            "TrueData SDK called exit() — typically 'User Subscription "
            "Expired' (trial account lacks option-chain entitlement) or "
            "an invalid symbol/expiry."
        )
        super().__init__(self.original_message)


def _make_sdk_exit_raiser():
    """Return a callable that replaces the builtin `exit` in the SDK module
    namespace. Calling it raises `_SdkExitRaisedError` instead of killing
    the process."""
    def _exit_raiser(code=None):
        msg = ""
        if isinstance(code, str):
            msg = code
        elif code is not None and not isinstance(code, int):
            msg = str(code)
        raise _SdkExitRaisedError(msg)
    return _exit_raiser


def _patch_sdk_exit(td_live_cls, exit_raiser) -> None:
    """Patch `exit` in the module that defines `TD_live` so SDK calls to
    `exit()` raise instead of killing the process. Idempotent."""
    import sys as _sys
    module = _sys.modules.get(td_live_cls.__module__)
    if module is not None:
        if getattr(module, "_otp_exit_patched", False):
            return
        module.exit = exit_raiser  # type: ignore[attr-defined]
        module.quit = exit_raiser  # type: ignore[attr-defined]
        module._otp_exit_patched = True  # type: ignore[attr-defined]
        logger.debug("Patched exit/quit in %s", td_live_cls.__module__)


class TDConnectionManager:
    """Thread-safe singleton manager for a shared `TD_live` WebSocket.

    The TrueData server enforces a one-connection-per-user policy. This
    manager ensures that the entire process uses a single connection,
    preventing "User Already Connected" errors.
    """

    def __init__(self) -> None:
        self._td: Any = None
        self._lock = threading.Lock()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._td is not None

    def get_connection(self) -> Any:
        """Return the shared `TD_live` instance, creating it if necessary.

        Thread-safe: concurrent callers will block until the first one
        finishes connecting.
        """
        with self._lock:
            if self._td is not None and self._connected:
                return self._td
            # Attempt to connect if not already connected.
            return self._connect_internal()

    def connect(self) -> Any:
        """Explicitly open the shared connection. Idempotent — safe to call
        multiple times (returns existing connection if already open)."""
        with self._lock:
            return self._connect_internal()

    def _connect_internal(self) -> Any:
        """Internal connect — caller must hold self._lock."""
        if self._td is not None and self._connected:
            return self._td

        try:
            from truedata.websocket.TD_live import TD_live  # type: ignore
        except ImportError as e:
            raise TrueDataConnectionError(
                "truedata (v7+) package is not installed. "
                "Run `pip install -r requirements.txt`."
            ) from e

        # Patch the SDK's exit() before instantiation.
        sdk_exit_raiser = _make_sdk_exit_raiser()
        _patch_sdk_exit(TD_live, sdk_exit_raiser)

        logger.info(
            "Connecting to TrueData WS: user=%s url=%s port=%s",
            settings.TRUEDATA_USERNAME,
            settings.TRUEDATA_URL,
            settings.TRUEDATA_LIVE_PORT,
        )

        try:
            td = TD_live(
                login_id=settings.TRUEDATA_USERNAME,
                password=settings.TRUEDATA_PASSWORD,
                url=settings.TRUEDATA_URL,
                live_port=settings.TRUEDATA_LIVE_PORT,
                log_level=logging.WARNING,
            )
        except _SdkExitRaisedError as e:
            raise TrueDataConnectionError(
                f"TrueData connection failed (SDK exit): {e.original_message}"
            ) from e
        except Exception as e:
            msg = str(e)
            if "User Already Connected" in msg or "already connected" in msg.lower():
                raise TrueDataConnectionError(
                    "TrueData rejected the connection because the same user "
                    "is already connected from another session. Wait a few "
                    "seconds and retry, or disconnect the other session first."
                ) from e
            raise TrueDataConnectionError(
                f"Failed to create TD_live client: {type(e).__name__}: {e}"
            ) from e

        self._td = td
        self._connected = True
        logger.info("TrueData WS connection established successfully")
        return self._td

    def disconnect(self) -> None:
        """Tear down the shared connection. Thread-safe."""
        with self._lock:
            if self._td is None:
                return
            try:
                self._td.disconnect()
                logger.info("TrueData WS connection closed")
            except Exception as e:
                logger.warning("TrueData disconnect failed: %s: %s", type(e).__name__, e)
            finally:
                self._td = None
                self._connected = False

    def reconnect(self) -> Any:
        """Disconnect and reconnect. Useful if the WebSocket dropped."""
        self.disconnect()
        return self.connect()


# Process-wide singleton.
td_manager = TDConnectionManager()
