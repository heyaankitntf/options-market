/**
 * Seed the database with sensible defaults so the app is usable on first load.
 */

import { db } from './db'
import { encrypt } from './crypto'
import { SYMBOL_SPECS } from './mock-market'

async function main() {
  // Default formula template
  const template = await db.formulaTemplate.upsert({
    where: { name: 'Default Options Template' },
    update: {},
    create: {
      name: 'Default Options Template',
      description: 'Standard PCR / Max Pain / IV / trend scoring (v1)',
      version: 1,
      enabled: true,
      configJson: JSON.stringify({
        atmRange: 2,
        pcrBullThreshold: 1.1,
        pcrBearThreshold: 0.9,
        trendWeights: { pcr: 40, oiShift: 25, ivSkew: 15, chgOi: 20 },
        supportResistanceLookback: 5,
      }),
    },
  })

  // Demo portal credential (encrypted). Password is "demo-password".
  const enc = encrypt('demo-password')
  await db.credential.upsert({
    where: { label: 'icharts-primary' },
    update: {},
    create: {
      label: 'icharts-primary',
      portal: 'icharts',
      username: 'demo@optflow.io',
      cipher: enc.cipher,
      iv: enc.iv,
      tag: enc.tag,
      active: true,
    },
  })

  // Notification channels
  const tg = await db.notificationChannel.upsert({
    where: { name: 'Trading Desk Telegram' },
    update: {},
    create: {
      name: 'Trading Desk Telegram',
      type: 'telegram',
      enabled: true,
      config: JSON.stringify({ token: '***bot-token***', chatId: '@optflow-desk' }),
    },
  })
  const em = await db.notificationChannel.upsert({
    where: { name: 'Desk Email Digest' },
    update: {},
    create: {
      name: 'Desk Email Digest',
      type: 'email',
      enabled: false,
      config: JSON.stringify({ smtp: 'smtp://mail.example.com', to: 'desk@example.com' }),
    },
  })

  // Profiles — staggered nextRunAt so they trickle in
  const now = Date.now()
  const intervals = [5, 10, 10, 15, 15]
  for (let i = 0; i < SYMBOL_SPECS.length; i++) {
    const spec = SYMBOL_SPECS[i]
    const exists = await db.profile.findFirst({ where: { symbol: spec.symbol } })
    if (exists) continue
    await db.profile.create({
      data: {
        name: `${spec.label} Auto`,
        symbol: spec.symbol,
        exchange: 'NFO',
        expiryKind: spec.symbol === 'SENSEX' ? 'weekly' : 'weekly',
        intervalMin: intervals[i],
        templateId: template.id,
        outputFormats: 'json,csv',
        enabled: true,
        paused: false,
        allStrikes: true,
        notifyChannels: `${tg.id},${em.id}`,
        nextRunAt: new Date(now + i * 8000),
        lastStatus: null,
      },
    })
  }

  // Admin user
  await db.user.upsert({
    where: { email: 'admin@optflow.io' },
    update: {},
    create: {
      email: 'admin@optflow.io',
      name: 'Administrator',
      password: 'admin123',
      role: 'admin',
      active: true,
    },
  })

  // System settings
  const settings = [
    ['scheduler.enabled', 'true'],
    ['scheduler.intervalMs', '30000'],
    ['market.hours.start', '09:15'],
    ['market.hours.end', '15:30'],
    ['portal.url', 'https://www.icharts.in/opt/index.php'],
    ['portal.timeout', '45000'],
    ['retry.maxAttempts', '3'],
    ['retry.backoffMs', '2000'],
    ['storage.retentionDays', '90'],
  ]
  for (const [k, v] of settings) {
    await db.systemSetting.upsert({ where: { id: k }, update: {}, create: { id: k, value: v } })
  }

  console.log('Seed complete. Profiles:', await db.profile.count())
}

main()
  .catch((e) => {
    console.error(e)
    process.exit(1)
  })
  .finally(async () => {
    await db.$disconnect()
  })
