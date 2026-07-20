/**
 * Runs once on server boot. Starts the automation scheduler.
 */
export async function register() {
  if (process.env.NEXT_RUNTIME === 'nodejs') {
    const { startScheduler } = await import('./lib/scheduler')
    startScheduler(30000)
  }
}
