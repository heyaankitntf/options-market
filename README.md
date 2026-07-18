# OptionFlow — OTP Auth + TrueData Market Data Export

FastAPI microservice that combines:

1. **OTP-based phone authentication** (registration, login, JWT issuance)
2. **TrueData market-data export** — fetch historical bars/ticks for any list
   of symbols and download them as a ZIP of legacy `.xls` files

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

## TrueData market-data export

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

### Configuration (env vars)

| Variable                              | Default                          | Description                              |
|---------------------------------------|----------------------------------|------------------------------------------|
| `TRUEDATA_USERNAME`                   | `Trial126`                       | TrueData sandbox login                   |
| `TRUEDATA_PASSWORD`                   | `sand126`                        | TrueData sandbox password                |
| `TRUEDATA_LIVE_PORT`                  | `8086`                           | Real-Time + History trial port           |
| `TRUEDATA_URL`                        | `push.truedata.in`               | Live websocket host                      |
| `TRUEDATA_HIST_URL`                   | `https://history.truedata.in`    | Historical REST host                     |
| `TRUEDATA_MAX_ROWS_PER_SYMBOL`        | `60000`                          | Row cap per `.xls` (BIFF8 limit is 65536)|
| `TRUEDATA_REQUEST_TIMEOUT_SEC`        | `60`                             | Per-request network timeout              |

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
│       ├── market_data.py       # TrueData export endpoint  ← NEW
│       └── router.py            # mounts all v1 routers
├── core/
│   ├── config.py                # Settings (DB, JWT, OTP, TrueData)
│   └── database.py              # SQLAlchemy session factory
├── models/                      # SQLAlchemy ORM models
├── schemas/
│   ├── market_data.py           # TrueDataExportRequest  ← NEW
│   ├── otp.py / token.py / user.py
├── services/
│   ├── jwt_service.py           # JWT encode / decode
│   ├── otp_service.py           # OTP generation / verification
│   ├── truedata_service.py      # TrueData SDK wrapper  ← NEW
│   └── excel_export_service.py  # DataFrame → .xls → ZIP ← NEW
└── main.py                      # FastAPI app factory
```

---

## Tests

```bash
pytest
```

---

## Trial account limits

The TrueData sandbox (`Trial126` / `sand126`) is capped at:

- 50 symbols (simultaneous)
- Segments: NSE Equity, NSE F&O, Indices, MCX, BSE EQ, BSE F&O, BSE Indices
- Real-Time + History streaming at **tick** time-frame
- Expiry: **24/07/2026**

Upgrade to a paid plan to lift these limits.
