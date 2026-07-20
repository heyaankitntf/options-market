import { NextRequest, NextResponse } from 'next/server'
import { runProfile } from '@/lib/scheduler'
import { db } from '@/lib/db'

export const dynamic = 'force-dynamic'

export async function POST(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const exec = await db.execution.findUnique({ where: { id } })
  if (!exec) return NextResponse.json({ error: 'Not found' }, { status: 404 })
  runProfile(exec.profileId, 'rerun').catch((e) => console.error('[rerun] failed', e))
  return NextResponse.json({ ok: true, message: 'Rerun triggered' })
}
