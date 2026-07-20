import { NextRequest, NextResponse } from 'next/server'
import { db } from '@/lib/db'

export const dynamic = 'force-dynamic'

export async function PATCH(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const body = await req.json()
  const data: Record<string, unknown> = {}
  if ('active' in body) data.active = !!body.active
  if ('label' in body) data.label = body.label
  if ('username' in body) data.username = body.username
  const updated = await db.credential.update({ where: { id }, data })
  return NextResponse.json({ id: updated.id, label: updated.label })
}

export async function DELETE(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  await db.credential.delete({ where: { id } })
  return NextResponse.json({ ok: true })
}
