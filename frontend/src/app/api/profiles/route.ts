import { NextRequest, NextResponse } from 'next/server'
import { db } from '@/lib/db'

export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const enabled = searchParams.get('enabled')
  const symbol = searchParams.get('symbol')

  const where: Record<string, unknown> = {}
  if (enabled === 'true') where.enabled = true
  if (enabled === 'paused') where.paused = true
  if (symbol) where.symbol = symbol

  const profiles = await db.profile.findMany({
    where,
    orderBy: { createdAt: 'asc' },
    include: { template: true },
  })
  return NextResponse.json(profiles)
}

export async function POST(req: NextRequest) {
  const body = await req.json()
  const profile = await db.profile.create({
    data: {
      name: body.name,
      symbol: body.symbol,
      exchange: body.exchange ?? 'NFO',
      expiryKind: body.expiryKind ?? 'weekly',
      expiryDate: body.expiryDate ?? null,
      intervalMin: Number(body.intervalMin) || 10,
      templateId: body.templateId || null,
      outputFormats: body.outputFormats ?? 'json,csv',
      enabled: body.enabled ?? true,
      paused: body.paused ?? false,
      allStrikes: body.allStrikes ?? true,
      notifyChannels: Array.isArray(body.notifyChannels) ? body.notifyChannels.join(',') : (body.notifyChannels ?? ''),
      nextRunAt: body.enabled && !body.paused ? new Date(Date.now() + 5000) : null,
    },
  })
  return NextResponse.json(profile, { status: 201 })
}
