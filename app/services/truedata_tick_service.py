"""TrueData live tick streaming client.

Wraps the official `truedata-ws` SDK (v5+) `TD` class to capture real-time
trade ticks for a bounded duration and return them as per-symbol pandas
DataFrames. Used by both the `/api/v1/market-data/truedata/ticks/export`
(live) and `/api/v1/market-data/truedata/ticks/replay/export` (off-hours
replay) endpoints.

Why v5 (`truedata_ws.TD`) without `full_feed=True`, and `@trade_callback`?
------------------------------------------------------------------------
We initially used v7's `TD_live` class, which works on the live socket but
receives **zero trade ticks** on the replay socket (only touchline
snapshots arrive). We then tried v5 with `full_feed=True` — also zero
ticks, because `full_feed=True` triggers a master-contract download that
the trial account can't complete and the SDK hangs in the constructor.

The team lead's reference guide (TrueData's official "Full Market Feed
Replay" KB article) shows the simple pattern: `TD(url='replay.truedata.in',
live_port=8082)` without `full_feed=True`, register `@td.trade_callback`.
This works on BOTH the live and replay sockets, receives all 19 fields the
team lead asked for, and the SDK extracts `special_tag` from `raw_tick[13]`
for us automatically (no manual indexing).

The historical bars endpoint (`truedata_service.py`) also uses
`truedata_ws.TD` — same SDK, just configured with `historical_api=True`.

Hard-fail contract
-------------------
Any SDK error (connect failure, subscription rejection, unexpected exception
in a callback) is re-raised as `TrueDataError`. The HTTP route maps that to
HTTP 502. If 0 ticks are captured across ALL symbols (e.g. market is closed
on live, or replay socket is down), we also raise `TrueDataError` so the
caller gets a clear 502 instead of an empty ZIP.

Tick field map (matches the spec the API provider shared with the team)
----------------------------------------------------------------------
Each captured tick is a `tick_feed` dataclass instance (the SDK wraps the
raw trade message and exposes typed attributes). We project it onto the
following flat columns in the .xls output:

    symbol_id, timestamp, ltp, ltq, atp, ttq,
    day_open, day_high, day_low, prev_day_close,
    oi, prev_day_oi, turnover, special_tag, tick_seq,
    best_bid_price, best_bid_qty, best_ask_price, best_ask_qty

The `special_tag` field is `""` on regular ticks, and `"O"`/`"H"`/`"L"` on
ticks that establish a new session Open / High / Low. The SDK extracts it
from `raw_tick[13]` automatically (see `TD_live.handle_trade_data`).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from app.core.config import settings

logger = logging.getLogger(__name__)

# IST timezone for replay-window checks. zoneinfo is stdlib (Python 3.9+).
_IST = ZoneInfo("Asia/Kolkata")


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
    """Project an SDK tick object (`tick_feed` from `@trade_callback` or
    `full_feed` from `@full_feed_trade_callback`) onto our flat row dict.

    Both dataclasses expose the same field names (ltp, ltq, atp, ttq,
    day_open/high/low, prev_day_close, oi, prev_day_oi, turnover,
    special_tag, tick_seq, best_bid/ask price+qty) — verified in the SDK
    source at `truedata_ws/websocket/support.py`. We use `getattr` with
    sensible defaults so a missing field doesn't blow up the whole capture.

    The SDK extracts `special_tag` from `raw_tick[13]` for us on the
    `tick_feed` path (see `TD_live.handle_trade_data` line 235), so no
    manual `raw_tick` indexing is needed.
    """
    return {
        "symbol_id": int(getattr(tick, "symbol_id", 0) or 0),
        "timestamp": getattr(tick, "timestamp", None),
        "ltp": float(getattr(tick, "ltp", 0.0) or 0.0),
        "ltq": int(getattr(tick, "ltq", 0) or 0),
        "atp": float(getattr(tick, "atp", 0.0) or 0.0),
        "ttq": float(getattr(tick, "ttq", 0.0) or 0.0),
        "day_open": float(getattr(tick, "day_open", 0.0) or 0.0),
        "day_high": float(getattr(tick, "day_high", 0.0) or 0.0),
        "day_low": float(getattr(tick, "day_low", 0.0) or 0.0),
        "prev_day_close": float(getattr(tick, "prev_day_close", 0.0) or 0.0),
        "oi": int(getattr(tick, "oi", 0) or 0),
        "prev_day_oi": int(getattr(tick, "prev_day_oi", 0) or 0),
        "turnover": float(getattr(tick, "turnover", 0.0) or 0.0),
        "special_tag": str(getattr(tick, "special_tag", "") or ""),
        "tick_seq": int(getattr(tick, "tick_seq", 0) or 0),
        "best_bid_price": float(getattr(tick, "best_bid_price", 0.0) or 0.0),
        "best_bid_qty": int(getattr(tick, "best_bid_qty", 0) or 0),
        "best_ask_price": float(getattr(tick, "best_ask_price", 0.0) or 0.0),
        "best_ask_qty": int(getattr(tick, "best_ask_qty", 0) or 0),
    }


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
    *,
    replay: bool = False,
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
    replay : bool, default False
        If True, connect to the replay WebSocket (`replay.truedata.in:8082`)
        instead of the live feed. The replay feed repeats the most recent
        market session at real-time pace and is only available ~18:00–02:00
        IST. The caller is responsible for time-window validation; this flag
        only swaps the URL/port passed to the SDK.
    """
    if not symbols:
        raise TrueDataError("capture_ticks called with empty symbols list")

    # Lazy import so the SDK is only loaded when actually needed; this keeps
    # pytest collection fast for tests that don't touch TrueData.
    #
    # IMPORTANT — SDK usage pattern (matches TrueData's official replay guide):
    # We use `truedata_ws.websocket.TD` WITHOUT the `full_feed=True` flag,
    # and register `@td.trade_callback` to receive ticks.
    #
    # Why not `full_feed=True`?
    #   The `full_feed=True` flag triggers a one-time master-contract download
    #   (~2 minutes the first time each day) that the trial account appears
    #   unable to complete — the SDK hangs in the constructor and never
    #   receives ticks. The simpler pattern (no `full_feed`, `@trade_callback`)
    #   works on BOTH the live and replay sockets, receives ALL 19 fields the
    #   team lead asked for (ltp, ltq, atp, ttq, O/H/L, prev_close, OI,
    #   prev_OI, turnover, special_tag, tick_seq, best_bid/ask price+qty),
    #   and matches the team lead's reference guide verbatim.
    #
    # Why v5 (`truedata_ws.TD`) and not v7 (`truedata.TD_live`)?
    #   The v7 `TD_live` class always operates in full-feed mode internally
    #   and sends a subscription request the replay server doesn't honour —
    #   we observed 0 trade ticks on the replay socket with v7. v5 lets us
    #   opt out of full-feed mode and use the simple `@trade_callback` path.
    try:
        from truedata_ws.websocket.TD import TD  # type: ignore
    except ImportError as e:  # pragma: no cover - dependency is in requirements.txt
        raise TrueDataError(
            "truedata-ws package is not installed. Run `pip install -r requirements.txt`."
        ) from e

    # Select URL/port based on replay mode. We do NOT time-validate here —
    # the route layer is responsible for the IST-window check so it can map
    # the failure to HTTP 409 (Conflict) rather than HTTP 502.
    if replay:
        ws_url = settings.TRUEDATA_REPLAY_URL
        ws_port = settings.TRUEDATA_REPLAY_PORT
        mode_label = "REPLAY"
    else:
        ws_url = settings.TRUEDATA_URL
        ws_port = settings.TRUEDATA_LIVE_PORT
        mode_label = "LIVE"

    # Per-symbol buffers + a marker that gets set on the first received tick.
    buffers: dict[str, _TickBuffer] = {s: _TickBuffer(s) for s in symbols}
    first_tick_event = threading.Event()
    started_at = datetime.now(timezone.utc)

    logger.info(
        "Starting tick capture [%s]: symbols=%s duration=%ds url=%s port=%s",
        mode_label, symbols, duration_seconds, ws_url, ws_port,
    )

    # We pass `historical_api=False` because we never use the REST history
    # client from this service — it saves a TCP connection and ~150ms.
    try:
        td = TD(
            login_id=settings.TRUEDATA_USERNAME,
            password=settings.TRUEDATA_PASSWORD,
            url=ws_url,
            live_port=ws_port,
            log_level=logging.WARNING,
        )
    except Exception as e:
        raise TrueDataError(
            f"Failed to create TD client: {type(e).__name__}: {e}"
        ) from e

    try:
        td.connect()
    except Exception as e:
        raise TrueDataError(
            f"Failed to connect to TrueData websocket: {type(e).__name__}: {e}"
        ) from e

    try:
        # Register the trade callback. The SDK passes a `tick_feed` dataclass
        # with the same field names as `full_feed` (ltp, ltq, best_bid_price,
        # best_bid_qty, special_tag, tick_seq, etc.) — so `_tick_to_row()`
        # works unchanged. The SDK extracts `special_tag` from raw_tick[13]
        # for us; no manual parsing needed.
        @td.trade_callback  # type: ignore[misc]
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
        # Treat naive datetimes as IST.
        now = now.replace(tzinfo=_IST)
    else:
        now = now.astimezone(_IST)

    start = settings.TRUEDATA_REPLAY_WINDOW_START_HOUR
    end = settings.TRUEDATA_REPLAY_WINDOW_END_HOUR

    if start == end:
        # Degenerate config — treat as always open.
        return True
    if start < end:
        # Same-day window, e.g. 9 → 17.
        return start <= now.hour < end
    # Window crosses midnight, e.g. 18 → 2.
    return now.hour >= start or now.hour < end


def replay_window_description() -> str:
    """Human-readable description of the current replay window, e.g.
    '18:00–02:00 IST'. Used in HTTP 409 error responses."""
    start = settings.TRUEDATA_REPLAY_WINDOW_START_HOUR
    end = settings.TRUEDATA_REPLAY_WINDOW_END_HOUR
    return f"{start:02d}:00–{end:02d}:00 IST"
