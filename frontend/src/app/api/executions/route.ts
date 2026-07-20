import { NextRequest, NextResponse } from 'next/server'
import { db } from '@/lib/db'

export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const status = searchParams.get('status')
  const profileId = searchParams.get('profileId')
  const limit = Math.min(200, Number(searchParams.get('limit') ?? 50))

  const where: Record<string, unknown> = {}
  if (status) where.status = status
  if (profileId) where.profileId = profileId

  const executions = await db.execution.findMany({
    where,
    orderBy: { startedAt: 'desc' },
    take: limit,
    include: { profile: { select: { name: true, symbol: true } } },
  })
  return NextResponse.json(executions)
}
