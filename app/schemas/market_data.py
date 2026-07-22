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


# ---------------------------------------------------------------------------
# Option-chain export
# ---------------------------------------------------------------------------

class OptionChainSpec(BaseModel):
    """A single (underlying, expiry) pair to subscribe to.

    The endpoint will start one option chain per spec, sample snapshots
    at `snapshot_interval_seconds` cadence for `duration_seconds`, and
    write one `.xls` file per spec into the returned ZIP.
    """

    underlying: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description=(
            "Underlying index or stock symbol — bare name, no expiry/strike "
            "suffix. Examples: `NIFTY`, `BANKNIFTY`, `FINNIFTY`, `SENSEX`, "
            "`MIDCPNIFTY`, `RELIANCE`. Underlying is normalised (strip + "
            "uppercase) before being forwarded to the TrueData SDK.\n\n"
            "Note: For stock options like RELIANCE, the endpoint automatically "
            "falls back to TrueData's REST API if the WebSocket live feed "
            "doesn't stream those symbols."
        ),
        examples=["NIFTY", "BANKNIFTY", "RELIANCE"],
    )
    expiry: date = Field(
        ...,
        description=(
            "Expiry date (YYYY-MM-DD). Must be a valid trading expiry for "
            "the underlying. NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY have "
            "weekly Thursday expiries; SENSEX has weekly Tuesday expiries. "
            "Monthly expiry is the last weekly expiry of the month."
        ),
        examples=["2026-07-30", "2026-08-27"],
    )
    chain_length: int = Field(
        default=10,
        ge=2,
        le=100,
        description=(
            "Total number of strikes in the chain (centred on ATM). "
            "The SDK generates `chain_length` strikes × 2 types (CE+PE) "
            "= `2 × chain_length` option contracts. Trial accounts cap "
            "live subscriptions at 50 contracts; `chain_length=10` → 20 "
            "contracts per chain, so 2 chains is the safe trial ceiling. "
            "Default 10."
        ),
        examples=[6, 10, 20],
    )
    bid_ask: bool = Field(
        default=True,
        description=(
            "If True, include best bid/ask price + quantity columns in "
            "the output. Default True. Disable to reduce row width."
        ),
    )
    greek: bool = Field(
        default=False,
        description=(
            "If True, request greeks (iv, delta, theta, gamma, vega, rho) "
            "from the SDK and include them as 6 extra columns in the "
            "output. Default False. Greeks require a TrueData plan with "
            "option-greek entitlement (NOT included in trial)."
        ),
    )


class TrueDataOptionChainExportRequest(BaseModel):
    """Filter spec for `POST /api/v1/market-data/truedata/option-chain/export`.

    Live option-chain streaming endpoint. Opens a real-time WebSocket to
    TrueData, starts one option chain per entry in `chains`, samples
    snapshots at `snapshot_interval_seconds` cadence for `duration_seconds`,
    then disconnects and returns per-(underlying, expiry) `.xls` files
    bundled into a ZIP.

    Each `.xls` row is one strike x option-type x snapshot-time, with
    23 base columns enriched from both the option-chain DataFrame and the
    full tick-level `live_data` dict:

        Symbol ID, Date Time, LTP, LTQ, ATP, TTQ,
        Open, High, Low, Prev Close,
        OI, Prev Open Int Close, Day's Turnover,
        Special Tag, Tick Sequence No,
        Bid, Bid Qty, Ask, Ask Qty,
        Underlying, Expiry, Strike, Type

    Plus 6 optional greek columns (IV, Delta, Theta, Gamma, Vega, Rho)
    when any chain requests greeks.

    Call (CE) and Put (PE) data are written to SEPARATE .xls files:
    each (underlying, expiry) pair produces `*_CE.xls` and `*_PE.xls`.

    IMPORTANT — Account entitlement & dual-mode:
        This endpoint uses a dual-mode approach:
          1. First tries the WebSocket live feed via `TD_live.start_option_chain()`
             (works reliably for NIFTY option chains).
          2. If WebSocket fails or captures no data, automatically falls back
             to TrueData's REST API (`getOptionChain` endpoint) which supports
             stock options like RELIANCE as well.

        Trial accounts: the WebSocket live feed may not stream stock option
        ticks, but the REST API fallback works during market hours.
        No code changes required — the fallback is automatic.
    """

    chains: list[OptionChainSpec] = Field(
        ...,
        min_length=1,
        description=(
            "List of (underlying, expiry) pairs to subscribe to. Trial "
            "accounts are effectively capped at 2 chains of length 10 "
            "(50-contract subscription ceiling); paid plans can use up "
            "to 5 chains (configurable via TRUEDATA_CHAIN_MAX_PAIRS). "
            "Duplicate (underlying, expiry) pairs are rejected."
        ),
    )
    duration_seconds: int = Field(
        default=60,
        ge=5,
        le=7200,
        description=(
            "Total capture window in seconds. Maximum 7200 (2 hours). "
            "Per-symbol change detection ensures only rows with actual "
            "data changes (LTP, Bid, Ask, OI, timestamp) are written, "
            "so longer captures stay compact. Default 60. During active "
            "market hours with active option trading, each 5-second "
            "snapshot yields ~20-40 rows per chain (depending on "
            "`chain_length`)."
        ),
        examples=[30, 60, 120, 300, 1800, 3600, 7200],
    )
    snapshot_interval_seconds: int = Field(
        default=5,
        ge=1,
        le=60,
        description=(
            "Time between snapshots in seconds. The endpoint samples each "
            "chain's current state at this cadence for the full "
            "`duration_seconds`. Default 5. Lower values = more snapshots "
            "but more rows; raise to 10 or 15 for longer captures to "
            "keep the .xls manageable."
        ),
        examples=[1, 5, 10, 15],
    )
    segment: Segment | None = Field(
        default=Segment.NSE_FNO,
        description=(
            "Optional segment tag used for metadata/filename grouping only. "
            "Symbol resolution still happens server-side at TrueData. "
            "Defaults to 'NSE F&O' since option chains are NSE F&O "
            "contracts (SENSEX option chains are BSE F&O — set explicitly "
            "if requesting SENSEX)."
        ),
    )

    @field_validator("chains")
    @classmethod
    def _normalize_chains(cls, v: list[OptionChainSpec]) -> list[OptionChainSpec]:
        # Normalise underlying names (strip + uppercase). Reject duplicate
        # (underlying, expiry) pairs — they'd produce identical .xls files
        # in the ZIP and waste subscription slots.
        seen: set[tuple[str, str]] = set()
        cleaned: list[OptionChainSpec] = []
        for spec in v:
            u = spec.underlying.strip().upper()
            if not u:
                continue
            key = (u, spec.expiry.isoformat())
            if key in seen:
                raise ValueError(
                    f"Duplicate (underlying, expiry) pair: {u} / "
                    f"{spec.expiry.isoformat()}. Each pair must be unique."
                )
            seen.add(key)
            # Pydantic models are mutable; assign the normalised underlying.
            spec.underlying = u
            cleaned.append(spec)
        if not cleaned:
            raise ValueError("chains must contain at least one non-empty entry")
        return cleaned


class TrueDataOptionChainExportResponseMeta(BaseModel):
    """JSON metadata for the option-chain export ZIP. The primary response
    is the binary ZIP itself; this schema documents the `X-Export-*`
    headers."""

    chains: list[OptionChainSpec]
    duration_seconds: int
    snapshot_interval_seconds: int
    segment: Segment | None
    files: list[str]
    total_rows: int
    generated_at: str
    capture_started_at: str
    capture_ended_at: str
