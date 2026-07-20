import { NextRequest, NextResponse } from 'next/server'
import { db } from '@/lib/db'

export const dynamic = 'force-dynamic'

/**
 * Per-symbol historical time-series.
 * Returns the last N reports for a symbol (or all symbols) ordered oldest→newest,
 * with the key indicators flattened for easy charting.
 */
export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const symbol = searchParams.get('symbol')
  const limit = Math.min(500, Number(searchParams.get('limit') ?? 100))
  const hours = Number(searchParams.get('hours') ?? 0)

  const where: Record<string, unknown> = {}
  if (symbol && symbol !== 'ALL') where.symbol = symbol
  if (hours > 0) where.generatedAt = { gte: new Date(Date.now() - hours * 3600000) }

  const reports = await db.report.findMany({
    where,
    orderBy: { generatedAt: 'asc' },
    take: limit,
    select: {
      id: true,
      symbol: true,
      generatedAt: true,
      spotPrice: true,
      pcr: true,
      pcrVolume: true,
      maxPain: true,
      ivCall: true,
      ivPut: true,
      atmStrike: true,
      totalCallOi: true,
      totalPutOi: true,
      callChgOi: true,
      putChgOi: true,
      trend: true,
      trendScore: true,
      support: true,
      resistance: true,
    },
  })

  // Group by symbol for multi-series charts
  const bySymbol: Record<string, typeof reports> = {}
  for (const r of reports) {
    if (!bySymbol[r.symbol]) bySymbol[r.symbol] = []
    bySymbol[r.symbol].push(r)
  }

  return NextResponse.json({
    points: reports,
    bySymbol,
    symbols: Object.keys(bySymbol),
  })
}
