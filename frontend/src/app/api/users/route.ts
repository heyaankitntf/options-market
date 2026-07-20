import { NextRequest, NextResponse } from 'next/server'
import { db } from '@/lib/db'

export const dynamic = 'force-dynamic'

export async function GET() {
  const users = await db.user.findMany({ orderBy: { createdAt: 'desc' } })
  return NextResponse.json(
    users.map((u) => ({ id: u.id, email: u.email, name: u.name, role: u.role, active: u.active, lastLogin: u.lastLogin, createdAt: u.createdAt })),
  )
}

export async function POST(req: NextRequest) {
  const body = await req.json()
  if (!body.email || !body.password) return NextResponse.json({ error: 'email+password required' }, { status: 400 })
  const user = await db.user.create({
    data: {
      email: body.email,
      name: body.name ?? body.email.split('@')[0],
      password: body.password,
      role: body.role ?? 'viewer',
      active: body.active ?? true,
    },
  })
  return NextResponse.json({ id: user.id, email: user.email }, { status: 201 })
}
