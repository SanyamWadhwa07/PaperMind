/**
 * Load every route and fail on any console error or uncaught exception.
 *
 * The point is to catch what lint and the production build cannot: runtime
 * errors that only appear when a component actually renders. A hook dependency
 * array naming a `const` declared further down the component is exactly that —
 * legal syntax, clean build, dead page — and it is the reason this exists.
 *
 * Usage (dev server and API must already be running):
 *
 *   npm run smoke
 *   SMOKE_EMAIL=you@example.com SMOKE_PASSWORD=… npm run smoke
 *
 * Without credentials it covers the public routes only. With them it signs in
 * and walks the authenticated pages plus every tab of a real summary, which is
 * where most of the rendering surface actually is.
 */
import { chromium } from 'playwright'

const BASE = process.env.SMOKE_BASE || 'http://localhost:3000'
const EMAIL = process.env.SMOKE_EMAIL
const PASSWORD = process.env.SMOKE_PASSWORD

const PUBLIC_ROUTES = ['/', '/login', '/signup', '/forgot-password', '/nope-404']
const AUTHED_ROUTES = ['/dashboard', '/batch', '/explore', '/timeline', '/discover', '/profile']

const problems = []

function watch(page, label) {
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return
    const text = msg.text()
    // Failed API calls are expected without a live library; we are hunting
    // React/JS errors, not HTTP status noise.
    if (/Failed to load resource|net::ERR|status of 4\d\d|status of 5\d\d/.test(text)) return
    problems.push(`[${label}] console.error: ${text}`)
  })
  page.on('pageerror', (err) => {
    problems.push(`[${label}] pageerror: ${err.message}`)
  })
}

const browser = await chromium.launch()
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await context.newPage()
watch(page, 'boot')

for (const route of PUBLIC_ROUTES) {
  page.removeAllListeners('console')
  page.removeAllListeners('pageerror')
  watch(page, route)
  await page.goto(BASE + route, { waitUntil: 'networkidle' }).catch((e) => {
    problems.push(`[${route}] navigation failed: ${e.message}`)
  })
  await page.waitForTimeout(400)
  const crashed = await page.locator('text=This page stopped working').count()
  if (crashed) problems.push(`[${route}] error boundary tripped`)
  console.log(`visited ${route}`)
}

if (EMAIL && PASSWORD) {
  page.removeAllListeners('console')
  page.removeAllListeners('pageerror')
  watch(page, 'login')
  await page.goto(BASE + '/login', { waitUntil: 'networkidle' })
  await page.fill('input[type="email"]', EMAIL)
  await page.fill('input[type="password"]', PASSWORD)
  await page.click('button[type="submit"]')
  await page.waitForURL(/dashboard/, { timeout: 20000 }).catch(() => {
    problems.push('[login] never reached /dashboard')
  })

  for (const route of AUTHED_ROUTES) {
    page.removeAllListeners('console')
    page.removeAllListeners('pageerror')
    watch(page, route)
    await page.goto(BASE + route, { waitUntil: 'networkidle' }).catch((e) => {
      problems.push(`[${route}] navigation failed: ${e.message}`)
    })
    await page.waitForTimeout(800)
    const crashed = await page.locator('text=This page stopped working').count()
    if (crashed) problems.push(`[${route}] error boundary tripped`)
    console.log(`visited ${route}`)
  }

  // Open the first paper in the library, which is the page that crashed.
  page.removeAllListeners('console')
  page.removeAllListeners('pageerror')
  watch(page, '/summary/:id')
  await page.goto(BASE + '/dashboard', { waitUntil: 'networkidle' })
  const link = page.locator('a[href^="/summary/"]').first()
  if (await link.count()) {
    const href = await link.getAttribute('href')
    await page.goto(BASE + href, { waitUntil: 'networkidle' })
    await page.waitForTimeout(1200)
    const crashed = await page.locator('text=This page stopped working').count()
    if (crashed) problems.push(`[${href}] error boundary tripped`)
    console.log(`visited ${href}`)

    // Every tab, since each renders a different subtree.
    for (const tab of ['Entities', 'Figures', 'Tables', 'Graph', 'Intelligence']) {
      const btn = page.locator(`button:has-text("${tab}")`).first()
      if (await btn.count()) {
        await btn.click().catch(() => {})
        await page.waitForTimeout(900)
        const broke = await page.locator('text=This page stopped working').count()
        if (broke) problems.push(`[summary tab ${tab}] error boundary tripped`)
        console.log(`  tab ${tab}`)
      }
    }
    if (process.env.SHOT_DIR) {
      await page.screenshot({ path: process.env.SHOT_DIR + '/summary.png' })
    }
  } else {
    console.log('(no papers in library — skipped /summary/:id)')
  }
} else {
  console.log('(no SMOKE_EMAIL/SMOKE_PASSWORD — authed routes skipped)')
}

await browser.close()

console.log('\n' + '='.repeat(60))
if (problems.length) {
  console.log(`FAILED — ${problems.length} problem(s):`)
  for (const p of problems) console.log('  - ' + p)
  process.exit(1)
}
console.log('CLEAN — no console errors, no uncaught exceptions, no tripped boundaries')
