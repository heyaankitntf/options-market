import { NextRequest, NextResponse } from 'next/server'
import { db } from '@/lib/db'

export const dynamic = 'force-dynamic'

/**
 * Deep analytics for a single symbol: latest report + aggregated stats
 * over the last N reports (avg PCR, IV range, trend distribution, OI walls).
 */
export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const symbol = searchParams.get('symbol')
  if (!symbol) return NextResponse.json({ error: 'symbol required' }, { status: 400 })

  const recent = await db.report.findMany({
    where: { symbol },
    orderBy: { generatedAt: 'desc' },
    take: 50,
  })

  if (recent.length === 0) return NextResponse.json({ error: 'no data' }, { status: 404 })

  const latest = recent[0]
  const points = recent.slice().reverse() // oldest → newest

  // Aggregates
  const avgPcr = points.reduce((s, r) => s + r.pcr, 0) / points.length
  const avgMaxPain = points.reduce((s, r) => s + r.maxPain, 0) / points.length
  const avgSpot = points.reduce((s, r) => s + r.spotPrice, 0) / points.length
  const minSpot = Math.min(...points.map((r) => r.spotPrice))
  const maxSpot = Math.max(...points.map((r) => r.spotPrice))
  const ivCallRange = [Math.min(...points.map((r) => r.ivCall)), Math.max(...points.map((r) => r.ivCall))]
  const ivPutRange = [Math.min(...points.map((r) => r.ivPut)), Math.max(...points.map((r) => r.ivPut))]

  // Trend distribution
  const trendDist = { bullish: 0, bearish: 0, neutral: 0 }
  for (const r of points) trendDist[r.trend as keyof typeof trendDist]++

  // Spot movement
  const firstSpot = points[0].spotPrice
  const lastSpot = points[points.length - 1].spotPrice
  const spotChange = lastSpot - firstSpot
  const spotChangePct = firstSpot > 0 ? (spotChange / firstSpot) * 100 : 0

  // PCR trend (linear regression slope approximation)
  const pcrValues = points.map((r) => r.pcr)
  const pcrSlope = linearSlope(pcrValues)

  return NextResponse.json({
    symbol,
    latest,
    points,
    aggregates: {
      avgPcr: round2(avgPcr),
      avgMaxPain: Math.round(avgMaxPain),
      avgSpot: Math.round(avgSpot),
      spotRange: [minSpot, maxSpot],
      ivCallRange: [round2(ivCallRange[0]), round2(ivCallRange[1])],
      ivPutRange: [round2(ivPutRange[0]), round2(ivPutRange[1])],
      trendDist,
      spotChange: Math.round(spotChange),
      spotChangePct: round2(spotChangePct),
      pcrSlope: round2(pcrSlope),
      sampleCount: points.length,
    },
  })
}

function round2(n: number): number {
  return Math.round(n * 100) / 100
}

function linearSlope(values: number[]): number {
  const n = values.length
  if (n < 2) return 0
  const xs = values.map((_, i) => i)
  const meanX = xs.reduce((s, x) => s + x, 0) / n
  const meanY = values.reduce((s, y) => s + y, 0) / n
  let num = 0
  let den = 0
  for (let i = 0; i < n; i++) {
    num += (xs[i] - meanX) * (values[i] - meanY)
    den += (xs[i] - meanX) ** 2
  }
  return den === 0 ? 0 : num / den
}
