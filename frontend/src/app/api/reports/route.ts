import { NextRequest, NextResponse } from 'next/server'
import { db } from '@/lib/db'

export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const symbol = searchParams.get('symbol')
  const profileId = searchParams.get('profileId')
  const trend = searchParams.get('trend')
  const limit = Math.min(200, Number(searchParams.get('limit') ?? 100))
  const from = searchParams.get('from')

  const where: Record<string, unknown> = {}
  if (symbol) where.symbol = symbol
  if (profileId) where.profileId = profileId
  if (trend) where.trend = trend
  if (from) where.generatedAt = { gte: new Date(from) }

  const reports = await db.report.findMany({
    where,
    orderBy: { generatedAt: 'desc' },
    take: limit,
    include: { profile: { select: { name: true, intervalMin: true } } },
  })
  return NextResponse.json(reports)
}
