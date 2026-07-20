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

### 3. (First run) Seed the database
On first launch, the database is auto-seeded with 5 demo profiles (Nifty, Bank Nifty,
Sensex, FinNifty, Midcap Nifty), a default formula template, notification channels,
and an admin user.

To re-seed manually:
```bash
bun run src/lib/seed.ts
```

### 4. Configure credentials
Real credentials (Telegram bot + icharts portal) are configured via:
```bash
bun run src/lib/setup-credentials.ts
```
This sets up:
- **Telegram bot** (`@quant_options_bot`) → sends reports to the `@quant_opt` group
- **icharts portal** login (encrypted at rest with AES-256-GCM)

You can also manage credentials from the **Administration** tab in the UI.

### 5. Start the scraper mini-service (optional, for real scraping)
The main app uses a high-fidelity mock data generator by default. To use real
icharts scraping via Playwright:
```bash
cd mini-services/scraper-service
bun install
bunx playwright install chromium   # one-time browser install
bun run dev                         # starts on port 3030
```

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
3. Run `bun run src/lib/setup-credentials.ts` (edit the token/chatId first)
4. Or configure via the **Notifications** tab in the UI

### icharts Portal Credentials
- Stored encrypted (AES-256-GCM) in the database
- Configure via `setup-credentials.ts` or the **Administration → Credentials** tab

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
│   ├── scheduler.ts    # Automation pipeline
│   ├── notify.ts       # Telegram/email/webhook dispatcher
│   ├── crypto.ts       # AES-256-GCM encryption
│   ├── export.ts       # CSV/JSON/XLSX/PDF
│   ├── mock-market.ts  # Synthetic option-chain generator
│   └── db.ts           # Prisma client
└── prisma/schema.prisma
mini-services/scraper-service/   # Playwright scraper (port 3030)
```

## License
Private / Internal use.
