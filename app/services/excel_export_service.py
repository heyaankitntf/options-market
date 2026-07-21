"""Build legacy `.xls` files from DataFrames and bundle them into a ZIP.

We use `xlwt` (BIFF8) directly — not via `pandas.to_excel(engine="xlwt")` —
because pandas 3.x removed the `xlwt` engine. Writing with `xlwt` directly
is also ~3x faster and uses less memory than going through pandas.

BIFF8 has a hard 65,536-row limit per sheet; rows beyond
`settings.TRUEDATA_MAX_ROWS_PER_SYMBOL` are silently truncated and the
truncation is recorded in `metadata.txt` so the caller knows.
"""

from __future__ import annotations

import datetime as _dt
import io
import logging
import re
import zipfile
from datetime import datetime, timezone

import pandas as pd
import xlwt

from app.core.config import settings
from app.schemas.market_data import BarSize, Segment

logger = logging.getLogger(__name__)

_MAX_ROWS = settings.TRUEDATA_MAX_ROWS_PER_SYMBOL

# Characters that are unsafe in filenames across operating systems.
_UNSAFE_FN_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def _sanitize_filename_chunk(s: str) -> str:
    """Make any string safe to embed in a filename."""
    return _UNSAFE_FN_CHARS.sub("_", s).strip("_") or "UNKNOWN"


def _to_native(value):
    """Convert numpy/pandas scalar types to plain Python natives that xlwt
    understands (int, float, str, datetime). Returns None for NaN/NA."""
    if value is None:
        return None
    # pandas.NaT / numpy.nan / pd.NA
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass  # pd.isna raises on list-like; ignore
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, _dt.datetime):
        return value
    if isinstance(value, _dt.date):
        return _dt.datetime(value.year, value.month, value.day)
    if isinstance(value, bool):
        return int(value)
    if hasattr(value, "item"):  # numpy scalar -> Python scalar
        try:
            return value.item()
        except Exception:  # noqa: BLE001
            return str(value)
    return value


def _build_xls_bytes(df: pd.DataFrame, sheet_name: str) -> bytes:
    """Serialise a DataFrame to `.xls` (BIFF8) bytes in memory using xlwt."""
    buf = io.BytesIO()

    # xlwt enforces 31-char sheet names and rejects some characters.
    safe_sheet = re.sub(r"[*?:/\\]", "_", sheet_name)[:31] or "Data"

    wb = xlwt.Workbook(encoding="utf-8")
    sheet = wb.add_sheet(safe_sheet, cell_overwrite_ok=False)

    # Default date style for the time column.
    date_style = xlwt.XFStyle()
    date_style.num_format_str = "YYYY-MM-DD HH:MM:SS"

    # Header row.
    columns = list(df.columns)
    for col_idx, col_name in enumerate(columns):
        sheet.write(0, col_idx, str(col_name))

    # Data rows. Iterate via `itertuples(index=False)` for speed; convert
    # every cell through `_to_native` because xlwt can't handle numpy scalars.
    for row_idx, row in enumerate(df.itertuples(index=False, name=None)):
        for col_idx, value in enumerate(row):
            native = _to_native(value)
            if native is None:
                continue
            if isinstance(native, _dt.datetime):
                sheet.write(row_idx + 1, col_idx, native, date_style)
            else:
                sheet.write(row_idx + 1, col_idx, native)

    wb.save(buf)
    return buf.getvalue()


def _build_metadata_text(
    symbols: list[str],
    start_date,
    end_date,
    bar_size: BarSize,
    segment: Segment | None,
    rows_per_symbol: dict[str, int],
    truncated: list[str],
) -> str:
    """Human-readable `metadata.txt` placed inside the ZIP."""
    lines = [
        "TrueData Market Data Export",
        "===========================",
        f"Generated at (UTC): {datetime.now(timezone.utc).isoformat()}",
        f"Bar size:          {bar_size.value}",
        f"Segment:           {segment.value if segment else '(not specified)'}",
        f"Date range:        {start_date} -> {end_date} (inclusive, IST market hours)",
        f"Symbols requested: {len(symbols)}",
        "",
        "Per-symbol row counts:",
    ]
    for sym in symbols:
        rows = rows_per_symbol.get(sym, 0)
        flag = "  [TRUNCATED to max rows]" if sym in truncated else ""
        lines.append(f"  - {sym:<20} {rows:>8} rows{flag}")
    lines.extend([
        "",
        f"Row cap per symbol: {_MAX_ROWS} "
        "(BIFF8 .xls has a 65536-row hard limit).",
        "Columns: time, open, high, low, close, volume, open_interest "
        "(+ bid/ask fields for tick data).",
    ])
    return "\n".join(lines) + "\n"


def build_zip(
    frames: dict[str, pd.DataFrame],
    *,
    start_date,
    end_date,
    bar_size: BarSize,
    segment: Segment | None,
) -> tuple[bytes, dict[str, int], list[str]]:
    """Bundle per-symbol DataFrames into a single ZIP archive.

    Returns
    -------
    zip_bytes : bytes
        Raw ZIP file content.
    rows_per_symbol : dict[str, int]
        Number of data rows written for each symbol (post-truncation).
    truncated : list[str]
        Symbols whose row count exceeded the cap and were truncated.
    """
    buf = io.BytesIO()
    rows_per_symbol: dict[str, int] = {}
    truncated: list[str] = []

    bar_tag = _sanitize_filename_chunk(bar_size.value)
    seg_tag = _sanitize_filename_chunk(segment.value) if segment else "ALL"
    range_tag = (
        f"{_sanitize_filename_chunk(str(start_date))}_"
        f"{_sanitize_filename_chunk(str(end_date))}"
    )

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for symbol, df in frames.items():
            sym_tag = _sanitize_filename_chunk(symbol)
            rows_per_symbol[symbol] = len(df)
            if len(df) > _MAX_ROWS:
                truncated.append(symbol)
                logger.warning(
                    "Symbol %s has %d rows; truncating to %d (BIFF8 limit).",
                    symbol, len(df), _MAX_ROWS,
                )
                df = df.iloc[:_MAX_ROWS].copy()

            xls_bytes = _build_xls_bytes(df, sheet_name=symbol)
            filename = (
                f"{sym_tag}_{seg_tag}_{range_tag}_{bar_tag}.xls"
            )
            zf.writestr(filename, xls_bytes)

        # Always include a metadata.txt so the receiver can audit the export
        # without opening the .xls files.
        meta = _build_metadata_text(
            symbols=list(frames.keys()),
            start_date=start_date,
            end_date=end_date,
            bar_size=bar_size,
            segment=segment,
            rows_per_symbol=rows_per_symbol,
            truncated=truncated,
        )
        zf.writestr("metadata.txt", meta)

    return buf.getvalue(), rows_per_symbol, truncated


def list_files(zip_bytes: bytes) -> list[str]:
    """Read the filenames back out of a ZIP (used for the JSON meta response)."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        return zf.namelist()


# ---------------------------------------------------------------------------
# Tick export
# ---------------------------------------------------------------------------

def _build_tick_metadata_text(
    symbols: list[str],
    duration_seconds: int,
    segment: Segment | None,
    rows_per_symbol: dict[str, int],
    truncated: list[str],
    capture_started_at: str,
    capture_ended_at: str,
    total_ticks: int,
) -> str:
    """Human-readable `metadata.txt` placed inside the tick ZIP."""
    lines = [
        "TrueData Live Tick Export",
        "=========================",
        f"Generated at (UTC):    {datetime.now(timezone.utc).isoformat()}",
        f"Capture started (UTC): {capture_started_at}",
        f"Capture ended (UTC):   {capture_ended_at}",
        f"Duration:              {duration_seconds} seconds",
        f"Segment:               {segment.value if segment else '(not specified)'}",
        f"Symbols requested:     {len(symbols)}",
        f"Total ticks captured:  {total_ticks}",
        "",
        "Per-symbol tick counts:",
    ]
    for sym in symbols:
        rows = rows_per_symbol.get(sym, 0)
        flag = "  [TRUNCATED to max rows]" if sym in truncated else ""
        lines.append(f"  - {sym:<32} {rows:>8} ticks{flag}")
    lines.extend([
        "",
        f"Row cap per symbol: {_MAX_ROWS} "
        "(BIFF8 .xls has a 65536-row hard limit).",
        "Columns (in sheet order):",
        "  symbol_id, timestamp, ltp, ltq, atp, ttq,",
        "  day_open, day_high, day_low, prev_day_close,",
        "  oi, prev_day_oi, turnover, special_tag, tick_seq,",
        "  best_bid_price, best_bid_qty, best_ask_price, best_ask_qty",
        "",
        "NOTE: TrueData has NO historical tick archive. These ticks were "
        "captured live during the request window only.",
    ])
    return "\n".join(lines) + "\n"


def build_tick_zip(
    frames: dict[str, pd.DataFrame],
    *,
    duration_seconds: int,
    segment: Segment | None,
    capture_started_at: str,
    capture_ended_at: str,
    total_ticks: int,
) -> tuple[bytes, dict[str, int], list[str]]:
    """Bundle per-symbol tick DataFrames into a single ZIP archive.

    Mirrors `build_zip` but with tick-specific metadata. The .xls files use
    the canonical tick column order (matches the spec the API provider
    shared with the team).
    """
    buf = io.BytesIO()
    rows_per_symbol: dict[str, int] = {}
    truncated: list[str] = []

    seg_tag = _sanitize_filename_chunk(segment.value) if segment else "ALL"
    dur_tag = f"{duration_seconds}s"

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for symbol, df in frames.items():
            sym_tag = _sanitize_filename_chunk(symbol)
            rows_per_symbol[symbol] = len(df)
            if len(df) > _MAX_ROWS:
                truncated.append(symbol)
                logger.warning(
                    "Symbol %s has %d ticks; truncating to %d (BIFF8 limit).",
                    symbol, len(df), _MAX_ROWS,
                )
                df = df.iloc[:_MAX_ROWS].copy()

            xls_bytes = _build_xls_bytes(df, sheet_name=symbol)
            filename = f"{sym_tag}_{seg_tag}_ticks_{dur_tag}.xls"
            zf.writestr(filename, xls_bytes)

        meta = _build_tick_metadata_text(
            symbols=list(frames.keys()),
            duration_seconds=duration_seconds,
            segment=segment,
            rows_per_symbol=rows_per_symbol,
            truncated=truncated,
            capture_started_at=capture_started_at,
            capture_ended_at=capture_ended_at,
            total_ticks=total_ticks,
        )
        zf.writestr("metadata.txt", meta)

    return buf.getvalue(), rows_per_symbol, truncated


# ---------------------------------------------------------------------------
# Option-chain export
# ---------------------------------------------------------------------------

def _build_option_chain_metadata_text(
    chains: list[dict[str, object]],
    duration_seconds: int,
    snapshot_interval_seconds: int,
    segment: Segment | None,
    rows_per_chain: dict[str, int],
    truncated: list[str],
    capture_started_at: str,
    capture_ended_at: str,
    total_rows: int,
) -> str:
    """Human-readable `metadata.txt` placed inside the option-chain ZIP."""
    lines = [
        "TrueData Option-Chain Export",
        "============================",
        f"Generated at (UTC):        {datetime.now(timezone.utc).isoformat()}",
        f"Capture started (UTC):     {capture_started_at}",
        f"Capture ended (UTC):       {capture_ended_at}",
        f"Duration:                  {duration_seconds} seconds",
        f"Snapshot interval:         {snapshot_interval_seconds} seconds",
        f"Approx snapshots/chain:    {max(1, duration_seconds // snapshot_interval_seconds)}",
        f"Segment:                   {segment.value if segment else '(not specified)'}",
        f"Chains requested:          {len(chains)}",
        f"Total rows captured:       {total_rows}",
        "",
        "Per-chain row counts:",
    ]
    for ch in chains:
        key = f"{ch['underlying']}_{ch['expiry']}"
        rows = rows_per_chain.get(key, 0)
        flag = "  [TRUNCATED to max rows]" if key in truncated else ""
        greek_tag = " greek=on" if ch.get("greek") else ""
        bidask_tag = " bidask=off" if not ch.get("bid_ask", True) else ""
        lines.append(
            f"  - {ch['underlying']:<12} {ch['expiry']}  len={ch['chain_length']:<3}"
            f"  {rows:>8} rows{greek_tag}{bidask_tag}{flag}"
        )
    lines.extend([
        "",
        f"Row cap per chain: {_MAX_ROWS} "
        "(BIFF8 .xls has a 65536-row hard limit).",
        "Columns (in sheet order):",
        "  snapshot_time, underlying, expiry, symbol, strike, type,",
        "  ltp, ltt, ltq, volume, price_change, price_change_perc,",
        "  oi, prev_oi, oi_change, oi_change_perc,",
        "  bid, bid_qty, ask, ask_qty",
        "  [+ iv, delta, theta, gamma, vega, rho]  (only when greek=true)",
        "",
        "NOTE: Each row is one strike x option-type x snapshot-time. The SDK "
        "updates the chain in real-time; we snapshot its current state at "
        "the configured cadence.",
        "",
        "TRIAL ACCOUNT CAVEAT: TrueData trial accounts get 'User Subscription "
        "Expired' on option-chain subscriptions. Upgrade the plan to use this "
        "endpoint; no code changes required.",
    ])
    return "\n".join(lines) + "\n"


def build_option_chain_zip(
    frames: dict[str, pd.DataFrame],
    *,
    chains: list[dict[str, object]],
    duration_seconds: int,
    snapshot_interval_seconds: int,
    segment: Segment | None,
    capture_started_at: str,
    capture_ended_at: str,
    total_rows: int,
    messages_log: str = "",
) -> tuple[bytes, dict[str, int], list[str]]:
    """Bundle per-(underlying, expiry) option-chain DataFrames into a ZIP.

    Mirrors `build_tick_zip` but with option-chain-specific metadata. The
    .xls files use the canonical option-chain column order (matches the
    spec the API provider shared with the team — see
    `OPTION_CHAIN_COLUMNS` in `truedata_option_chain_service.py`).

    If `messages_log` is non-empty, it is written as a `messages.log` file
    inside the ZIP — this contains every SDK log line + callback event
    (trade ticks, bidask, greeks, bars) captured during the run, so the
    user can see exactly what the SDK emitted. Especially useful for
    debugging trial-account 'User Subscription Expired' errors.
    """
    buf = io.BytesIO()
    rows_per_chain: dict[str, int] = {}
    truncated: list[str] = []

    seg_tag = _sanitize_filename_chunk(segment.value) if segment else "ALL"
    dur_tag = f"{duration_seconds}s"
    snap_tag = f"snap{snapshot_interval_seconds}s"

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for key, df in frames.items():
            # key format is "{UNDERLYING}_{YYYY-MM-DD}" — already sanitised
            # (uppercase letters, digits, underscore) but pass through the
            # sanitizer anyway for defence-in-depth.
            key_tag = _sanitize_filename_chunk(key)
            rows_per_chain[key] = len(df)
            if len(df) > _MAX_ROWS:
                truncated.append(key)
                logger.warning(
                    "Chain %s has %d rows; truncating to %d (BIFF8 limit).",
                    key, len(df), _MAX_ROWS,
                )
                df = df.iloc[:_MAX_ROWS].copy()

            xls_bytes = _build_xls_bytes(df, sheet_name=key)
            filename = f"{key_tag}_{seg_tag}_chain_{dur_tag}_{snap_tag}.xls"
            zf.writestr(filename, xls_bytes)

        meta = _build_option_chain_metadata_text(
            chains=chains,
            duration_seconds=duration_seconds,
            snapshot_interval_seconds=snapshot_interval_seconds,
            segment=segment,
            rows_per_chain=rows_per_chain,
            truncated=truncated,
            capture_started_at=capture_started_at,
            capture_ended_at=capture_ended_at,
            total_rows=total_rows,
        )
        zf.writestr("metadata.txt", meta)

        # Include the SDK message log so the caller can see every log line +
        # callback event captured during the run. Even when empty we still
        # write the file (with a single header line) so downstream tooling
        # can rely on the file always being present.
        if messages_log:
            zf.writestr("messages.log", messages_log)
        else:
            zf.writestr(
                "messages.log",
                "(no SDK messages were captured during this run)\n",
            )

    return buf.getvalue(), rows_per_chain, truncated
