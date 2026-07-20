import { NextRequest, NextResponse } from 'next/server'
import { db } from '@/lib/db'

export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const profileId = searchParams.get('profileId')
  const limit = Math.min(100, Number(searchParams.get('limit') ?? 30))
  const where: Record<string, unknown> = {}
  if (profileId) where.profileId = profileId
  const snaps = await db.rawSnapshot.findMany({
    where,
    orderBy: { fetchedAt: 'desc' },
    take: limit,
    select: {
      id: true,
      profileId: true,
      symbol: true,
      expiry: true,
      spotPrice: true,
      fetchedAt: true,
      status: true,
      durationMs: true,
    },
  })
  return NextResponse.json(snaps)
}
