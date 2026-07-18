# OTP-Based Authentication System

A FastAPI-based OTP authentication system for mobile-first applications.

## Features

- User registration with phone number
- OTP generation and verification (6 digits, 5 min expiry)
- Separate country code and phone number fields
- Login via phone + OTP (no password)
- JWT token-based authentication
- Protected routes
- Health check endpoint

## Tech Stack

- **FastAPI** - Web framework
- **SQLAlchemy** - ORM
- **SQLite** - Database
- **python-jose** - JWT tokens
- **pydantic** - Data validation

## Setup

### Install & Run (one command)

A `run.sh` helper is included — it creates a virtualenv, installs dependencies,
and launches the server with auto-reload:

```bash
cd fastapi-auth
bash run.sh
```

> Default port is `8000`. Override with `PORT=8080 bash run.sh`.

### Manual setup

```bash
cd fastapi-auth
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API runs on `http://localhost:8000`
API docs: `http://localhost:8000/docs` (Swagger) · `/redoc`

### Reset Database (optional)

If you want a fresh database:
```bash
rm data/app.db
uvicorn app.main:app --reload
```

### Using Docker

```bash
docker build -t fastapi-auth .
docker run -p 8000:8000 --env-file .env fastapi-auth
```

### Run tests

```bash
source .venv/bin/activate
pytest -v
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/auth/request-otp` | POST | Request OTP for registration |
| `/api/v1/auth/register` | POST | Verify OTP + create user |
| `/api/v1/auth/request-login-otp` | POST | Request OTP for login |
| `/api/v1/auth/login` | POST | Verify OTP + return JWT |
| `/api/v1/users/me` | GET | Get current user (protected) |
| `/api/v1/auth/dev-otp` | GET | **Dev only** — returns the latest OTP for a phone (OTP is mock, not sent via SMS) |
| `/health` | GET | Health check |

## Usage Example

### Registration (New User)

**1. Request OTP for registration**
```bash
curl -X POST http://localhost:8000/api/v1/auth/request-otp \
  -H "Content-Type: application/json" \
  -d '{"country_code": "+91", "phone": "9876543210"}'
```

**2. Get OTP from database**
```bash
sqlite3 "data/app.db" "SELECT code FROM otp WHERE phone='9876543210' ORDER BY created_at DESC LIMIT 1;"
```

**3. Register**
```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"country_code": "+91", "phone": "9876543210", "code": "YOUR_OTP", "name": "John Doe", "email": "john@example.com"}'
```

### Login (Returning User)

**1. Request Login OTP**
```bash
curl -X POST http://localhost:8000/api/v1/auth/request-login-otp \
  -H "Content-Type: application/json" \
  -d '{"country_code": "+91", "phone": "9876543210"}'
```

**2. Get OTP from database**
```bash
sqlite3 "data/app.db" "SELECT code FROM otp WHERE phone='9876543210' ORDER BY created_at DESC LIMIT 1;"
```

**3. Login**
```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"country_code": "+91", "phone": "9876543210", "code": "YOUR_OTP"}'
```

### Get Current User

```bash
curl -X GET http://localhost:8000/api/v1/users/me \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

## Project Structure

```
.
├── app/
│   ├── main.py              # FastAPI app factory (CORS, lifespan, routers)
│   ├── core/
│   │   ├── config.py         # pydantic-settings (env-driven)
│   │   └── database.py       # engine, session, init_db
│   ├── api/
│   │   ├── deps.py           # shared deps: get_db, get_current_user
│   │   └── v1/
│   │       ├── router.py     # aggregates v1 routers under /api/v1
│   │       ├── auth.py       # /auth/* routes (APIRouter)
│   │       └── users.py      # /users/* routes (APIRouter)
│   ├── models/               # one model per file
│   │   ├── user.py
│   │   └── otp.py
│   ├── schemas/              # one domain per file
│   │   ├── user.py
│   │   ├── otp.py
│   │   └── token.py
│   └── services/             # business logic
│       ├── jwt_service.py
│       └── otp_service.py
├── tests/                    # pytest + httpx (in-memory SQLite per test)
├── data/                     # SQLite database (auto-created)
├── .env.example              # env var template
├── Dockerfile
├── pytest.ini
├── requirements.txt
└── run.sh                    # one-command launcher
```

This structure mirrors widely-used FastAPI best practices
(`APIRouter`-based routing, app factory, split models/schemas, reusable
dependencies) so it scales cleanly as you add more endpoints or more
microservices.

## Notes

- OTP is mock (generated and stored, not sent via SMS) — use the `/api/v1/auth/dev-otp` endpoint to fetch it during development. Wire a real SMS provider in `app/services/otp_service.py` to go live.
- OTP expires after 5 minutes; JWT expires after 30 minutes (configurable via env).
- SQLite database at `./data/app.db`; swap `AUTH_DATABASE_URL` for Postgres/MySQL in production.
- Country code and phone number are stored as separate fields.
- All configuration is env-driven — see `.env.example`.