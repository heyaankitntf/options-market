import { NextRequest, NextResponse } from 'next/server'
import { db } from '@/lib/db'

export const dynamic = 'force-dynamic'

export async function PATCH(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const body = await req.json()
  const data: Record<string, unknown> = {}
  if ('name' in body) data.name = body.name
  if ('description' in body) data.description = body.description
  if ('enabled' in body) data.enabled = !!body.enabled
  if ('config' in body) data.configJson = typeof body.config === 'string' ? body.config : JSON.stringify(body.config)
  const updated = await db.formulaTemplate.update({ where: { id }, data })
  return NextResponse.json(updated)
}

export async function DELETE(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  await db.formulaTemplate.delete({ where: { id } })
  return NextResponse.json({ ok: true })
}
