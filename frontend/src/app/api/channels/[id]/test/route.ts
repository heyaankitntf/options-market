import { NextRequest, NextResponse } from 'next/server'
import { sendTestMessage } from '@/lib/notify'

export const dynamic = 'force-dynamic'

export async function POST(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const result = await sendTestMessage(id)
  return NextResponse.json(result, { status: result.ok ? 200 : 400 })
}
