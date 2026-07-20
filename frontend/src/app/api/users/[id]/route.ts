import { NextRequest, NextResponse } from 'next/server'
import { db } from '@/lib/db'

export const dynamic = 'force-dynamic'

export async function PATCH(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const body = await req.json()
  const data: Record<string, unknown> = {}
  if ('role' in body) data.role = body.role
  if ('active' in body) data.active = !!body.active
  if ('name' in body) data.name = body.name
  if (body.password) data.password = body.password
  const updated = await db.user.update({ where: { id }, data })
  return NextResponse.json({ id: updated.id })
}

export async function DELETE(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  await db.user.delete({ where: { id } })
  return NextResponse.json({ ok: true })
}
