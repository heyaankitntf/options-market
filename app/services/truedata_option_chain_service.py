"""TrueData live option-chain snapshot client.

Wraps the official `truedata` SDK (v7+) `TD_live` class to capture real-time
option-chain snapshots for one or more (underlying, expiry) pairs over a
bounded duration. Used by the
`/api/v1/market-data/truedata/option-chain/export` endpoint.

Architecture
------------
This service uses a **dual-mode approach** to maximise compatibility:

  **Mode 1 — WebSocket (TD_live SDK):** Uses the shared `TDConnectionManager`
  singleton to subscribe to option-chain symbols via WebSocket and capture
  live tick-level data. Works reliably for NIFTY option chains.

  **Mode 2 — REST API fallback:** When the WebSocket approach captures no data
  (e.g. for stock options like RELIANCE where the trial WebSocket feed doesn't
  stream those symbols), falls back to TrueData's REST API endpoint
  `https://api.truedata.in/getOptionChain` which returns a snapshot directly.

TrueData's server enforces a strict one-connection-per-user policy — opening
a second connection while the standalone app already holds one causes the
"User Already Connected" error. By sharing a single process-wide `TD_live`
instance, we avoid this entirely.

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

For the REST API fallback, the response already contains most fields per
contract (ltp, volume, oi, bid/ask, etc.) so we map them directly.

Output schema
-------------
Call (CE) and Put (PE) data are segregated into **separate .xls files**
within the ZIP. For each (underlying, expiry) pair, the ZIP contains two
files: `..._CE.xls` and `..._PE.xls`.

Each row in every .xls is one strike × snapshot-time:

    Symbol ID, Symbol, Date Time, LTP, LTQ, ATP, TTQ,
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
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, time as dt_time
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from app.core.config import settings
from app.services.truedata_connection_manager import (
    td_manager,
    TrueDataConnectionError,
    _make_sdk_exit_raiser,
    _patch_sdk_exit,
)

# TrueData REST API URLs — used by the REST fallback mode.
REST_API_ATM_URL = "https://api.truedata.in/getATMStrike"
REST_API_CHAIN_URL = "https://api.truedata.in/getOptionChain"

# IST timezone for replay-window checks. zoneinfo is stdlib (Python 3.9+).
_IST = ZoneInfo("Asia/Kolkata")

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
    "Symbol",
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
    dict keyed by symbol NAME contains the full `tick_feed` dataclass with
    all the fields the user wants (symbol_id, atp, day_open, day_high,
    day_low, prev_day_close, turnover, special_tag, tick_seq, etc.).

    IMPORTANT: The v7 SDK (TD_live) stores live_data and touchline_data
    keyed by the **symbol name string** (e.g. "NIFTY26072124000CE"), NOT
    by req_id or symbol_id. We look up the symbol directly.
    """
    # Try to find the symbol in live_data — keyed by symbol NAME string.
    live_entry = None
    if hasattr(td, 'live_data') and td.live_data:
        live_entry = td.live_data.get(symbol_name)

    # Fallback to touchline_data (initial snapshot) — also keyed by name.
    if live_entry is None and hasattr(td, 'touchline_data') and td.touchline_data:
        live_entry = td.touchline_data.get(symbol_name)

    # Build the row with user's requested column order.
    row: dict[str, Any] = {}

    if live_entry is not None:
        # Full tick-level data available from live_data.
        row["Symbol ID"] = int(_safe_attr(live_entry, "symbol_id", 0) or 0)
        row["Symbol"] = str(_safe_attr(live_entry, "symbol", symbol_name) or symbol_name)
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
        row["Symbol"] = symbol_name
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
    """Try to look up greek data for a symbol from td.greek_data.

    The SDK stores greek_data keyed by symbol name string (same as
    live_data / touchline_data).
    """
    if not hasattr(td, 'greek_data') or not td.greek_data:
        return None
    gd = td.greek_data.get(symbol_name)
    if gd is None:
        return None
    return {
        "iv": _safe_attr(gd, "iv"),
        "delta": _safe_attr(gd, "delta"),
        "theta": _safe_attr(gd, "theta"),
        "gamma": _safe_attr(gd, "gamma"),
        "vega": _safe_attr(gd, "vega"),
        "rho": _safe_attr(gd, "rho"),
    }


# --- REST API helpers (fallback mode) -----------------------------------

def _rest_get_atm_strike(underlying: str, expiry: Any) -> tuple[float, float]:
    """Call TrueData's getATMStrike REST API to get the ATM strike and
    strike step for a given underlying and expiry.

    Returns (atm_strike, strike_step) as floats.

    Raises TrueDataError on failure.
    """
    expiry_str = expiry.strftime("%Y%m%d")
    params = {
        "user": settings.TRUEDATA_USERNAME,
        "password": settings.TRUEDATA_PASSWORD,
        "symbol": underlying,
        "expiry": expiry_str,
    }
    try:
        resp = requests.get(REST_API_ATM_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise TrueDataError(
            f"REST API getATMStrike failed for {underlying}/{expiry_str}: {e}"
        ) from e

    if data.get("status") != "Success" or not data.get("Records"):
        raise TrueDataError(
            f"REST API getATMStrike returned no data for {underlying}/{expiry_str}. "
            f"Response: {data}. Possible causes: (a) the expiry is not a valid "
            "trading expiry for this underlying, (b) account not entitled, "
            "(c) market has no ATM data for this symbol."
        )

    records = data["Records"]
    atm_strike = float(records["strike"])
    strike_step = float(records["strikestep"])
    logger.info(
        "REST getATMStrike: underlying=%s expiry=%s atm=%.2f step=%.2f",
        underlying, expiry_str, atm_strike, strike_step,
    )
    return atm_strike, strike_step


def _rest_get_option_chain(
    underlying: str,
    expiry: Any,
    atm_strike: float,
    strike_step: float,
    chain_length: int,
) -> list[dict[str, Any]]:
    """Call TrueData's getOptionChain REST API to get a snapshot of option
    chain data for a given underlying, expiry, ATM strike, and chain length.

    Returns a list of dicts, each representing one option contract row.

    The REST API endpoint returns records with fields like:
      symbol, ltp, volume, oi, prev_oi, bid, bid_qty, ask, ask_qty, etc.

    Raises TrueDataError on failure.
    """
    expiry_str = expiry.strftime("%Y%m%d")
    params = {
        "user": settings.TRUEDATA_USERNAME,
        "password": settings.TRUEDATA_PASSWORD,
        "symbol": underlying,
        "expiry": expiry_str,
        "strike": int(atm_strike) if atm_strike == int(atm_strike) else atm_strike,
        "strikestep": int(strike_step) if strike_step == int(strike_step) else strike_step,
        "chainlength": chain_length,
    }
    try:
        resp = requests.get(REST_API_CHAIN_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise TrueDataError(
            f"REST API getOptionChain failed for {underlying}/{expiry_str}: {e}"
        ) from e

    if data.get("status") != "Success":
        raise TrueDataError(
            f"REST API getOptionChain returned error for {underlying}/{expiry_str}. "
            f"Response: {data}"
        )

    records = data.get("Records", [])
    if not records:
        logger.warning(
            "REST API getOptionChain returned empty Records for %s/%s",
            underlying, expiry_str,
        )
    else:
        logger.info(
            "REST getOptionChain: underlying=%s expiry=%s records=%d",
            underlying, expiry_str, len(records),
        )
    return records


def _parse_strike_from_symbol(symbol_name: str) -> Any:
    """Extract the numeric strike price from an option symbol name.

    Example: 'RELIANCE2607301300CE' -> 1300
    Example: 'NIFTY26073024500PE' -> 24500

    The strike is the numeric portion after the 6-digit expiry (YYMMDD)
    and before the CE/PE suffix.
    """
    # Match: underlying + 6-digit expiry + strike + CE/PE
    # The strike starts after the expiry digits and before CE/PE
    m = re.search(r'\d{6}(\d+(?:\.\d+)?)C?P?[CE]$', symbol_name)
    if m:
        strike_str = m.group(1)
        return float(strike_str) if '.' in strike_str else int(strike_str)
    # Fallback: just extract the last numeric run before CE/PE
    m = re.search(r'(\d+(?:\.\d+)?)(?:CE|PE)$', symbol_name, re.IGNORECASE)
    if m:
        strike_str = m.group(1)
        return float(strike_str) if '.' in strike_str else int(strike_str)
    return None


def _parse_type_from_symbol(symbol_name: str) -> str:
    """Extract option type (CE/PE) from symbol name."""
    if symbol_name.endswith("CE"):
        return "CE"
    elif symbol_name.endswith("PE"):
        return "PE"
    return ""


def _enrich_row_from_rest_data(
    record: dict[str, Any],
    underlying: str,
    expiry_str: str,
    snapshot_time: datetime,
) -> dict[str, Any]:
    """Build a complete row from a REST API getOptionChain record.

    The REST API returns per-contract data with fields that map to our
    output schema. Not all 19 fields are available from the REST API;
    missing ones are set to None/0.

    Typical REST API record fields:
      symbol, ltp, volume, oi, prev_oi, bid, bid_qty, ask, ask_qty,
      atp, day_open, day_high, day_low, prev_close, turnover, ltq,
      symbol_id, timestamp, etc.
    """
    symbol_name = str(record.get("symbol", ""))
    strike = _parse_strike_from_symbol(symbol_name)
    option_type = _parse_type_from_symbol(symbol_name)

    row: dict[str, Any] = {
        "Symbol ID": int(record.get("symbol_id", 0) or 0),
        "Symbol": symbol_name,
        "Date Time": record.get("timestamp", snapshot_time) or snapshot_time,
        "LTP": float(record.get("ltp", 0) or 0),
        "LTQ": int(record.get("ltq", 0) or 0),
        "ATP": float(record.get("atp", 0) or 0),
        "TTQ": float(record.get("volume", 0) or 0),
        "Open": float(record.get("day_open", 0) or 0),
        "High": float(record.get("day_high", 0) or 0),
        "Low": float(record.get("day_low", 0) or 0),
        "Prev Close": float(record.get("prev_close", 0) or 0),
        "OI": int(record.get("oi", 0) or 0),
        "Prev Open Int Close": int(record.get("prev_oi", 0) or 0),
        "Day's Turnover": float(record.get("turnover", 0) or 0),
        "Special Tag": str(record.get("special_tag", "") or ""),
        "Tick Sequence No": int(record.get("tick_seq", 0) or 0),
        "Bid": float(record.get("bid", 0) or 0),
        "Bid Qty": int(record.get("bid_qty", 0) or 0),
        "Ask": float(record.get("ask", 0) or 0),
        "Ask Qty": int(record.get("ask_qty", 0) or 0),
        "Underlying": underlying,
        "Expiry": expiry_str,
        "Strike": strike,
        "Type": option_type,
    }
    return row


def capture_option_chains_via_rest(
    requests: list[ChainRequest],
) -> ChainCaptureResult:
    """Capture option-chain data using TrueData's REST API (no WebSocket).

    This is the fallback mode used when the WebSocket approach captures no
    data (e.g. for stock options like RELIANCE where the trial WebSocket
    feed doesn't stream those symbols).

    The REST API provides a single snapshot per call (no time-series
    sampling). We take one snapshot and return it. If multiple snapshots
    are needed, the caller can invoke this function multiple times.

    Hard-fails (raises TrueDataError) if:
      - The getATMStrike REST call fails for any underlying.
      - The getOptionChain REST call returns no records for ALL chains.
    """
    if not requests:
        raise TrueDataError("capture_option_chains_via_rest called with empty requests list")

    started_at = datetime.now(timezone.utc)
    logger.info(
        "Starting option-chain capture via REST API: %d chains",
        len(requests),
    )

    snapshot_time = datetime.now(timezone.utc)
    snapshot_rows: dict[str, list[dict[str, Any]]] = {}
    any_greek = any(req.greek for req in requests)

    for req in requests:
        expiry_str = req.expiry.strftime("%Y-%m-%d")
        base_key = f"{req.underlying}_{expiry_str}"
        snapshot_rows[f"{base_key}_CE"] = []
        snapshot_rows[f"{base_key}_PE"] = []

        # Step 1: Get ATM strike via REST.
        try:
            atm_strike, strike_step = _rest_get_atm_strike(req.underlying, req.expiry)
        except TrueDataError:
            raise
        except Exception as e:
            raise TrueDataError(
                f"REST API getATMStrike failed for {req.underlying}/{expiry_str}: "
                f"{type(e).__name__}: {e}"
            ) from e

        # Step 2: Get option chain snapshot via REST.
        try:
            records = _rest_get_option_chain(
                underlying=req.underlying,
                expiry=req.expiry,
                atm_strike=atm_strike,
                strike_step=strike_step,
                chain_length=req.chain_length,
            )
        except TrueDataError:
            raise
        except Exception as e:
            raise TrueDataError(
                f"REST API getOptionChain failed for {req.underlying}/{expiry_str}: "
                f"{type(e).__name__}: {e}"
            ) from e

        # Step 3: Map REST records to our output schema.
        for record in records:
            enriched = _enrich_row_from_rest_data(
                record=record,
                underlying=req.underlying,
                expiry_str=expiry_str,
                snapshot_time=snapshot_time,
            )
            # Add greek columns as None (REST API doesn't return greeks).
            if any_greek:
                for col in GREEK_COLUMNS:
                    enriched[col] = None

            opt_type = enriched.get("Type", "").upper()
            suffix = "CE" if opt_type == "CE" else "PE"
            key = f"{req.underlying}_{expiry_str}_{suffix}"
            snapshot_rows[key].append(enriched)

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
        df = df.sort_values(
            ["Date Time", "Strike", "Type"], kind="stable"
        ).reset_index(drop=True)
        frames[key] = df

    if total == 0:
        raise TrueDataError(
            "REST API getOptionChain returned no records for any chain. "
            "Common causes: (a) market is closed (IST 09:15–15:30 Mon–Fri) "
            "and the REST API has no snapshot data, (b) the requested expiry "
            "is not a valid trading expiry for the underlying, "
            "(c) account not entitled for option-chain data."
        )

    capture_ended_at = datetime.now(timezone.utc)
    logger.info(
        "REST API option-chain capture complete: %d total rows across %d chains",
        total, len(frames),
    )

    return ChainCaptureResult(
        frames=frames,
        capture_started_at=started_at.isoformat(),
        capture_ended_at=capture_ended_at.isoformat(),
        total_rows=total,
    )


# --- Capture orchestrator (dual-mode) -----------------------------------

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

    If the WebSocket approach fails (connection error, SDK exit, subscription
    expired, or 0 rows captured), automatically falls back to TrueData's
    REST API (`getOptionChain` endpoint).

    Uses the shared `TDConnectionManager` singleton to avoid "User Already
    Connected" errors from TrueData's server.
    """
    if not requests:
        raise TrueDataError("capture_option_chains called with empty requests list")

    started_at = datetime.now(timezone.utc)
    logger.info(
        "Starting option-chain capture: %d chains, duration=%ds, snapshot_interval=%ds",
        len(requests), duration_seconds, snapshot_interval_seconds,
    )

    # 1. Get the shared connection (creates it if not already connected).
    td = None
    ws_error: str | None = None
    try:
        td = td_manager.get_connection()
    except TrueDataConnectionError as e:
        ws_error = f"WebSocket connection failed: {e}"
        logger.warning("WebSocket connection failed, will try REST fallback: %s", e)

    # Start each requested chain via WebSocket. Track which chains failed
    # so we can retry them via REST API.
    chains: list[tuple[ChainRequest, Any, str]] = []
    failed_ws_requests: list[ChainRequest] = []

    if td is not None:
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
                expiry_str = req.expiry.strftime("%Y-%m-%d")
                chains.append((req, chain, expiry_str))
                logger.info(
                    "Started chain via WebSocket: underlying=%s expiry=%s length=%d",
                    req.underlying, expiry_str, req.chain_length,
                )
            except SystemExit:
                # SDK called exit() — our patch should prevent this, but
                # catch SystemExit as a safety net. Mark this chain for
                # REST fallback instead of hard-failing.
                logger.warning(
                    "SDK exit() for %s/%s — will retry via REST API",
                    req.underlying, req.expiry,
                )
                failed_ws_requests.append(req)
            except Exception as e:
                msg = str(e)
                if "Subscription Expired" in msg or "expired" in msg.lower():
                    logger.warning(
                        "Subscription expired for %s/%s — will retry via REST API",
                        req.underlying, req.expiry,
                    )
                    failed_ws_requests.append(req)
                else:
                    logger.warning(
                        "WebSocket start_option_chain failed for %s/%s: %s — "
                        "will retry via REST API",
                        req.underlying, req.expiry, e,
                    )
                    failed_ws_requests.append(req)

        # Wait for the SDK's update_chain daemon thread to populate the
        # dataframe from live_data.
        time.sleep(3)

    # If all chains failed WebSocket subscription, go straight to REST.
    if not chains and failed_ws_requests:
        logger.info(
            "All %d chains failed WebSocket — using REST API fallback",
            len(failed_ws_requests),
        )
        return capture_option_chains_via_rest(failed_ws_requests)

    # Sample WebSocket snapshots at the requested cadence.
    # Separate CE and PE rows so they go into different .xls files.
    snapshot_rows: dict[str, list[dict[str, Any]]] = {}
    any_greek = any(req.greek for req in requests)
    columns = OPTION_CHAIN_COLUMNS + (GREEK_COLUMNS if any_greek else [])

    for req, _, expiry_str in chains:
        base_key = f"{req.underlying}_{expiry_str}"
        snapshot_rows[f"{base_key}_CE"] = []
        snapshot_rows[f"{base_key}_PE"] = []

    snapshot_count = 0
    try:
        deadline = time.monotonic() + duration_seconds

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

    except Exception as e:
        logger.warning(
            "Error during WebSocket capture: %s: %s — will try REST fallback",
            type(e).__name__, e,
        )
        failed_ws_requests.extend(req for req, _, _ in chains)
        chains = []  # Don't try to stop chains that errored
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

    # Build per-(underlying, expiry) DataFrames from WebSocket data.
    frames: dict[str, pd.DataFrame] = {}
    total = 0
    for key, rows in snapshot_rows.items():
        total += len(rows)
        if not rows:
            frames[key] = pd.DataFrame(columns=columns)
            continue
        df = pd.DataFrame(rows, columns=columns)
        df = df.sort_values(
            ["Date Time", "Strike", "Type"], kind="stable"
        ).reset_index(drop=True)
        frames[key] = df

    # If WebSocket captured nothing or some chains failed, try REST fallback
    # for the failed/empty chains.
    needs_rest = failed_ws_requests.copy()
    if total == 0:
        needs_rest = requests  # Nothing from WS at all, retry everything via REST

    if needs_rest:
        logger.info(
            "Attempting REST API fallback for %d chains...",
            len(needs_rest),
        )
        try:
            rest_result = capture_option_chains_via_rest(needs_rest)
            # Merge REST results with any WebSocket results.
            for key, rest_df in rest_result.frames.items():
                if key in frames and not frames[key].empty:
                    # Append REST rows to existing WebSocket rows.
                    frames[key] = pd.concat(
                        [frames[key], rest_df], ignore_index=True
                    ).sort_values(
                        ["Date Time", "Strike", "Type"], kind="stable"
                    ).reset_index(drop=True)
                else:
                    frames[key] = rest_df
            total = sum(len(f) for f in frames.values())
            logger.info(
                "REST API fallback succeeded: combined total=%d rows",
                total,
            )
        except TrueDataError as rest_err:
            if total == 0:
                # Neither WebSocket nor REST produced any data.
                raise TrueDataError(
                    "No option-chain rows were captured via WebSocket or REST API. "
                    f"WebSocket: 0 rows (trial WebSocket feed may not stream this "
                    "underlying's options, or market is closed IST 09:15–15:30 "
                    "Mon–Fri, or requested expiry is invalid). "
                    f"REST fallback also failed: {rest_err}"
                ) from rest_err
            # WebSocket had some data, REST failed for the rest — log and continue.
            logger.warning(
                "REST fallback failed for some chains, but WebSocket captured "
                "%d rows. Continuing with WebSocket data only. REST error: %s",
                total, rest_err,
            )

    if total == 0:
        raise TrueDataError(
            "No option-chain rows were captured during the capture window. "
            "Common causes: (a) account not entitled for option-chain data, "
            "(b) market is closed (IST 09:15–15:30 Mon–Fri), "
            "(c) requested expiry is not a valid trading expiry for the underlying."
        )

    capture_ended_at = datetime.now(timezone.utc)

    logger.info(
        "Option-chain capture complete: %d total rows across %d frames",
        total, len(frames),
    )

    return ChainCaptureResult(
        frames=frames,
        capture_started_at=started_at.isoformat(),
        capture_ended_at=capture_ended_at.isoformat(),
        total_rows=total,
    )


# --- Replay helpers -----------------------------------------------------

def is_replay_window_open(now: datetime | None = None) -> bool:
    """Return True if `now` (IST) is inside the TrueData replay availability
    window.

    The replay feed is available from `TRUEDATA_REPLAY_WINDOW_START_HOUR`
    (default 18 = 6 PM IST) through `TRUEDATA_REPLAY_WINDOW_END_HOUR`
    (default 2 = 2 AM IST next day). Because the window crosses midnight,
    "inside" means: `hour >= start` OR `hour < end`.

    Parameters
    ----------
    now : datetime, optional
        If None, uses the current time. Always interpreted in IST — if the
        supplied datetime is naive or in another timezone, we convert it.
    """
    if now is None:
        now = datetime.now(_IST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=_IST)
    else:
        now = now.astimezone(_IST)

    start = settings.TRUEDATA_REPLAY_WINDOW_START_HOUR
    end = settings.TRUEDATA_REPLAY_WINDOW_END_HOUR

    if start == end:
        return True  # Degenerate config — treat as always open.
    if start < end:
        return start <= now.hour < end
    # Window crosses midnight, e.g. 18 → 2.
    return now.hour >= start or now.hour < end


def replay_window_description() -> str:
    """Human-readable description of the current replay window, e.g.
    '18:00–02:00 IST'. Used in HTTP 409 error responses."""
    start = settings.TRUEDATA_REPLAY_WINDOW_START_HOUR
    end = settings.TRUEDATA_REPLAY_WINDOW_END_HOUR
    return f"{start:02d}:00–{end:02d}:00 IST"


def capture_option_chains_replay(
    requests: list[ChainRequest],
    *,
    duration_seconds: int,
    snapshot_interval_seconds: int,
) -> ChainCaptureResult:
    """Capture option-chain data via TrueData's replay WebSocket.

    Connects to the replay server (replay.truedata.in:8082) instead of the
    live push server. The replay feed repeats the most recent market session
    at real-time pace and is only available ~18:00–02:00 IST.

    This creates a **separate** `TD_live` instance (not the shared singleton)
    because the replay server uses a different URL/port. The replay connection
    is ephemeral — created for this request and torn down afterwards.

    If the replay WebSocket approach captures no data, automatically falls
    back to TrueData's REST API (`getOptionChain` endpoint).

    NO AUTHENTICATION REQUIRED — this is a public endpoint.

    Hard-fails (raises TrueDataError) if:
      - The replay connection cannot be established.
      - 0 rows are captured via both WebSocket replay AND REST fallback.
    """
    if not requests:
        raise TrueDataError("capture_option_chains_replay called with empty requests list")

    started_at = datetime.now(timezone.utc)
    logger.info(
        "Starting option-chain REPLAY capture: %d chains, duration=%ds, snapshot_interval=%ds",
        len(requests), duration_seconds, snapshot_interval_seconds,
    )

    # 1. Create a dedicated TD_live instance connected to the replay server.
    td = None
    try:
        from truedata.websocket.TD_live import TD_live  # type: ignore
    except ImportError as e:
        raise TrueDataError(
            "truedata (v7+) package is not installed. "
            "Run `pip install -r requirements.txt`."
        ) from e

    # Patch SDK exit before instantiation (same as connection manager).
    sdk_exit_raiser = _make_sdk_exit_raiser()
    _patch_sdk_exit(TD_live, sdk_exit_raiser)

    try:
        logger.info(
            "Connecting to TrueData REPLAY WS: user=%s url=%s port=%s",
            settings.TRUEDATA_USERNAME,
            settings.TRUEDATA_REPLAY_URL,
            settings.TRUEDATA_REPLAY_PORT,
        )
        td = TD_live(
            login_id=settings.TRUEDATA_USERNAME,
            password=settings.TRUEDATA_PASSWORD,
            url=settings.TRUEDATA_REPLAY_URL,
            live_port=settings.TRUEDATA_REPLAY_PORT,
            log_level=logging.WARNING,
        )
    except Exception as e:
        msg = str(e)
        if "User Already Connected" in msg or "already connected" in msg.lower():
            logger.warning(
                "Replay WebSocket already in use — falling back to REST API"
            )
            return capture_option_chains_via_rest(requests)
        logger.warning(
            "Replay TD_live connection failed: %s — falling back to REST API", e
        )
        return capture_option_chains_via_rest(requests)

    # 2. Start option chains on the replay connection.
    chains: list[tuple[ChainRequest, Any, str]] = []
    failed_ws_requests: list[ChainRequest] = []

    for req in requests:
        try:
            expiry_dt = datetime.combine(req.expiry, dt_time(15, 30))
            chain = td.start_option_chain(
                symbol=req.underlying,
                expiry=expiry_dt,
                chain_length=req.chain_length,
                bid_ask=req.bid_ask,
                greek=req.greek,
            )
            expiry_str = req.expiry.strftime("%Y-%m-%d")
            chains.append((req, chain, expiry_str))
            logger.info(
                "Started chain via REPLAY WebSocket: underlying=%s expiry=%s length=%d",
                req.underlying, expiry_str, req.chain_length,
            )
        except SystemExit:
            logger.warning(
                "SDK exit() for %s/%s on replay — will retry via REST API",
                req.underlying, req.expiry,
            )
            failed_ws_requests.append(req)
        except Exception as e:
            logger.warning(
                "Replay start_option_chain failed for %s/%s: %s — "
                "will retry via REST API",
                req.underlying, req.expiry, e,
            )
            failed_ws_requests.append(req)

    # Wait for data to populate.
    time.sleep(3)

    # If all chains failed on replay WebSocket, go straight to REST.
    if not chains and failed_ws_requests:
        logger.info(
            "All %d chains failed on replay WebSocket — using REST API fallback",
            len(failed_ws_requests),
        )
        _safe_disconnect(td)
        return capture_option_chains_via_rest(failed_ws_requests)

    # 3. Sample snapshots from the replay WebSocket.
    snapshot_rows: dict[str, list[dict[str, Any]]] = {}
    any_greek = any(req.greek for req in requests)
    columns = OPTION_CHAIN_COLUMNS + (GREEK_COLUMNS if any_greek else [])

    for req, _, expiry_str in chains:
        base_key = f"{req.underlying}_{expiry_str}"
        snapshot_rows[f"{base_key}_CE"] = []
        snapshot_rows[f"{base_key}_PE"] = []

    snapshot_count = 0
    try:
        deadline = time.monotonic() + duration_seconds

        while time.monotonic() < deadline:
            snapshot_time = datetime.now(timezone.utc)
            for req, chain, expiry_str in chains:
                try:
                    chain_df = chain.get_option_chain()
                except Exception as e:
                    logger.warning(
                        "Replay get_option_chain failed for %s/%s: %s",
                        req.underlying, expiry_str, e,
                    )
                    continue
                if chain_df is None or chain_df.empty:
                    continue

                df = chain_df.reset_index() if "symbols" not in chain_df.columns else chain_df
                if "symbols" in df.columns:
                    df = df.rename(columns={"symbols": "symbol"})

                for _, row_data in df.iterrows():
                    symbol_name = str(row_data.get("symbol", ""))

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
                    opt_type = str(row_data.get("type", "")).upper()
                    suffix = "CE" if opt_type == "CE" else "PE"
                    key = f"{req.underlying}_{expiry_str}_{suffix}"
                    snapshot_rows[key].append(enriched)

            snapshot_count += 1
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(snapshot_interval_seconds, remaining))

    except Exception as e:
        logger.warning(
            "Error during replay capture: %s: %s — will try REST fallback",
            type(e).__name__, e,
        )
        failed_ws_requests.extend(req for req, _, _ in chains)
        chains = []
    finally:
        # Stop all chains on the replay connection.
        for req, chain, _ in chains:
            try:
                chain.stop_option_chain()
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "Replay stop_option_chain failed for %s: %s", req.underlying, e
                )
        # Disconnect the replay connection — it's ephemeral, not shared.
        _safe_disconnect(td)

    # Build DataFrames from replay WebSocket data.
    frames: dict[str, pd.DataFrame] = {}
    total = 0
    for key, rows in snapshot_rows.items():
        total += len(rows)
        if not rows:
            frames[key] = pd.DataFrame(columns=columns)
            continue
        df = pd.DataFrame(rows, columns=columns)
        df = df.sort_values(
            ["Date Time", "Strike", "Type"], kind="stable"
        ).reset_index(drop=True)
        frames[key] = df

    # If replay captured nothing, try REST fallback.
    needs_rest = failed_ws_requests.copy()
    if total == 0:
        needs_rest = requests

    if needs_rest:
        logger.info(
            "Attempting REST API fallback for %d replay chains...",
            len(needs_rest),
        )
        try:
            rest_result = capture_option_chains_via_rest(needs_rest)
            for key, rest_df in rest_result.frames.items():
                if key in frames and not frames[key].empty:
                    frames[key] = pd.concat(
                        [frames[key], rest_df], ignore_index=True
                    ).sort_values(
                        ["Date Time", "Strike", "Type"], kind="stable"
                    ).reset_index(drop=True)
                else:
                    frames[key] = rest_df
            total = sum(len(f) for f in frames.values())
            logger.info(
                "REST API fallback succeeded for replay: combined total=%d rows",
                total,
            )
        except TrueDataError as rest_err:
            if total == 0:
                raise TrueDataError(
                    "No option-chain rows were captured via replay WebSocket or "
                    f"REST API. Replay WebSocket: 0 rows. REST fallback also "
                    f"failed: {rest_err}"
                ) from rest_err
            logger.warning(
                "REST fallback failed for some replay chains, but replay "
                "WebSocket captured %d rows. Continuing with replay data only. "
                "REST error: %s",
                total, rest_err,
            )

    if total == 0:
        raise TrueDataError(
            "No option-chain rows were captured during the replay capture "
            "window. Common causes: (a) replay feed is not active (check "
            "18:00–02:00 IST), (b) account not entitled for option-chain data, "
            "(c) requested expiry is not a valid trading expiry for the underlying."
        )

    capture_ended_at = datetime.now(timezone.utc)
    logger.info(
        "Option-chain REPLAY capture complete: %d total rows across %d frames",
        total, len(frames),
    )

    return ChainCaptureResult(
        frames=frames,
        capture_started_at=started_at.isoformat(),
        capture_ended_at=capture_ended_at.isoformat(),
        total_rows=total,
    )


def _safe_disconnect(td: Any) -> None:
    """Safely disconnect a TD_live instance, swallowing errors."""
    if td is None:
        return
    try:
        td.disconnect()
    except Exception as e:  # noqa: BLE001
        logger.warning("Replay disconnect failed: %s: %s", type(e).__name__, e)
