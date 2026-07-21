/**
 * ============================================================================
 * ⚠️  TEST DATA ONLY — DO NOT USE IN PRODUCTION CODE PATHS  ⚠️
 * ============================================================================
 *
 * This module generates SYNTHETIC option-chain snapshots for testing,
 * local development, and demos. The data produced here is RANDOM — it
 * does not represent any real market and has zero predictive value.
 *
 * HARD RULES:
 *   1. Never import this module from production code paths (scheduler,
 *      API routes that write to RawSnapshot/Report, the scraper-service,
 *      etc.). Importing from a production path will cause random data
 *      to be written to the database indistinguishable from real market
 *      data. Use the live data source instead (e.g. the Python TrueData
 *      backend or the scraper-service).
 *   2. The only allowed callers are:
 *        - Unit tests (under tests/ or *.test.ts)
 *        - Storybook / component-preview fixtures
 *        - Explicit developer-only CLI scripts guarded by NODE_ENV
 *   3. Snapshots produced here MUST be tagged `source: 'mock'` when
 *      written to the database, so they can be distinguished from real
 *      data after the fact.
 *
 * Reference data (strike steps, label, base spot for UI hints) lives in
 * `symbols.ts`. Import from there instead of here when you only need
 * the symbol metadata.
 * ============================================================================
 */

import type { OptionChainRow } from './analytics'
import { SYMBOL_SPECS, getSpec, defaultExpiry } from './symbols'

// Re-export for backwards compatibility with existing test imports.
// New code should import directly from './symbols'.
export { SYMBOL_SPECS, getSpec, defaultExpiry }
export type { SymbolSpec } from './symbols'

let spotDrift: Record<string, number> = {}
SYMBOL_SPECS.forEach((s) => (spotDrift[s.symbol] = s.baseSpot))

/** Advance the synthetic spot with a random walk. TEST DATA ONLY. */
export function nextSpot(symbol: string): number {
  const spec = getSpec(symbol)
  const cur = spotDrift[symbol] ?? spec.baseSpot
  const vol = spec.strikeStep / 4
  const step = (Math.random() - 0.48) * vol
  const next = Math.max(spec.baseSpot * 0.9, Math.min(spec.baseSpot * 1.1, cur + step))
  spotDrift[symbol] = next
  return Math.round(next)
}

/** Reset spot drift (used by tests / admin). TEST DATA ONLY. */
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
  /** Always 'mock' — call sites MUST propagate this to the DB source column. */
  source: 'mock'
}

/** Generate a synthetic option-chain snapshot. TEST DATA ONLY. */
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
    source: 'mock',
  }
}

/** List upcoming expiries for a symbol. Re-exported from symbols.ts. */
export { upcomingExpiries } from './symbols'
