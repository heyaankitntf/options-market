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
from unittest.mock import patch

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
