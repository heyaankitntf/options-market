/**
 * Analytics Engine — replicates the Excel-based option chain calculations in TypeScript.
 *
 * Input  : raw option chain rows (strikes with CE/PE OI, volume, IV, LTP, chgOI ...)
 * Output : computed indicators + structured report sections.
 *
 * All thresholds / weights are driven by a FormulaTemplate config so logic can
 * change without touching code.
 */

export interface OptionChainRow {
  strike: number
  ceLtp: number
  ceOi: number
  ceChgOi: number
  ceVolume: number
  ceIv: number
  peLtp: number
  peOi: number
  peChgOi: number
  peVolume: number
  peIv: number
}

export interface FormulaConfig {
  atmRange: number            // strikes either side of spot considered ATM
  pcrBullThreshold: number    // pcr above => bullish
  pcrBearThreshold: number    // pcr below => bearish
  trendWeights: {
    pcr: number
    oiShift: number
    ivSkew: number
    chgOi: number
  }
  supportResistanceLookback: number // strikes around max OI walls
}

export const DEFAULT_FORMULA: FormulaConfig = {
  atmRange: 2,
  pcrBullThreshold: 1.1,
  pcrBearThreshold: 0.9,
  trendWeights: { pcr: 40, oiShift: 25, ivSkew: 15, chgOi: 20 },
  supportResistanceLookback: 5,
}

export interface ComputedIndicators {
  spotPrice: number
  atmStrike: number
  pcr: number
  pcrVolume: number
  maxPain: number
  ivCall: number
  ivPut: number
  ivSkew: number
  totalCallOi: number
  totalPutOi: number
  totalCallVol: number
  totalPutVol: number
  callChgOi: number
  putChgOi: number
  support: number
  resistance: number
  trend: 'bullish' | 'bearish' | 'neutral'
  trendScore: number
  oiShift: number          // net OI shift indicator
  painDistance: number     // spot vs max pain in %
  ceItmOi: number
  peItmOi: number
  dominantWall: 'call' | 'put' | 'balanced'
  callWall: number
  putWall: number
}

export interface StrikeAnalysis {
  strike: number
  ceOi: number
  peOi: number
  totalOi: number
  ceChgOi: number
  peChgOi: number
  netChgOi: number
  ceIv: number
  peIv: number
  ivDiff: number
  ceLtp: number
  peLtp: number
  distanceFromSpot: number
  isAtm: boolean
  isItmCe: boolean
  isItmPe: boolean
  signal: 'support' | 'resistance' | 'neutral'
}

export interface ProcessedReport {
  indicators: ComputedIndicators
  strikes: StrikeAnalysis[]
  summary: {
    headline: string
    trend: string
    keyLevels: string
    oiBuildup: string
    ivOutlook: string
    maxPainNote: string
    riskNote: string
  }
}

/** Round to 2 decimals safely. */
function r2(n: number): number {
  if (!isFinite(n)) return 0
  return Math.round(n * 100) / 100
}

/** Find the strike nearest to spot price. */
export function findAtmStrike(rows: OptionChainRow[], spot: number): number {
  let best = rows[0]?.strike ?? 0
  let bestDist = Infinity
  for (const r of rows) {
    const d = Math.abs(r.strike - spot)
    if (d < bestDist) {
      bestDist = d
      best = r.strike
    }
  }
  return best
}

/** Max pain: strike where total option writer payout is minimized. */
export function computeMaxPain(rows: OptionChainRow[]): number {
  let minPain = Infinity
  let painStrike = rows[0]?.strike ?? 0
  for (const candidate of rows) {
    let total = 0
    for (const r of rows) {
      // Call writers pay when spot > strike
      if (candidate.strike > r.strike) total += (candidate.strike - r.strike) * r.ceOi
      // Put writers pay when spot < strike
      if (candidate.strike < r.strike) total += (r.strike - candidate.strike) * r.peOi
    }
    if (total < minPain) {
      minPain = total
      painStrike = candidate.strike
    }
  }
  return painStrike
}

export function computeIndicators(
  rows: OptionChainRow[],
  spotPrice: number,
  cfg: FormulaConfig = DEFAULT_FORMULA,
): ComputedIndicators {
  const totalCallOi = rows.reduce((s, r) => s + r.ceOi, 0)
  const totalPutOi = rows.reduce((s, r) => s + r.peOi, 0)
  const totalCallVol = rows.reduce((s, r) => s + r.ceVolume, 0)
  const totalPutVol = rows.reduce((s, r) => s + r.peVolume, 0)
  const callChgOi = rows.reduce((s, r) => s + r.ceChgOi, 0)
  const putChgOi = rows.reduce((s, r) => s + r.peChgOi, 0)

  const pcr = totalCallOi > 0 ? totalPutOi / totalCallOi : 0
  const pcrVolume = totalCallVol > 0 ? totalPutVol / totalCallVol : 0

  const atm = findAtmStrike(rows, spotPrice)
  const atmIdx = rows.findIndex((r) => r.strike === atm)
  const start = Math.max(0, atmIdx - cfg.atmRange)
  const end = Math.min(rows.length, atmIdx + cfg.atmRange + 1)
  const atmRows = rows.slice(start, end)
  const ivCall = atmRows.length
    ? atmRows.reduce((s, r) => s + r.ceIv, 0) / atmRows.length
    : 0
  const ivPut = atmRows.length
    ? atmRows.reduce((s, r) => s + r.peIv, 0) / atmRows.length
    : 0
  const ivSkew = ivPut - ivCall

  const maxPain = computeMaxPain(rows)

  // Support / resistance from largest OI walls
  let callWall = 0
  let callWallOi = -1
  let putWall = 0
  let putWallOi = -1
  for (const r of rows) {
    if (r.ceOi > callWallOi) {
      callWallOi = r.ceOi
      callWall = r.strike
    }
    if (r.peOi > putWallOi) {
      putWallOi = r.peOi
      putWall = r.strike
    }
  }
  const support = Math.min(callWall, putWall)
  const resistance = Math.max(callWall, putWall)
  const dominantWall =
    callWallOi > putWallOi * 1.1 ? 'call' : putWallOi > callWallOi * 1.1 ? 'put' : 'balanced'

  // ITM OI
  const ceItmOi = rows.filter((r) => r.strike < spotPrice).reduce((s, r) => s + r.ceOi, 0)
  const peItmOi = rows.filter((r) => r.strike > spotPrice).reduce((s, r) => s + r.peOi, 0)

  // OI shift indicator: positive => long buildup bias
  const oiShift = (putChgOi - callChgOi) / Math.max(1, totalCallOi + totalPutOi)

  // Trend scoring
  let score = 0
  score += (pcr > cfg.pcrBullThreshold ? 1 : pcr < cfg.pcrBearThreshold ? -1 : 0) * cfg.trendWeights.pcr
  score += (oiShift > 0 ? 1 : -1) * cfg.trendWeights.oiShift
  score += (ivSkew > 0 ? -1 : 1) * cfg.trendWeights.ivSkew
  score += (callChgOi > putChgOi ? -1 : 1) * cfg.trendWeights.chgOi
  score = Math.max(-100, Math.min(100, score))

  const trend: ComputedIndicators['trend'] =
    score > 18 ? 'bullish' : score < -18 ? 'bearish' : 'neutral'

  const painDistance = spotPrice > 0 ? ((spotPrice - maxPain) / spotPrice) * 100 : 0

  return {
    spotPrice: r2(spotPrice),
    atmStrike: atm,
    pcr: r2(pcr),
    pcrVolume: r2(pcrVolume),
    maxPain,
    ivCall: r2(ivCall),
    ivPut: r2(ivPut),
    ivSkew: r2(ivSkew),
    totalCallOi,
    totalPutOi,
    totalCallVol,
    totalPutVol,
    callChgOi,
    putChgOi,
    support,
    resistance,
    trend,
    trendScore: Math.round(score),
    oiShift: r2(oiShift),
    painDistance: r2(painDistance),
    ceItmOi,
    peItmOi,
    dominantWall,
    callWall,
    putWall,
  }
}

export function analyzeStrikes(
  rows: OptionChainRow[],
  spot: number,
  atm: number,
): StrikeAnalysis[] {
  return rows.map((r) => {
    const totalOi = r.ceOi + r.peOi
    const netChgOi = r.peChgOi - r.ceChgOi
    const ivDiff = r.peIv - r.ceIv
    const distanceFromSpot = r2(((r.strike - spot) / spot) * 100)
    const isItmCe = r.strike < spot
    const isItmPe = r.strike > spot
    let signal: StrikeAnalysis['signal'] = 'neutral'
    if (r.peOi > r.ceOi * 1.3) signal = 'support'
    else if (r.ceOi > r.peOi * 1.3) signal = 'resistance'
    return {
      strike: r.strike,
      ceOi: r.ceOi,
      peOi: r.peOi,
      totalOi,
      ceChgOi: r.ceChgOi,
      peChgOi: r.peChgOi,
      netChgOi,
      ceIv: r.ceIv,
      peIv: r.peIv,
      ivDiff: r2(ivDiff),
      ceLtp: r.ceLtp,
      peLtp: r.peLtp,
      distanceFromSpot,
      isAtm: r.strike === atm,
      isItmCe,
      isItmPe,
      signal,
    }
  })
}

export function buildSummary(
  ind: ComputedIndicators,
  symbol: string,
): ProcessedReport['summary'] {
  const dir = ind.trend === 'bullish' ? 'Bullish' : ind.trend === 'bearish' ? 'Bearish' : 'Neutral'
  const headline = `${symbol} @ ${ind.spotPrice} • ${dir} bias (score ${ind.trendScore > 0 ? '+' : ''}${ind.trendScore})`

  const trend =
    ind.pcr > 1.1
      ? `PCR ${ind.pcr} above 1.1 indicates bullish positioning — put writers aggressive.`
      : ind.pcr < 0.9
        ? `PCR ${ind.pcr} below 0.9 indicates bearish positioning — call writers dominant.`
        : `PCR ${ind.pcr} near equilibrium — range-bound activity likely.`

  const keyLevels = `Immediate support ${ind.support}, resistance ${ind.resistance}. Max pain at ${ind.maxPain} (${ind.painDistance > 0 ? '+' : ''}${ind.painDistance}% from spot).`

  const oiBuildup =
    ind.callChgOi > ind.putChgOi
      ? `Call OI added ${fmt(ind.callChgOi)} vs Put OI ${fmt(ind.putChgOi)} → resistance being built, capped upside.`
      : `Put OI added ${fmt(ind.putChgOi)} vs Call OI ${fmt(ind.callChgOi)} → support building, downside cushioned.`

  const ivOutlook =
    ind.ivSkew > 0
      ? `Put IV premium over Call (skew ${ind.ivSkew}) → hedging demand rising, protective sentiment.`
      : `Call IV slightly richer than Put (skew ${ind.ivSkew}) → bullish option buying.`

  const maxPainNote = `Max pain ${ind.maxPain} tends to magnetise price into expiry; spot is ${ind.painDistance > 0 ? 'above' : 'below'} by ${Math.abs(ind.painDistance)}%.`

  const riskNote =
    ind.trend === 'bearish'
      ? 'Risk: breakdown below support can accelerate. Watch Call-wall erosion.'
      : ind.trend === 'bullish'
        ? 'Risk: failure to sustain above resistance may trigger profit booking.'
        : 'Risk: choppy expiry — straddle buyers exposed to IV crush.'

  return { headline, trend, keyLevels, oiBuildup, ivOutlook, maxPainNote, riskNote }
}

function fmt(n: number): string {
  const abs = Math.abs(n)
  if (abs >= 1e7) return (n / 1e7).toFixed(2) + 'Cr'
  if (abs >= 1e5) return (n / 1e5).toFixed(2) + 'L'
  if (abs >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return String(n)
}

export function processReport(
  rows: OptionChainRow[],
  spotPrice: number,
  symbol: string,
  cfg: FormulaConfig = DEFAULT_FORMULA,
): ProcessedReport {
  const indicators = computeIndicators(rows, spotPrice, cfg)
  const strikes = analyzeStrikes(rows, spotPrice, indicators.atmStrike)
  const summary = buildSummary(indicators, symbol)
  return { indicators, strikes, summary }
}
