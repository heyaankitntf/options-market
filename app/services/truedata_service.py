"""TrueData market-data client.

Wraps the official `truedata_ws` SDK so the rest of the app can stay
agnostic of its quirks (list-of-dict response shape, blocking connect call,
background websocket thread, etc.).

Design notes
------------
- A fresh `TD` client is created **per request**. TrueData's websocket is
  stateful and the SDK was not designed to be shared across concurrent
  callers; per-request isolation keeps the surface area small and the
  failure mode obvious. Connection overhead is ~1-2s.
- All SDK calls are wrapped in `try/except` and re-raised as
  `TrueDataError` so the route layer can map them to HTTP 502 cleanly.
- `fetch_historical` returns a pandas DataFrame keyed by `symbol`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime, time
from typing import Any

import pandas as pd

from app.core.config import settings

logger = logging.getLogger(__name__)


class TrueDataError(RuntimeError):
    """Raised when the TrueData SDK fails to connect or returns no data.

    The HTTP route maps this to a 502 Bad Gateway with the message as the
    response body detail.
    """


# IST market session times — used to scope start/end dates to trading hours.
_MARKET_OPEN = time(9, 15, 0)
_MARKET_CLOSE = time(15, 30, 0)

# Canonical column order we want in the .xls output, regardless of how the
# SDK chose to order keys in its dict response.
_COLUMN_ORDER = [
    "time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "open_interest",
]

# Map SDK dict keys -> our snake_case column names.
_KEY_MAP: Mapping[str, str] = {
    "time": "time",
    "o": "open",
    "h": "high",
    "l": "low",
    "c": "close",
    "v": "volume",
    "oi": "open_interest",
    # Tick-data response uses different keys; map those too.
    "trade_time": "time",
    "price": "close",
    "qty": "volume",
    "bid": "bid",
    "ask": "ask",
    "bid_qty": "bid_qty",
    "ask_qty": "ask_qty",
}


def _to_dataframe(raw: Any, symbol: str) -> pd.DataFrame:
    """Convert the raw SDK response (list[dict] | DataFrame | None) into a
    clean DataFrame with stable column names."""
    if raw is None:
        raise TrueDataError(
            f"TrueData returned no data for symbol '{symbol}'. "
            "This usually means the symbol is invalid for the account's "
            "segment permissions, or the date range is outside market "
            "sessions."
        )

    if isinstance(raw, pd.DataFrame):
        df = raw.copy()
    elif isinstance(raw, list) and raw and isinstance(raw[0], dict):
        df = pd.DataFrame(raw)
    elif isinstance(raw, list) and not raw:
        # Empty list — treat as "no data" so caller can 502 with a clear msg.
        raise TrueDataError(
            f"TrueData returned an empty dataset for symbol '{symbol}'."
        )
    else:
        raise TrueDataError(
            f"Unexpected response shape from TrueData for '{symbol}': "
            f"{type(raw).__name__}"
        )

    # Rename SDK keys to our canonical names (only those that exist).
    rename_map = {k: v for k, v in _KEY_MAP.items() if k in df.columns}
    df = df.rename(columns=rename_map)

    # Make sure the time column is a datetime so Excel renders it cleanly.
    if "time" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["time"]):
        df["time"] = pd.to_datetime(df["time"], errors="coerce")

    # Reorder columns: keep canonical ones first, then any extras the SDK
    # returned (e.g. bid/ask for tick data).
    canonical_present = [c for c in _COLUMN_ORDER if c in df.columns]
    extras = [c for c in df.columns if c not in canonical_present]
    df = df[canonical_present + extras]

    return df


class TrueDataClient:
    """Thin per-request wrapper around `truedata_ws.websocket.TD`.

    Use as a context manager:

        with TrueDataClient() as td:
            df = td.fetch_historical(symbol, start, end, bar_size)
    """

    def __init__(self) -> None:
        self._td: Any = None

    def __enter__(self) -> "TrueDataClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.disconnect()

    def connect(self) -> None:
        """Create the TD client and open the websocket + historical REST
        session. Raises `TrueDataError` on any failure."""
        # Lazy import so the SDK is only loaded when actually needed; this
        # keeps `pytest` collection fast for tests that don't touch TrueData.
        try:
            from truedata_ws.websocket import TD  # type: ignore
        except ImportError as e:  # pragma: no cover - dependency is in requirements.txt
            raise TrueDataError(
                "truedata-ws package is not installed. "
                "Run `pip install -r requirements.txt`."
            ) from e

        try:
            self._td = TD(
                login_id=settings.TRUEDATA_USERNAME,
                password=settings.TRUEDATA_PASSWORD,
                live_port=settings.TRUEDATA_LIVE_PORT,
                url=settings.TRUEDATA_URL,
                hist_url=settings.TRUEDATA_HIST_URL,
                historical_api=True,
                log_level=logging.WARNING,
            )
            self._td.connect()
        except Exception as e:
            # SDK raises a variety of exceptions; collapse them into one type.
            raise TrueDataError(
                f"Failed to connect to TrueData: {type(e).__name__}: {e}"
            ) from e

    def disconnect(self) -> None:
        if self._td is None:
            return
        try:
            self._td.disconnect()
        except Exception as e:  # noqa: BLE001 - best-effort cleanup
            logger.warning("TrueData disconnect failed: %s: %s", type(e).__name__, e)
        finally:
            self._td = None

    def fetch_historical(
        self,
        symbol: str,
        start_date,
        end_date,
        bar_size: str,
    ) -> pd.DataFrame:
        """Fetch historical bars/ticks for one symbol.

        Parameters
        ----------
        symbol : str
            TrueData contract symbol, e.g. ``"NIFTY-I"`` or ``"RELIANCE"``.
        start_date, end_date : datetime.date
            Inclusive date range. Times are forced to market open / close.
        bar_size : str
            One of the values accepted by the SDK (``"tick"``, ``"1 min"``,
            ``"EOD"`` …).

        Returns
        -------
        pd.DataFrame
            Cleaned dataframe with canonical columns.
        """
        if self._td is None:
            raise TrueDataError("TrueDataClient used before connect()")

        # Combine the inclusive date range with IST market session times so
        # the SDK gets a fully-formed start_time / end_time pair.
        start_dt = datetime.combine(start_date, _MARKET_OPEN)
        end_dt = datetime.combine(end_date, _MARKET_CLOSE)

        try:
            raw = self._td.get_historic_data(
                contract=symbol,
                start_time=start_dt,
                end_time=end_dt,
                bar_size=bar_size,
            )
        except Exception as e:
            raise TrueDataError(
                f"TrueData fetch failed for '{symbol}' "
                f"({start_date} → {end_date}, {bar_size}): "
                f"{type(e).__name__}: {e}"
            ) from e

        return _to_dataframe(raw, symbol)


def fetch_many(
    symbols: list[str],
    start_date,
    end_date,
    bar_size: str,
) -> dict[str, pd.DataFrame]:
    """Connect once, fetch every symbol, disconnect, return a symbol→df map.

    On the first symbol that fails, the connection is torn down and the
    error is raised as `TrueDataError` — this matches the "hard fail"
    contract the user picked.
    """
    out: dict[str, pd.DataFrame] = {}
    with TrueDataClient() as td:
        for sym in symbols:
            logger.info("Fetching %s (%s, %s → %s)", sym, bar_size, start_date, end_date)
            out[sym] = td.fetch_historical(sym, start_date, end_date, bar_size)
    return out
