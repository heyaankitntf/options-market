/**
 * In-process automation scheduler.
 *
 * Replaces Celery/Redis with a lightweight single-node scheduler that:
 *  - ticks every 30s
 *  - finds due profiles (nextRunAt <= now, enabled, not paused)
 *  - runs the pipeline: scrape → process → store → notify
 *  - updates nextRunAt based on intervalMin
 *
 * Designed so it can be swapped for an external queue later without touching
 * the pipeline code.
 */

import { db } from './db'
import { generateOptionChain } from './mock-market'
import { processReport, DEFAULT_FORMULA } from './analytics'
import { notifyChannels } from './notify'
import type { OptionChainRow } from './analytics'

let timer: NodeJS.Timeout | null = null
let running = false
export let schedulerEnabled = true

export function setSchedulerEnabled(v: boolean) {
  schedulerEnabled = v
}

export interface RunResult {
  executionId: string
  snapshotId?: string
  reportId?: string
  status: 'success' | 'failed'
  durationMs: number
}

/**
 * Run the full pipeline for a single profile.
 * `triggeredBy` = scheduler | manual | rerun
 */
export async function runProfile(profileId: string, triggeredBy = 'manual'): Promise<RunResult> {
  const startedAt = Date.now()
  const profile = await db.profile.findUnique({ where: { id: profileId } })
  if (!profile) throw new Error('Profile not found')

  const execution = await db.execution.create({
    data: {
      profileId,
      status: 'running',
      stage: 'login',
      triggeredBy,
    },
  })

  const log = (level: string, source: string, message: string, meta?: unknown) =>
    db.log.create({
      data: {
        executionId: execution.id,
        profileId,
        level,
        source,
        message,
        meta: meta ? JSON.stringify(meta) : undefined,
      },
    })

  try {
    // Stage 1 — login
    await log('info', 'browser', `Authenticating to icharts portal for ${profile.symbol}`)
    await sleep(300 + Math.random() * 400)
    await log('info', 'browser', 'Session established', { portal: 'icharts' })
    await db.execution.update({ where: { id: execution.id }, data: { stage: 'navigate' } })

    // Stage 2 — navigate + select
    await log('info', 'browser', `Navigating to options chain for ${profile.symbol}`)
    await sleep(200 + Math.random() * 300)
    await log('info', 'browser', `Selecting expiry ${profile.expiryKind}`)
    if (profile.allStrikes) await log('info', 'browser', 'Enabled "All Strikes" toggle')
    await db.execution.update({ where: { id: execution.id }, data: { stage: 'export' } })

    // Stage 3 — capture raw data (mock generator stands in for live scrape)
    const snap = generateOptionChain(profile.symbol, profile.expiryDate ?? undefined)
    await log('info', 'browser', `Captured ${snap.rows.length} strikes @ spot ${snap.spotPrice}`, {
      spot: snap.spotPrice,
      expiry: snap.expiry,
    })

    const snapshot = await db.rawSnapshot.create({
      data: {
        profileId,
        symbol: snap.symbol,
        expiry: snap.expiry,
        spotPrice: snap.spotPrice,
        rowsJson: JSON.stringify(snap.rows),
        status: 'captured',
        durationMs: Math.round(Math.random() * 1500 + 800),
      },
    })
    await db.execution.update({ where: { id: execution.id }, data: { stage: 'process', snapshotId: snapshot.id } })

    // Stage 4 — process with analytics engine
    await log('info', 'engine', 'Running analytics engine (PCR, max pain, IV, trend)')
    const processed = processReport(snap.rows as OptionChainRow[], snap.spotPrice, snap.symbol, DEFAULT_FORMULA)
    await log('info', 'engine', `Trend=${processed.indicators.trend} PCR=${processed.indicators.pcr} MaxPain=${processed.indicators.maxPain}`)

    const hash = await sha256(JSON.stringify(processed))
    const report = await db.report.create({
      data: {
        profileId,
        snapshotId: snapshot.id,
        symbol: snap.symbol,
        expiry: snap.expiry,
        spotPrice: processed.indicators.spotPrice,
        pcr: processed.indicators.pcr,
        pcrVolume: processed.indicators.pcrVolume,
        maxPain: processed.indicators.maxPain,
        ivPut: processed.indicators.ivPut,
        ivCall: processed.indicators.ivCall,
        atmStrike: processed.indicators.atmStrike,
        totalCallOi: processed.indicators.totalCallOi,
        totalPutOi: processed.indicators.totalPutOi,
        totalCallVol: processed.indicators.totalCallVol,
        totalPutVol: processed.indicators.totalPutVol,
        callChgOi: processed.indicators.callChgOi,
        putChgOi: processed.indicators.putChgOi,
        trend: processed.indicators.trend,
        trendScore: processed.indicators.trendScore,
        support: processed.indicators.support,
        resistance: processed.indicators.resistance,
        indicatorsJson: JSON.stringify(processed.indicators),
        summaryJson: JSON.stringify(processed.summary),
        reportHash: hash,
      },
    })
    await db.execution.update({ where: { id: execution.id }, data: { stage: 'notify', reportId: report.id } })

    // Stage 5 — notify
    const channelIds = profile.notifyChannels.split(',').filter(Boolean)
    if (channelIds.length) {
      await log('info', 'notify', `Dispatching report to ${channelIds.length} channel(s)`)
      await notifyChannels(channelIds, profile, report.id, processed.summary.headline, {
        pcr: processed.indicators.pcr,
        trend: processed.indicators.trend,
        spot: processed.indicators.spotPrice,
        maxPain: processed.indicators.maxPain,
      })
    }

    // Finalize
    const durationMs = Date.now() - startedAt
    await db.execution.update({
      where: { id: execution.id },
      data: { status: 'success', stage: 'done', finishedAt: new Date(), durationMs },
    })
    await db.profile.update({
      where: { id: profileId },
      data: {
        lastRunAt: new Date(),
        lastStatus: 'success',
        runCount: { increment: 1 },
        successCount: { increment: 1 },
        nextRunAt: profile.paused ? null : new Date(Date.now() + profile.intervalMin * 60000),
        avgDurationMs: profile.avgDurationMs
          ? Math.round((profile.avgDurationMs * profile.runCount + durationMs) / (profile.runCount + 1))
          : durationMs,
      },
    })
    await log('info', 'system', `Pipeline complete in ${durationMs}ms`, { reportId: report.id })

    return { executionId: execution.id, snapshotId: snapshot.id, reportId: report.id, status: 'success', durationMs }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    const durationMs = Date.now() - startedAt
    await db.execution.update({
      where: { id: execution.id },
      data: { status: 'failed', finishedAt: new Date(), durationMs, error: message },
    })
    await db.profile.update({
      where: { id: profileId },
      data: {
        lastRunAt: new Date(),
        lastStatus: 'failed',
        runCount: { increment: 1 },
        failCount: { increment: 1 },
        nextRunAt: profile.paused ? null : new Date(Date.now() + profile.intervalMin * 60000),
      },
    })
    await log('error', 'system', `Pipeline failed: ${message}`)
    return { executionId: execution.id, status: 'failed', durationMs }
  }
}

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms))
}

async function sha256(s: string): Promise<string> {
  const { createHash } = await import('crypto')
  return createHash('sha256').update(s).digest('hex').slice(0, 16)
}

/** Main scheduler loop. */
export async function tick() {
  if (running || !schedulerEnabled) return
  running = true
  try {
    const due = await db.profile.findMany({
      where: {
        enabled: true,
        paused: false,
        nextRunAt: { lte: new Date() },
      },
      take: 5,
    })
    for (const p of due) {
      try {
        await runProfile(p.id, 'scheduler')
      } catch (e) {
        console.error('[scheduler] run failed', p.id, e)
      }
    }
  } finally {
    running = false
  }
}

export function startScheduler(intervalMs = 30000) {
  if (timer) return
  timer = setInterval(() => {
    tick().catch((e) => console.error('[scheduler] tick error', e))
  }, intervalMs)
  console.log('[scheduler] started, interval', intervalMs, 'ms')
  // run once immediately
  tick().catch(() => {})
}

export function stopScheduler() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}
