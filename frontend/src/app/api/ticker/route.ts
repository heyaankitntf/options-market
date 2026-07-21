import { NextResponse } from 'next/server'
import { db } from '@/lib/db'
import { SYMBOL_SPECS } from '@/lib/symbols'

export const dynamic = 'force-dynamic'

/**
 * Market ticker: latest report + previous report per symbol so the UI can
 * compute intraday change. Powers the sticky ticker bar.
 */
export async function GET() {
  const items = []
  for (const spec of SYMBOL_SPECS) {
    const recent = await db.report.findMany({
      where: { symbol: spec.symbol },
      orderBy: { generatedAt: 'desc' },
      take: 2,
    })
    if (recent.length === 0) continue
    const latest = recent[0]
    const prev = recent[1]
    const change = prev ? latest.spotPrice - prev.spotPrice : 0
    const changePct = prev && prev.spotPrice > 0 ? (change / prev.spotPrice) * 100 : 0
    items.push({
      symbol: spec.symbol,
      label: spec.label,
      spotPrice: latest.spotPrice,
      prevSpot: prev?.spotPrice ?? latest.spotPrice,
      change: Math.round(change),
      changePct: Math.round(changePct * 100) / 100,
      pcr: latest.pcr,
      trend: latest.trend,
      trendScore: latest.trendScore,
      generatedAt: latest.generatedAt,
      maxPain: latest.maxPain,
    })
  }
  return NextResponse.json(items)
}
