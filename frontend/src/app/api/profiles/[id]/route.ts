import { NextRequest, NextResponse } from 'next/server'
import { db } from '@/lib/db'

export const dynamic = 'force-dynamic'

export async function GET(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const profile = await db.profile.findUnique({ where: { id }, include: { template: true } })
  if (!profile) return NextResponse.json({ error: 'Not found' }, { status: 404 })
  return NextResponse.json(profile)
}

export async function PATCH(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const body = await req.json()
  const existing = await db.profile.findUnique({ where: { id } })
  if (!existing) return NextResponse.json({ error: 'Not found' }, { status: 404 })

  const data: Record<string, unknown> = {}
  for (const k of ['name', 'symbol', 'exchange', 'expiryKind', 'expiryDate', 'outputFormats']) {
    if (k in body) data[k] = body[k]
  }
  if ('intervalMin' in body) data.intervalMin = Number(body.intervalMin) || 10
  if ('enabled' in body) data.enabled = !!body.enabled
  if ('paused' in body) {
    data.paused = !!body.paused
    data.nextRunAt = body.paused ? null : new Date(Date.now() + 5000)
  }
  if ('allStrikes' in body) data.allStrikes = !!body.allStrikes
  if ('templateId' in body) data.templateId = body.templateId || null
  if ('notifyChannels' in body) {
    data.notifyChannels = Array.isArray(body.notifyChannels) ? body.notifyChannels.join(',') : body.notifyChannels
  }

  const updated = await db.profile.update({ where: { id }, data })
  return NextResponse.json(updated)
}

export async function DELETE(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  await db.profile.delete({ where: { id } })
  return NextResponse.json({ ok: true })
}
