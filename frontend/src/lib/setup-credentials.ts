/**
 * Configure real credentials: Telegram bot + icharts portal login.
 *
 * Usage: bun run src/lib/setup-credentials.ts
 *
 * This script:
 *   1. Updates the "Trading Desk Telegram" channel with the real bot token
 *      and the @quant_opt group chat ID.
 *   2. Replaces the demo icharts credential with the real portal login
 *      (encrypted at rest with AES-256-GCM).
 */

import { db } from './db'
import { encrypt } from './crypto'

async function main() {
  // ---- Telegram channel ----
  const TELEGRAM_TOKEN = '8912931610:AAG2fipnBUy-G-2EqsdhFCSE6oPfkWfPUgA'
  const TELEGRAM_CHAT_ID = '-1004376202654' // @quant_opt supergroup

  const tg = await db.notificationChannel.findFirst({ where: { name: 'Trading Desk Telegram' } })
  if (tg) {
    await db.notificationChannel.update({
      where: { id: tg.id },
      data: {
        enabled: true,
        config: JSON.stringify({ token: TELEGRAM_TOKEN, chatId: TELEGRAM_CHAT_ID }),
      },
    })
    console.log('✓ Updated Telegram channel:', tg.id)
  } else {
    const created = await db.notificationChannel.create({
      data: {
        name: 'Trading Desk Telegram',
        type: 'telegram',
        enabled: true,
        config: JSON.stringify({ token: TELEGRAM_TOKEN, chatId: TELEGRAM_CHAT_ID }),
      },
    })
    console.log('✓ Created Telegram channel:', created.id)
  }

  // ---- icharts credential (encrypted) ----
  const ICHARTS_USERNAME = 'aakansha001'
  const ICHARTS_PASSWORD = 'ntf12345'

  const enc = encrypt(ICHARTS_PASSWORD)
  const existing = await db.credential.findFirst({ where: { label: 'icharts-primary' } })
  if (existing) {
    await db.credential.update({
      where: { id: existing.id },
      data: {
        username: ICHARTS_USERNAME,
        cipher: enc.cipher,
        iv: enc.iv,
        tag: enc.tag,
        active: true,
      },
    })
    console.log('✓ Updated icharts credential:', existing.id)
  } else {
    const created = await db.credential.create({
      data: {
        label: 'icharts-primary',
        portal: 'icharts',
        username: ICHARTS_USERNAME,
        cipher: enc.cipher,
        iv: enc.iv,
        tag: enc.tag,
        active: true,
      },
    })
    console.log('✓ Created icharts credential:', created.id)
  }

  // Make sure all profiles use the Telegram channel
  const tgChannel = await db.notificationChannel.findFirst({ where: { name: 'Trading Desk Telegram' } })
  if (tgChannel) {
    const profiles = await db.profile.findMany()
    for (const p of profiles) {
      const channels = p.notifyChannels.split(',').filter(Boolean)
      if (!channels.includes(tgChannel.id)) {
        channels.push(tgChannel.id)
        await db.profile.update({ where: { id: p.id }, data: { notifyChannels: channels.join(',') } })
        console.log(`  → linked ${p.symbol} profile to Telegram channel`)
      }
    }
  }

  console.log('\n✅ Configuration complete. Telegram messages will be sent to @quant_opt.')
  await db.$disconnect()
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
