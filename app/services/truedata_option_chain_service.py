"""TrueData live option-chain snapshot client.

Wraps the official `truedata` SDK (v7+) `TD_live` class to capture real-time
option-chain snapshots for one or more (underlying, expiry) pairs over a
bounded duration. Used by the
`/api/v1/market-data/truedata/option-chain/export` endpoint.

Why v7 (`truedata.TD_live`) and not v5 (`truedata_ws.TD`)?
----------------------------------------------------------
The option-chain feature is only available in v7's `TD_live` class via the
`start_option_chain()` method. v5 (`truedata_ws.TD`) has a separate
`TD_chain.py` module that calls `exit()` on any error (kills the process)
and doesn't support greeks — unusable for a long-running web service.

How it works
------------
1. Open a `TD_live` websocket connection to `push.truedata.in:<live_port>`.
2. For each requested (underlying, expiry) pair, call
   `td.start_option_chain(symbol, expiry, chain_length, bid_ask, greek)`
   which returns an `OptionChain` object that auto-updates in a daemon
   thread by reading the shared `td.live_data` dict.
3. Sleep for `snapshot_interval_seconds`, then call `chain.get_option_chain()`
   to grab a point-in-time copy of the dataframe for each chain. Repeat
   until `duration_seconds` elapses.
4. Stop all chains, disconnect, project every snapshot onto a flat row
   schema, and return per-(underlying, expiry) DataFrames.

Hard-fail contract
-------------------
Any SDK error (connect failure, subscription rejection, missing data) is
re-raised as `TrueDataError`. The HTTP route maps that to HTTP 502. If
0 rows are captured across ALL chains (typically the trial-account
"User Subscription Expired" error, or market closed with no option
trades), we also raise `TrueDataError` so the caller gets a clear 502
instead of an empty ZIP.

CRITICAL: The v7 SDK's `TD_live.start_option_chain()` calls the builtin
`exit()` whenever `get_atm()` or `OptionChain()` raises — which would
kill the entire FastAPI worker process. We patch `exit` in the SDK
module's namespace at the start of `capture_option_chains` so it raises
`_SdkExitRaisedError` instead, which we catch and re-raise as
`TrueDataError`. This keeps the worker alive across SDK errors.

Note: `TD_live.__init__` already calls `self.connect()` at the end of
its constructor — we do NOT call `td.connect()` again. Connection
errors are caught by wrapping the constructor in try/except.

Trial-account caveat
--------------------
The trial account we ship as default (`Trial126` / `sand126`) does NOT
include option-chain entitlement. Calling `start_option_chain` will raise
`TrueDataError` with the message `"User Subscription Expired"` from the
SDK's WS layer. The endpoint will work the moment the account is upgraded
to a plan with option-chain support — no code changes required. This is
documented prominently in the README and in the error message.

Output schema (20 base columns + 6 optional greek columns)
-----------------------------------------------------------
Each row in the output .xls is one strike × option-type × snapshot-time:

    snapshot_time, underlying, expiry,
    symbol, strike, type,
    ltp, ltt, ltq, volume, price_change, price_change_perc,
    oi, prev_oi, oi_change, oi_change_perc,
    bid, bid_qty, ask, ask_qty,
    [iv, delta, theta, gamma, vega, rho]   # only when greek=true

The first 3 columns identify the snapshot + chain; the next 3 identify
the contract within the chain; the remaining columns mirror the SDK's
`chain_columns` + `chain_greek_fields` constants exactly (see
`truedata/websocket/constants.py`).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from app.core.config import settings

logger = logging.getLogger(__name__)


class TrueDataError(RuntimeError):
    """Raised when the TrueData SDK fails to connect, subscribe, or capture
    at least one option-chain row. Mapped to HTTP 502 by the route layer."""


class _SdkExitRaisedError(RuntimeError):
    """Raised by our patched `exit` to prevent the truedata SDK from killing
    the FastAPI worker process. Not part of the public API."""

    def __init__(self, original_message: str = "") -> None:
        # Strip "exit(") wrapper noise if any leaked through; the SDK calls
        # `exit()` (no args) so the message is usually empty.
        self.original_message = original_message or (
            "TrueData SDK called exit() — typically 'User Subscription "
            "Expired' (trial account lacks option-chain entitlement) or "
            "an invalid symbol/expiry."
        )
        super().__init__(self.original_message)


def _make_sdk_exit_raiser():
    """Return a callable that replaces the builtin `exit` in the SDK module
    namespace. Calling it raises `_SdkExitRaisedError` instead of killing the
    process."""
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
    `exit()` raise instead of killing the process. Idempotent — safe to call
    multiple times.

    The SDK's `start_option_chain` uses the builtin `exit` looked up at
    call time from its module globals, so patching the module namespace is
    sufficient. We do NOT need to patch `builtins.exit` (which would affect
    the whole interpreter).
    """
    import sys as _sys
    # The TD_live class is defined in truedata.websocket.TD_live
    module = _sys.modules.get(td_live_cls.__module__)
    if module is not None:
        if getattr(module, "_otp_exit_patched", False):
            return
        module.exit = exit_raiser  # type: ignore[attr-defined]
        # Also patch `quit` for completeness — some SDK versions use it.
        module.quit = exit_raiser  # type: ignore[attr-defined]
        module._otp_exit_patched = True  # type: ignore[attr-defined]
        logger.debug("Patched exit/quit in %s", td_live_cls.__module__)


def _format_subscription_error(original_msg: str) -> str:
    """Format a friendly 'trial account not entitled' error message."""
    return (
        "TrueData reports the account is not entitled for option-chain "
        f"data ({original_msg}). This is the typical behaviour for trial "
        "accounts — the trial plan does NOT include NSE F&O option chain. "
        "Upgrade the TrueData plan to one that includes option-chain "
        "entitlement; no code changes are required after the upgrade."
    )


# --- Output schema -------------------------------------------------------

# Base columns — always present in the output .xls. Matches the SDK's
# `chain_columns` constant (see truedata/websocket/constants.py) prepended
# with three identification columns (snapshot_time, underlying, expiry) and
# with the SDK's internal `symbols` index promoted to a regular column
# named `symbol` for easier downstream consumption.
OPTION_CHAIN_COLUMNS: list[str] = [
    "snapshot_time",
    "underlying",
    "expiry",
    "symbol",
    "strike",
    "type",
    "ltp",
    "ltt",
    "ltq",
    "volume",
    "price_change",
    "price_change_perc",
    "oi",
    "prev_oi",
    "oi_change",
    "oi_change_perc",
    "bid",
    "bid_qty",
    "ask",
    "ask_qty",
]

# Greek columns — appended after OPTION_CHAIN_COLUMNS when the caller
# requests `greek=true`. Order matches `chain_greek_fields` in the SDK.
GREEK_COLUMNS: list[str] = ["iv", "delta", "theta", "gamma", "vega", "rho"]


# --- Request / result dataclasses ---------------------------------------

@dataclass
class ChainRequest:
    """A single (underlying, expiry) pair to subscribe to.

    `underlying` is normalised to uppercase by the schema layer before
    reaching here. `expiry` is a `date` (not `datetime`).
    """
    underlying: str
    expiry: Any  # datetime.date — typed as Any to avoid import cycle
    chain_length: int
    bid_ask: bool
    greek: bool


@dataclass
class ChainCaptureResult:
    """Result of a `capture_option_chains` run.

    `frames` maps each (underlying, expiry) pair → its DataFrame (columns
    in `OPTION_CHAIN_COLUMNS` order, plus `GREEK_COLUMNS` if any chain
    requested greeks). The key format is `"{UNDERLYING}_{YYYY-MM-DD}"`.
    """
    frames: dict[str, pd.DataFrame]
    capture_started_at: str
    capture_ended_at: str
    total_rows: int


# --- Row projection -----------------------------------------------------

def _row_from_chain_df(
    chain_df: pd.DataFrame,
    *,
    underlying: str,
    expiry_str: str,
    snapshot_time: datetime,
    include_greek: bool,
) -> list[dict[str, Any]]:
    """Project the SDK's chain dataframe onto our flat row schema.

    The SDK's dataframe is indexed by symbol (e.g. `NIFTY26082825000CE`)
    with `strike` and `type` as regular columns plus the data columns
    from `chain_columns` (and optionally `chain_greek_fields`). We
    flatten it to one dict per row, prepending our identification columns.

    We coerce numeric types to plain Python natives because xlwt can't
    serialise numpy scalars. Missing values become `None` (which xlwt
    skips) so a partially-populated snapshot still writes cleanly.
    """
    if chain_df is None or chain_df.empty:
        return []

    # Determine which columns to read. The SDK always includes the base
    # chain_columns; greek_columns only when greek=true was requested.
    base_cols = [
        "strike", "type",
        "ltp", "ltt", "ltq", "volume",
        "price_change", "price_change_perc",
        "oi", "prev_oi", "oi_change", "oi_change_perc",
        "bid", "bid_qty", "ask", "ask_qty",
    ]
    greek_cols = GREEK_COLUMNS if include_greek else []

    # The SDK dataframe has the symbol as its index. Reset so we can read
    # it as a column.
    df = chain_df.reset_index() if "symbols" not in chain_df.columns else chain_df
    # The SDK names the index 'symbols' (see TD_chain.init_dataframe); rename
    # to our preferred 'symbol' for clarity.
    if "symbols" in df.columns:
        df = df.rename(columns={"symbols": "symbol"})

    rows: list[dict[str, Any]] = []
    snap_iso = snapshot_time.isoformat()
    for _, row in df.iterrows():
        out: dict[str, Any] = {
            "snapshot_time": snap_iso,
            "underlying": underlying,
            "expiry": expiry_str,
            "symbol": str(row.get("symbol", "")),
        }
        for col in base_cols + greek_cols:
            val = row.get(col)
            out[col] = _to_native_or_none(val)
        rows.append(out)
    return rows


def _to_native_or_none(val: Any) -> Any:
    """Coerce a numpy/pandas scalar to a plain Python native, returning
    None for NaN/NA so xlwt skips the cell."""
    if val is None:
        return None
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(val, "item"):
        try:
            return val.item()
        except Exception:  # noqa: BLE001
            return str(val)
    return val


# --- Capture orchestrator ----------------------------------------------

def capture_option_chains(
    requests: list[ChainRequest],
    *,
    duration_seconds: int,
    snapshot_interval_seconds: int,
) -> ChainCaptureResult:
    """Open a TrueData WS, start each requested option chain, sample
    snapshots at `snapshot_interval_seconds` cadence for `duration_seconds`,
    stop all chains, disconnect, and return per-(underlying, expiry)
    DataFrames.

    Hard-fails (raises `TrueDataError`) if:
      - The SDK cannot be imported / instantiated / connected.
      - Starting any chain fails (e.g. trial account "User Subscription
        Expired" error — see module docstring).
      - 0 rows are captured across ALL chains (typically means account
        not entitled for option chain, or all symbols are invalid).

    Parameters
    ----------
    requests : list[ChainRequest]
        One entry per (underlying, expiry) pair. Caller is responsible for
        de-duplication and length clamping to `TRUEDATA_CHAIN_MAX_PAIRS`.
    duration_seconds : int
        Total capture window. Caller clamps to
        `[5, TRUEDATA_CHAIN_MAX_DURATION_SEC]`.
    snapshot_interval_seconds : int
        Time between snapshots. Caller clamps to
        `[TRUEDATA_CHAIN_MIN_SNAPSHOT_INTERVAL_SEC,
          TRUEDATA_CHAIN_MAX_SNAPSHOT_INTERVAL_SEC]`.
    """
    if not requests:
        raise TrueDataError("capture_option_chains called with empty requests list")

    # Lazy import so the SDK is only loaded when actually needed; this keeps
    # pytest collection fast for tests that don't touch TrueData.
    try:
        from truedata.websocket.TD_live import TD_live  # type: ignore
    except ImportError as e:  # pragma: no cover - dependency is in requirements.txt
        raise TrueDataError(
            "truedata (v7+) package is not installed. "
            "Run `pip install -r requirements.txt`."
        ) from e

    started_at = datetime.now(timezone.utc)
    logger.info(
        "Starting option-chain capture: %d chains, duration=%ds, snapshot_interval=%ds, "
        "url=%s, port=%s",
        len(requests), duration_seconds, snapshot_interval_seconds,
        settings.TRUEDATA_URL, settings.TRUEDATA_LIVE_PORT,
    )

    # --- Patch the SDK's `exit()` calls before instantiating TD_live -----------
    # The v7 truedata SDK calls the builtin `exit()` from
    # `TD_live.start_option_chain()` whenever `get_atm()` or `OptionChain()`
    # raises (e.g. trial-account "User Subscription Expired", bad symbol, bad
    # expiry). That would kill the whole FastAPI worker. We replace `exit` in
    # the SDK module's namespace with a function that raises `TrueDataError`
    # instead, so we can catch it cleanly.
    # NB: `start_option_chain` does NOT wrap `exit()` in its own try/except, so
    # our patched `exit` will propagate as soon as it's called — perfect.
    sdk_exit_raiser = _make_sdk_exit_raiser()
    _patch_sdk_exit(TD_live, sdk_exit_raiser)

    # We pass `full_feed=False` because the option-chain feature only needs
    # the regular live-data subscription (the chain object reads from
    # `td.live_data` directly). `full_feed=True` would trigger a master-
    # contract download the trial account can't complete.
    #
    # IMPORTANT: TD_live.__init__() already calls self.connect() at the end
    # (see truedata/websocket/TD_live.py). So we must NOT call td.connect()
    # again — that would re-establish the websocket and likely hang. We wrap
    # the constructor itself in try/except to catch connection errors.
    td = None
    try:
        td = TD_live(
            login_id=settings.TRUEDATA_USERNAME,
            password=settings.TRUEDATA_PASSWORD,
            url=settings.TRUEDATA_URL,
            live_port=settings.TRUEDATA_LIVE_PORT,
            log_level=logging.WARNING,
        )
    except _SdkExitRaisedError as e:
        # Our patched exit() raised this — the SDK was about to die because
        # of a bad symbol/expiry OR the trial-account subscription error.
        raise TrueDataError(
            _format_subscription_error(e.original_message)
        ) from e
    except Exception as e:
        msg = str(e)
        if "Subscription Expired" in msg or "expired" in msg.lower():
            raise TrueDataError(
                _format_subscription_error(msg)
            ) from e
        raise TrueDataError(
            f"Failed to create TD_live client: {type(e).__name__}: {e}"
        ) from e

    # Start each requested chain. We track them in a list of (request, chain)
    # tuples so we can iterate over them at snapshot time.
    chains: list[tuple[ChainRequest, Any, str]] = []
    try:
        for req in requests:
            try:
                chain = td.start_option_chain(
                    symbol=req.underlying,
                    expiry=req.expiry,
                    chain_length=req.chain_length,
                    bid_ask=req.bid_ask,
                    greek=req.greek,
                )
            except _SdkExitRaisedError as e:
                # start_option_chain called exit() — typically because
                # get_atm() failed (trial account / bad symbol / bad expiry).
                raise TrueDataError(
                    f"Failed to start option chain for {req.underlying} "
                    f"expiry {req.expiry}: {e.original_message}. "
                    "If using a trial account, option-chain entitlement is "
                    "not included — upgrade the TrueData plan."
                ) from e
            except Exception as e:
                # Defensive: any other SDK exception.
                raise TrueDataError(
                    f"Failed to start option chain for {req.underlying} "
                    f"expiry {req.expiry}: {type(e).__name__}: {e}. "
                    "If using a trial account, option-chain entitlement is "
                    "not included — upgrade the TrueData plan."
                ) from e
            expiry_str = req.expiry.strftime("%Y-%m-%d")
            chains.append((req, chain, expiry_str))
            logger.info(
                "Started chain: underlying=%s expiry=%s length=%d bid_ask=%s greek=%s",
                req.underlying, expiry_str, req.chain_length, req.bid_ask, req.greek,
            )

        # Wait a moment for the SDK's `update_chain` daemon thread to
        # populate the dataframe from the live_data dict. The SDK itself
        # sleeps 2s after start_live_data before starting the thread, so
        # we wait an extra second beyond that.
        time.sleep(3)

        # Sample snapshots at the requested cadence. We use monotonic time
        # so we don't drift if the system clock jumps.
        snapshot_rows: dict[str, list[dict[str, Any]]] = {
            f"{req.underlying}_{expiry_str}": []
            for req, _, expiry_str in chains
        }
        deadline = time.monotonic() + duration_seconds
        snapshot_count = 0
        any_greek = any(req.greek for req, _, _ in chains)

        while time.monotonic() < deadline:
            snapshot_time = datetime.now(timezone.utc)
            for req, chain, expiry_str in chains:
                try:
                    chain_df = chain.get_option_chain()
                except Exception as e:
                    logger.warning(
                        "get_option_chain failed for %s/%s: %s",
                        req.underlying, expiry_str, e,
                    )
                    continue
                rows = _row_from_chain_df(
                    chain_df,
                    underlying=req.underlying,
                    expiry_str=expiry_str,
                    snapshot_time=snapshot_time,
                    include_greek=req.greek,
                )
                key = f"{req.underlying}_{expiry_str}"
                snapshot_rows[key].extend(rows)
            snapshot_count += 1
            # Sleep for the snapshot interval, but don't overshoot the deadline.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(snapshot_interval_seconds, remaining))

        capture_ended_at = datetime.now(timezone.utc)

    except TrueDataError:
        raise
    except Exception as e:
        raise TrueDataError(
            f"Error during option-chain capture: {type(e).__name__}: {e}"
        ) from e
    finally:
        # Stop all chains first (unsubscribes their option symbols), then
        # disconnect the WS. Both are best-effort — if they fail we log and
        # move on because we already have the captured data.
        for req, chain, _ in chains:
            try:
                chain.stop_option_chain()
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "stop_option_chain failed for %s: %s", req.underlying, e
                )
        try:
            td.disconnect()
        except Exception as e:  # noqa: BLE001
            logger.warning("TrueData disconnect failed: %s: %s", type(e).__name__, e)

    # Build per-(underlying, expiry) DataFrames.
    columns = OPTION_CHAIN_COLUMNS + (GREEK_COLUMNS if any_greek else [])
    frames: dict[str, pd.DataFrame] = {}
    total = 0
    for key, rows in snapshot_rows.items():
        total += len(rows)
        if not rows:
            frames[key] = pd.DataFrame(columns=columns)
            continue
        df = pd.DataFrame(rows, columns=columns)
        # Sort by snapshot_time, then strike, then type — stable so the
        # .xls reads naturally (chronological, then ascending strike, then
        # CE before PE which matches the SDK's sort).
        df = df.sort_values(
            ["snapshot_time", "strike", "type"], kind="stable"
        ).reset_index(drop=True)
        frames[key] = df

    if total == 0:
        raise TrueDataError(
            "No option-chain rows were captured during the capture window. "
            "Common causes: (a) account not entitled for option-chain data "
            "(trial accounts get 'User Subscription Expired'), (b) market is "
            "closed (IST 09:15–15:30 Mon–Fri) and no option trades occurred, "
            "(c) requested expiry is not a valid trading expiry for the "
            "underlying. Check the logs above for SDK errors."
        )

    logger.info(
        "Option-chain capture complete: %d total rows across %d chains "
        "(%d snapshots each)",
        total, len(frames), snapshot_count,
    )

    return ChainCaptureResult(
        frames=frames,
        capture_started_at=started_at.isoformat(),
        capture_ended_at=capture_ended_at.isoformat(),
        total_rows=total,
    )
