import { NextRequest, NextResponse } from 'next/server'
import { db } from '@/lib/db'

export const dynamic = 'force-dynamic'

export async function GET(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const report = await db.report.findUnique({
    where: { id },
    include: { profile: true },
  })
  if (!report) return NextResponse.json({ error: 'Not found' }, { status: 404 })

  let indicators = {}
  let summary = {}
  let strikes: unknown[] = []
  try {
    indicators = JSON.parse(report.indicatorsJson)
  } catch { /* empty */ }
  try {
    summary = JSON.parse(report.summaryJson)
  } catch { /* empty */ }

  // Rebuild strikes from the linked raw snapshot
  if (report.snapshotId) {
    const snap = await db.rawSnapshot.findUnique({ where: { id: report.snapshotId } })
    if (snap) {
      try {
        strikes = JSON.parse(snap.rowsJson)
      } catch { /* empty */ }
    }
  }

  return NextResponse.json({ ...report, indicators, summary, strikes })
}
