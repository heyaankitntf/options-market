"""TrueData live tick streaming client.

Wraps the official `truedata` SDK (v7+) `TD_live` class to capture real-time
trade ticks for a bounded duration and return them as per-symbol pandas
DataFrames. Used by the `/api/v1/market-data/truedata/ticks/export` endpoint.

Why a separate service from `truedata_service.py`?
--------------------------------------------------
The historical bars endpoint (`truedata_service.py`) uses `truedata_ws.TD` —
a different SDK package with a different API surface (`get_historic_data`).
The live tick endpoint uses `truedata.TD_live` which exposes decorator-based
callbacks (`@td.full_feed_trade_callback`) for streaming ticks. The two SDKs
cannot share a client object.

Hard-fail contract
-------------------
Any SDK error (connect failure, subscription rejection, unexpected exception
in a callback) is re-raised as `TrueDataError`. The HTTP route maps that to
HTTP 502. If 0 ticks are captured across ALL symbols (e.g. market is closed),
we also raise `TrueDataError` so the caller gets a clear 502 instead of an
empty ZIP.

Tick field map (matches the spec the API provider shared with the team)
----------------------------------------------------------------------
Each captured tick is a `full_feed` dataclass instance. We project it onto
the following flat columns in the .xls output:

    symbol_id, timestamp, ltp, ltq, atp, ttq,
    day_open, day_high, day_low, prev_day_close,
    oi, prev_day_oi, turnover, special_tag, tick_seq,
    best_bid_price, best_bid_qty, best_ask_price, best_ask_qty

The `special_tag` field lives at `raw_tick[13]` in the SDK's internal tuple
(the SDK itself skips parsing this index — we extract it manually so the
"O/H/L" / empty-string marker the team lead mentioned is preserved).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from app.core.config import settings

logger = logging.getLogger(__name__)


class TrueDataError(RuntimeError):
    """Raised when the TrueData SDK fails to connect, subscribe, or capture
    at least one tick. Mapped to HTTP 502 by the route layer."""


# Canonical column order in the .xls output. Matches the spec the API
# provider shared with the team (Symbol ID, Date Time, LTP, LTQ, ATP, TTQ,
# Open, High, Low, Prev Close, OI, Prev OI Close, Day's Turnover, Special
# Tag, Tick Sequence No, Bid, Bid Qty, Ask, Ask Qty).
TICK_COLUMNS: list[str] = [
    "symbol_id",
    "timestamp",
    "ltp",
    "ltq",
    "atp",
    "ttq",
    "day_open",
    "day_high",
    "day_low",
    "prev_day_close",
    "oi",
    "prev_day_oi",
    "turnover",
    "special_tag",
    "tick_seq",
    "best_bid_price",
    "best_bid_qty",
    "best_ask_price",
    "best_ask_qty",
]


@dataclass
class _TickBuffer:
    """Per-symbol in-memory tick buffer.

    Ticks arrive on the SDK's websocket thread; the request thread reads the
    buffer after the capture window elapses. A simple list + lock is enough
    because we never concurrently read+write from the same thread.
    """

    symbol: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def append(self, row: dict[str, Any]) -> None:
        with self.lock:
            self.rows.append(row)

    def drain(self) -> list[dict[str, Any]]:
        with self.lock:
            out, self.rows = self.rows, []
            return out


def _tick_to_row(tick: Any) -> dict[str, Any]:
    """Project a `full_feed` SDK tick object onto our flat row dict.

    The SDK skips `raw_tick[13]` (the 'special tag' field — typically an
    empty string, or "O"/"H"/"L" on session extreme ticks). We extract it
    manually so the column the team lead asked for is populated.
    """
    # Most fields are direct attributes on the dataclass.
    row: dict[str, Any] = {
        "symbol_id": int(getattr(tick, "symbol_id", 0)),
        "timestamp": getattr(tick, "timestamp", None),
        "ltp": float(getattr(tick, "ltp", 0.0)),
        "ltq": int(getattr(tick, "ltq", 0)),
        "atp": float(getattr(tick, "atp", 0.0)),
        "ttq": float(getattr(tick, "ttq", 0.0)),
        "day_open": float(getattr(tick, "day_open", 0.0)),
        "day_high": float(getattr(tick, "day_high", 0.0)),
        "day_low": float(getattr(tick, "day_low", 0.0)),
        "prev_day_close": float(getattr(tick, "prev_day_close", 0.0)),
        "oi": int(getattr(tick, "oi", 0)),
        "prev_day_oi": int(getattr(tick, "prev_day_oi", 0)),
        "turnover": float(getattr(tick, "turnover", 0.0)),
        "tick_seq": int(getattr(tick, "tick_seq", 0)),
        "best_bid_price": float(getattr(tick, "best_bid_price", 0.0)),
        "best_bid_qty": int(getattr(tick, "best_bid_qty", 0)),
        "best_ask_price": float(getattr(tick, "best_ask_price", 0.0)),
        "best_ask_qty": int(getattr(tick, "best_ask_qty", 0)),
    }

    # Extract the special_tag from raw_tick[13] — the SDK skips this index.
    raw = getattr(tick, "raw_tick", None)
    if isinstance(raw, (list, tuple)) and len(raw) > 13:
        row["special_tag"] = str(raw[13]) if raw[13] is not None else ""
    else:
        row["special_tag"] = ""

    return row


@dataclass
class TickCaptureResult:
    """Result of a `capture_ticks` run.

    `frames` maps each requested symbol → its DataFrame (sorted by timestamp,
    columns in `TICK_COLUMNS` order). `capture_started_at` and
    `capture_ended_at` are UTC ISO strings for the metadata file.
    """

    frames: dict[str, pd.DataFrame]
    capture_started_at: str
    capture_ended_at: str
    total_ticks: int


def capture_ticks(
    symbols: list[str],
    duration_seconds: int,
) -> TickCaptureResult:
    """Open a TrueData WS, subscribe to `symbols`, capture trade ticks for
    `duration_seconds`, disconnect, and return per-symbol DataFrames.

    Hard-fails (raises `TrueDataError`) if:
      - The SDK cannot be imported / instantiated / connected.
      - Subscription to any symbol is rejected by the server.
      - 0 ticks are captured across ALL requested symbols (typically means
        market is closed or all symbols are invalid for the account).

    Parameters
    ----------
    symbols : list[str]
        Pre-normalised (upper-cased, de-duped) TrueData contract symbols.
    duration_seconds : int
        How long to keep the WS open and capture ticks. Caller is responsible
        for clamping to `[5, TRUEDATA_TICK_MAX_DURATION_SEC]`.
    """
    if not symbols:
        raise TrueDataError("capture_ticks called with empty symbols list")

    # Lazy import so the SDK is only loaded when actually needed; this keeps
    # pytest collection fast for tests that don't touch TrueData.
    try:
        from truedata import TD_live  # type: ignore
    except ImportError as e:  # pragma: no cover - dependency is in requirements.txt
        raise TrueDataError(
            "truedata package is not installed. Run `pip install -r requirements.txt`."
        ) from e

    # Per-symbol buffers + a marker that gets set on the first received tick.
    buffers: dict[str, _TickBuffer] = {s: _TickBuffer(s) for s in symbols}
    first_tick_event = threading.Event()
    started_at = datetime.now(timezone.utc)

    logger.info(
        "Starting tick capture: symbols=%s duration=%ds",
        symbols, duration_seconds,
    )

    try:
        td = TD_live(
            login_id=settings.TRUEDATA_USERNAME,
            password=settings.TRUEDATA_PASSWORD,
            url=settings.TRUEDATA_URL,
            live_port=settings.TRUEDATA_LIVE_PORT,
            log_level=logging.WARNING,
        )
    except Exception as e:
        raise TrueDataError(
            f"Failed to create TD_live client: {type(e).__name__}: {e}"
        ) from e

    try:
        td.connect()
    except Exception as e:
        raise TrueDataError(
            f"Failed to connect to TrueData websocket: {type(e).__name__}: {e}"
        ) from e

    try:
        # Register the full-feed trade callback. We use full_feed (not the
        # narrower trade_callback) because it carries every field the team
        # lead asked for, including best_bid/ask which the narrow trade_tick
        # object doesn't expose.
        @td.full_feed_trade_callback  # type: ignore[misc]
        def _on_tick(tick: Any) -> None:  # noqa: ANN001 - SDK passes its own dataclass
            sym = getattr(tick, "symbol", None)
            if sym is None or sym not in buffers:
                # Tick for a symbol we didn't request (shouldn't happen, but
                # the SDK occasionally relabels). Drop it.
                return
            buffers[sym].append(_tick_to_row(tick))
            if not first_tick_event.is_set():
                first_tick_event.set()
                logger.info("First tick received: symbol=%s ltp=%s", sym, getattr(tick, "ltp", "?"))

        # Subscribe to all requested symbols in one shot.
        td.start_live_data(list(symbols))
        logger.info("Subscribed to %d symbols. Capturing for %ds...", len(symbols), duration_seconds)

        # Wait for either:
        #   (a) at least one tick to arrive, OR
        #   (b) the first-tick timeout to elapse.
        # We don't fail-fast here — even if the first-tick timeout expires,
        # we keep capturing for the full duration because ticks can arrive in
        # bursts (especially for less-liquid option contracts).
        first_tick_event.wait(timeout=settings.TRUEDATA_TICK_FIRST_TICK_TIMEOUT_SEC)

        # Sleep for the remaining capture window. We use busy-wait with short
        # sleeps so the thread stays interruptible (e.g. by pytest timeout).
        deadline = time.monotonic() + duration_seconds
        while time.monotonic() < deadline:
            time.sleep(0.5)

        capture_ended_at = datetime.now(timezone.utc)

    except TrueDataError:
        raise
    except Exception as e:
        raise TrueDataError(
            f"Error during tick capture: {type(e).__name__}: {e}"
        ) from e
    finally:
        # Always disconnect, even on error.
        try:
            td.disconnect()
        except Exception as e:  # noqa: BLE001 - best-effort cleanup
            logger.warning("TrueData disconnect failed: %s: %s", type(e).__name__, e)

    # Drain buffers and build DataFrames.
    frames: dict[str, pd.DataFrame] = {}
    total = 0
    for sym, buf in buffers.items():
        rows = buf.drain()
        total += len(rows)
        if not rows:
            frames[sym] = pd.DataFrame(columns=TICK_COLUMNS)
            continue
        df = pd.DataFrame(rows, columns=TICK_COLUMNS)
        # Sort by timestamp ascending so the .xls reads chronologically.
        if "timestamp" in df.columns:
            df = df.sort_values("timestamp", kind="stable").reset_index(drop=True)
        frames[sym] = df

    if total == 0:
        raise TrueDataError(
            "No trade ticks were received during the capture window. "
            "This typically means (a) market is closed (IST 09:15–15:30 Mon–Fri), "
            "(b) the requested symbols are illiquid, or (c) the account's plan "
            "does not include live tick streaming for the requested segments."
        )

    logger.info(
        "Tick capture complete: %d total ticks across %d symbols",
        total, len(frames),
    )

    return TickCaptureResult(
        frames=frames,
        capture_started_at=started_at.isoformat(),
        capture_ended_at=capture_ended_at.isoformat(),
        total_ticks=total,
    )
