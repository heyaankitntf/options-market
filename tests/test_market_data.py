"""Tests for the TrueData market-data export endpoint.

We don't hit the real TrueData API here — the TrueData service is monkey-
patched so the tests stay hermetic and fast. The goal is to verify:

  - the endpoint is JWT-protected (401 without a token)
  - the request schema validates filters (date order, symbol non-empty, …)
  - on a TrueData failure, the endpoint returns HTTP 502 (hard-fail contract)
  - on success, the endpoint returns a ZIP with one .xls per symbol
    + a metadata.txt entry
"""

from __future__ import annotations

import io
import zipfile
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from app.services import truedata_service


def _login(client: TestClient, phone: str = "9000055555") -> str:
    """Register + login a fresh user; return the JWT."""
    client.post(
        "/api/v1/auth/request-otp",
        json={"country_code": "+91", "phone": phone},
    )
    code = client.get("/api/v1/auth/dev-otp", params={"phone": phone}).json()["code"]
    client.post(
        "/api/v1/auth/register",
        json={"country_code": "+91", "phone": phone, "code": code, "name": "Md Test"},
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


def _fake_dataframe(symbol: str, n: int = 5) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": pd.date_range("2026-07-14 09:15", periods=n, freq="1min"),
            "open": [100.0 + i for i in range(n)],
            "high": [101.0 + i for i in range(n)],
            "low": [99.0 + i for i in range(n)],
            "close": [100.5 + i for i in range(n)],
            "volume": [1000 * (i + 1) for i in range(n)],
            "open_interest": [50000 + i for i in range(n)],
        }
    )


def test_export_requires_auth(client: TestClient):
    """No Bearer token → 401."""
    r = client.post(
        "/api/v1/market-data/truedata/export",
        json={
            "symbols": ["NIFTY-I"],
            "start_date": "2026-07-14",
            "end_date": "2026-07-18",
            "bar_size": "1 min",
        },
    )
    assert r.status_code == 401, r.text


def test_export_validates_date_order(client: TestClient):
    """end_date before start_date → 422."""
    token = _login(client)
    r = client.post(
        "/api/v1/market-data/truedata/export",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "symbols": ["NIFTY-I"],
            "start_date": "2026-07-18",
            "end_date": "2026-07-14",
            "bar_size": "1 min",
        },
    )
    assert r.status_code == 422, r.text


def test_export_validates_empty_symbols(client: TestClient):
    """Empty symbols list → 422 (min_length=1)."""
    token = _login(client, phone="9000055556")
    r = client.post(
        "/api/v1/market-data/truedata/export",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "symbols": [],
            "start_date": "2026-07-14",
            "end_date": "2026-07-18",
            "bar_size": "1 min",
        },
    )
    assert r.status_code == 422, r.text


def test_export_hard_fails_on_truedata_error(client: TestClient):
    """If TrueData raises, endpoint returns 502 (hard-fail contract)."""
    token = _login(client, phone="9000055557")

    def _boom(*args, **kwargs):
        raise truedata_service.TrueDataError("simulated TrueData outage")

    with patch.object(truedata_service, "fetch_many", side_effect=_boom):
        r = client.post(
            "/api/v1/market-data/truedata/export",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "symbols": ["NIFTY-I"],
                "start_date": "2026-07-14",
                "end_date": "2026-07-18",
                "bar_size": "1 min",
            },
        )
    assert r.status_code == 502, r.text
    assert "TrueData error" in r.json()["detail"]


def test_export_success_returns_zip_with_per_symbol_xls(client: TestClient):
    """Happy path: ZIP with one .xls per symbol + a metadata.txt entry."""
    token = _login(client, phone="9000055558")

    fake_frames = {
        "NIFTY-I": _fake_dataframe("NIFTY-I"),
        "BANKNIFTY-I": _fake_dataframe("BANKNIFTY-I"),
    }

    with patch.object(truedata_service, "fetch_many", return_value=fake_frames):
        r = client.post(
            "/api/v1/market-data/truedata/export",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "symbols": ["NIFTY-I", "BANKNIFTY-I"],
                "start_date": "2026-07-14",
                "end_date": "2026-07-18",
                "bar_size": "1 min",
                "segment": "NSE F&O",
            },
        )

    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert 'attachment; filename="' in r.headers["content-disposition"]
    assert r.headers["x-export-total-rows"] == "10"  # 5 + 5

    # Inspect the ZIP.
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = zf.namelist()
        assert "metadata.txt" in names
        xls_names = [n for n in names if n.endswith(".xls")]
        assert len(xls_names) == 2
        # Each .xls parses back as a DataFrame with the expected columns.
        for xls_name in xls_names:
            df = pd.read_excel(io.BytesIO(zf.read(xls_name)), engine="xlrd")
            assert list(df.columns) == [
                "time", "open", "high", "low", "close", "volume", "open_interest",
            ]
            assert len(df) == 5


def test_export_dedupes_and_uppercases_symbols(client: TestClient):
    """Symbol list is normalised (strip + upper + dedupe) before fetching."""
    token = _login(client, phone="9000055559")

    captured: dict = {}

    def _capture(symbols, start_date, end_date, bar_size):
        captured["symbols"] = symbols
        captured["bar_size"] = bar_size
        return {s: _fake_dataframe(s) for s in symbols}

    with patch.object(truedata_service, "fetch_many", side_effect=_capture):
        r = client.post(
            "/api/v1/market-data/truedata/export",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "symbols": [" nifty-i ", "NIFTY-I", "BANKNIFTY-I"],
                "start_date": "2026-07-14",
                "end_date": "2026-07-18",
                "bar_size": "1 min",
            },
        )

    assert r.status_code == 200, r.text
    assert captured["symbols"] == ["NIFTY-I", "BANKNIFTY-I"]
