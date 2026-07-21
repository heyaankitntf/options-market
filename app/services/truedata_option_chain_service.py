"""TrueData live option-chain snapshot client.

Wraps the official `truedata` SDK (v7+) `TD_live` class to capture real-time
option-chain snapshots for one or more (underlying, expiry) pairs over a
bounded duration. Used by the
`/api/v1/market-data/truedata/option-chain/export` endpoint.

Architecture
------------
This service now uses the shared `TDConnectionManager` singleton instead of
creating a new `TD_live` per request. TrueData's server enforces a strict
one-connection-per-user policy — opening a second connection while the
standalone app already holds one causes the "User Already Connected" error
that was blocking the team.

By sharing a single process-wide `TD_live` instance, we avoid this entirely.

Data enrichment
---------------
The SDK's `OptionChain.update_chain()` method only copies a subset of fields
from `live_data` into its DataFrame (ltp, ltq, volume, oi, bid/ask, etc.).
However, `live_data[symbol_id]` contains the FULL tick-level dataclass
(`TickLiveData`) with many more fields: symbol_id, atp, day_open,
day_high, day_low, prev_day_close, turnover, special_tag, tick_seq, etc.

After calling `chain.get_option_chain()` to get the base DataFrame, we
enrich each row by looking up the corresponding entry in `td.live_data`
and pulling the additional fields the user requested.

Output schema
-------------
Call (CE) and Put (PE) data are segregated into **separate .xls files**
within the ZIP. For each (underlying, expiry) pair, the ZIP contains two
files: `..._CE.xls` and `..._PE.xls`.

Each row in every .xls is one strike × snapshot-time:

    Symbol ID, Date Time, LTP, LTQ, ATP, TTQ,
    Open, High, Low, Prev Close,
    OI, Prev Open Int Close, Day's Turnover,
    Special Tag, Tick Sequence No,
    Bid, Bid Qty, Ask, Ask Qty,
    Underlying, Expiry, Strike, Type

This matches the spec the user requested exactly. The `Type` column is
always present (will be "CE" in the CE file, "PE" in the PE file) so
downstream consumers can identify the option type even if files are merged.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, time as dt_time
from typing import Any

import pandas as pd

from app.core.config import settings
from app.services.truedata_connection_manager import (
    td_manager,
    TrueDataConnectionError,
)

logger = logging.getLogger(__name__)


class TrueDataError(RuntimeError):
    """Raised when the TrueData SDK fails to connect, subscribe, or capture
    at least one option-chain row. Mapped to HTTP 502 by the route layer."""


# --- Output schema -------------------------------------------------------
# Matches the user's requested column order exactly:
# Symbol ID, Date Time (Timestamp), LTP, LTQ, ATP, TTQ,
# Open, High, Low, Prev Close,
# OI, Prev Open Int Close, Day's Turnover,
# Special Tag, Tick Sequence No,
# Bid, Bid Qty, Ask, Ask Qty
#
# Plus identification columns appended at the end:
# Underlying, Expiry, Strike, Type
OPTION_CHAIN_COLUMNS: list[str] = [
    "Symbol ID",
    "Date Time",
    "LTP",
    "LTQ",
    "ATP",
    "TTQ",
    "Open",
    "High",
    "Low",
    "Prev Close",
    "OI",
    "Prev Open Int Close",
    "Day's Turnover",
    "Special Tag",
    "Tick Sequence No",
    "Bid",
    "Bid Qty",
    "Ask",
    "Ask Qty",
    "Underlying",
    "Expiry",
    "Strike",
    "Type",
]

# Greek columns — appended when greek=true is requested on any chain.
GREEK_COLUMNS: list[str] = ["IV", "Delta", "Theta", "Gamma", "Vega", "Rho"]


# --- Request / result dataclasses ---------------------------------------

@dataclass
class ChainRequest:
    """A single (underlying, expiry) pair to subscribe to."""
    underlying: str
    expiry: Any  # datetime.date
    chain_length: int
    bid_ask: bool
    greek: bool


@dataclass
class ChainCaptureResult:
    """Result of a `capture_option_chains` run.

    `frames` maps each (underlying, expiry, option_type) triplet → its
    DataFrame. The key format is `"{UNDERLYING}_{YYYY-MM-DD}_CE"` or
    `"{UNDERLYING}_{YYYY-MM-DD}_PE"`, so Call and Put data are already
    segregated into separate frames (each becoming a separate .xls file
    in the ZIP).
    """
    frames: dict[str, pd.DataFrame]
    capture_started_at: str
    capture_ended_at: str
    total_rows: int


# --- Row projection (enriched from live_data) ----------------------------

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


def _safe_attr(obj: Any, name: str, default: Any = None) -> Any:
    """Get attribute from an object, returning default if missing or None."""
    val = getattr(obj, name, default)
    return val if val is not None else default


def _enrich_row_from_live_data(
    td: Any,
    symbol_name: str,
    snapshot_time: datetime,
    underlying: str,
    expiry_str: str,
    strike: Any,
    option_type: str,
    chain_ltp: Any,
    chain_oi: Any,
    chain_prev_oi: Any,
    chain_bid: Any,
    chain_bid_qty: Any,
    chain_ask: Any,
    chain_ask_qty: Any,
    chain_ltq: Any,
    chain_volume: Any,
    greek_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a complete row by combining chain DataFrame data with the
    enriched tick-level fields from `td.live_data`.

    The chain DataFrame only contains a subset of fields. The `live_data`
    dict keyed by symbol_id contains the full `TickLiveData` with all the
    fields the user wants (atp, day_open, day_high, day_low, prev_day_close,
    turnover, special_tag, tick_seq, etc.).

    We look up each option symbol in `td.live_data` via the
    `symbol_mkt_id_map` (which maps symbol names → symbol IDs → live_data
    entries). If not found, we fall back to the chain DataFrame values
    for the fields that exist there, and use None for the rest.
    """
    # Try to find the symbol in live_data.
    live_entry = None
    if hasattr(td, 'live_data') and td.live_data:
        # The SDK maintains a symbol_mkt_id_map: symbol_name -> set of req_ids
        # and live_data: req_id -> TickLiveData
        symbol_map = getattr(td, 'symbol_mkt_id_map', {})
        req_ids = symbol_map.get(symbol_name, set())
        for rid in req_ids:
            if rid in td.live_data:
                live_entry = td.live_data[rid]
                break

    # Also try direct lookup in touchline_data (initial snapshot).
    if live_entry is None and hasattr(td, 'touchline_data') and td.touchline_data:
        symbol_map = getattr(td, 'symbol_mkt_id_map', {})
        req_ids = symbol_map.get(symbol_name, set())
        for rid in req_ids:
            if rid in td.touchline_data:
                live_entry = td.touchline_data[rid]
                break

    # Build the row with user's requested column order.
    row: dict[str, Any] = {}

    if live_entry is not None:
        # Full tick-level data available from live_data.
        row["Symbol ID"] = int(_safe_attr(live_entry, "symbol_id", 0) or 0)
        row["Date Time"] = _safe_attr(live_entry, "timestamp", snapshot_time)
        row["LTP"] = float(_safe_attr(live_entry, "ltp", chain_ltp) or chain_ltp or 0.0)
        row["LTQ"] = int(_safe_attr(live_entry, "ltq", chain_ltq) or chain_ltq or 0)
        row["ATP"] = float(_safe_attr(live_entry, "atp", 0.0) or 0.0)
        row["TTQ"] = float(_safe_attr(live_entry, "ttq", chain_volume) or chain_volume or 0.0)
        row["Open"] = float(_safe_attr(live_entry, "day_open", 0.0) or 0.0)
        row["High"] = float(_safe_attr(live_entry, "day_high", 0.0) or 0.0)
        row["Low"] = float(_safe_attr(live_entry, "day_low", 0.0) or 0.0)
        row["Prev Close"] = float(_safe_attr(live_entry, "prev_day_close", 0.0) or 0.0)
        row["OI"] = int(_safe_attr(live_entry, "oi", chain_oi) or chain_oi or 0)
        row["Prev Open Int Close"] = int(_safe_attr(live_entry, "prev_day_oi", chain_prev_oi) or chain_prev_oi or 0)
        row["Day's Turnover"] = float(_safe_attr(live_entry, "turnover", 0.0) or 0.0)
        row["Special Tag"] = str(_safe_attr(live_entry, "special_tag", "") or "")
        row["Tick Sequence No"] = int(_safe_attr(live_entry, "tick_seq", 0) or 0)
        row["Bid"] = float(_safe_attr(live_entry, "best_bid_price", chain_bid) or chain_bid or 0.0)
        row["Bid Qty"] = int(_safe_attr(live_entry, "best_bid_qty", chain_bid_qty) or chain_bid_qty or 0)
        row["Ask"] = float(_safe_attr(live_entry, "best_ask_price", chain_ask) or chain_ask or 0.0)
        row["Ask Qty"] = int(_safe_attr(live_entry, "best_ask_qty", chain_ask_qty) or chain_ask_qty or 0)
    else:
        # Fallback: use only what the chain DataFrame provides.
        # Missing fields are set to None.
        row["Symbol ID"] = None
        row["Date Time"] = snapshot_time
        row["LTP"] = _to_native_or_none(chain_ltp)
        row["LTQ"] = _to_native_or_none(chain_ltq)
        row["ATP"] = None
        row["TTQ"] = _to_native_or_none(chain_volume)
        row["Open"] = None
        row["High"] = None
        row["Low"] = None
        row["Prev Close"] = None
        row["OI"] = _to_native_or_none(chain_oi)
        row["Prev Open Int Close"] = _to_native_or_none(chain_prev_oi)
        row["Day's Turnover"] = None
        row["Special Tag"] = ""
        row["Tick Sequence No"] = None
        row["Bid"] = _to_native_or_none(chain_bid)
        row["Bid Qty"] = _to_native_or_none(chain_bid_qty)
        row["Ask"] = _to_native_or_none(chain_ask)
        row["Ask Qty"] = _to_native_or_none(chain_ask_qty)

    # Identification columns (always present).
    row["Underlying"] = underlying
    row["Expiry"] = expiry_str
    row["Strike"] = _to_native_or_none(strike)
    row["Type"] = str(option_type) if option_type else ""

    # Greek columns (if requested).
    if greek_data is not None:
        row["IV"] = greek_data.get("iv")
        row["Delta"] = greek_data.get("delta")
        row["Theta"] = greek_data.get("theta")
        row["Gamma"] = greek_data.get("gamma")
        row["Vega"] = greek_data.get("vega")
        row["Rho"] = greek_data.get("rho")

    return row


def _get_greek_data(td: Any, symbol_name: str) -> dict[str, Any] | None:
    """Try to look up greek data for a symbol from td.greek_data."""
    if not hasattr(td, 'greek_data') or not td.greek_data:
        return None
    greek_data = td.greek_data
    # greek_data is typically keyed by symbol_id or symbol name
    # Try symbol name first, then by looking up symbol_id from live_data
    if symbol_name in greek_data:
        gd = greek_data[symbol_name]
        return {
            "iv": _safe_attr(gd, "iv"),
            "delta": _safe_attr(gd, "delta"),
            "theta": _safe_attr(gd, "theta"),
            "gamma": _safe_attr(gd, "gamma"),
            "vega": _safe_attr(gd, "vega"),
            "rho": _safe_attr(gd, "rho"),
        }
    # Try via symbol_id
    symbol_map = getattr(td, 'symbol_mkt_id_map', {})
    req_ids = symbol_map.get(symbol_name, set())
    for rid in req_ids:
        if rid in greek_data:
            gd = greek_data[rid]
            return {
                "iv": _safe_attr(gd, "iv"),
                "delta": _safe_attr(gd, "delta"),
                "theta": _safe_attr(gd, "theta"),
                "gamma": _safe_attr(gd, "gamma"),
                "vega": _safe_attr(gd, "vega"),
                "rho": _safe_attr(gd, "rho"),
            }
    return None


# --- Capture orchestrator ----------------------------------------------

def capture_option_chains(
    requests: list[ChainRequest],
    *,
    duration_seconds: int,
    snapshot_interval_seconds: int,
) -> ChainCaptureResult:
    """Use the shared TrueData WS connection, start each requested option
    chain, sample snapshots at `snapshot_interval_seconds` cadence for
    `duration_seconds`, stop all chains, and return per-(underlying, expiry)
    DataFrames.

    Uses the shared `TDConnectionManager` singleton to avoid "User Already
    Connected" errors from TrueData's server.

    Hard-fails (raises `TrueDataError`) if:
      - The shared connection cannot be established.
      - Starting any chain fails.
      - 0 rows are captured across ALL chains.
    """
    if not requests:
        raise TrueDataError("capture_option_chains called with empty requests list")

    started_at = datetime.now(timezone.utc)
    logger.info(
        "Starting option-chain capture: %d chains, duration=%ds, snapshot_interval=%ds",
        len(requests), duration_seconds, snapshot_interval_seconds,
    )

    # 1. Get the shared connection (creates it if not already connected).
    try:
        td = td_manager.get_connection()
    except TrueDataConnectionError as e:
        raise TrueDataError(str(e)) from e

    # Start each requested chain.
    chains: list[tuple[ChainRequest, Any, str]] = []
    try:
        for req in requests:
            try:
                # The TrueData SDK's start_option_chain() internally calls
                # expiry.date(), so it expects a datetime.datetime, NOT a
                # datetime.date.  Pydantic parses the JSON "expiry" field as
                # a bare date — wrap it into a datetime so the SDK doesn't
                # crash with "'date' object has no attribute 'date'".
                expiry_dt = datetime.combine(req.expiry, dt_time(15, 30))
                chain = td.start_option_chain(
                    symbol=req.underlying,
                    expiry=expiry_dt,
                    chain_length=req.chain_length,
                    bid_ask=req.bid_ask,
                    greek=req.greek,
                )
            except SystemExit:
                # SDK called exit() — our patch should prevent this, but
                # catch SystemExit as a safety net.
                raise TrueDataError(
                    f"Failed to start option chain for {req.underlying} "
                    f"expiry {req.expiry}: SDK called exit(). "
                    "If using a trial account, option-chain entitlement is "
                    "not included — upgrade the TrueData plan."
                )
            except Exception as e:
                msg = str(e)
                if "Subscription Expired" in msg or "expired" in msg.lower():
                    raise TrueDataError(
                        f"Failed to start option chain for {req.underlying} "
                        f"expiry {req.expiry}: {msg}. "
                        "If using a trial account, option-chain entitlement is "
                        "not included — upgrade the TrueData plan."
                    ) from e
                raise TrueDataError(
                    f"Failed to start option chain for {req.underlying} "
                    f"expiry {req.expiry}: {type(e).__name__}: {e}"
                ) from e
            expiry_str = req.expiry.strftime("%Y-%m-%d")
            chains.append((req, chain, expiry_str))
            logger.info(
                "Started chain: underlying=%s expiry=%s length=%d bid_ask=%s greek=%s",
                req.underlying, expiry_str, req.chain_length, req.bid_ask, req.greek,
            )

        # Wait for the SDK's update_chain daemon thread to populate the
        # dataframe from live_data.
        time.sleep(3)

        # Sample snapshots at the requested cadence.
        # Separate CE and PE rows so they go into different .xls files.
        snapshot_rows: dict[str, list[dict[str, Any]]] = {}
        for req, _, expiry_str in chains:
            base_key = f"{req.underlying}_{expiry_str}"
            snapshot_rows[f"{base_key}_CE"] = []
            snapshot_rows[f"{base_key}_PE"] = []
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
                if chain_df is None or chain_df.empty:
                    continue

                # Reset index so 'symbols' becomes a regular column.
                df = chain_df.reset_index() if "symbols" not in chain_df.columns else chain_df
                if "symbols" in df.columns:
                    df = df.rename(columns={"symbols": "symbol"})

                for _, row_data in df.iterrows():
                    symbol_name = str(row_data.get("symbol", ""))

                    # Try to get greek data if requested.
                    greek_data = None
                    if any_greek:
                        greek_data = _get_greek_data(td, symbol_name)

                    enriched = _enrich_row_from_live_data(
                        td=td,
                        symbol_name=symbol_name,
                        snapshot_time=snapshot_time,
                        underlying=req.underlying,
                        expiry_str=expiry_str,
                        strike=row_data.get("strike"),
                        option_type=str(row_data.get("type", "")),
                        chain_ltp=row_data.get("ltp"),
                        chain_oi=row_data.get("oi"),
                        chain_prev_oi=row_data.get("prev_oi"),
                        chain_bid=row_data.get("bid"),
                        chain_bid_qty=row_data.get("bid_qty"),
                        chain_ask=row_data.get("ask"),
                        chain_ask_qty=row_data.get("ask_qty"),
                        chain_ltq=row_data.get("ltq"),
                        chain_volume=row_data.get("volume"),
                        greek_data=greek_data,
                    )
                    # Route CE rows to _CE key, PE rows to _PE key.
                    opt_type = str(row_data.get("type", "")).upper()
                    suffix = "CE" if opt_type == "CE" else "PE"
                    key = f"{req.underlying}_{expiry_str}_{suffix}"
                    snapshot_rows[key].append(enriched)

            snapshot_count += 1
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
        # Stop all chains (unsubscribes), but do NOT disconnect the shared
        # connection — other callers may still be using it.
        for req, chain, _ in chains:
            try:
                chain.stop_option_chain()
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "stop_option_chain failed for %s: %s", req.underlying, e
                )

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
        # Sort by Date Time, then Strike, then Type.
        df = df.sort_values(
            ["Date Time", "Strike", "Type"], kind="stable"
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
