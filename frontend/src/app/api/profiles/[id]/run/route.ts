import { NextRequest, NextResponse } from 'next/server'
import { runProfile } from '@/lib/scheduler'

export const dynamic = 'force-dynamic'

export async function POST(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  // Fire and forget — run in background so the UI gets an instant response.
  runProfile(id, 'manual').catch((e) => console.error('[run] failed', e))
  return NextResponse.json({ ok: true, message: 'Pipeline triggered' })
}
