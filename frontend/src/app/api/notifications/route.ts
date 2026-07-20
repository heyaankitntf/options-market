import { NextRequest, NextResponse } from 'next/server'
import { db } from '@/lib/db'

export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const limit = Math.min(200, Number(searchParams.get('limit') ?? 50))
  const logs = await db.notificationLog.findMany({
    orderBy: { createdAt: 'desc' },
    take: limit,
    include: { channel: { select: { name: true, type: true } } },
  })
  return NextResponse.json(logs)
}
