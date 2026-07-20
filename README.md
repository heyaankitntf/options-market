# OptionFlow — OTP Auth + TrueData Market Data Export

FastAPI microservice that combines:

1. **OTP-based phone authentication** (registration, login, JWT issuance)
2. **TrueData historical OHLCV export** — fetch bars (1-min, 5-min, EOD, …)
   for any list of symbols and download them as a ZIP of legacy `.xls` files
3. **TrueData live tick export** — capture real-time trade ticks (LTP, LTQ,
   ATP, TTQ, O/H/L, OI, Bid/Ask, special tag, tick sequence) for a bounded
   duration and download them as a ZIP of legacy `.xls` files
4. **TrueData replay tick export** — same pipeline as #3 but connects to
   TrueData's off-hours replay feed (`replay.truedata.in:8082`) so you can
   exercise the tick-consuming code path between 18:00–02:00 IST without
   waiting for live market hours

---

## Quick start

```bash
bash run.sh          # creates .venv, installs deps, launches uvicorn on :8000
```

Swagger UI: <http://localhost:8000/docs>
ReDoc:     <http://localhost:8000/redoc>

---

## Authentication flow

| Method | Endpoint                              | Purpose                                  |
|--------|---------------------------------------|------------------------------------------|
| POST   | `/api/v1/auth/request-otp`            | Request a registration OTP               |
| POST   | `/api/v1/auth/register`               | Verify OTP + create user                 |
| POST   | `/api/v1/auth/request-login-otp`      | Request a login OTP                      |
| POST   | `/api/v1/auth/login`                  | Verify OTP + return JWT                  |
| GET    | `/api/v1/users/me`                    | Fetch current user (Bearer JWT required) |
| GET    | `/api/v1/auth/dev-otp?phone=...`      | DEV — peek at the latest OTP             |

---

## TrueData historical OHLCV export

### Endpoint

```
POST /api/v1/market-data/truedata/export
Authorization: Bearer <jwt>
Content-Type: application/json
```

### Request body

```jsonc
{
  "symbols":   ["NIFTY-I", "BANKNIFTY-I"],   // up to 50 (trial cap)
  "start_date": "2026-07-14",                // YYYY-MM-DD, inclusive
  "end_date":   "2026-07-18",                // YYYY-MM-DD, inclusive
  "bar_size":   "1 min",                     // tick | 1 min | 5 min | 15 min | 30 min | 1 hour | EOD
  "segment":    "NSE F&O"                    // optional, metadata-only
}
```

### Symbol formats (verified against the trial account)

Not all symbol conventions work in the trial account. Below is what we
verified by probing TrueData on 2026-07-18.

| Category | Working symbols | Notes |
|----------|-----------------|-------|
| **Indices** | `NIFTY 50`, `SENSEX`, `BANKEX` | Note the **space** in `NIFTY 50` — bare `NIFTY` returns empty |
| **Index futures (continuous)** | `NIFTY-I`, `BANKNIFTY-I`, `FINNIFTY-I` | The `-I` suffix means "continuous front-month" |
| **Commodity futures (continuous)** | `CRUDEOIL-I`, `GOLD-I`, `SILVER-I` | MCX segment |
| **NSE Equity** | `SBIN`, `RELIANCE`, `TCS`, `INFY`, … | Plain ticker, no suffix |

**Symbols that DON'T work in the trial** (return 502 from this endpoint):

- Bare index names (`NIFTY`, `BANKNIFTY`) — use `NIFTY 50` or `NIFTY-I`
- BSE equity with `-BE` suffix (`SBIN-BE`) — TrueData doesn't use the Zerodha convention
- Option contracts (`NIFTY26JUL24000CE`) — trial doesn't include NSE F&O option history
- Currency derivatives (`USDINR26JULFUT`) — not in trial segments

Symbols are normalised (strip + uppercase + dedupe) before being sent to
TrueData, so `" nifty-i "` and `"NIFTY-I"` are treated as the same symbol.

### Response

`Content-Type: application/zip` — a ZIP containing:

```
NIFTY-I_NSE_F_O_2026-07-14_2026-07-18_1_min.xls
BANKNIFTY-I_NSE_F_O_2026-07-14_2026-07-18_1_min.xls
metadata.txt
```

Each `.xls` is a legacy BIFF8 file (one sheet per symbol) with columns:
`time, open, high, low, close, volume, open_interest`
(plus `bid / ask / bid_qty / ask_qty` for `bar_size: "tick"`).

### Error behaviour

If TrueData is unreachable, or returns no data for **any** requested symbol,
the endpoint responds with **HTTP 502** and a `TrueData error: ...` detail
message. No partial ZIP is returned.

### Example (curl)

```bash
# 1. Register a user (one-time)
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/request-otp \
  -H 'Content-Type: application/json' \
  -d '{"country_code":"+91","phone":"9999999999"}' > /dev/null && \
  OTP=$(curl -s "http://localhost:8000/api/v1/auth/dev-otp?phone=9999999999" \
       | python3 -c 'import sys,json; print(json.load(sys.stdin)["code"])') && \
  curl -s -X POST http://localhost:8000/api/v1/auth/register \
    -H 'Content-Type: application/json' \
    -d "{\"country_code\":\"+91\",\"phone\":\"9999999999\",\"code\":\"$OTP\",\"name\":\"Test\"}" \
       > /dev/null && \
  curl -s -X POST http://localhost:8000/api/v1/auth/request-login-otp \
    -H 'Content-Type: application/json' \
    -d '{"country_code":"+91","phone":"9999999999"}' > /dev/null && \
  OTP=$(curl -s "http://localhost:8000/api/v1/auth/dev-otp?phone=9999999999" \
       | python3 -c 'import sys,json; print(json.load(sys.stdin)["code"])') && \
  curl -s -X POST http://localhost:8000/api/v1/auth/login \
    -H 'Content-Type: application/json' \
    -d "{\"country_code\":\"+91\",\"phone\":\"9999999999\",\"code\":\"$OTP\"}" \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

# 2. Export TrueData data
curl -s -X POST http://localhost:8000/api/v1/market-data/truedata/export \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
        "symbols":    ["NIFTY-I", "BANKNIFTY-I"],
        "start_date": "2026-07-14",
        "end_date":   "2026-07-18",
        "bar_size":   "1 min",
        "segment":    "NSE F&O"
      }' \
  -o truedata_export.zip

unzip -l truedata_export.zip
```

---

## TrueData live tick export

### Endpoint

```
POST /api/v1/market-data/truedata/ticks/export
Authorization: Bearer <jwt>
Content-Type: application/json
```

### What this endpoint does

Opens a real-time WebSocket to TrueData, subscribes to the requested
symbols, captures every trade tick for the requested `duration_seconds`,
then disconnects and returns the captured ticks as a ZIP of legacy `.xls`
files (one per symbol).

### ⚠️ Real-time only — no historical backfill

TrueData has **no historical tick archive**. Ticks are captured only for
the duration of the HTTP request. Calling this endpoint outside market
hours (09:15–15:30 IST, Mon–Fri) returns **HTTP 502** with the message
`"No trade ticks were received during the capture window."` — that is the
expected behaviour, not a bug.

### Request body

```jsonc
{
  "symbols":          ["NIFTY-I", "BANKNIFTY-I"],  // up to 50 (trial cap)
  "duration_seconds": 60,                          // 5–300, default 60
  "segment":          "NSE F&O"                    // optional, metadata-only
}
```

### `.xls` column schema (matches the spec the API provider shared with the team)

Each `.xls` file has exactly these columns, in this order:

| #  | Column            | Type      | Source field on TrueData `full_feed` tick |
|----|-------------------|-----------|-------------------------------------------|
| 1  | `symbol_id`       | int       | `tick.symbol_id`                          |
| 2  | `timestamp`       | datetime  | `tick.timestamp`                          |
| 3  | `ltp`             | float     | `tick.ltp`                                |
| 4  | `ltq`             | int       | `tick.ltq`                                |
| 5  | `atp`             | float     | `tick.atp` (avg traded price, day)        |
| 6  | `ttq`             | float     | `tick.ttq` (total traded qty, day)        |
| 7  | `day_open`        | float     | `tick.day_open`                           |
| 8  | `day_high`        | float     | `tick.day_high`                           |
| 9  | `day_low`         | float     | `tick.day_low`                            |
| 10 | `prev_day_close`  | float     | `tick.prev_day_close`                     |
| 11 | `oi`              | int       | `tick.oi` (open interest, F&O only)       |
| 12 | `prev_day_oi`     | int       | `tick.prev_day_oi`                        |
| 13 | `turnover`        | float     | `tick.turnover` (day's turnover)          |
| 14 | `special_tag`     | str       | `tick.raw_tick[13]` — `"O"`, `"H"`, `"L"`, or `""` |
| 15 | `tick_seq`        | int       | `tick.tick_seq`                           |
| 16 | `best_bid_price`  | float     | `tick.best_bid_price` (L1)                |
| 17 | `best_bid_qty`    | int       | `tick.best_bid_qty`   (L1)                |
| 18 | `best_ask_price`  | float     | `tick.best_ask_price` (L1)                |
| 19 | `best_ask_qty`    | int       | `tick.best_ask_qty`   (L1)                |

**Notes:**

- The `special_tag` field lives at `raw_tick[13]` in the SDK's internal
  tuple. The official `truedata` v7 SDK skips parsing this index; we
  extract it manually so the `"O"/"H"/"L"` marker the team lead mentioned
  is preserved. It is `""` (empty string) on regular ticks, and `"O"`,
  `"H"`, or `"L"` on ticks that establish a new session Open / High / Low.
- `oi` and `prev_day_oi` are non-zero only for F&O contracts. For equity
  ticks they are always 0.
- The Bid / Bid Qty / Ask / Ask Qty columns are **L1 (best level only)**.
  For 5-level depth, use the TrueData `bidask_callback` API (not yet
  exposed by this endpoint — see "Future work" below).

### Symbol formats (option contracts supported)

Same verified formats as the historical endpoint, **plus** option contracts
per the format the API provider shared:

```
Symbol Format = SymbolName + Expiry(YYMMDD) + StrikePrice + CE/PE

Example: NIFTY + 260828 (YYMMDD) + 25000 + CE = NIFTY26082825000CE
Example: BANKNIFTY + 260828 + 58000 + PE      = BANKNIFTY26082858000PE
```

| Category | Example | Notes |
|----------|---------|-------|
| **Index futures (continuous)** | `NIFTY-I`, `BANKNIFTY-I` | The `-I` suffix = continuous front-month |
| **Index (spot)** | `NIFTY 50`, `SENSEX` | Note the space in `NIFTY 50` |
| **NSE Equity** | `SBIN`, `RELIANCE` | Plain ticker, no suffix |
| **Index options** | `NIFTY26082825000CE`, `NIFTY26082825000PE` | YYMMDD expiry + strike + CE/PE |
| **Stock options** | `SBIN260828300CE` | Same format |
| **Commodity futures (continuous)** | `CRUDEOIL-I`, `GOLD-I` | MCX segment |

### Response

`Content-Type: application/zip` — a ZIP containing:

```
NIFTY-I_NSE_F_O_ticks_60s.xls
BANKNIFTY-I_NSE_F_O_ticks_60s.xls
metadata.txt
```

### Response headers

| Header | Meaning |
|--------|---------|
| `Content-Disposition` | `attachment; filename="truedata_ticks_<userid>_<duration>s.zip"` |
| `X-Export-Files` | Comma-separated list of filenames inside the ZIP |
| `X-Export-Total-Rows` | Total ticks captured across all symbols |
| `X-Export-Truncated` | Comma-separated symbols that hit the 60k-row BIFF8 cap (usually empty) |
| `X-Export-Capture-Started` | UTC ISO timestamp when the WS subscription began |
| `X-Export-Capture-Ended` | UTC ISO timestamp when the WS disconnected |
| `X-Export-Generated-At` | UTC ISO timestamp when the ZIP was assembled |

### Error behaviour

| Code | When |
|------|------|
| `401` | Missing/invalid JWT |
| `422` | Empty symbols, `duration_seconds` outside `[5, 300]` |
| `502` | TrueData connect/subscribe failed, OR 0 ticks captured (market closed, illiquid symbols, plan doesn't include tick streaming) |

### Example (curl)

```bash
# 1. Get a JWT (see auth flow above) — abbreviated here
TOKEN="..."

# 2. Capture 60 seconds of live ticks for NIFTY-I and BANKNIFTY-I
curl -s -X POST http://localhost:8000/api/v1/market-data/truedata/ticks/export \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
        "symbols":          ["NIFTY-I", "BANKNIFTY-I"],
        "duration_seconds": 60,
        "segment":          "NSE F&O"
      }' \
  -D headers.txt \
  -o truedata_ticks.zip

cat headers.txt            # inspect X-Export-* headers
unzip -l truedata_ticks.zip
```

### Replay feed (off-hours tick replay)

TrueData replays the day's market session over a **separate WebSocket** so
you can exercise your tick-consuming code path outside market hours. The
replay feed uses the same SDK, same callbacks, and the same 19-column tick
schema as the live endpoint — only the WebSocket URL differs
(`replay.truedata.in:8082` instead of `push.truedata.in:<live_port>`).

**Availability window:** ~18:00–02:00 IST daily (i.e. starting ~2.5 hours
after market close and ending before the next session's pre-open). Outside
this window the replay socket rejects connections; the endpoint returns
HTTP 409 (Conflict) with a descriptive message rather than letting the SDK
hang.

**Tick pacing:** replayed ticks are delivered at real-time pace (not
sped-up). The `timestamp` column carries the *original* market timestamp
(e.g. a replay tick arriving at 19:00 IST will have a `timestamp` near
09:30 IST from the morning session).

```bash
# Capture 60 seconds of REPLAYED ticks for NIFTY-I and BANKNIFTY-I.
# Only works between 18:00 and 02:00 IST — otherwise 409.
curl -s -X POST http://localhost:8000/api/v1/market-data/truedata/ticks/replay/export \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
        "symbols":          ["NIFTY-I", "BANKNIFTY-I"],
        "duration_seconds": 60,
        "segment":          "NSE F&O"
      }' \
  -D headers.txt \
  -o truedata_replay_ticks.zip

cat headers.txt            # X-Export-Mode: replay
unzip -l truedata_replay_ticks.zip
```

#### Replay endpoint — additional headers

| Header                    | Value                                                |
|---------------------------|------------------------------------------------------|
| `X-Export-Mode`           | `replay` (always; lets you distinguish from live)    |

All other headers (`X-Export-Files`, `X-Export-Total-Rows`, `X-Export-Capture-Started`, `X-Export-Capture-Ended`, `X-Export-Generated-At`, `X-Export-Truncated`) match the live tick export.

#### Replay endpoint — error codes

| Status | Cause                                                                                       |
|--------|---------------------------------------------------------------------------------------------|
| 401    | Missing/invalid Bearer JWT                                                                  |
| 422    | Schema validation failed (empty symbols, duration out of `[5, 300]`, …)                     |
| 409    | Outside the replay availability window (call the live endpoint during market hours instead) |
| 502    | Replay socket itself unreachable, or 0 ticks captured (rare; usually a config issue)        |

### Future work (Level 2 market depth)

This endpoint captures the **L1 trade tick** (best bid/ask only). If your
team needs 5-level market depth, the TrueData SDK exposes a separate
`@td.bidask_callback` decorator that delivers `bidask_feed` objects with
`bid`/`ask` lists of (price, qty) tuples up to 5 levels deep. Adding a
sibling endpoint (e.g. `POST /api/v1/market-data/truedata/depth/export`)
that captures depth alongside ticks is a straightforward extension of
this service — see `app/services/truedata_tick_service.py` for the
pattern.

---

## Configuration (env vars)

| Variable                              | Default                          | Description                              |
|---------------------------------------|----------------------------------|------------------------------------------|
| `TRUEDATA_USERNAME`                   | `Trial126`                       | TrueData sandbox login                   |
| `TRUEDATA_PASSWORD`                   | `sand126`                        | TrueData sandbox password                |
| `TRUEDATA_LIVE_PORT`                  | `8086`                           | Real-Time + History trial port           |
| `TRUEDATA_URL`                        | `push.truedata.in`               | Live websocket host                      |
| `TRUEDATA_HIST_URL`                   | `https://history.truedata.in`    | Historical REST host                     |
| `TRUEDATA_MAX_ROWS_PER_SYMBOL`        | `60000`                          | Row cap per `.xls` (BIFF8 limit is 65536)|
| `TRUEDATA_REQUEST_TIMEOUT_SEC`        | `60`                             | Per-request network timeout              |
| `TRUEDATA_TICK_MAX_DURATION_SEC`      | `300`                            | Max capture window for tick export       |
| `TRUEDATA_TICK_DEFAULT_DURATION_SEC`  | `60`                             | Default capture window for tick export   |
| `TRUEDATA_TICK_MAX_SYMBOLS`           | `50`                             | Max symbols per tick-export request      |
| `TRUEDATA_TICK_FIRST_TICK_TIMEOUT_SEC`| `30`                             | Wait-for-first-tick timeout (info only)  |
| `TRUEDATA_REPLAY_URL`                 | `replay.truedata.in`             | Replay websocket host (off-hours dev)    |
| `TRUEDATA_REPLAY_PORT`                | `8082`                           | Replay websocket port                    |
| `TRUEDATA_REPLAY_WINDOW_START_HOUR`   | `18`                             | Replay availability window start (IST, 24h) |
| `TRUEDATA_REPLAY_WINDOW_END_HOUR`     | `2`                              | Replay availability window end (IST, 24h; crosses midnight) |

Override any of them via a `.env` file or real env vars in production.

---

## Project structure

```
app/
├── api/
│   ├── deps.py                  # get_current_user (JWT dependency)
│   └── v1/
│       ├── auth.py              # OTP + register + login routes
│       ├── users.py             # /users/me
│       ├── market_data.py       # TrueData historical + tick export endpoints
│       └── router.py            # mounts all v1 routers
├── core/
│   ├── config.py                # Settings (DB, JWT, OTP, TrueData, ticks)
│   └── database.py              # SQLAlchemy session factory
├── models/                      # SQLAlchemy ORM models
├── schemas/
│   ├── market_data.py           # TrueDataExportRequest, TrueDataTickExportRequest
│   ├── otp.py / token.py / user.py
├── services/
│   ├── jwt_service.py           # JWT encode / decode
│   ├── otp_service.py           # OTP generation / verification
│   ├── truedata_service.py      # Historical bars SDK wrapper (`truedata-ws`)
│   ├── truedata_tick_service.py # Live tick SDK wrapper (`truedata`)
│   └── excel_export_service.py  # DataFrame → .xls → ZIP
└── main.py                      # FastAPI app factory
```

---

## Tests

```bash
pytest
```

The suite covers:
- Auth flow (registration, login, JWT issuance)
- Historical OHLCV export (auth, validation, hard-fail, happy path, symbol normalisation)
- Live tick export (auth, validation, hard-fail, happy path, default duration, symbol normalisation)

The TrueData SDK is monkey-patched in tests so they stay hermetic — no live
network calls. To run an end-to-end live test against the trial account,
see `scripts/probe_truedata_ticks.py` (requires market hours).

---

## Trial account limits

The TrueData sandbox (`Trial126` / `sand126`) is capped at:

- 50 symbols (simultaneous)
- Segments: NSE Equity, NSE F&O, Indices, MCX, BSE EQ, BSE F&O, BSE Indices
- Real-Time + History streaming at **tick** time-frame
- Expiry: **24/07/2026**

Live tick streaming is confirmed working in the trial (verified
2026-07-20 — touchline snapshots arrive immediately on subscription for
NIFTY-I, BANKNIFTY-I, SBIN, RELIANCE). Trade ticks only flow during
market hours.

Upgrade to a paid plan to lift these limits.
