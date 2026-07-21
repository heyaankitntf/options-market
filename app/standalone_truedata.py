"""Standalone TrueData option-chain + tick-data API.

NO AUTH — runs as a separate FastAPI app on port 8086 alongside the main
authenticated app. Uses a single long-lived TD_live websocket connection
with a daemon-thread auto-save loop, exactly matching the team-lead's
reference script.

Run with:
    .venv/bin/python -m app.standalone_truedata
or:
    .venv/bin/uvicorn app.standalone_truedata:app --host 0.0.0.0 --port 8086

Endpoints (all public, no JWT):
    GET /                                -> status
    GET /option-chain/{symbol}           -> current chain as JSON records
    GET /option-chain/all                -> all chains as JSON
    GET /export/{symbol}                 -> save one chain to .xlsx
    GET /export/all                      -> save all chains to single .xlsx
    GET /export/ticks                    -> save captured ticks to .xlsx
    GET /ticks                           -> last 100 captured ticks
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from datetime import datetime as dt

import pandas as pd
import uvicorn
from fastapi import FastAPI, HTTPException, Request

# Load .env from the CWD so the standalone picks up the same TrueData
# credentials as the main app. pydantic-settings does this for the main
# app automatically; the standalone uses os.environ directly, so we need
# to call load_dotenv() ourselves.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    # python-dotenv is a transitive dep of pydantic-settings, so this should
    # never fire. If it does, env vars still work — .env just isn't loaded.
    pass

# TrueData is imported lazily so importing this module doesn't crash if the
# SDK isn't installed yet (e.g. during testing).
try:
    from truedata import TD_live
except ImportError:  # pragma: no cover
    TD_live = None  # type: ignore

# ---------------- Config ----------------
# All of these can be overridden via env vars (or .env — load_dotenv() above).
# Defaults match the team-lead's reference script exactly.
AUTO_SAVE_INTERVAL_SECONDS = int(os.environ.get("AUTO_SAVE_INTERVAL_SECONDS", "30"))
API_PORT = int(os.environ.get("API_PORT", "8086"))

TRUEDATA_USERNAME = os.environ.get("TRUEDATA_USERNAME", "Trial126")
TRUEDATA_PASSWORD = os.environ.get("TRUEDATA_PASSWORD", "sand126")
TRUEDATA_LIVE_PORT = int(os.environ.get("TRUEDATA_LIVE_PORT", "8086"))

# Symbols for live tick + bidask stream.
MY_SYMBOLS = ["BANKNIFTY-I", "SBIN-I", "SBIN", "NIFTY 50"]

# Pre-configured option chains. Each entry: (key, underlying, expiry, chain_length, bid_ask, greek).
# Adjust expiry dates as needed — they must be valid NSE F&O expiry dates.
PRESET_CHAINS = [
    ("nifty", "NIFTY", dt(2026, 7, 28), 20, True, False),
]

# ---------------- Globals (populated at startup) ----------------
td_obj = None  # type: ignore
CHAIN_MAP: dict[str, object] = {}

# ---------------- Tick data storage ----------------
TICK_COLUMNS = [
    "Symbol ID", "Date Time", "LTP", "LTQ", "ATP", "TTQ",
    "Open", "High", "Low", "Prev Close", "OI", "Prev Open Int Close",
    "Day's Turnover", "Special Tag", "Tick Sequence No",
    "Bid", "Bid Qty", "Ask", "Ask Qty",
]

tick_records: list[dict] = []
tick_lock = threading.Lock()

EXCEL_DIR = "option_chain_exports"
TICK_DIR = "tick_data_exports"
os.makedirs(EXCEL_DIR, exist_ok=True)
os.makedirs(TICK_DIR, exist_ok=True)


# ---------------- Helpers ----------------
def safe_get(obj, *names):
    """Return the first matching attribute on `obj`, else None."""
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    return None


def build_tick_row(data) -> dict:
    """Project a truedata tick/bidask object onto the 18-column tick schema."""
    return {
        "Symbol ID": safe_get(data, "symbol_id", "symbolid", "symbol"),
        "Date Time": safe_get(data, "timestamp", "date_time", "time") or datetime.now(),
        "LTP": safe_get(data, "ltp", "last_traded_price"),
        "LTQ": safe_get(data, "ltq", "last_traded_qty"),
        "ATP": safe_get(data, "atp", "avg_traded_price"),
        "TTQ": safe_get(data, "ttq", "volume", "total_traded_qty"),
        "Open": safe_get(data, "open", "day_open"),
        "High": safe_get(data, "high", "day_high"),
        "Low": safe_get(data, "low", "day_low"),
        "Prev Close": safe_get(data, "prev_close", "previous_close"),
        "OI": safe_get(data, "oi", "open_interest"),
        "Prev Open Int Close": safe_get(data, "prev_oi", "prev_open_interest"),
        "Day's Turnover": safe_get(data, "turnover", "day_turnover"),
        "Special Tag": safe_get(data, "special_tag", "tag") or "",
        "Tick Sequence No": safe_get(data, "tick_seq", "tick_sequence_no", "seq_no"),
        "Bid": safe_get(data, "bid", "bid_price"),
        "Bid Qty": safe_get(data, "bid_qty", "bid_qty1"),
        "Ask": safe_get(data, "ask", "ask_price"),
        "Ask Qty": safe_get(data, "ask_qty", "ask_qty1"),
    }


def save_chain_to_excel(symbol: str, df) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(EXCEL_DIR, f"{symbol}_{timestamp}.xlsx")
    df.to_excel(filepath, index=False)
    return filepath


def save_all_chains_to_single_excel() -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(EXCEL_DIR, f"all_chains_{timestamp}.xlsx")
    with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
        for name, chain_obj in CHAIN_MAP.items():
            df = chain_obj.get_option_chain()
            if df is not None and not df.empty:
                df.to_excel(writer, sheet_name=name.upper(), index=False)
    return filepath


def save_tick_data_to_excel():
    with tick_lock:
        if not tick_records:
            return None
        df = pd.DataFrame(tick_records, columns=TICK_COLUMNS)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(TICK_DIR, f"tick_data_{timestamp}.xlsx")
    df.to_excel(filepath, index=False)
    return filepath


# ---------------- Background auto-save ----------------
def auto_save_loop() -> None:
    """Periodically flush captured ticks to .xlsx files. Daemon thread."""
    while True:
        time.sleep(AUTO_SAVE_INTERVAL_SECONDS)
        fp = save_tick_data_to_excel()
        if fp:
            print(f"[AUTO-SAVE] Tick data saved to {fp}")


# ---------------- App + startup ----------------
app = FastAPI(title="TrueData Option Chain & Tick Data API (no-auth)")


@app.on_event("startup")
def _startup() -> None:
    """Open the long-lived TD_live WS, start live data + preset chains,
    register callbacks, and launch the auto-save daemon thread."""
    global td_obj

    if TD_live is None:
        # We still start the app — endpoints will return 503 with a clear
        # message. This makes the container boot successfully even if
        # truedata isn't installed yet.
        print("[STARTUP] truedata SDK is not installed — endpoints will return 503")
        return

    print(
        f"[STARTUP] Connecting to TrueData as {TRUEDATA_USERNAME} "
        f"on port {TRUEDATA_LIVE_PORT}..."
    )
    td_obj = TD_live(
        TRUEDATA_USERNAME,
        TRUEDATA_PASSWORD,
        live_port=TRUEDATA_LIVE_PORT,
        log_level=logging.WARNING,
    )
    td_obj.start_live_data(MY_SYMBOLS)
    time.sleep(1)

    for key, underlying, expiry, chain_length, bid_ask, greek in PRESET_CHAINS:
        try:
            chain = td_obj.start_option_chain(
                underlying, expiry,
                chain_length=chain_length,
                bid_ask=bid_ask,
                greek=greek,
            )
            CHAIN_MAP[key] = chain
            print(f"[STARTUP] Started option chain: {key} ({underlying} {expiry.date()})")
        except SystemExit:
            # SDK calls exit() on failure (e.g. trial account 'User Subscription
            # Expired'). We catch SystemExit so the worker doesn't die.
            print(
                f"[STARTUP] Failed to start chain {key} ({underlying} {expiry.date()}) "
                f"— SDK called exit(). Likely 'User Subscription Expired' for trial "
                f"accounts. The endpoint will return 503 for this symbol."
            )
        except Exception as e:  # noqa: BLE001
            print(f"[STARTUP] Failed to start chain {key}: {type(e).__name__}: {e}")

    time.sleep(1)

    # Register callbacks. Each prints + (for trade/bidask) appends to tick_records.
    @td_obj.bidask_callback
    def new_bidask(bidask_data):
        try:
            sym = getattr(bidask_data, "symbol", None)
            if sym in MY_SYMBOLS:
                print("bidask data >", bidask_data)
                with tick_lock:
                    tick_records.append(build_tick_row(bidask_data))
        except Exception as e:  # noqa: BLE001
            print(f"[warn] bidask_callback error: {e}")

    @td_obj.one_min_bar_callback
    def new_min_bar_data(bar_data):
        try:
            sym = getattr(bar_data, "symbol", None)
            if sym in MY_SYMBOLS:
                print("one min >", bar_data)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] one_min_bar_callback error: {e}")

    @td_obj.five_min_bar_callback
    def new_five_min_bar(bar_data):
        try:
            sym = getattr(bar_data, "symbol", None)
            if sym in MY_SYMBOLS:
                print("five min >", bar_data)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] five_min_bar_callback error: {e}")

    @td_obj.greek_callback
    def mygreek_bidask(greek_data):
        try:
            sym = getattr(greek_data, "symbol", None)
            if sym in MY_SYMBOLS:
                print("greek >", greek_data)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] greek_callback error: {e}")

    @td_obj.trade_callback
    def strategy_callback(tick_data):
        try:
            sym = getattr(tick_data, "symbol", None)
            if sym in MY_SYMBOLS:
                print("Tick >", tick_data)
                with tick_lock:
                    tick_records.append(build_tick_row(tick_data))
        except Exception as e:  # noqa: BLE001
            print(f"[warn] trade_callback error: {e}")

    threading.Thread(target=auto_save_loop, daemon=True).start()
    print(
        f"[STARTUP] Ready. Symbols={MY_SYMBOLS} Chains={list(CHAIN_MAP.keys())} "
        f"Auto-save={AUTO_SAVE_INTERVAL_SECONDS}s"
    )


@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"[URL HIT] {request.method} {request.url}")
    response = await call_next(request)
    return response


# ---------------- Endpoints (no auth) ----------------

@app.get("/")
def root():
    return {
        "status": "running",
        "available_endpoints": list(CHAIN_MAP.keys()),
        "truedata_connected": td_obj is not None,
        "tick_records_captured": len(tick_records),
    }


@app.get("/option-chain/all")
def get_all_chains():
    if td_obj is None:
        raise HTTPException(status_code=503, detail="TrueData SDK not initialized")
    result: dict[str, list] = {}
    for name, chain_obj in CHAIN_MAP.items():
        df = chain_obj.get_option_chain()
        result[name] = df.to_dict(orient="records") if df is not None and not df.empty else []
    return result


@app.get("/option-chain/{symbol}")
def get_option_chain(symbol: str):
    if td_obj is None:
        raise HTTPException(status_code=503, detail="TrueData SDK not initialized")
    symbol = symbol.lower()
    if symbol not in CHAIN_MAP:
        raise HTTPException(
            status_code=404,
            detail=f"Symbol '{symbol}' not found. Use one of {list(CHAIN_MAP.keys())}",
        )
    df = CHAIN_MAP[symbol].get_option_chain()
    if df is None or df.empty:
        return []
    return df.to_dict(orient="records")


@app.get("/export/all")
def export_all_excel():
    if td_obj is None:
        raise HTTPException(status_code=503, detail="TrueData SDK not initialized")
    filepath = save_all_chains_to_single_excel()
    return {"status": "saved", "file": filepath}


@app.get("/export/ticks")
def export_ticks_excel():
    filepath = save_tick_data_to_excel()
    if not filepath:
        raise HTTPException(status_code=204, detail="No tick data captured yet")
    return {"status": "saved", "file": filepath}


@app.get("/export/{symbol}")
def export_chain_excel(symbol: str):
    if td_obj is None:
        raise HTTPException(status_code=503, detail="TrueData SDK not initialized")
    symbol = symbol.lower()
    if symbol not in CHAIN_MAP:
        raise HTTPException(
            status_code=404,
            detail=f"Symbol '{symbol}' not found. Use one of {list(CHAIN_MAP.keys())}",
        )
    df = CHAIN_MAP[symbol].get_option_chain()
    if df is None or df.empty:
        raise HTTPException(status_code=204, detail="No data available yet")
    filepath = save_chain_to_excel(symbol, df)
    return {"status": "saved", "file": filepath}


@app.get("/ticks")
def get_ticks():
    with tick_lock:
        return tick_records[-100:]


# ---------------- Run ----------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=API_PORT)
