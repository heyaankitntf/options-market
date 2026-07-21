/**
 * Reference data for tradable indices — NOT mock data.
 *
 * This file lists the symbols the platform recognises, their strike step,
 * and an approximate base spot used for UI defaults (e.g. selecting an
 * ATM strike when no live spot has been fetched yet). The base spot is
 * NOT used as a fake price source — it is a UI hint only.
 *
 * If you need synthetic option-chain data for testing, see
 * `mock-market.ts` (which is test-only and must never be wired into
 * production code paths).
 */

export interface SymbolSpec {
  symbol: string
  /** UI hint only — NOT a data source. */
  baseSpot: number
  strikeStep: number
  strikesEitherSide: number
  label: string
}

export const SYMBOL_SPECS: SymbolSpec[] = [
  { symbol: 'NIFTY', baseSpot: 24850, strikeStep: 50, strikesEitherSide: 18, label: 'Nifty 50' },
  { symbol: 'BANKNIFTY', baseSpot: 54200, strikeStep: 100, strikesEitherSide: 18, label: 'Bank Nifty' },
  { symbol: 'SENSEX', baseSpot: 81300, strikeStep: 100, strikesEitherSide: 16, label: 'BSE Sensex' },
  { symbol: 'FINNIFTY', baseSpot: 23400, strikeStep: 50, strikesEitherSide: 16, label: 'Fin Nifty' },
  { symbol: 'MIDCPNIFTY', baseSpot: 12650, strikeStep: 25, strikesEitherSide: 16, label: 'Midcap Nifty' },
]

export function getSpec(symbol: string): SymbolSpec {
  return SYMBOL_SPECS.find((s) => s.symbol === symbol) ?? SYMBOL_SPECS[0]
}

/** Compute the next weekly expiry (Thursday) for the symbol. */
export function defaultExpiry(symbol: string): string {
  const now = new Date()
  const day = now.getDay()
  // Weekly expiry Thursday for NIFTY/BANKNIFTY; Sensex Tuesday
  const target = symbol === 'SENSEX' ? 2 : 4
  let diff = (target - day + 7) % 7
  if (diff === 0) {
    // today is expiry — if past 3:30pm, move to next week
    if (now.getHours() >= 16) diff = 7
  }
  const d = new Date(now.getTime() + diff * 86400000)
  return d.toISOString().slice(0, 10)
}

/** List upcoming expiries for a symbol. */
export function upcomingExpiries(symbol: string, count = 6): { date: string; kind: string }[] {
  const out: { date: string; kind: string }[] = []
  const now = new Date()
  const target = symbol === 'SENSEX' ? 2 : 4
  let day = now.getDay()
  let diff = (target - day + 7) % 7
  if (diff === 0 && now.getHours() >= 16) diff = 7
  for (let i = 0; i < count; i++) {
    const d = new Date(now.getTime() + (diff + i * 7) * 86400000)
    out.push({ date: d.toISOString().slice(0, 10), kind: i === 0 ? 'weekly' : i === count - 1 ? 'monthly' : 'weekly' })
  }
  return out
}
