import { NextRequest, NextResponse } from 'next/server'
import { db } from '@/lib/db'

export const dynamic = 'force-dynamic'

export async function GET() {
  const channels = await db.notificationChannel.findMany({ orderBy: { createdAt: 'desc' } })
  return NextResponse.json(
    channels.map((c) => ({ ...c, config: c.config })),
  )
}

export async function POST(req: NextRequest) {
  const body = await req.json()
  const ch = await db.notificationChannel.create({
    data: {
      name: body.name,
      type: body.type,
      enabled: body.enabled ?? true,
      config: body.config ?? '{}',
    },
  })
  return NextResponse.json(ch, { status: 201 })
}
