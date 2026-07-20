'use client'

import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { api, type TickerItem } from '@/lib/api'
import { fmtNum, fmtSigned } from '@/lib/format'
import { cn } from '@/lib/utils'

export function MarketTicker({ onSelectSymbol }: { onSelectSymbol?: (s: string) => void }) {
  const { data } = useQuery({
    queryKey: ['ticker'],
    queryFn: () => api<TickerItem[]>('/api/ticker'),
    refetchInterval: 12000,
  })

  const items = data ?? []

  return (
    <div className="relative overflow-hidden border-b bg-card/60 backdrop-blur-sm">
      <div className="absolute inset-y-0 left-0 w-12 bg-gradient-to-r from-card to-transparent z-10 pointer-events-none" />
      <div className="absolute inset-y-0 right-0 w-12 bg-gradient-to-l from-card to-transparent z-10 pointer-events-none" />
      <div className="flex items-center gap-1 px-4 py-2 overflow-x-auto scroll-thin">
        {items.length === 0 ? (
          <div className="flex items-center gap-4 px-2 text-xs text-muted-foreground">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-9 w-32 rounded-md bg-muted/40 animate-pulse" />
            ))}
          </div>
        ) : (
          items.map((t) => {
            const up = t.change > 0
            const down = t.change < 0
            const trendIcon =
              t.trend === 'bullish' ? <TrendingUp className="h-3 w-3 text-emerald-500" /> :
              t.trend === 'bearish' ? <TrendingDown className="h-3 w-3 text-rose-500" /> :
              <Minus className="h-3 w-3 text-amber-500" />
            return (
              <button
                key={t.symbol}
                onClick={() => onSelectSymbol?.(t.symbol)}
                className="group shrink-0 flex items-center gap-2.5 rounded-lg px-3 py-1.5 hover:bg-muted/60 transition-colors"
              >
                <div className="flex flex-col items-start leading-tight">
                  <span className="text-[11px] font-semibold tracking-wide">{t.symbol}</span>
                  <span className="text-[9px] text-muted-foreground">{t.label}</span>
                </div>
                <div className="flex flex-col items-end leading-tight">
                  <span className="text-xs font-semibold tnum">{fmtNum(t.spotPrice)}</span>
                  <span className={cn('text-[10px] tnum font-medium', up ? 'text-emerald-500' : down ? 'text-rose-500' : 'text-muted-foreground')}>
                    {up ? '▲' : down ? '▼' : '·'} {fmtSigned(t.change, 0)} ({fmtSigned(t.changePct)}%)
                  </span>
                </div>
                <div className="flex items-center gap-1 pl-1.5 border-l border-border/60">
                  {trendIcon}
                  <span className="text-[10px] text-muted-foreground tnum">{t.pcr}</span>
                </div>
              </button>
            )
          })
        )}
      </div>
    </div>
  )
}
