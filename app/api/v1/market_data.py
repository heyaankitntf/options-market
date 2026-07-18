"""Market-data export routes.

Currently exposes one endpoint:

    POST /api/v1/market-data/truedata/export

Authenticates via the same Bearer JWT dependency used by `/users/me`,
fetches historical bars/ticks from TrueData for the requested symbols +
date range + bar size, writes one legacy `.xls` file per symbol, and
streams the bundle back as a `application/zip` download.

Hard-fail contract
------------------
If TrueData cannot be reached, or returns no data for *any* requested
symbol, the endpoint responds with HTTP 502 and the TrueData error
message as the response body. No partial ZIP is returned.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.market_data import TrueDataExportRequest
from app.services import excel_export_service, truedata_service

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
