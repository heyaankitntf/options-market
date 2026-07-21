# OptFlow — Options Market Data Automation Platform

Automated options-chain collection, processing, and analytics platform that scrapes
[icharts.in](https://www.icharts.in/opt/index.php), replicates Excel-based calculations
in a TypeScript analytics engine, and serves a real-time monitoring dashboard.

## Run Locally

### Prerequisites
- [Node.js](https://nodejs.org/) 18+ or [Bun](https://bun.sh/) (recommended)
- The project ships with SQLite — no external database needed.

### 1. Install dependencies
```bash
bun install
# or: npm install
```

### 2. Start the dev server
```bash
bun run dev
# or: npm run dev
```
The app starts on **http://localhost:3000**. Open it in your browser.

### 3. (First run) Database setup
The app no longer auto-seeds demo data — that would have written `admin@optflow.io` /
`admin123` and demo icharts credentials into your deployment, which is unsafe and
makes it impossible to tell real data from test data.

Instead, on first launch:
1. Open the **Administration → Users** tab and create a real admin user with a
   strong password.
2. Open **Administration → Credentials** and add your real icharts portal login
   (stored encrypted with AES-256-GCM).
3. Open **Profiles** and create the automation profiles you actually need.
4. (Optional) Open **Administration → Formula Templates** to tune the analytics
   thresholds.

### 4. Configure credentials
Real credentials (Telegram bot + icharts portal) are managed via the
**Administration** tab in the UI — never hardcoded in the repo. Hardcoded
secrets (e.g. the old `setup-credentials.ts` script with a plaintext Telegram
bot token) have been removed; rotate any credentials that may have been
committed historically.

### 5. Start the scraper mini-service (for real icharts scraping)
The scheduler refuses to run without a real data source — it will NOT silently
fall back to mock data. To enable real icharts scraping via Playwright:
```bash
cd mini-services/scraper-service
bun install
bunx playwright install chromium   # one-time browser install
bun run dev                         # starts on port 3030
```
If Playwright is not installed, `/scrape` returns HTTP 503 with a clear error
message rather than serving synthetic data.

The in-process scheduler (`src/lib/scheduler.ts`) also exposes a single
`captureLiveOptionChain()` function that must be wired to your real data source
(TrueData backend, scraper-service, etc.). Until this is wired, profile runs
fail with a clear error instead of producing fake data.

## Features

### 8 Dashboard Views
1. **Dashboard** — live status, execution timeline, system health, latest reports
2. **Deep Analytics** — per-symbol historical trends (Spot vs Max Pain, PCR Evolution, OI Buildup, IV Outlook, Trend Distribution)
3. **Reports** — historical reports with option-chain detail + CSV/JSON/XLSX/PDF export
4. **Executions** — pipeline run history with stage progress + rerun
5. **Profiles** — automation profile management (create/edit/pause/run)
6. **Processing Logs** — live log streaming with level/source filters
7. **Notifications** — Telegram/email/WhatsApp/webhook channels + delivery history
8. **Administration** — credentials, formula templates, users/RBAC, system settings

### Automation
- Configurable refresh intervals (5/10/15 min per profile)
- 5-stage pipeline: login → navigate → select expiry → export → process → notify
- Rule-based analytics: PCR, Max Pain, ATM IV, support/resistance, trend scoring
- Historical archival of all reports + raw snapshots

### Notifications
- **Telegram** (fully functional) — HTML-formatted reports with trend emojis
- Email / WhatsApp / Webhook (stubbed — add your SMTP/WhatsApp API keys)

### Exports
- CSV, JSON, XLSX (Excel), printable PDF

## Tech Stack
- **Framework**: Next.js 16 (App Router) + TypeScript 5
- **Styling**: Tailwind CSS 4 + shadcn/ui (New York style)
- **Database**: Prisma ORM + SQLite
- **Charts**: Recharts
- **State**: TanStack Query (server) + React state (client)
- **Automation**: In-process scheduler (replaceable with Celery/BullMQ)
- **Scraping**: Playwright (mini-service on port 3030)

## Configuration

### Telegram Bot Setup
1. Create a bot via [@BotFather](https://t.me/BotFather) → get the API token
2. Add the bot to your Telegram group as an admin (so it can send messages)
3. Configure the bot token + chat ID via the **Notifications** tab in the UI
   (stored encrypted in the database; never committed to the repo)

### icharts Portal Credentials
- Stored encrypted (AES-256-GCM) in the database
- Configure via the **Administration → Credentials** tab in the UI

### System Settings
Editable via **Administration → System Settings**:
- Scheduler interval, market hours (09:15–15:30 IST)
- Portal URL + timeout, retry policy, storage retention

## Scripts
```bash
bun run dev          # Start dev server (port 3000)
bun run lint         # ESLint check
bun run db:push      # Push Prisma schema to SQLite
bun run db:generate  # Regenerate Prisma client
bun run db:reset     # Reset database (destructive)
```

## Project Structure
```
src/
├── app/
│   ├── api/            # 26 REST API routes
│   ├── page.tsx        # Single-page dashboard (8 views)
│   └── layout.tsx
├── components/
│   ├── ui/             # shadcn/ui primitives
│   └── views/          # Dashboard, Analytics, Reports, etc.
├── lib/
│   ├── analytics.ts    # PCR, Max Pain, IV, trend engine
│   ├── scheduler.ts    # Automation pipeline (live data only — no mock fallback)
│   ├── notify.ts       # Telegram/email/webhook dispatcher
│   ├── crypto.ts       # AES-256-GCM encryption
│   ├── export.ts       # CSV/JSON/XLSX/PDF
│   ├── symbols.ts      # Reference data: tradable indices, strike steps, expiry calc
│   ├── mock-market.ts  # TEST ONLY — synthetic option-chain generator (not wired to prod)
│   └── db.ts           # Prisma client
└── prisma/schema.prisma
mini-services/scraper-service/   # Playwright scraper (port 3030)
```

## License
Private / Internal use.
