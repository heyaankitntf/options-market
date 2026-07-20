/**
 * Notification dispatcher.
 *
 * Supports telegram / email / whatsapp / webhook channel types.
 * Telegram dispatch is fully functional (calls the real Bot API with
 * HTML-formatted messages). Email/WhatsApp remain stubbed (would need
 * SMTP / WhatsApp Business API credentials).
 */

import { db } from './db'

interface ChannelConfig {
  [k: string]: string
}

export async function notifyChannels(
  channelIds: string[],
  profile: { symbol: string; name: string; id: string },
  reportId: string,
  headline: string,
  extra?: { pcr?: number; trend?: string; spot?: number; maxPain?: number },
) {
  const channels = await db.notificationChannel.findMany({
    where: { id: { in: channelIds }, enabled: true },
  })
  for (const ch of channels) {
    try {
      const cfg = JSON.parse(ch.config) as ChannelConfig
      const message = formatMessage(profile, headline, extra)
      await dispatch(ch.type, cfg, message)
      await db.notificationLog.create({
        data: {
          channelId: ch.id,
          reportId,
          profileId: profile.id,
          status: 'sent',
          message,
        },
      })
    } catch (e) {
      await db.notificationLog.create({
        data: {
          channelId: ch.id,
          reportId,
          profileId: profile.id,
          status: 'failed',
          error: e instanceof Error ? e.message : String(e),
        },
      })
    }
  }
}

function formatMessage(
  profile: { symbol: string; name: string },
  headline: string,
  extra?: { pcr?: number; trend?: string; spot?: number; maxPain?: number },
): string {
  const trendEmoji =
    extra?.trend === 'bullish' ? '🟢' : extra?.trend === 'bearish' ? '🔴' : '🟡'
  const lines = [
    `<b>📊 ${profile.symbol} Options Report</b>`,
    '',
    `${trendEmoji} ${headline}`,
  ]
  if (extra) {
    const stats: string[] = []
    if (extra.spot != null) stats.push(`Spot: <b>${extra.spot}</b>`)
    if (extra.pcr != null) stats.push(`PCR: <b>${extra.pcr}</b>`)
    if (extra.maxPain != null) stats.push(`Max Pain: <b>${extra.maxPain}</b>`)
    if (stats.length) lines.push('📈 ' + stats.join('  •  '))
  }
  lines.push('', `<i>Profile: ${profile.name}</i>`, `<i>OptFlow Auto • ${new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })}</i>`)
  return lines.join('\n')
}

async function dispatch(type: string, cfg: ChannelConfig, message: string) {
  switch (type) {
    case 'telegram': {
      if (!cfg.token) throw new Error('Telegram channel missing token')
      if (!cfg.chatId) throw new Error('Telegram channel missing chatId')
      const res = await fetch(
        `https://api.telegram.org/bot${cfg.token}/sendMessage`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            chat_id: cfg.chatId,
            text: message,
            parse_mode: 'HTML',
            disable_web_page_preview: true,
          }),
        },
      )
      const data = await res.json()
      if (!data.ok) {
        throw new Error(`Telegram API error: ${data.description ?? data.error_code}`)
      }
      break
    }
    case 'email': {
      // Would use nodemailer / SMTP — stubbed
      console.log('[notify:email]', cfg.to, message.replace(/<[^>]+>/g, ''))
      break
    }
    case 'whatsapp': {
      console.log('[notify:whatsapp]', cfg.phone, message.replace(/<[^>]+>/g, ''))
      break
    }
    case 'webhook': {
      if (cfg.url) {
        try {
          await fetch(cfg.url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: message.replace(/<[^>]+>/g, ''), html: message }),
          })
        } catch {
          /* swallow */
        }
      }
      break
    }
  }
}

/** Send a test message to a channel (used by the admin "Send test" button). */
export async function sendTestMessage(channelId: string): Promise<{ ok: boolean; message: string }> {
  const ch = await db.notificationChannel.findUnique({ where: { id: channelId } })
  if (!ch) return { ok: false, message: 'Channel not found' }
  try {
    const cfg = JSON.parse(ch.config) as ChannelConfig
    const testMsg = `<b>🔧 OptFlow Test Message</b>\n\nThis is a test notification from OptFlow.\nChannel: <b>${ch.name}</b>\nTime: ${new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })}`
    await dispatch(ch.type, cfg, testMsg)
    await db.notificationLog.create({
      data: { channelId, status: 'sent', message: testMsg },
    })
    return { ok: true, message: 'Test message sent successfully' }
  } catch (e) {
    const err = e instanceof Error ? e.message : String(e)
    await db.notificationLog.create({
      data: { channelId, status: 'failed', error: err },
    })
    return { ok: false, message: err }
  }
}
