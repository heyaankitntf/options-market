"""Tests for the TrueData option-chain export endpoint.

We don't hit the real TrueData API here — the option-chain service is
monkey-patched so the tests stay hermetic and fast. The goal is to verify:

  - the endpoint is PUBLIC (no JWT required — auth was disabled per team-lead directive)
  - the request schema validates filters (empty chains, too many chains,
    chain_length bounds, duration bounds, duplicate pairs)
  - on a TrueData failure (incl. 0 rows captured, or trial's "User
    Subscription Expired"), the endpoint returns 502
  - on success, the endpoint returns a ZIP with one .xls per
    (underlying, expiry) pair + a metadata.txt entry, and the .xls has
    the team-lead's full column spec (20 base cols + 6 greek cols when
    greek=true)
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



def _fake_chain_dataframe(underlying: str, expiry: date, n_strikes: int = 3, *, greek: bool = False) -> pd.DataFrame:
    """Build a DataFrame mimicking what the SDK's `chain.get_option_chain()`
    returns: indexed by symbol, with `strike` and `type` columns plus the
    chain data columns."""
    expiry_str = expiry.strftime("%y%m%d")
    symbols = []
    strikes = []
    types = []
    for i in range(n_strikes):
        strike = 25000 + i * 50
        for t in ("CE", "PE"):
            symbols.append(f"{underlying}{expiry_str}{strike}{t}")
            strikes.append(str(strike))
            types.append(t)
    data = {
        "symbols": symbols,
        "strike": strikes,
        "type": types,
        "ltp": [100.5 + i * 0.5 for i in range(len(symbols))],
        "ltt": pd.date_range("2026-07-21 09:15", periods=len(symbols), freq="1s"),
        "ltq": [150 + i for i in range(len(symbols))],
        "volume": [12500 + i * 100 for i in range(len(symbols))],
        "price_change": [2.5 + i * 0.1 for i in range(len(symbols))],
        "price_change_perc": [0.025 + i * 0.001 for i in range(len(symbols))],
        "oi": [45000 + i * 50 for i in range(len(symbols))],
        "prev_oi": [44000 + i * 50 for i in range(len(symbols))],
        "oi_change": [1000 + i for i in range(len(symbols))],
        "oi_change_perc": [0.022 + i * 0.001 for i in range(len(symbols))],
        "bid": [100.4 + i * 0.5 for i in range(len(symbols))],
        "bid_qty": [200 + i for i in range(len(symbols))],
        "ask": [100.6 + i * 0.5 for i in range(len(symbols))],
        "ask_qty": [180 + i for i in range(len(symbols))],
    }
    if greek:
        data.update({
            "iv": [12.5 + i * 0.1 for i in range(len(symbols))],
            "delta": [0.5 + i * 0.01 for i in range(len(symbols))],
            "theta": [-5.2 + i * 0.05 for i in range(len(symbols))],
            "gamma": [0.001 + i * 0.0001 for i in range(len(symbols))],
            "vega": [8.5 + i * 0.1 for i in range(len(symbols))],
            "rho": [-0.5 + i * 0.01 for i in range(len(symbols))],
        })
    df = pd.DataFrame(data)
    df.set_index("symbols", inplace=True)
    return df


def _fake_option_chain_result(
    chains: list[ChainRequest],
    *,
    snapshots_per_chain: int = 2,
) -> ChainCaptureResult:
    """Build a ChainCaptureResult mimicking what the service would return
    after capturing `snapshots_per_chain` snapshots for each chain."""
    frames: dict[str, pd.DataFrame] = {}
    total = 0
    for req in chains:
        key = f"{req.underlying}_{req.expiry.isoformat()}"
        chain_df = _fake_chain_dataframe(
            req.underlying, req.expiry,
            n_strikes=req.chain_length // 2,
            greek=req.greek,
        )
        rows: list[dict] = []
        for snap_i in range(snapshots_per_chain):
            snap_time = datetime(2026, 7, 21, 9, 15, snap_i * 5, tzinfo=timezone.utc)
            rows.extend(
                truedata_option_chain_service._row_from_chain_df(
                    chain_df,
                    underlying=req.underlying,
                    expiry_str=req.expiry.isoformat(),
                    snapshot_time=snap_time,
                    include_greek=req.greek,
                )
            )
        total += len(rows)
        columns = OPTION_CHAIN_COLUMNS + (GREEK_COLUMNS if any(r.greek for r in chains) else [])
        frames[key] = pd.DataFrame(rows, columns=columns)

    return ChainCaptureResult(
        frames=frames,
        capture_started_at="2026-07-21T03:45:00+00:00",
        capture_ended_at="2026-07-21T03:46:00+00:00",
        total_rows=total,
    )


# --- Auth (or lack thereof) ---------------------------------------------

def test_option_chain_export_is_public(client: TestClient):
    """Endpoint is PUBLIC — no JWT required (auth disabled per team-lead directive).

    The other /market-data/* endpoints still require a Bearer JWT, but the
    option-chain endpoint must NOT 401 when no Authorization header is sent.
    We don't assert a specific success code here because the request below
    would normally hit the TrueData SDK (monkey-patched in other tests) —
    we only assert that the auth layer doesn't reject it.
    """
    # Monkey-patch the service to avoid hitting the real SDK.
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
            # NOTE: no Authorization header.
        )
    # 200 = the endpoint accepted the unauthenticated request and returned a ZIP.
    # (If auth were still wired up, this would be 401.)
    assert r.status_code == 200, f"expected 200 (no auth), got {r.status_code}: {r.text}"


# --- Schema validation --------------------------------------------------

def test_option_chain_export_rejects_empty_chains(client: TestClient):
    """`chains` must be non-empty."""
    r = client.post(
        "/api/v1/market-data/truedata/option-chain/export",
        json={"chains": [], "duration_seconds": 30},
    )
    assert r.status_code == 422  # min_length=1 enforced by pydantic


def test_option_chain_export_rejects_too_many_chains(client: TestClient):
    """`chains` length is capped at TRUEDATA_CHAIN_MAX_PAIRS (default 5)."""
    # Build 10 chains (more than the default cap of 5).
    chains = [
        {"underlying": "NIFTY", "expiry": f"2026-08-{6 + i:02d}"}
        for i in range(10)
    ]
    r = client.post(
        "/api/v1/market-data/truedata/option-chain/export",
        json={"chains": chains, "duration_seconds": 30},
    )
    # Could be 422 (schema min_length=1, max_length not set on Field) or
    # the route's explicit 422 check. Either way it's rejected.
    assert r.status_code == 422


def test_option_chain_export_rejects_chain_length_too_small(client: TestClient):
    """`chain_length` must be >= 2."""
    r = client.post(
        "/api/v1/market-data/truedata/option-chain/export",
        json={
            "chains": [
                {"underlying": "NIFTY", "expiry": "2026-07-30", "chain_length": 1},
            ],
            "duration_seconds": 30,
        },
    )
    assert r.status_code == 422


def test_option_chain_export_rejects_duration_too_long(client: TestClient):
    """`duration_seconds` capped at 300."""
    r = client.post(
        "/api/v1/market-data/truedata/option-chain/export",
        json={
            "chains": [{"underlying": "NIFTY", "expiry": "2026-07-30"}],
            "duration_seconds": 301,
        },
    )
    assert r.status_code == 422


def test_option_chain_export_rejects_duplicate_pairs(client: TestClient):
    """Duplicate (underlying, expiry) pairs are rejected."""
    r = client.post(
        "/api/v1/market-data/truedata/option-chain/export",
        json={
            "chains": [
                {"underlying": "NIFTY", "expiry": "2026-07-30"},
                {"underlying": "NIFTY", "expiry": "2026-07-30"},  # duplicate
            ],
            "duration_seconds": 30,
        },
    )
    assert r.status_code == 422
    # The validator's error message should mention "Duplicate".
    assert "Duplicate" in r.text or "duplicate" in r.text.lower()


# --- Hard-fail contract -------------------------------------------------

def test_option_chain_export_hard_fails_on_truedata_error(client: TestClient):
    """On TrueDataError (incl. trial's 'User Subscription Expired'), the
    endpoint returns 502 with the error message."""

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


# --- Happy path ---------------------------------------------------------

def test_option_chain_export_success_returns_zip_with_per_chain_xls(client: TestClient):
    """Happy path: ZIP with one .xls per chain + a metadata.txt entry,
    and the .xls has the team-lead's 20-column base spec."""

    # Build a dual-expiry request mimicking the team lead's "current +
    # next expiry" use case (both Thursday weekly expiries).
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
    assert 'attachment; filename="' in r.headers["content-disposition"]
    assert r.headers["x-export-mode"] == "option-chain"
    # 2 chains × 3 strikes × 2 types × 2 snapshots = 24 rows
    assert r.headers["x-export-total-rows"] == "24"

    # Inspect the ZIP.
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = zf.namelist()
        assert "metadata.txt" in names
        xls_names = [n for n in names if n.endswith(".xls")]
        assert len(xls_names) == 2  # one .xls per (underlying, expiry) pair

        # Each .xls parses back as a DataFrame with the 20 base columns.
        expected_base_cols = [
            "snapshot_time", "underlying", "expiry", "symbol", "strike", "type",
            "ltp", "ltt", "ltq", "volume",
            "price_change", "price_change_perc",
            "oi", "prev_oi", "oi_change", "oi_change_perc",
            "bid", "bid_qty", "ask", "ask_qty",
        ]
        for xls_name in xls_names:
            df = pd.read_excel(io.BytesIO(zf.read(xls_name)), engine="xlrd")
            assert list(df.columns) == expected_base_cols, (
                f"{xls_name} columns mismatch: got {list(df.columns)}"
            )
            # 3 strikes × 2 types × 2 snapshots = 12 rows per chain
            assert len(df) == 12
            # Spot-check a value to confirm data flowed through.
            assert df["underlying"].iloc[0] == "NIFTY"
            assert df["ltp"].iloc[0] == 100.5

        # metadata.txt should mention the option-chain column spec + trial caveat.
        meta = zf.read("metadata.txt").decode("utf-8")
        assert "TrueData Option-Chain Export" in meta
        assert "snapshot_time" in meta
        assert "TRIAL ACCOUNT CAVEAT" in meta


def test_option_chain_export_includes_greek_columns_when_requested(client: TestClient):
    """When greek=true is set on any chain, the .xls has 26 columns
    (20 base + 6 greek) for ALL chains in the request."""

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
        assert len(xls_names) == 1
        df = pd.read_excel(io.BytesIO(zf.read(xls_names[0])), engine="xlrd")
        expected = OPTION_CHAIN_COLUMNS + GREEK_COLUMNS  # 26 cols
        assert list(df.columns) == expected, (
            f"greek-mode columns mismatch: got {list(df.columns)}"
        )
        assert len(df.columns) == 26
        # Spot-check a greek value
        assert df["iv"].iloc[0] == 12.5


# --- Underlying normalisation -------------------------------------------

def test_option_chain_export_uppercases_underlying(client: TestClient):
    """Underlying names are upper-cased before being forwarded to the service."""

    captured: dict = {}

    def _capture(reqs, *, duration_seconds, snapshot_interval_seconds):
        captured["requests"] = reqs
        # Return a minimal valid result so the route proceeds to ZIP building.
        return _fake_option_chain_result(reqs, snapshots_per_chain=1)

    with patch.object(truedata_option_chain_service, "capture_option_chains", side_effect=_capture):
        r = client.post(
            "/api/v1/market-data/truedata/option-chain/export",
            json={
                "chains": [
                    {"underlying": " nifty ", "expiry": "2026-07-30"},
                ],
                "duration_seconds": 30,
            },
        )

    assert r.status_code == 200, r.text
    assert captured["requests"][0].underlying == "NIFTY"


# --- Service-level edge case --------------------------------------------

def test_capture_option_chains_raises_on_empty_requests():
    """The service itself raises TrueDataError if called with empty list."""
    with pytest.raises(truedata_option_chain_service.TrueDataError):
        truedata_option_chain_service.capture_option_chains(
            [], duration_seconds=30, snapshot_interval_seconds=5,
        )


# --- exit() patching (critical safety net) ------------------------------

def test_sdk_exit_patching_prevents_process_death():
    """The v7 SDK's `start_option_chain` calls builtin `exit()` on failure.
    Our service patches `exit` in the SDK module namespace so it raises
    `_SdkExitRaisedError` instead of killing the process. This test verifies
    that a real (mocked) SDK call that triggers `exit()` is converted to a
    `TrueDataError` — not a `SystemExit`."""
    import sys
    import types

    # Build a fake `truedata.websocket.TD_live` module whose `start_option_chain`
    # simulates the SDK's failure path by calling `exit()` (just like the real
    # SDK does on `get_atm` failure).
    fake_module = types.ModuleType("truedata.websocket.TD_live")

    class _FakeTDLive:
        def __init__(self, *args, **kwargs):
            # Real TD_live.__init__ calls self.connect() — fake that too.
            self.live_data = {}
            self.greek_data = {}

        def connect(self):
            pass

        def disconnect(self):
            pass

        def start_option_chain(self, symbol, expiry, chain_length=None,
                               bid_ask=False, greek=False):
            # Simulate the SDK's failure path: `exit()` is called when
            # `get_atm()` raises. The real SDK code is:
            #     except Exception as e:
            #         self.logger.warning(...)
            #         exit()
            exit()  # noqa: PLR1722 — intentionally mimics the SDK

    fake_module.TD_live = _FakeTDLive
    # Capture a reference to the exit_raiser our service installs, so we can
    # verify it actually got called.
    captured = {}

    # Replace the real module BEFORE the service tries to import from it.
    real_module = sys.modules.get("truedata.websocket.TD_live")
    sys.modules["truedata.websocket.TD_live"] = fake_module
    try:
        with pytest.raises(truedata_option_chain_service.TrueDataError) as exc_info:
            truedata_option_chain_service.capture_option_chains(
                [ChainRequest(
                    underlying="NIFTY", expiry=date(2026, 7, 30),
                    chain_length=10, bid_ask=True, greek=True,
                )],
                duration_seconds=5,
                snapshot_interval_seconds=2,
            )
        # Verify the error message mentions the trial-account explanation.
        assert "option-chain" in str(exc_info.value).lower()
    finally:
        if real_module is not None:
            sys.modules["truedata.websocket.TD_live"] = real_module
        # Clean up the patch flag so future imports re-patch correctly.
        if hasattr(fake_module, "_otp_exit_patched"):
            del fake_module._otp_exit_patched


def test_format_subscription_error_mentions_upgrade():
    """The subscription-error helper mentions both the original error and
    the upgrade instruction."""
    msg = truedata_option_chain_service._format_subscription_error(
        "User Subscription Expired"
    )
    assert "User Subscription Expired" in msg
    assert "Upgrade" in msg
    assert "option-chain" in msg.lower()


def test_sdk_exit_raiser_raises_not_exits():
    """The `_make_sdk_exit_raiser` returns a callable that raises
    `_SdkExitRaisedError` rather than calling sys.exit."""
    raiser = truedata_option_chain_service._make_sdk_exit_raiser()
    with pytest.raises(truedata_option_chain_service._SdkExitRaisedError):
        raiser()
    # With a string argument
    with pytest.raises(truedata_option_chain_service._SdkExitRaisedError) as exc_info:
        raiser("boom")
    assert exc_info.value.original_message == "boom"
