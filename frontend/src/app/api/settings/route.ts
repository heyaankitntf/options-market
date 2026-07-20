import { NextRequest, NextResponse } from 'next/server'
import { db } from '@/lib/db'

export const dynamic = 'force-dynamic'

export async function GET() {
  const settings = await db.systemSetting.findMany({ orderBy: { id: 'asc' } })
  return NextResponse.json(Object.fromEntries(settings.map((s) => [s.id, s.value])))
}

export async function PATCH(req: NextRequest) {
  const body = (await req.json()) as Record<string, string>
  for (const [k, v] of Object.entries(body)) {
    await db.systemSetting.upsert({ where: { id: k }, update: { value: String(v) }, create: { id: k, value: String(v) } })
  }
  return NextResponse.json({ ok: true })
}
