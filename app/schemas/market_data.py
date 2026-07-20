"""Request/response schemas for the TrueData market-data export endpoint.

The endpoint accepts a JSON body describing *what* to fetch and *how* to slice
it, then streams back a ZIP archive containing one legacy `.xls` file per
requested symbol.
"""

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


# Bar sizes accepted by the TrueData historical REST API. Values match the
# strings the upstream SDK forwards verbatim to `getbars` / `getticks`.
#
# Verified against the trial account (2026-07-18): every value below returns
# data successfully. TrueData also accepts case variants (e.g. `eod`) but we
# normalise via the enum so the .xls filenames are deterministic.
class BarSize(str, Enum):
    TICK = "tick"
    ONE_MIN = "1 min"
    FIVE_MIN = "5 min"
    FIFTEEN_MIN = "15 min"
    THIRTY_MIN = "30 min"        # PyPI docs also use "30 mins" — both work server-side
    ONE_HOUR = "1 hour"
    EOD = "EOD"


# Segments enabled in the TrueData trial account. Used purely for grouping /
# metadata — symbol resolution itself happens server-side at TrueData.
class Segment(str, Enum):
    NSE_EQUITY = "NSE Equity"
    NSE_FNO = "NSE F&O"
    INDICES = "Indices"
    MCX = "MCX"
    BSE_EQ = "BSE EQ"
    BSE_FNO = "BSE F&O"
    BSE_INDICES = "BSE Indices"


class TrueDataExportRequest(BaseModel):
    """Filter spec for `POST /api/v1/market-data/truedata/export`.

    The endpoint will fetch historical bars/ticks for every requested symbol
    between `start_date` and `end_date` at the chosen `bar_size`, write each
    symbol to its own legacy `.xls` file, and return all of them bundled into
    a single ZIP archive.
    """

    symbols: list[str] = Field(
        ...,
        min_length=1,
        max_length=50,  # TrueData trial cap
        description=(
            "List of TrueData contract symbols. Trial accounts are capped at "
            "50 symbols. Verified-working symbol formats in the trial:\n\n"
            "  • Indices:          `NIFTY 50` (note the space), `SENSEX`, `BANKEX`\n"
            "  • Index futures:    `NIFTY-I`, `BANKNIFTY-I`, `FINNIFTY-I`\n"
            "  • Commodity futures:`CRUDEOIL-I`, `GOLD-I`, `SILVER-I`\n"
            "  • NSE Equity:       `SBIN`, `RELIANCE`, `TCS`, `INFY`, …\n\n"
            "Symbols that DON'T work in the trial:\n"
            "  • Bare index names (`NIFTY`, `BANKNIFTY`) — use `NIFTY 50` or `NIFTY-I` instead\n"
            "  • BSE equity with `-BE` suffix — TrueData doesn't use the Zerodha convention\n"
            "  • Option contracts (`NIFTY26JUL24000CE`) — trial doesn't include NSE F&O history\n"
            "  • Currency derivatives (`USDINR26JULFUT`) — not in trial segments\n\n"
            "Symbols are normalised (strip + uppercase + dedupe) before fetching."
        ),
        examples=[["NIFTY-I", "BANKNIFTY-I"], ["SBIN", "RELIANCE", "TCS"], ["NIFTY 50", "SENSEX"]],
    )
    start_date: date = Field(
        ...,
        description="Inclusive start date (YYYY-MM-DD). Market session start "
        "time (09:15 IST) is used automatically.",
        examples=["2026-07-14"],
    )
    end_date: date = Field(
        ...,
        description="Inclusive end date (YYYY-MM-DD). Market session end time "
        "(15:30 IST) is used automatically.",
        examples=["2026-07-18"],
    )
    bar_size: BarSize = Field(
        default=BarSize.ONE_MIN,
        description="Aggregation bar size. Use `tick` for tick-level trade "
        "data; everything else returns OHLCV + open-interest bars.",
    )
    segment: Segment | None = Field(
        default=None,
        description="Optional segment tag used for metadata/filename grouping "
        "only. Symbol resolution still happens server-side at TrueData.",
    )

    @field_validator("symbols")
    @classmethod
    def _normalize_symbols(cls, v: list[str]) -> list[str]:
        # Strip + uppercase + de-duplicate while preserving order.
        seen: set[str] = set()
        cleaned: list[str] = []
        for s in v:
            s2 = s.strip().upper()
            if not s2:
                continue
            if s2 in seen:
                continue
            seen.add(s2)
            cleaned.append(s2)
        if not cleaned:
            raise ValueError("symbols must contain at least one non-empty value")
        return cleaned

    @model_validator(mode="after")
    def _check_date_order(self) -> "TrueDataExportRequest":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class TrueDataExportResponseMeta(BaseModel):
    """JSON metadata returned alongside the ZIP when called via the `meta`
    query param. The primary response is the binary ZIP itself."""

    symbols: list[str]
    start_date: date
    end_date: date
    bar_size: BarSize
    segment: Segment | None
    files: list[str]  # filenames inside the ZIP
    total_rows: int
    generated_at: str


class TrueDataTickExportRequest(BaseModel):
    """Filter spec for `POST /api/v1/market-data/truedata/ticks/export`.

    Live tick streaming endpoint. Opens a real-time WebSocket to TrueData,
    subscribes to the requested symbols, captures every trade tick for the
    requested `duration_seconds`, then disconnects and returns the captured
    ticks as one legacy `.xls` file per symbol (bundled into a ZIP).

    The .xls files contain the full tick schema (matches the spec the API
    provider shared with the team):

        symbol_id, timestamp, ltp, ltq, atp, ttq, day_open, day_high,
        day_low, prev_day_close, oi, prev_day_oi, turnover, special_tag,
        tick_seq, best_bid_price, best_bid_qty, best_ask_price, best_ask_qty

    IMPORTANT — Real-time only:
        TrueData has NO historical tick archive. Ticks are captured only for
        the duration of this request. Calling this endpoint outside market
        hours (09:15–15:30 IST, Mon–Fri) will return 0 ticks and the request
        will fail with HTTP 502 ("no ticks received").
    """

    symbols: list[str] = Field(
        ...,
        min_length=1,
        max_length=50,
        description=(
            "List of TrueData contract symbols to subscribe to. Trial accounts "
            "are capped at 50 concurrent symbol subscriptions.\n\n"
            "Verified-working symbol formats in the trial:\n"
            "  • Index futures (continuous): `NIFTY-I`, `BANKNIFTY-I`, `FINNIFTY-I`\n"
            "  • Index spot:                  `NIFTY 50` (note the space), `SENSEX`\n"
            "  • NSE Equity:                  `SBIN`, `RELIANCE`, `TCS`, `INFY`\n"
            "  • Commodity futures:           `CRUDEOIL-I`, `GOLD-I`, `SILVER-I`\n\n"
            "Option contracts (per team lead's format guidance):\n"
            "  Symbol Format = SymbolName + Expiry(YYMMDD) + StrikePrice + CE/PE\n"
            "  Example: NIFTY + 260828 (YYMMDD) + 25000 + CE = `NIFTY26082825000CE`\n"
            "  Example: BANKNIFTY + 260828 + 58000 + PE      = `BANKNIFTY26082858000PE`\n\n"
            "Symbols are normalised (strip + uppercase + dedupe) before subscribing."
        ),
        examples=[
            ["NIFTY-I", "BANKNIFTY-I"],
            ["NIFTY26082825000CE", "NIFTY26082825000PE"],
            ["SBIN", "RELIANCE", "TCS"],
        ],
    )
    duration_seconds: int = Field(
        default=60,
        ge=5,
        le=300,
        description=(
            "How long (seconds) to keep the WebSocket open and capture ticks. "
            "Capped at 300 (5 min) to avoid HTTP proxy timeouts. Default 60. "
            "During active market hours, liquid symbols typically produce "
            "5–50 ticks/sec, so a 60s capture yields 300–3000 rows per symbol."
        ),
        examples=[30, 60, 120, 300],
    )
    segment: Segment | None = Field(
        default=None,
        description=(
            "Optional segment tag used for metadata/filename grouping only. "
            "Symbol resolution still happens server-side at TrueData."
        ),
    )

    @field_validator("symbols")
    @classmethod
    def _normalize_symbols(cls, v: list[str]) -> list[str]:
        # Strip + uppercase + de-duplicate while preserving order.
        seen: set[str] = set()
        cleaned: list[str] = []
        for s in v:
            s2 = s.strip().upper()
            if not s2:
                continue
            if s2 in seen:
                continue
            seen.add(s2)
            cleaned.append(s2)
        if not cleaned:
            raise ValueError("symbols must contain at least one non-empty value")
        return cleaned


class TrueDataTickExportResponseMeta(BaseModel):
    """JSON metadata for the tick export ZIP. The primary response is the
    binary ZIP itself; this schema documents the `X-Export-*` headers."""

    symbols: list[str]
    duration_seconds: int
    segment: Segment | None
    files: list[str]
    total_rows: int
    generated_at: str
    capture_started_at: str
    capture_ended_at: str
