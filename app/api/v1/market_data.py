"""Market-data export routes.

Exposes two endpoints:

    POST /api/v1/market-data/truedata/export
        Historical OHLCV bars (1-min, 5-min, EOD, etc.) → ZIP of .xls files.

    POST /api/v1/market-data/truedata/ticks/export
        Live trade ticks (LTP, LTQ, ATP, TTQ, O/H/L, OI, Bid/Ask, etc.)
        captured for a bounded duration → ZIP of .xls files.

Both authenticate via the same Bearer JWT dependency used by `/users/me`,
write one legacy `.xls` file per requested symbol, and stream the bundle
back as a `application/zip` download.

Hard-fail contract
------------------
If TrueData cannot be reached, or returns/captures no data for *any*
requested symbol, the endpoint responds with HTTP 502 and the TrueData
error message as the response body. No partial ZIP is returned.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User
from app.schemas.market_data import (
    TrueDataExportRequest,
    TrueDataTickExportRequest,
)
from app.services import (
    excel_export_service,
    truedata_service,
    truedata_tick_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market-data", tags=["market-data"])


@router.post(
    "/truedata/export",
    summary="Export TrueData market data to a ZIP of .xls files",
    status_code=status.HTTP_200_OK,
)
def export_truedata_xls(
    payload: TrueDataExportRequest,
    current_user: User = Depends(get_current_user),
    _db: Session = Depends(get_db),
) -> Response:
    """Fetch historical bars/ticks from TrueData and return them as a ZIP of
    legacy `.xls` files (one per requested symbol).

    The response has `Content-Type: application/zip` and a
    `Content-Disposition: attachment; filename=...` header, so browsers
    will prompt the user to download the file.

    Requires a valid Bearer JWT (same auth as `/users/me`).
    """
    logger.info(
        "TrueData export requested by user_id=%s phone=%s — symbols=%s range=%s→%s bar=%s segment=%s",
        current_user.id,
        current_user.phone,
        payload.symbols,
        payload.start_date,
        payload.end_date,
        payload.bar_size.value,
        payload.segment.value if payload.segment else None,
    )

    # 1. Pull data from TrueData (hard-fail on any error).
    try:
        frames = truedata_service.fetch_many(
            symbols=payload.symbols,
            start_date=payload.start_date,
            end_date=payload.end_date,
            bar_size=payload.bar_size.value,
        )
    except truedata_service.TrueDataError as e:
        logger.error("TrueData export failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"TrueData error: {e}",
        ) from e

    # 2. Bundle into a ZIP of .xls files.
    zip_bytes, rows_per_symbol, truncated = excel_export_service.build_zip(
        frames,
        start_date=payload.start_date,
        end_date=payload.end_date,
        bar_size=payload.bar_size,
        segment=payload.segment,
    )

    files = excel_export_service.list_files(zip_bytes)
    generated_at = datetime.now(timezone.utc).isoformat()

    # 3. Build a filename for the download.
    safe_user = str(current_user.id).replace("-", "")[:8]
    zip_name = (
        f"truedata_export_{safe_user}_"
        f"{payload.start_date}_{payload.end_date}_"
        f"{payload.bar_size.value.replace(' ', '')}.zip"
    )

    logger.info(
        "TrueData export ready: %d files, %d total rows, truncated=%s",
        len(files),
        sum(rows_per_symbol.values()),
        truncated,
    )

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{zip_name}"',
            "X-Export-Files": ",".join(files),
            "X-Export-Generated-At": generated_at,
            "X-Export-Total-Rows": str(sum(rows_per_symbol.values())),
            "X-Export-Truncated": ",".join(truncated) if truncated else "",
        },
    )


@router.post(
    "/truedata/ticks/export",
    summary="Capture live TrueData trade ticks and return them as a ZIP of .xls files",
    status_code=status.HTTP_200_OK,
)
def export_truedata_ticks_xls(
    payload: TrueDataTickExportRequest,
    current_user: User = Depends(get_current_user),
    _db: Session = Depends(get_db),
) -> Response:
    """Open a real-time WebSocket to TrueData, subscribe to the requested
    symbols, capture every trade tick for `duration_seconds`, then return
    the captured ticks as a ZIP of legacy `.xls` files (one per symbol).

    Each `.xls` contains the full tick schema (matches the spec the API
    provider shared with the team):

        symbol_id, timestamp, ltp, ltq, atp, ttq, day_open, day_high,
        day_low, prev_day_close, oi, prev_day_oi, turnover, special_tag,
        tick_seq, best_bid_price, best_bid_qty, best_ask_price, best_ask_qty

    IMPORTANT — Real-time only:
        TrueData has NO historical tick archive. Ticks are captured only
        during the request window. Calling this endpoint outside market
        hours (09:15–15:30 IST, Mon–Fri) will return HTTP 502 with the
        message "No trade ticks were received during the capture window."

    Requires a valid Bearer JWT (same auth as `/users/me`).
    """
    # Clamp duration to the configured max ( defence-in-depth — pydantic
    # already enforces this, but a misconfigured setting could raise the cap).
    duration = min(
        max(payload.duration_seconds, 5),
        settings.TRUEDATA_TICK_MAX_DURATION_SEC,
    )

    logger.info(
        "TrueData tick export requested by user_id=%s phone=%s — symbols=%s duration=%ds segment=%s",
        current_user.id,
        current_user.phone,
        payload.symbols,
        duration,
        payload.segment.value if payload.segment else None,
    )

    # 1. Capture live ticks (hard-fail on any error or 0-tick result).
    try:
        result = truedata_tick_service.capture_ticks(
            symbols=payload.symbols,
            duration_seconds=duration,
        )
    except truedata_tick_service.TrueDataError as e:
        logger.error("TrueData tick export failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"TrueData error: {e}",
        ) from e

    # 2. Bundle into a ZIP of .xls files.
    zip_bytes, rows_per_symbol, truncated = excel_export_service.build_tick_zip(
        result.frames,
        duration_seconds=duration,
        segment=payload.segment,
        capture_started_at=result.capture_started_at,
        capture_ended_at=result.capture_ended_at,
        total_ticks=result.total_ticks,
    )

    files = excel_export_service.list_files(zip_bytes)
    generated_at = datetime.now(timezone.utc).isoformat()

    safe_user = str(current_user.id).replace("-", "")[:8]
    zip_name = f"truedata_ticks_{safe_user}_{duration}s.zip"

    logger.info(
        "TrueData tick export ready: %d files, %d total ticks, truncated=%s",
        len(files),
        result.total_ticks,
        truncated,
    )

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{zip_name}"',
            "X-Export-Files": ",".join(files),
            "X-Export-Generated-At": generated_at,
            "X-Export-Total-Rows": str(result.total_ticks),
            "X-Export-Truncated": ",".join(truncated) if truncated else "",
            "X-Export-Capture-Started": result.capture_started_at,
            "X-Export-Capture-Ended": result.capture_ended_at,
        },
    )


@router.post(
    "/truedata/ticks/replay/export",
    summary="Capture replayed TrueData trade ticks (off-hours) and return them as a ZIP of .xls files",
    status_code=status.HTTP_200_OK,
)
def export_truedata_replay_ticks_xls(
    payload: TrueDataTickExportRequest,
    current_user: User = Depends(get_current_user),
    _db: Session = Depends(get_db),
) -> Response:
    """Connect to TrueData's **replay** WebSocket, subscribe to the requested
    symbols, capture every replayed trade tick for `duration_seconds`, then
    return the captured ticks as a ZIP of legacy `.xls` files (one per symbol).

    The replay feed repeats the most recent market session at real-time pace
    and is only available outside market hours (~18:00–02:00 IST). It uses
    the exact same SDK, callbacks, and tick schema as the live endpoint —
    only the WebSocket URL (`replay.truedata.in:8082` instead of
    `push.truedata.in:<live_port>`) differs.

    Use this endpoint to exercise your tick-consuming code path during
    evenings/weekends without waiting for live market hours. The .xls files
    contain the same 19-column tick schema as the live tick export.

    Availability:
        Replay socket is open ~18:00–02:00 IST daily. Calling this endpoint
        outside that window returns HTTP 409 with a descriptive message.

    Requires a valid Bearer JWT (same auth as `/users/me`).
    """
    # Refuse before we even touch the SDK if we're outside the replay window.
    # The SDK would either hang on connect or raise an opaque auth error;
    # HTTP 409 (Conflict) is clearer for the caller.
    if not truedata_tick_service.is_replay_window_open():
        window = truedata_tick_service.replay_window_description()
        logger.info("Replay export rejected — outside window (%s)", window)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"TrueData replay feed is only available between {window}. "
                "Call the live tick export endpoint during market hours "
                "(09:15–15:30 IST, Mon–Fri) instead."
            ),
        )

    # Clamp duration to the configured max (defence-in-depth).
    duration = min(
        max(payload.duration_seconds, 5),
        settings.TRUEDATA_TICK_MAX_DURATION_SEC,
    )

    logger.info(
        "TrueData REPLAY tick export requested by user_id=%s phone=%s — symbols=%s duration=%ds segment=%s",
        current_user.id,
        current_user.phone,
        payload.symbols,
        duration,
        payload.segment.value if payload.segment else None,
    )

    # 1. Capture replayed ticks (hard-fail on any error or 0-tick result).
    try:
        result = truedata_tick_service.capture_ticks(
            symbols=payload.symbols,
            duration_seconds=duration,
            replay=True,
        )
    except truedata_tick_service.TrueDataError as e:
        logger.error("TrueData replay tick export failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"TrueData error: {e}",
        ) from e

    # 2. Bundle into a ZIP of .xls files (reuses the live tick bundler —
    # the per-symbol .xls format is identical).
    zip_bytes, rows_per_symbol, truncated = excel_export_service.build_tick_zip(
        result.frames,
        duration_seconds=duration,
        segment=payload.segment,
        capture_started_at=result.capture_started_at,
        capture_ended_at=result.capture_ended_at,
        total_ticks=result.total_ticks,
    )

    files = excel_export_service.list_files(zip_bytes)
    generated_at = datetime.now(timezone.utc).isoformat()

    safe_user = str(current_user.id).replace("-", "")[:8]
    zip_name = f"truedata_replay_ticks_{safe_user}_{duration}s.zip"

    logger.info(
        "TrueData REPLAY tick export ready: %d files, %d total ticks, truncated=%s",
        len(files),
        result.total_ticks,
        truncated,
    )

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{zip_name}"',
            "X-Export-Files": ",".join(files),
            "X-Export-Generated-At": generated_at,
            "X-Export-Total-Rows": str(result.total_ticks),
            "X-Export-Truncated": ",".join(truncated) if truncated else "",
            "X-Export-Capture-Started": result.capture_started_at,
            "X-Export-Capture-Ended": result.capture_ended_at,
            "X-Export-Mode": "replay",
        },
    )
