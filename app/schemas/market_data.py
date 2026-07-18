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
