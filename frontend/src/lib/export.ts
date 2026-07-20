/** Export utilities — CSV / JSON / XLSX / PDF(printable HTML). */

import ExcelJS from 'exceljs'
import type { ProcessedReport } from './analytics'

export function reportToCsv(report: ProcessedReport, symbol: string): string {
  const header = [
    'Strike',
    'CE LTP',
    'CE OI',
    'CE Chg OI',
    'CE Vol',
    'CE IV',
    'PE LTP',
    'PE OI',
    'PE Chg OI',
    'PE Vol',
    'PE IV',
    'Signal',
  ]
  const lines = [header.join(',')]
  for (const s of report.strikes) {
    lines.push(
      [
        s.strike,
        s.ceLtp,
        s.ceOi,
        s.ceChgOi,
        '',
        s.ceIv,
        s.peLtp,
        s.peOi,
        s.peChgOi,
        '',
        s.peIv,
        s.signal,
      ].join(','),
    )
  }
  return lines.join('\n')
}

export function reportToJson(report: ProcessedReport, meta: Record<string, unknown>): string {
  return JSON.stringify({ meta, ...report }, null, 2)
}

export async function reportToXlsx(report: ProcessedReport, meta: Record<string, unknown>): Promise<Buffer> {
  const wb = new ExcelJS.Workbook()
  wb.creator = 'OptFlow'
  wb.created = new Date()

  const ind = wb.addWorksheet('Indicators')
  ind.columns = [
    { header: 'Metric', key: 'k', width: 28 },
    { header: 'Value', key: 'v', width: 22 },
  ]
  const i = report.indicators
  const rows: [string, string | number][] = [
    ['Symbol', String(meta.symbol ?? '')],
    ['Expiry', String(meta.expiry ?? '')],
    ['Generated', String(meta.generatedAt ?? '')],
    ['Spot Price', i.spotPrice],
    ['ATM Strike', i.atmStrike],
    ['PCR (OI)', i.pcr],
    ['PCR (Volume)', i.pcrVolume],
    ['Max Pain', i.maxPain],
    ['IV Call (ATM)', i.ivCall],
    ['IV Put (ATM)', i.ivPut],
    ['IV Skew', i.ivSkew],
    ['Total Call OI', i.totalCallOi],
    ['Total Put OI', i.totalPutOi],
    ['Call Chg OI', i.callChgOi],
    ['Put Chg OI', i.putChgOi],
    ['Support', i.support],
    ['Resistance', i.resistance],
    ['Trend', i.trend],
    ['Trend Score', i.trendScore],
    ['Pain Distance %', i.painDistance],
  ]
  for (const [k, v] of rows) ind.addRow({ k, v })
  ind.getRow(1).font = { bold: true }

  const ws = wb.addWorksheet('Option Chain')
  ws.columns = [
    { header: 'Strike', key: 'strike', width: 10 },
    { header: 'CE LTP', key: 'ceLtp', width: 10 },
    { header: 'CE OI', key: 'ceOi', width: 14 },
    { header: 'CE Chg OI', key: 'ceChgOi', width: 14 },
    { header: 'CE IV', key: 'ceIv', width: 8 },
    { header: 'PE LTP', key: 'peLtp', width: 10 },
    { header: 'PE OI', key: 'peOi', width: 14 },
    { header: 'PE Chg OI', key: 'peChgOi', width: 14 },
    { header: 'PE IV', key: 'peIv', width: 8 },
    { header: 'Signal', key: 'signal', width: 12 },
  ]
  for (const s of report.strikes) ws.addRow(s)
  ws.getRow(1).font = { bold: true }

  const sum = wb.addWorksheet('Summary')
  sum.columns = [{ header: 'Section', key: 'k', width: 22 }, { header: 'Note', key: 'v', width: 90 }]
  for (const [k, v] of Object.entries(report.summary)) sum.addRow({ k, v })
  sum.getRow(1).font = { bold: true }

  return Buffer.from(await wb.xlsx.writeBuffer())
}

export function reportToPrintableHtml(report: ProcessedReport, meta: Record<string, unknown>): string {
  const i = report.indicators
  const s = report.summary
  const rows = report.strikes
    .map(
      (r) => `<tr>
        <td>${r.strike}</td>
        <td>${r.ceLtp}</td><td>${r.ceOi.toLocaleString('en-IN')}</td><td>${r.ceChgOi.toLocaleString('en-IN')}</td><td>${r.ceIv}</td>
        <td>${r.peLtp}</td><td>${r.peOi.toLocaleString('en-IN')}</td><td>${r.peChgOi.toLocaleString('en-IN')}</td><td>${r.peIv}</td>
        <td>${r.signal}</td>
      </tr>`,
    )
    .join('')
  return `<!doctype html><html><head><meta charset="utf-8"/>
  <title>${meta.symbol} Report</title>
  <style>
    body{font-family:Inter,system-ui,sans-serif;padding:24px;color:#0f172a}
    h1{font-size:20px;margin:0 0 4px}
    .meta{color:#64748b;font-size:13px;margin-bottom:16px}
    .grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}
    .card{border:1px solid #e2e8f0;border-radius:8px;padding:12px}
    .card .k{font-size:11px;color:#64748b;text-transform:uppercase}
    .card .v{font-size:18px;font-weight:600;margin-top:4px}
    table{width:100%;border-collapse:collapse;font-size:12px}
    th,td{border:1px solid #e2e8f0;padding:6px 8px;text-align:right}
    th{background:#f8fafc;text-align:center}
    td:first-child{font-weight:600}
    .summary{margin-top:20px}
    .summary div{margin-bottom:8px;font-size:13px}
    .summary b{color:#0f172a}
  </style></head>
  <body>
    <h1>${meta.symbol} — Options Chain Report</h1>
    <div class="meta">Expiry: ${meta.expiry} • Generated: ${meta.generatedAt} • Spot: ${i.spotPrice}</div>
    <div class="grid">
      <div class="card"><div class="k">PCR (OI)</div><div class="v">${i.pcr}</div></div>
      <div class="card"><div class="k">Max Pain</div><div class="v">${i.maxPain}</div></div>
      <div class="card"><div class="k">Trend</div><div class="v">${i.trend} (${i.trendScore > 0 ? '+' : ''}${i.trendScore})</div></div>
      <div class="card"><div class="k">ATM Strike</div><div class="v">${i.atmStrike}</div></div>
      <div class="card"><div class="k">Support</div><div class="v">${i.support}</div></div>
      <div class="card"><div class="k">Resistance</div><div class="v">${i.resistance}</div></div>
      <div class="card"><div class="k">IV Call</div><div class="v">${i.ivCall}%</div></div>
      <div class="card"><div class="k">IV Put</div><div class="v">${i.ivPut}%</div></div>
    </div>
    <table>
      <thead><tr><th>Strike</th><th>CE LTP</th><th>CE OI</th><th>CE ChgOI</th><th>CE IV</th><th>PE LTP</th><th>PE OI</th><th>PE ChgOI</th><th>PE IV</th><th>Signal</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div class="summary">
      <div><b>Headline:</b> ${s.headline}</div>
      <div><b>Trend:</b> ${s.trend}</div>
      <div><b>Key Levels:</b> ${s.keyLevels}</div>
      <div><b>OI Buildup:</b> ${s.oiBuildup}</div>
      <div><b>IV Outlook:</b> ${s.ivOutlook}</div>
      <div><b>Max Pain:</b> ${s.maxPainNote}</div>
      <div><b>Risk:</b> ${s.riskNote}</div>
    </div>
    <script>window.onload=()=>window.print()</script>
  </body></html>`
}
