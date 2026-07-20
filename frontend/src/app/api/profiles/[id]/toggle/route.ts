import { NextRequest, NextResponse } from 'next/server'
import { db } from '@/lib/db'

export const dynamic = 'force-dynamic'

export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const body = await req.json().catch(() => ({}))
  const paused = !!body.paused
  const updated = await db.profile.update({
    where: { id },
    data: { paused, nextRunAt: paused ? null : new Date(Date.now() + 5000) },
  })
  return NextResponse.json(updated)
}
