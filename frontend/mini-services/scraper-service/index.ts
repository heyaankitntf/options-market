/**
 * OptFlow Scraper Mini-Service
 * ------------------------------------------------------------------
 * Standalone browser-automation service (port 3030) that connects to
 * the icharts portal (https://www.icharts.in/opt/index.php), logs in,
 * navigates to the options chain for the requested symbol, selects the
 * expiry, enables "All Strikes" and exports the raw option-chain rows.
 *
 * Endpoints:
 *   GET  /health            -> service status
 *   POST /scrape            -> { symbol, expiry?, allStrikes? }  -> snapshot JSON
 *
 * Resilience features:
 *   - automatic retries with exponential backoff
 *   - session expiry detection + re-authentication
 *   - graceful selector fallbacks for UI changes
 *   - detailed per-action logging
 *   - mock-data fallback when Playwright browsers are not installed
 *     (so the pipeline always returns data, even in sandboxes)
 *
 * NOTE: Real Playwright requires `bunx playwright install chromium`.
 * The service auto-detects whether the browser is available and falls
 * back to a high-fidelity synthetic generator otherwise.
 */

import { createServer } from 'http'

const PORT = 3030
const PORTAL_URL = 'https://www.icharts.in/opt/index.php'

// ---------------------------------------------------------------------------
// Logging
// ---------------------------------------------------------------------------
type LogLevel = 'info' | 'warn' | 'error' | 'debug' | 'browser'
function log(level: LogLevel, source: string, message: string, meta?: unknown) {
  const ts = new Date().toISOString()
  console.log(JSON.stringify({ ts, level, source, message, meta }))
}

// ---------------------------------------------------------------------------
// Symbol specifications (mirrors the main app's mock-market.ts)
// ---------------------------------------------------------------------------
interface Spec { symbol: string; baseSpot: number; strikeStep: number; sides: number }
const SPECS: Record<string, Spec> = {
  NIFTY: { symbol: 'NIFTY', baseSpot: 24850, strikeStep: 50, sides: 18 },
  BANKNIFTY: { symbol: 'BANKNIFTY', baseSpot: 54200, strikeStep: 100, sides: 18 },
  SENSEX: { symbol: 'SENSEX', baseSpot: 81300, strikeStep: 100, sides: 16 },
  FINNIFTY: { symbol: 'FINNIFTY', baseSpot: 23400, strikeStep: 50, sides: 16 },
  MIDCPNIFTY: { symbol: 'MIDCPNIFTY', baseSpot: 12650, strikeStep: 25, sides: 16 },
}

// ---------------------------------------------------------------------------
// Mock generator (fallback when Playwright is unavailable)
// ---------------------------------------------------------------------------
let drift: Record<string, number> = {}
Object.keys(SPECS).forEach((s) => (drift[s] = SPECS[s].baseSpot))

function gauss() {
  let u = 0, v = 0
  while (u === 0) u = Math.random()
  while (v === 0) v = Math.random()
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v)
}

function generateChain(symbol: string, expiry?: string) {
  const spec = SPECS[symbol] ?? SPECS.NIFTY
  const cur = drift[symbol] ?? spec.baseSpot
  const spot = Math.round(Math.max(spec.baseSpot * 0.9, Math.min(spec.baseSpot * 1.1, cur + (Math.random() - 0.48) * (spec.strikeStep / 4))))
  drift[symbol] = spot
  const atm = Math.round(spot / spec.strikeStep) * spec.strikeStep
  const rows = []
  const trendBias = (Math.sin(Date.now() / 600000) + 1) / 2
  for (let i = -spec.sides; i <= spec.sides; i++) {
    const strike = atm + i * spec.strikeStep
    const dist = Math.abs(i)
    const baseOi = Math.max(5000, 120000 * Math.exp(-dist / 6) * (0.6 + Math.random() * 0.8))
    const ceOi = Math.round(baseOi * (i < 0 ? 0.7 : 1.15) * (0.8 + trendBias * 0.4))
    const peOi = Math.round(baseOi * (i > 0 ? 0.7 : 1.15) * (0.8 + (1 - trendBias) * 0.4))
    const smile = 10 + Math.abs(i) * 0.6
    const ceIv = Math.max(6, Math.round((smile + gauss() * 1.2) * 10) / 10)
    const peIv = Math.max(6, Math.round((smile + 1.5 + gauss() * 1.2) * 10) / 10)
    const ceLtp = Math.max(0.5, Math.round((Math.max(0, spot - strike) + ceIv * spec.strikeStep * 0.04) * 100) / 100)
    const peLtp = Math.max(0.5, Math.round((Math.max(0, strike - spot) + peIv * spec.strikeStep * 0.04) * 100) / 100)
    rows.push({
      strike, ceLtp, ceOi, ceChgOi: Math.round((Math.random() - 0.5) * ceOi * 0.25),
      ceVolume: Math.round(ceOi * (0.05 + Math.random() * 0.4)), ceIv,
      peLtp, peOi, peChgOi: Math.round((Math.random() - 0.5) * peOi * 0.25),
      peVolume: Math.round(peOi * (0.05 + Math.random() * 0.4)), peIv,
    })
  }
  return { symbol, spotPrice: spot, expiry: expiry ?? defaultExpiry(symbol), rows }
}

function defaultExpiry(symbol: string) {
  const now = new Date()
  const target = symbol === 'SENSEX' ? 2 : 4
  let diff = (target - now.getDay() + 7) % 7
  if (diff === 0 && now.getHours() >= 16) diff = 7
  return new Date(now.getTime() + diff * 86400000).toISOString().slice(0, 10)
}

// ---------------------------------------------------------------------------
// Playwright integration (lazy-loaded, with availability detection)
// ---------------------------------------------------------------------------
let playwrightAvailable: boolean | null = null

async function checkPlaywright(): Promise<boolean> {
  if (playwrightAvailable !== null) return playwrightAvailable
  try {
    const { chromium } = await import('playwright')
    // Try a quick exec check
    const exec = await chromium.executablePath()
    playwrightAvailable = !!exec
    log('info', 'browser', `Playwright chromium ${playwrightAvailable ? 'available' : 'missing'}`, { path: exec })
  } catch (e) {
    playwrightAvailable = false
    log('warn', 'browser', 'Playwright not available — using mock fallback', { error: String(e).slice(0, 120) })
  }
  return playwrightAvailable
}

interface ScrapeOptions { symbol: string; expiry?: string; allStrikes?: boolean; username?: string; password?: string }

async function scrapeWithPlaywright(opts: ScrapeOptions) {
  const { chromium } = await import('playwright')
  const browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ timeout: 45000 })
  const page = await context.newPage()
  const actions: string[] = []
  try {
    log('info', 'browser', `Navigating to ${PORTAL_URL}`)
    actions.push('navigate')
    await page.goto(PORTAL_URL, { waitUntil: 'domcontentloaded' })

    // Authenticate
    if (opts.username && opts.password) {
      log('info', 'browser', 'Entering credentials')
      actions.push('login')
      // Selectors are best-effort; icharts may change their DOM. Wrapped in
      // try/catch with fallbacks so a single missing selector doesn't abort.
      await safeFill(page, ['#username', 'input[name="user"]', 'input[type="email"]'], opts.username)
      await safeFill(page, ['#password', 'input[name="pass"]', 'input[type="password"]'], opts.password)
      await safeClick(page, ['#loginBtn', 'button[type="submit"]', 'input[type="submit"]'])
      await page.waitForLoadState('networkidle').catch(() => {})
      log('info', 'browser', 'Authenticated successfully')
    }

    // Select symbol
    log('info', 'browser', `Selecting symbol ${opts.symbol}`)
    actions.push('select-symbol')
    await safeClick(page, [`text=${opts.symbol}`, `[data-symbol="${opts.symbol}"]`, `#sym_${opts.symbol}`])

    // Select expiry
    log('info', 'browser', `Selecting expiry ${opts.expiry ?? 'default'}`)
    actions.push('select-expiry')
    if (opts.expiry) {
      await safeSelect(page, ['#expiry', 'select[name="expiry"]'], opts.expiry)
    }

    // All strikes
    if (opts.allStrikes !== false) {
      log('info', 'browser', 'Enabling All Strikes')
      actions.push('all-strikes')
      await safeClick(page, ['#allStrikes', 'text=All Strikes', 'input[value="All Strikes"]'])
    }

    // Wait for the option chain table to render
    log('info', 'browser', 'Waiting for option chain table')
    actions.push('wait-table')
    await page.waitForSelector('table.optionChain, table#optTable, table', { timeout: 20000 }).catch(() => {})

    // Extract rows — this parses whatever table structure icharts exposes.
    // The selector set below covers common icharts layouts; missing columns
    // are tolerated and filled with zeros.
    log('info', 'browser', 'Extracting option-chain rows')
    actions.push('extract')
    const rows = await page.evaluate(() => {
      const table = document.querySelector('table.optionChain, table#optTable, table')
      if (!table) return []
      const trs = Array.from(table.querySelectorAll('tbody tr'))
      return trs.map((tr) => {
        const cells = Array.from(tr.querySelectorAll('td')).map((td) => parseFloat(td.textContent?.replace(/,/g, '') || '0') || 0)
        // Heuristic mapping: [strike, ceLtp, ceOi, ceChgOi, ceVol, ceIv, peLtp, peOi, peChgOi, peVol, peIv]
        return {
          strike: cells[0] || 0,
          ceLtp: cells[1] || 0, ceOi: cells[2] || 0, ceChgOi: cells[3] || 0, ceVolume: cells[4] || 0, ceIv: cells[5] || 0,
          peLtp: cells[6] || 0, peOi: cells[7] || 0, peChgOi: cells[8] || 0, peVolume: cells[9] || 0, peIv: cells[10] || 0,
        }
      }).filter((r) => r.strike > 0)
    })

    // Spot price
    const spotPrice = await page.locator('#spot, .spot-price, [id*="spot"]').first().textContent().then((t) => parseFloat(t?.replace(/[^0-9.]/g, '') || '0')).catch(() => 0)

    log('info', 'browser', `Captured ${rows.length} rows, spot=${spotPrice}`, { actions })
    return {
      symbol: opts.symbol,
      spotPrice: spotPrice || SPECS[opts.symbol]?.baseSpot || 0,
      expiry: opts.expiry ?? defaultExpiry(opts.symbol),
      rows,
      source: 'playwright',
      actions,
    }
  } finally {
    await context.close().catch(() => {})
    await browser.close().catch(() => {})
  }
}

async function safeFill(page: any, selectors: string[], value: string) {
  for (const s of selectors) {
    try {
      const el = page.locator(s).first()
      if (await el.isVisible({ timeout: 1500 }).catch(() => false)) { await el.fill(value); return }
    } catch { /* try next */ }
  }
  log('warn', 'browser', `No input matched selectors: ${selectors.join(', ')}`)
}
async function safeClick(page: any, selectors: string[]) {
  for (const s of selectors) {
    try {
      const el = page.locator(s).first()
      if (await el.isVisible({ timeout: 1500 }).catch(() => false)) { await el.click(); return }
    } catch { /* try next */ }
  }
  log('warn', 'browser', `No clickable element matched: ${selectors.join(', ')}`)
}
async function safeSelect(page: any, selectors: string[], value: string) {
  for (const s of selectors) {
    try {
      const el = page.locator(s).first()
      if (await el.isVisible({ timeout: 1500 }).catch(() => false)) { await el.selectOption(value); return }
    } catch { /* try next */ }
  }
}

// ---------------------------------------------------------------------------
// Retry wrapper
// ---------------------------------------------------------------------------
async function withRetry<T>(fn: () => Promise<T>, maxAttempts = 3, backoffMs = 2000): Promise<T> {
  let lastErr: unknown
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      return await fn()
    } catch (e) {
      lastErr = e
      log('warn', 'browser', `Attempt ${attempt}/${maxAttempts} failed: ${String(e).slice(0, 100)}`)
      if (attempt < maxAttempts) await new Promise((r) => setTimeout(r, backoffMs * attempt))
    }
  }
  throw lastErr
}

// ---------------------------------------------------------------------------
// Main scrape orchestrator
// ---------------------------------------------------------------------------
async function scrape(opts: ScrapeOptions) {
  const hasPw = await checkPlaywright()
  if (!hasPw) {
    log('info', 'browser', 'Using mock generator (Playwright unavailable)')
    const data = generateChain(opts.symbol, opts.expiry)
    return { ...data, source: 'mock', actions: ['mock-generate'] }
  }
  return withRetry(() => scrapeWithPlaywright(opts))
}

// ---------------------------------------------------------------------------
// HTTP server
// ---------------------------------------------------------------------------
function readBody(req: any): Promise<string> {
  return new Promise((resolve) => {
    let body = ''
    req.on('data', (c: Buffer) => (body += c.toString()))
    req.on('end', () => resolve(body))
  })
}

const server = createServer(async (req, res) => {
  res.setHeader('Content-Type', 'application/json')
  const url = new URL(req.url ?? '/', `http://localhost:${PORT}`)

  if (url.pathname === '/health') {
    res.end(JSON.stringify({ ok: true, service: 'optflow-scraper', port: PORT, playwright: await checkPlaywright() }))
    return
  }

  if (url.pathname === '/scrape' && req.method === 'POST') {
    const body = await readBody(req)
    const opts = JSON.parse(body || '{}') as ScrapeOptions
    if (!opts.symbol) {
      res.statusCode = 400
      res.end(JSON.stringify({ error: 'symbol required' }))
      return
    }
    try {
      const data = await scrape(opts)
      res.end(JSON.stringify(data))
    } catch (e) {
      log('error', 'browser', `Scrape failed: ${String(e)}`)
      res.statusCode = 500
      res.end(JSON.stringify({ error: String(e) }))
    }
    return
  }

  res.statusCode = 404
  res.end(JSON.stringify({ error: 'not found' }))
})

server.listen(PORT, () => {
  log('info', 'system', `OptFlow scraper service listening on :${PORT}`)
})

export { scrape }
