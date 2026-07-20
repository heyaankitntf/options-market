import { NextRequest, NextResponse } from 'next/server'
import { db } from '@/lib/db'
import { processReport, DEFAULT_FORMULA } from '@/lib/analytics'
import { reportToCsv, reportToJson, reportToXlsx, reportToPrintableHtml } from '@/lib/export'
import type { OptionChainRow } from '@/lib/analytics'

export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const { searchParams } = new URL(req.url)
  const format = (searchParams.get('format') ?? 'json').toLowerCase()

  const report = await db.report.findUnique({ where: { id }, include: { profile: true } })
  if (!report) return NextResponse.json({ error: 'Not found' }, { status: 404 })

  let indicators = {}
  let summary = {}
  try {
    indicators = JSON.parse(report.indicatorsJson)
    summary = JSON.parse(report.summaryJson)
  } catch { /* empty */ }

  let strikes: OptionChainRow[] = []
  if (report.snapshotId) {
    const snap = await db.rawSnapshot.findUnique({ where: { id: report.snapshotId } })
    if (snap) {
      try {
        strikes = JSON.parse(snap.rowsJson)
      } catch { /* empty */ }
    }
  }

  const processed = processReport(strikes, report.spotPrice, report.symbol, DEFAULT_FORMULA)
  const meta = {
    symbol: report.symbol,
    expiry: report.expiry,
    generatedAt: report.generatedAt,
    profile: report.profile.name,
  }

  const safeSymbol = report.symbol.replace(/[^A-Za-z0-9]/g, '_')
  const ts = new Date(report.generatedAt).toISOString().slice(0, 16).replace(/[:T]/g, '-')

  if (format === 'csv') {
    const csv = reportToCsv(processed, report.symbol)
    return new NextResponse(csv, {
      headers: {
        'Content-Type': 'text/csv',
        'Content-Disposition': `attachment; filename="${safeSymbol}-${ts}.csv"`,
      },
    })
  }

  if (format === 'json') {
    const json = reportToJson(processed, meta)
    return new NextResponse(json, {
      headers: {
        'Content-Type': 'application/json',
        'Content-Disposition': `attachment; filename="${safeSymbol}-${ts}.json"`,
      },
    })
  }

  if (format === 'xlsx') {
    const buf = await reportToXlsx(processed, meta)
    return new NextResponse(new Uint8Array(buf), {
      headers: {
        'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'Content-Disposition': `attachment; filename="${safeSymbol}-${ts}.xlsx"`,
      },
    })
  }

  if (format === 'pdf') {
    const html = reportToPrintableHtml(processed, meta)
    return new NextResponse(html, { headers: { 'Content-Type': 'text/html' } })
  }

  return NextResponse.json({ error: 'Unsupported format' }, { status: 400 })
}
