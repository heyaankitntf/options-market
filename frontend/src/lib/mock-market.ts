/**
 * Mock option-chain generator.
 *
 * Produces realistic, internally-consistent option chain snapshots around a
 * live-ish spot price for NIFTY / BANKNIFTY / SENSEX / FINNIFTY. Used as the
 * default data source when the icharts portal is unreachable or credentials
 * are absent, so the entire pipeline can be exercised end-to-end.
 *
 * Each call jitters the values so successive snapshots look like a moving
 * market — essential for trend & comparison features.
 */

import type { OptionChainRow } from './analytics'

export interface SymbolSpec {
  symbol: string
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

let spotDrift: Record<string, number> = {}
SYMBOL_SPECS.forEach((s) => (spotDrift[s.symbol] = s.baseSpot))

/** Advance the synthetic spot with a random walk. */
export function nextSpot(symbol: string): number {
  const spec = getSpec(symbol)
  const cur = spotDrift[symbol] ?? spec.baseSpot
  const vol = spec.strikeStep / 4
  const step = (Math.random() - 0.48) * vol
  const next = Math.max(spec.baseSpot * 0.9, Math.min(spec.baseSpot * 1.1, cur + step))
  spotDrift[symbol] = next
  return Math.round(next)
}

/** Reset spot drift (used by tests / admin). */
export function resetSpot(symbol?: string) {
  if (symbol) {
    spotDrift[symbol] = getSpec(symbol).baseSpot
  } else {
    SYMBOL_SPECS.forEach((s) => (spotDrift[s.symbol] = s.baseSpot))
  }
}

function gauss(): number {
  // Box-Muller
  let u = 0
  let v = 0
  while (u === 0) u = Math.random()
  while (v === 0) v = Math.random()
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v)
}

export interface GeneratedSnapshot {
  symbol: string
  spotPrice: number
  expiry: string
  rows: OptionChainRow[]
}

export function generateOptionChain(symbol: string, expiry?: string): GeneratedSnapshot {
  const spec = getSpec(symbol)
  const spot = nextSpot(symbol)
  const atm = Math.round(spot / spec.strikeStep) * spec.strikeStep

  const rows: OptionChainRow[] = []
  for (let i = -spec.strikesEitherSide; i <= spec.strikesEitherSide; i++) {
    const strike = atm + i * spec.strikeStep
    const dist = Math.abs(i)
    // OI peaks near ATM and decays outward; calls/puts skewed by trend bias
    const trendBias = (Math.sin(Date.now() / 600000) + 1) / 2 // 0..1 slow oscillation
    const baseOi = Math.max(5000, 120000 * Math.exp(-dist / 6) * (0.6 + Math.random() * 0.8))

    // Put OI stronger below, call OI stronger above (typical structure)
    const callOiFactor = i < 0 ? 0.7 : 1.15
    const putOiFactor = i > 0 ? 0.7 : 1.15
    const ceOi = Math.round(baseOi * callOiFactor * (0.8 + trendBias * 0.4))
    const peOi = Math.round(baseOi * putOiFactor * (0.8 + (1 - trendBias) * 0.4))

    // IV smile — higher away from ATM
    const smile = 10 + Math.abs(i) * 0.6
    const ceIv = Math.max(6, Math.round((smile + gauss() * 1.2) * 10) / 10)
    const peIv = Math.max(6, Math.round((smile + 1.5 + gauss() * 1.2) * 10) / 10)

    // LTP — intrinsic + time value
    const intrinsicCe = Math.max(0, spot - strike)
    const intrinsicPe = Math.max(0, strike - spot)
    const ceLtp = Math.max(0.5, Math.round((intrinsicCe + ceIv * spec.strikeStep * 0.04) * 100) / 100)
    const peLtp = Math.max(0.5, Math.round((intrinsicPe + peIv * spec.strikeStep * 0.04) * 100) / 100)

    // Volume proportional to OI with randomness
    const ceVolume = Math.round(ceOi * (0.05 + Math.random() * 0.4))
    const peVolume = Math.round(peOi * (0.05 + Math.random() * 0.4))

    // Change in OI — buildup/unwinding
    const ceChgOi = Math.round((Math.random() - 0.5) * ceOi * 0.25)
    const peChgOi = Math.round((Math.random() - 0.5) * peOi * 0.25)

    rows.push({
      strike,
      ceLtp,
      ceOi,
      ceChgOi,
      ceVolume,
      ceIv,
      peLtp,
      peOi,
      peChgOi,
      peVolume,
      peIv,
    })
  }

  return {
    symbol,
    spotPrice: spot,
    expiry: expiry ?? defaultExpiry(symbol),
    rows,
  }
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
