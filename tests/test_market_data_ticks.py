"""Tests for the TrueData live tick export endpoint.

We don't hit the real TrueData API here — the tick service is monkey-patched
so the tests stay hermetic and fast. The goal is to verify:

  - the endpoint is JWT-protected (401 without a token)
  - the request schema validates filters (duration bounds, symbol non-empty, …)
  - on a TrueData failure (incl. 0 ticks captured), the endpoint returns 502
  - on success, the endpoint returns a ZIP with one .xls per symbol
    + a metadata.txt entry, and the .xls has the team-lead's full column spec
  - symbol normalisation (strip + upper + dedupe) works
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
from fastapi.testclient import TestClient

from app.services import truedata_tick_service
from app.services.truedata_tick_service import TickCaptureResult


def _login(client: TestClient, phone: str = "9000060001") -> str:
    """Register + login a fresh user; return the JWT."""
    client.post(
        "/api/v1/auth/request-otp",
        json={"country_code": "+91", "phone": phone},
    )
    code = client.get("/api/v1/auth/dev-otp", params={"phone": phone}).json()["code"]
    client.post(
        "/api/v1/auth/register",
        json={"country_code": "+91", "phone": phone, "code": code, "name": "Tick Test"},
    )
    client.post(
        "/api/v1/auth/request-login-otp",
        json={"country_code": "+91", "phone": phone},
    )
    code = client.get("/api/v1/auth/dev-otp", params={"phone": phone}).json()["code"]
    return client.post(
        "/api/v1/auth/login",
        json={"country_code": "+91", "phone": phone, "code": code},
    ).json()["access_token"]


def _fake_tick_dataframe(symbol: str, n: int = 5) -> pd.DataFrame:
    """Build a DataFrame with the canonical tick column order."""
    return pd.DataFrame(
        {
            "symbol_id": [900000596 + i for i in range(n)],
            "timestamp": pd.date_range("2026-07-21 09:15", periods=n, freq="1s"),
            "ltp": [24269.0 + i for i in range(n)],
            "ltq": [65 + i for i in range(n)],
            "atp": [24210.82 + i for i in range(n)],
            "ttq": [3024125.0 + i for i in range(n)],
            "day_open": [24290.0 for _ in range(n)],
            "day_high": [24295.0 + i for i in range(n)],
            "day_low": [24285.0 + i for i in range(n)],
            "prev_day_close": [24321.7 for _ in range(n)],
            "oi": [14294475 + i for i in range(n)],
            "prev_day_oi": [14630915 for _ in range(n)],
            "turnover": [73216546032.5 + i for i in range(n)],
            "special_tag": ["" for _ in range(n)],
            "tick_seq": [1000 + i for i in range(n)],
            "best_bid_price": [24266.0 + i for i in range(n)],
            "best_bid_qty": [65 + i for i in range(n)],
            "best_ask_price": [24269.0 + i for i in range(n)],
            "best_ask_qty": [325 + i for i in range(n)],
        },
        columns=truedata_tick_service.TICK_COLUMNS,
    )


def _fake_result(symbols: list[str]) -> TickCaptureResult:
    return TickCaptureResult(
        frames={s: _fake_tick_dataframe(s) for s in symbols},
        capture_started_at="2026-07-21T03:45:00+00:00",
        capture_ended_at="2026-07-21T03:46:00+00:00",
        total_ticks=5 * len(symbols),
    )


# --- Auth ---------------------------------------------------------------

def test_tick_export_requires_auth(client: TestClient):
    """No Bearer token → 401."""
    r = client.post(
        "/api/v1/market-data/truedata/ticks/export",
        json={"symbols": ["NIFTY-I"], "duration_seconds": 30},
    )
    assert r.status_code == 401, r.text


# --- Schema validation --------------------------------------------------

def test_tick_export_validates_empty_symbols(client: TestClient):
    """Empty symbols list → 422."""
    token = _login(client, phone="9000060002")
    r = client.post(
        "/api/v1/market-data/truedata/ticks/export",
        headers={"Authorization": f"Bearer {token}"},
        json={"symbols": [], "duration_seconds": 30},
    )
    assert r.status_code == 422, r.text


def test_tick_export_validates_duration_too_short(client: TestClient):
    """duration_seconds < 5 → 422."""
    token = _login(client, phone="9000060003")
    r = client.post(
        "/api/v1/market-data/truedata/ticks/export",
        headers={"Authorization": f"Bearer {token}"},
        json={"symbols": ["NIFTY-I"], "duration_seconds": 1},
    )
    assert r.status_code == 422, r.text


def test_tick_export_validates_duration_too_long(client: TestClient):
    """duration_seconds > 300 → 422."""
    token = _login(client, phone="9000060004")
    r = client.post(
        "/api/v1/market-data/truedata/ticks/export",
        headers={"Authorization": f"Bearer {token}"},
        json={"symbols": ["NIFTY-I"], "duration_seconds": 301},
    )
    assert r.status_code == 422, r.text


# --- Hard-fail contract -------------------------------------------------

def test_tick_export_hard_fails_on_truedata_error(client: TestClient):
    """If TrueData raises (incl. 0-tick result), endpoint returns 502."""
    token = _login(client, phone="9000060005")

    def _boom(*args, **kwargs):
        raise truedata_tick_service.TrueDataError(
            "No trade ticks were received during the capture window."
        )

    with patch.object(truedata_tick_service, "capture_ticks", side_effect=_boom):
        r = client.post(
            "/api/v1/market-data/truedata/ticks/export",
            headers={"Authorization": f"Bearer {token}"},
            json={"symbols": ["NIFTY-I"], "duration_seconds": 30},
        )
    assert r.status_code == 502, r.text
    assert "TrueData error" in r.json()["detail"]
    assert "No trade ticks" in r.json()["detail"]


# --- Happy path ---------------------------------------------------------

def test_tick_export_success_returns_zip_with_per_symbol_xls(client: TestClient):
    """Happy path: ZIP with one .xls per symbol + a metadata.txt entry,
    and the .xls has the full team-lead column spec."""
    token = _login(client, phone="9000060006")

    fake_result = _fake_result(["NIFTY-I", "BANKNIFTY-I"])

    with patch.object(truedata_tick_service, "capture_ticks", return_value=fake_result):
        r = client.post(
            "/api/v1/market-data/truedata/ticks/export",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "symbols": ["NIFTY-I", "BANKNIFTY-I"],
                "duration_seconds": 30,
                "segment": "NSE F&O",
            },
        )

    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert 'attachment; filename="' in r.headers["content-disposition"]
    assert r.headers["x-export-total-rows"] == "10"  # 5 + 5 ticks
    assert r.headers["x-export-capture-started"] == fake_result.capture_started_at
    assert r.headers["x-export-capture-ended"] == fake_result.capture_ended_at

    # Inspect the ZIP.
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = zf.namelist()
        assert "metadata.txt" in names
        xls_names = [n for n in names if n.endswith(".xls")]
        assert len(xls_names) == 2

        # Each .xls parses back as a DataFrame with the team-lead's columns.
        expected_cols = [
            "symbol_id", "timestamp", "ltp", "ltq", "atp", "ttq",
            "day_open", "day_high", "day_low", "prev_day_close",
            "oi", "prev_day_oi", "turnover", "special_tag", "tick_seq",
            "best_bid_price", "best_bid_qty", "best_ask_price", "best_ask_qty",
        ]
        for xls_name in xls_names:
            df = pd.read_excel(io.BytesIO(zf.read(xls_name)), engine="xlrd")
            assert list(df.columns) == expected_cols, (
                f"{xls_name} columns mismatch: got {list(df.columns)}"
            )
            assert len(df) == 5
            # Spot-check one value to make sure data flowed through.
            assert df["ltp"].iloc[0] == 24269.0

        # metadata.txt should mention the team-lead column spec.
        meta = zf.read("metadata.txt").decode("utf-8")
        assert "TrueData Live Tick Export" in meta
        assert "special_tag" in meta
        assert "tick_seq" in meta
        assert "best_bid_price" in meta
        assert "NO historical tick archive" in meta


# --- Symbol normalisation -----------------------------------------------

def test_tick_export_dedupes_and_uppercases_symbols(client: TestClient):
    """Symbol list is normalised (strip + upper + dedupe) before subscribing."""
    token = _login(client, phone="9000060007")

    captured: dict = {}

    def _capture(symbols, duration_seconds):
        captured["symbols"] = symbols
        captured["duration"] = duration_seconds
        return _fake_result(symbols)

    with patch.object(truedata_tick_service, "capture_ticks", side_effect=_capture):
        r = client.post(
            "/api/v1/market-data/truedata/ticks/export",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "symbols": [" nifty-i ", "NIFTY-I", "BANKNIFTY-I"],
                "duration_seconds": 45,
            },
        )

    assert r.status_code == 200, r.text
    assert captured["symbols"] == ["NIFTY-I", "BANKNIFTY-I"]
    assert captured["duration"] == 45


# --- Default duration ---------------------------------------------------

def test_tick_export_uses_default_duration_when_omitted(client: TestClient):
    """If duration_seconds is omitted, default (60) is used."""
    token = _login(client, phone="9000060008")

    captured: dict = {}

    def _capture(symbols, duration_seconds):
        captured["duration"] = duration_seconds
        return _fake_result(symbols)

    with patch.object(truedata_tick_service, "capture_ticks", side_effect=_capture):
        r = client.post(
            "/api/v1/market-data/truedata/ticks/export",
            headers={"Authorization": f"Bearer {token}"},
            json={"symbols": ["NIFTY-I"]},
        )

    assert r.status_code == 200, r.text
    assert captured["duration"] == 60  # default


# =========================================================================
# Replay endpoint tests
# =========================================================================
#
# The replay endpoint reuses the same request schema, the same .xls bundler,
# and the same `capture_ticks` service function — only the URL/port the SDK
# connects to changes, plus an IST time-window guard that returns 409 when
# the replay socket is closed.
#
# We test:
#   - auth required (401)
#   - schema validation (empty symbols → 422, bad duration → 422)
#   - 409 outside the replay window (we monkey-patch `is_replay_window_open`
#     to return False without depending on the actual wall-clock time)
#   - happy path inside the window (mocked capture_ticks; verifies the
#     `replay=True` flag is forwarded to the service and the response ZIP
#     has X-Export-Mode: replay)
#   - hard-fail on TrueDataError → 502
#   - capture_ticks is called with replay=True even when the time-of-day
#     check passes (verifies the route layer wiring)


REPLAY_URL = "/api/v1/market-data/truedata/ticks/replay/export"


def test_replay_export_requires_auth(client: TestClient):
    """No Bearer token → 401 (even before the replay-window check)."""
    r = client.post(
        REPLAY_URL,
        json={"symbols": ["NIFTY-I"], "duration_seconds": 30},
    )
    assert r.status_code == 401, r.text


def test_replay_export_validates_empty_symbols(client: TestClient):
    """Empty symbols → 422 (schema validation runs before window check)."""
    token = _login(client, phone="9000060010")
    r = client.post(
        REPLAY_URL,
        headers={"Authorization": f"Bearer {token}"},
        json={"symbols": [], "duration_seconds": 30},
    )
    assert r.status_code == 422, r.text


def test_replay_export_validates_duration_too_long(client: TestClient):
    """duration_seconds > 300 → 422."""
    token = _login(client, phone="9000060011")
    r = client.post(
        REPLAY_URL,
        headers={"Authorization": f"Bearer {token}"},
        json={"symbols": ["NIFTY-I"], "duration_seconds": 301},
    )
    assert r.status_code == 422, r.text


def test_replay_export_refused_outside_window(client: TestClient):
    """When `is_replay_window_open` returns False → HTTP 409."""
    token = _login(client, phone="9000060012")

    with patch.object(
        truedata_tick_service, "is_replay_window_open", return_value=False
    ), patch.object(
        truedata_tick_service, "capture_ticks",
        side_effect=AssertionError("capture_ticks should not be called outside window"),
    ):
        r = client.post(
            REPLAY_URL,
            headers={"Authorization": f"Bearer {token}"},
            json={"symbols": ["NIFTY-I"], "duration_seconds": 30},
        )

    assert r.status_code == 409, r.text
    assert "replay feed is only available" in r.json()["detail"].lower()
    assert "18:00" in r.json()["detail"]  # window description


def test_replay_export_success_returns_zip_with_replay_mode_header(client: TestClient):
    """Inside the replay window: happy path returns a ZIP with
    X-Export-Mode: replay, and `capture_ticks` is called with replay=True."""
    token = _login(client, phone="9000060013")

    fake_result = _fake_result(["NIFTY-I"])
    captured: dict = {}

    def _capture(symbols, duration_seconds, *, replay=False):
        captured["replay"] = replay
        captured["symbols"] = symbols
        captured["duration"] = duration_seconds
        return fake_result

    with patch.object(
        truedata_tick_service, "is_replay_window_open", return_value=True
    ), patch.object(
        truedata_tick_service, "capture_ticks", side_effect=_capture
    ):
        r = client.post(
            REPLAY_URL,
            headers={"Authorization": f"Bearer {token}"},
            json={"symbols": ["NIFTY-I"], "duration_seconds": 30},
        )

    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["x-export-mode"] == "replay"
    assert r.headers["x-export-total-rows"] == "5"
    assert "truedata_replay_ticks_" in r.headers["content-disposition"]
    # Verify the route forwarded replay=True to the service.
    assert captured["replay"] is True
    assert captured["duration"] == 30

    # Verify the ZIP itself is structurally identical to the live export.
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = zf.namelist()
        assert "metadata.txt" in names
        xls_names = [n for n in names if n.endswith(".xls")]
        assert len(xls_names) == 1


def test_replay_export_hard_fails_on_truedata_error(client: TestClient):
    """If capture_ticks raises TrueDataError even inside the replay window
    (e.g. replay socket itself is down), endpoint returns 502."""
    token = _login(client, phone="9000060014")

    def _boom(*args, **kwargs):
        raise truedata_tick_service.TrueDataError(
            "Failed to connect to TrueData websocket: ConnectionRefusedError"
        )

    with patch.object(
        truedata_tick_service, "is_replay_window_open", return_value=True
    ), patch.object(truedata_tick_service, "capture_ticks", side_effect=_boom):
        r = client.post(
            REPLAY_URL,
            headers={"Authorization": f"Bearer {token}"},
            json={"symbols": ["NIFTY-I"], "duration_seconds": 30},
        )
    assert r.status_code == 502, r.text
    assert "TrueData error" in r.json()["detail"]


# --- Replay window helper unit tests -----------------------------------

def test_replay_window_helper_handles_midnight_crossing():
    """The default 18:00–02:00 IST window crosses midnight — verify the
    helper returns True for 19:00, 23:30, 00:30, 01:59 and False for
    09:00, 15:00, 17:59, 02:00."""
    _IST = ZoneInfo("Asia/Kolkata")
    # Inside the window.
    for hh, mm in [(19, 0), (23, 30), (0, 30), (1, 59)]:
        t = datetime(2026, 7, 21, hh, mm, tzinfo=_IST)
        assert truedata_tick_service.is_replay_window_open(t) is True, f"{hh}:{mm} should be inside"
    # Outside the window.
    for hh, mm in [(9, 0), (15, 0), (17, 59), (2, 0), (5, 0)]:
        t = datetime(2026, 7, 21, hh, mm, tzinfo=_IST)
        assert truedata_tick_service.is_replay_window_open(t) is False, f"{hh}:{mm} should be outside"


def test_replay_window_helper_accepts_utc_datetime():
    """UTC datetimes are converted to IST before the window check.
    13:30 UTC = 19:00 IST → inside the default 18:00–02:00 window."""
    _IST = ZoneInfo("Asia/Kolkata")
    t_utc = datetime(2026, 7, 21, 13, 30, tzinfo=timezone.utc)
    assert truedata_tick_service.is_replay_window_open(t_utc) is True
    # 03:00 UTC = 08:30 IST → outside.
    t_utc = datetime(2026, 7, 21, 3, 0, tzinfo=timezone.utc)
    assert truedata_tick_service.is_replay_window_open(t_utc) is False


def test_replay_window_description_format():
    """The 409 error message includes a human-readable window string."""
    desc = truedata_tick_service.replay_window_description()
    assert "18:00" in desc
    assert "02:00" in desc
    assert "IST" in desc
