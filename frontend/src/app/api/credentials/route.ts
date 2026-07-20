import { NextRequest, NextResponse } from 'next/server'
import { db } from '@/lib/db'
import { encrypt } from '@/lib/crypto'

export const dynamic = 'force-dynamic'

export async function GET() {
  const creds = await db.credential.findMany({ orderBy: { createdAt: 'desc' } })
  // Never expose cipher — return metadata only
  return NextResponse.json(
    creds.map((c) => ({
      id: c.id,
      label: c.label,
      portal: c.portal,
      username: c.username,
      active: c.active,
      lastUsed: c.lastUsed,
      createdAt: c.createdAt,
      hasPassword: !!c.cipher,
    })),
  )
}

export async function POST(req: NextRequest) {
  const body = await req.json()
  if (!body.password) return NextResponse.json({ error: 'password required' }, { status: 400 })
  const enc = encrypt(body.password)
  const cred = await db.credential.create({
    data: {
      label: body.label,
      portal: body.portal ?? 'icharts',
      username: body.username,
      cipher: enc.cipher,
      iv: enc.iv,
      tag: enc.tag,
      active: body.active ?? true,
    },
  })
  return NextResponse.json({ id: cred.id, label: cred.label }, { status: 201 })
}
