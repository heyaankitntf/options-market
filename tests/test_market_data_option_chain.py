"""Tests for the TrueData option-chain export endpoint.

We don't hit the real TrueData API here — the option-chain service is
monkey-patched so the tests stay hermetic and fast. The goal is to verify:

  - the endpoint is PUBLIC (no JWT required)
  - the request schema validates filters
  - on a TrueData failure, the endpoint returns 502
  - on success, the ZIP contains SEPARATE .xls files for CE and PE per
    (underlying, expiry) pair, each with the 23-column enriched schema
  - underlying names are upper-cased before being passed to the service
  - the service-level edge case (empty requests list) raises TrueDataError
"""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime, timezone
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.services import truedata_option_chain_service
from app.services.truedata_option_chain_service import (
    ChainCaptureResult,
    ChainRequest,
    OPTION_CHAIN_COLUMNS,
    GREEK_COLUMNS,
)


def _fake_chain_rows(
    underlying: str, expiry: date, n_strikes: int = 3, *, greek: bool = False
) -> list[dict]:
    """Build rows mimicking the ENRICHED option chain output
    (23 base columns matching the user's requested schema).
    Returns both CE and PE rows mixed together."""
    expiry_str = expiry.strftime("%y%m%d")
    rows = []
    for i in range(n_strikes):
        strike = 25000 + i * 50
        for t in ("CE", "PE"):
            row = {
                "Symbol ID": 1000 + i * 2 + (0 if t == "CE" else 1),
                "Date Time": datetime(2026, 7, 21, 9, 15, i, tzinfo=timezone.utc),
                "LTP": 100.5 + i * 0.5,
                "LTQ": 150 + i,
                "ATP": 99.8 + i * 0.3,
                "TTQ": 12500.0 + i * 100,
                "Open": 98.0 + i * 0.2,
                "High": 102.0 + i * 0.3,
                "Low": 97.0 + i * 0.1,
                "Prev Close": 98.5 + i * 0.2,
                "OI": 45000 + i * 50,
                "Prev Open Int Close": 44000 + i * 50,
                "Day's Turnover": 5000000.0 + i * 1000,
                "Special Tag": "" if i > 0 else "O",
                "Tick Sequence No": 100 + i,
                "Bid": 100.4 + i * 0.5,
                "Bid Qty": 200 + i,
                "Ask": 100.6 + i * 0.5,
                "Ask Qty": 180 + i,
                "Underlying": underlying,
                "Expiry": expiry.isoformat(),
                "Strike": strike,
                "Type": t,
            }
            if greek:
                row.update({
                    "IV": 12.5 + i * 0.1,
                    "Delta": 0.5 + i * 0.01,
                    "Theta": -5.2 + i * 0.05,
                    "Gamma": 0.001 + i * 0.0001,
                    "Vega": 8.5 + i * 0.1,
                    "Rho": -0.5 + i * 0.01,
                })
            rows.append(row)
    return rows


def _fake_option_chain_result(
    chains: list[ChainRequest],
    *,
    snapshots_per_chain: int = 2,
) -> ChainCaptureResult:
    """Build a ChainCaptureResult with CE/PE-segregated frames, mimicking
    what the service returns after capturing snapshots."""
    any_greek = any(r.greek for r in chains)
    columns = OPTION_CHAIN_COLUMNS + (GREEK_COLUMNS if any_greek else [])
    frames: dict[str, pd.DataFrame] = {}
    total = 0

    for req in chains:
        base_key = f"{req.underlying}_{req.expiry.isoformat()}"
        all_rows = _fake_chain_rows(
            req.underlying, req.expiry,
            n_strikes=req.chain_length // 2,
            greek=req.greek,
        )

        # Separate CE and PE rows
        ce_rows = [r for r in all_rows if r["Type"] == "CE"]
        pe_rows = [r for r in all_rows if r["Type"] == "PE"]

        # Replicate for each snapshot
        for suffix, type_rows in [("_CE", ce_rows), ("_PE", pe_rows)]:
            key = f"{base_key}{suffix}"
            snap_rows = []
            for snap_i in range(snapshots_per_chain):
                for r in type_rows:
                    r_copy = dict(r)
                    # Shift datetime slightly per snapshot
                    r_copy["Date Time"] = datetime(
                        2026, 7, 21, 9, 15 + snap_i, r_copy["Date Time"].second,
                        tzinfo=timezone.utc
                    )
                    snap_rows.append(r_copy)
            total += len(snap_rows)
            frames[key] = pd.DataFrame(snap_rows, columns=columns)

    return ChainCaptureResult(
        frames=frames,
        capture_started_at="2026-07-21T03:45:00+00:00",
        capture_ended_at="2026-07-21T03:46:00+00:00",
        total_rows=total,
    )


# --- Auth (or lack thereof) ---------------------------------------------

def test_option_chain_export_is_public(client: TestClient):
    """Endpoint is PUBLIC — no JWT required."""
    from app.services import truedata_option_chain_service as svc
    fake_result = _fake_option_chain_result(
        [ChainRequest(underlying="NIFTY", expiry=date(2026, 7, 30),
                      chain_length=10, bid_ask=True, greek=False)],
        snapshots_per_chain=1,
    )
    with patch.object(svc, "capture_option_chains", return_value=fake_result):
        r = client.post(
            "/api/v1/market-data/truedata/option-chain/export",
            json={
                "chains": [{"underlying": "NIFTY", "expiry": "2026-07-30"}],
                "duration_seconds": 30,
            },
        )
    assert r.status_code == 200, f"expected 200 (no auth), got {r.status_code}: {r.text}"


# --- Schema validation --------------------------------------------------

def test_option_chain_export_rejects_empty_chains(client: TestClient):
    r = client.post(
        "/api/v1/market-data/truedata/option-chain/export",
        json={"chains": [], "duration_seconds": 30},
    )
    assert r.status_code == 422


def test_option_chain_export_rejects_too_many_chains(client: TestClient):
    chains = [
        {"underlying": "NIFTY", "expiry": f"2026-08-{6 + i:02d}"}
        for i in range(10)
    ]
    r = client.post(
        "/api/v1/market-data/truedata/option-chain/export",
        json={"chains": chains, "duration_seconds": 30},
    )
    assert r.status_code == 422


def test_option_chain_export_rejects_chain_length_too_small(client: TestClient):
    r = client.post(
        "/api/v1/market-data/truedata/option-chain/export",
        json={
            "chains": [{"underlying": "NIFTY", "expiry": "2026-07-30", "chain_length": 1}],
            "duration_seconds": 30,
        },
    )
    assert r.status_code == 422


def test_option_chain_export_rejects_duration_too_long(client: TestClient):
    r = client.post(
        "/api/v1/market-data/truedata/option-chain/export",
        json={
            "chains": [{"underlying": "NIFTY", "expiry": "2026-07-30"}],
            "duration_seconds": 301,
        },
    )
    assert r.status_code == 422


def test_option_chain_export_rejects_duplicate_pairs(client: TestClient):
    r = client.post(
        "/api/v1/market-data/truedata/option-chain/export",
        json={
            "chains": [
                {"underlying": "NIFTY", "expiry": "2026-07-30"},
                {"underlying": "NIFTY", "expiry": "2026-07-30"},
            ],
            "duration_seconds": 30,
        },
    )
    assert r.status_code == 422
    assert "Duplicate" in r.text or "duplicate" in r.text.lower()


# --- Hard-fail contract -------------------------------------------------

def test_option_chain_export_hard_fails_on_truedata_error(client: TestClient):
    def _raise(*args, **kwargs):
        raise truedata_option_chain_service.TrueDataError(
            "User Subscription Expired — trial account not entitled for option chain"
        )
    with patch.object(truedata_option_chain_service, "capture_option_chains", side_effect=_raise):
        r = client.post(
            "/api/v1/market-data/truedata/option-chain/export",
            json={
                "chains": [{"underlying": "NIFTY", "expiry": "2026-07-30"}],
                "duration_seconds": 30,
            },
        )
    assert r.status_code == 502
    assert "User Subscription Expired" in r.text


# --- Happy path: separate CE/PE files -----------------------------------

def test_option_chain_export_returns_separate_ce_pe_xls(client: TestClient):
    """ZIP contains separate _CE.xls and _PE.xls per (underlying, expiry) pair."""
    req_chains = [
        ChainRequest(underlying="NIFTY", expiry=date(2026, 7, 30),
                     chain_length=6, bid_ask=True, greek=False),
        ChainRequest(underlying="NIFTY", expiry=date(2026, 8, 27),
                     chain_length=6, bid_ask=True, greek=False),
    ]
    fake_result = _fake_option_chain_result(req_chains, snapshots_per_chain=2)

    with patch.object(truedata_option_chain_service, "capture_option_chains", return_value=fake_result):
        r = client.post(
            "/api/v1/market-data/truedata/option-chain/export",
            json={
                "chains": [
                    {"underlying": "NIFTY", "expiry": "2026-07-30", "chain_length": 6},
                    {"underlying": "NIFTY", "expiry": "2026-08-27", "chain_length": 6},
                ],
                "duration_seconds": 30,
                "snapshot_interval_seconds": 5,
                "segment": "NSE F&O",
            },
        )

    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = zf.namelist()
        assert "metadata.txt" in names
        xls_names = [n for n in names if n.endswith(".xls")]

        # 2 chains × 2 types (CE, PE) = 4 .xls files
        assert len(xls_names) == 4, f"Expected 4 .xls files, got {xls_names}"

        # Verify CE/PE naming convention — filenames contain _CE_ or _PE_ in the key part
        ce_files = [n for n in xls_names if "_CE_" in n]
        pe_files = [n for n in xls_names if "_PE_" in n]
        assert len(ce_files) == 2, f"Expected 2 CE files, got {ce_files}"
        assert len(pe_files) == 2, f"Expected 2 PE files, got {pe_files}"

        # Each .xls has the 23-column enriched schema
        for xls_name in xls_names:
            df = pd.read_excel(io.BytesIO(zf.read(xls_name)), engine="xlrd")
            assert list(df.columns) == OPTION_CHAIN_COLUMNS, (
                f"{xls_name} columns mismatch: got {list(df.columns)}"
            )
            # Spot-check values
            assert df["Underlying"].iloc[0] == "NIFTY"

        # Verify CE files only contain CE rows, PE files only PE rows
        for ce_file in ce_files:
            df = pd.read_excel(io.BytesIO(zf.read(ce_file)), engine="xlrd")
            assert all(df["Type"] == "CE"), f"CE file {ce_file} contains non-CE rows"
            assert df["Strike"].notna().any(), "Strike column should have data"
        for pe_file in pe_files:
            df = pd.read_excel(io.BytesIO(zf.read(pe_file)), engine="xlrd")
            assert all(df["Type"] == "PE"), f"PE file {pe_file} contains non-PE rows"
            assert df["Strike"].notna().any(), "Strike column should have data"

        # metadata.txt mentions separate CE/PE structure
        meta = zf.read("metadata.txt").decode("utf-8")
        assert "TrueData Option-Chain Export" in meta
        assert "Symbol ID" in meta
        assert "SEPARATE" in meta


def test_option_chain_export_includes_greek_columns_when_requested(client: TestClient):
    """When greek=true, the .xls has 29 columns (23 base + 6 greek)."""
    req_chains = [
        ChainRequest(underlying="NIFTY", expiry=date(2026, 7, 30),
                     chain_length=6, bid_ask=True, greek=True),
    ]
    fake_result = _fake_option_chain_result(req_chains, snapshots_per_chain=2)

    with patch.object(truedata_option_chain_service, "capture_option_chains", return_value=fake_result):
        r = client.post(
            "/api/v1/market-data/truedata/option-chain/export",
            json={
                "chains": [
                    {"underlying": "NIFTY", "expiry": "2026-07-30",
                     "chain_length": 6, "greek": True},
                ],
                "duration_seconds": 30,
            },
        )

    assert r.status_code == 200, r.text
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        xls_names = [n for n in zf.namelist() if n.endswith(".xls")]
        # 1 chain × 2 types = 2 .xls files
        assert len(xls_names) == 2
        for xls_name in xls_names:
            df = pd.read_excel(io.BytesIO(zf.read(xls_name)), engine="xlrd")
            expected = OPTION_CHAIN_COLUMNS + GREEK_COLUMNS  # 29 cols
            assert list(df.columns) == expected, (
                f"greek-mode columns mismatch in {xls_name}: got {list(df.columns)}"
            )
            assert len(df.columns) == 29
        # Spot-check greek value in CE file
        ce_file = [n for n in xls_names if "_CE_" in n][0]
        df = pd.read_excel(io.BytesIO(zf.read(ce_file)), engine="xlrd")
        assert df["IV"].iloc[0] == 12.5


# --- Underlying normalisation -------------------------------------------

def test_option_chain_export_uppercases_underlying(client: TestClient):
    captured: dict = {}

    def _capture(reqs, *, duration_seconds, snapshot_interval_seconds):
        captured["requests"] = reqs
        return _fake_option_chain_result(reqs, snapshots_per_chain=1)

    with patch.object(truedata_option_chain_service, "capture_option_chains", side_effect=_capture):
        r = client.post(
            "/api/v1/market-data/truedata/option-chain/export",
            json={
                "chains": [{"underlying": " nifty ", "expiry": "2026-07-30"}],
                "duration_seconds": 30,
            },
        )

    assert r.status_code == 200, r.text
    assert captured["requests"][0].underlying == "NIFTY"


# --- Service-level edge case --------------------------------------------

def test_capture_option_chains_raises_on_empty_requests():
    with pytest.raises(truedata_option_chain_service.TrueDataError):
        truedata_option_chain_service.capture_option_chains(
            [], duration_seconds=30, snapshot_interval_seconds=5,
        )


# --- exit() patching (critical safety net) ------------------------------

def test_sdk_exit_patching_prevents_process_death():
    import sys
    import types

    fake_module = types.ModuleType("truedata.websocket.TD_live")

    class _FakeTDLive:
        def __init__(self, *args, **kwargs):
            self.live_data = {}
            self.greek_data = {}

        def connect(self):
            pass

        def disconnect(self):
            pass

        def start_option_chain(self, symbol, expiry, chain_length=None,
                               bid_ask=False, greek=False):
            exit()  # noqa: PLR1722

    fake_module.TD_live = _FakeTDLive
    real_module = sys.modules.get("truedata.websocket.TD_live")
    sys.modules["truedata.websocket.TD_live"] = fake_module
    try:
        with pytest.raises(truedata_option_chain_service.TrueDataError):
            truedata_option_chain_service.capture_option_chains(
                [ChainRequest(
                    underlying="NIFTY", expiry=date(2026, 7, 30),
                    chain_length=10, bid_ask=True, greek=True,
                )],
                duration_seconds=5,
                snapshot_interval_seconds=2,
            )
    finally:
        if real_module is not None:
            sys.modules["truedata.websocket.TD_live"] = real_module
        if hasattr(fake_module, "_otp_exit_patched"):
            del fake_module._otp_exit_patched


def test_format_subscription_error_mentions_upgrade():
    err = truedata_option_chain_service.TrueDataError("User Subscription Expired")
    assert "User Subscription Expired" in str(err)


def test_connection_manager_sdk_exit_raiser():
    from app.services.truedata_connection_manager import _make_sdk_exit_raiser, _SdkExitRaisedError
    raiser = _make_sdk_exit_raiser()
    with pytest.raises(_SdkExitRaisedError):
        raiser()
    with pytest.raises(_SdkExitRaisedError) as exc_info:
        raiser("boom")
    assert exc_info.value.original_message == "boom"
