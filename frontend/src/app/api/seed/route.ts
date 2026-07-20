import { NextResponse } from 'next/server'
import { execSync } from 'child_process'

export const dynamic = 'force-dynamic'

export async function POST() {
  try {
    execSync('bun run src/lib/seed.ts', { cwd: process.cwd(), stdio: 'pipe', timeout: 30000 })
    return NextResponse.json({ ok: true, message: 'Seed complete' })
  } catch (e) {
    return NextResponse.json({ ok: false, error: e instanceof Error ? e.message : String(e) }, { status: 500 })
  }
}
