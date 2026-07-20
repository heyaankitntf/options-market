import { NextRequest, NextResponse } from 'next/server'
import { db } from '@/lib/db'

export const dynamic = 'force-dynamic'

export async function GET() {
  const templates = await db.formulaTemplate.findMany({ orderBy: { createdAt: 'desc' } })
  return NextResponse.json(
    templates.map((t) => ({ ...t, config: JSON.parse(t.configJson) })),
  )
}

export async function POST(req: NextRequest) {
  const body = await req.json()
  const tpl = await db.formulaTemplate.create({
    data: {
      name: body.name,
      description: body.description ?? '',
      version: body.version ?? 1,
      enabled: body.enabled ?? true,
      configJson: typeof body.config === 'string' ? body.config : JSON.stringify(body.config ?? {}),
    },
  })
  return NextResponse.json(tpl, { status: 201 })
}
