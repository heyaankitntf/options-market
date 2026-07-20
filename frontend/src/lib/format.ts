/** Shared formatting + export helpers. */

export function fmtNum(n: number, digits = 2): string {
  if (n == null || !isFinite(n)) return '-'
  return n.toLocaleString('en-IN', { maximumFractionDigits: digits, minimumFractionDigits: 0 })
}

export function fmtOI(n: number): string {
  const abs = Math.abs(n)
  if (abs >= 1e7) return (n / 1e7).toFixed(2) + ' Cr'
  if (abs >= 1e5) return (n / 1e5).toFixed(2) + ' L'
  if (abs >= 1e3) return (n / 1e3).toFixed(1) + ' K'
  return String(Math.round(n))
}

export function fmtSigned(n: number, digits = 2): string {
  const s = fmtNum(n, digits)
  return n > 0 ? '+' + s : s
}

export function fmtPct(n: number, digits = 2): string {
  return fmtSigned(n, digits) + '%'
}

export function fmtTime(d: Date | string | number): string {
  const date = new Date(d)
  return date.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function fmtDateTime(d: Date | string | number): string {
  const date = new Date(d)
  return date.toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function relTime(d: Date | string | number): string {
  const date = new Date(d)
  const diff = Date.now() - date.getTime()
  if (diff < 0) return 'in ' + msToStr(-diff)
  return msToStr(diff) + ' ago'
}

function msToStr(ms: number): string {
  const s = Math.floor(ms / 1000)
  if (s < 60) return s + 's'
  const m = Math.floor(s / 60)
  if (m < 60) return m + 'm'
  const h = Math.floor(m / 60)
  if (h < 24) return h + 'h'
  const d = Math.floor(h / 24)
  return d + 'd'
}

export function statusColor(status: string): string {
  switch (status) {
    case 'success':
    case 'sent':
    case 'running':
      return 'text-emerald-400'
    case 'failed':
      return 'text-rose-400'
    case 'cancelled':
    case 'queued':
      return 'text-amber-400'
    default:
      return 'text-muted-foreground'
  }
}

export function trendColor(trend: string): string {
  if (trend === 'bullish') return 'text-emerald-400'
  if (trend === 'bearish') return 'text-rose-400'
  return 'text-amber-400'
}

export function cn(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ')
}
