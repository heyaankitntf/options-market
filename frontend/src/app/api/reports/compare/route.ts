import { NextRequest, NextResponse } from 'next/server'
import { db } from '@/lib/db'

export const dynamic = 'force-dynamic'

/**
 * Report comparison. Pass ?ids=id1,id2,... (2-4 ids).
 * Returns ordered reports + computed deltas between consecutive snapshots.
 */
export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const ids = searchParams.get('ids')?.split(',').filter(Boolean) ?? []
  if (ids.length < 2) return NextResponse.json({ error: 'Provide at least 2 ids' }, { status: 400 })

  const reports = await db.report.findMany({
    where: { id: { in: ids } },
    orderBy: { generatedAt: 'asc' },
  })

  const rows = reports.map((r) => ({
    id: r.id,
    symbol: r.symbol,
    generatedAt: r.generatedAt,
    spotPrice: r.spotPrice,
    pcr: r.pcr,
    maxPain: r.maxPain,
    trend: r.trend,
    trendScore: r.trendScore,
    totalCallOi: r.totalCallOi,
    totalPutOi: r.totalPutOi,
    ivCall: r.ivCall,
    ivPut: r.ivPut,
    support: r.support,
    resistance: r.resistance,
    pcrVolume: r.pcrVolume,
    callChgOi: r.callChgOi,
    putChgOi: r.putChgOi,
    atmStrike: r.atmStrike,
  }))

  // Compute deltas between consecutive reports (chronological)
  const deltas = []
  for (let i = 1; i < rows.length; i++) {
    const prev = rows[i - 1]
    const curr = rows[i]
    deltas.push({
      from: prev.id,
      to: curr.id,
      spotDelta: Math.round(curr.spotPrice - prev.spotPrice),
      spotDeltaPct: prev.spotPrice > 0 ? Math.round(((curr.spotPrice - prev.spotPrice) / prev.spotPrice) * 10000) / 100 : 0,
      pcrDelta: Math.round((curr.pcr - prev.pcr) * 100) / 100,
      maxPainDelta: Math.round(curr.maxPain - prev.maxPain),
      callOiDelta: curr.totalCallOi - prev.totalCallOi,
      putOiDelta: curr.totalPutOi - prev.totalPutOi,
      ivCallDelta: Math.round((curr.ivCall - prev.ivCall) * 100) / 100,
      ivPutDelta: Math.round((curr.ivPut - prev.ivPut) * 100) / 100,
      trendScoreDelta: curr.trendScore - prev.trendScore,
      trendChanged: prev.trend !== curr.trend,
      timeDeltaMin: Math.round((new Date(curr.generatedAt).getTime() - new Date(prev.generatedAt).getTime()) / 60000),
    })
  }

  return NextResponse.json({ reports: rows, deltas })
}
