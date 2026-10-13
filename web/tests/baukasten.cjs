// Browser check of web/baukasten/index.html: every action on every broker, lessons, tabs, languages, wire profiles, palette, widths, CSP, no external requests.
// Run: make web-check (needs Node.js and Playwright: npm install -g playwright, then
// npx playwright install chromium). SHOTS=<dir> also writes screenshots there.
const path = require("path");
const { chromium } = require("playwright");
const PAGE = "file://" + path.resolve(__dirname, "../baukasten/index.html");
const OUT = process.env.SHOTS || "";
if (OUT) require("fs").mkdirSync(OUT, { recursive: true });
const shot = (page, name, opts = {}) => OUT ? page.screenshot({ path: path.join(OUT, name), ...opts }) : Promise.resolve();
let failures = 0, checks = 0;
const check = (ok, msg) => { checks++; if (!ok) { failures++; console.log("FAIL", msg); } };
const idle = p => p.waitForFunction(() => !running, null, { timeout: 30000 });

async function newPage(browser, opts = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce", ...opts });
  await ctx.addInitScript(() => { window.__csp = []; document.addEventListener("securitypolicyviolation", e => window.__csp.push(e.violatedDirective)); });
  const page = await ctx.newPage();
  page.__errors = []; page.__requests = [];
  page.on("pageerror", e => page.__errors.push(String(e)));
  page.on("console", m => { if (m.type() === "error") page.__errors.push(m.text()); });
  page.on("request", r => { if (!/^(file|data):/.test(r.url())) page.__requests.push(r.url()); });
  return { ctx, page };
}
async function clean(page, label) {
  check(page.__errors.length === 0, `${label}: errors ${page.__errors.join(" | ")}`);
  check(page.__requests.length === 0, `${label}: requests ${page.__requests.join(", ")}`);
  check((await page.evaluate(() => window.__csp.length)) === 0, `${label}: CSP violations`);
}

(async () => {
  const browser = await chromium.launch();
  for (const lang of ["de", "en"]) {
    const { ctx, page } = await newPage(browser, { colorScheme: lang === "en" ? "dark" : "light" });
    await page.goto(`${PAGE}?lang=${lang}`);
    check(await page.evaluate(() => document.documentElement.lang) === lang, `${lang}: lang attribute`);
    await page.click("#btn-lab");
    const gws = await page.$$eval("[data-gw]", e => e.length);
    check(gws === 12, `${lang}: lab fleet has 12 gateways (got ${gws})`);

    // Jede Aktion eines normalen Gateways bei jedem Broker
    for (const broker of ["mosquitto-lab", "emqx", "emqx-registry", "cedalo"]) {
      await page.click(`#broker-switch [data-switch-broker="${broker}"]`); await idle(page);
      await page.click('[data-gw="gw-sim-000001"]');
      const ids = await page.$$eval('#inspect [data-action]:not([disabled])', e => e.map(b => b.dataset.action));
      check(ids.length >= 20, `${lang}/${broker}: actions available (${ids.length})`);
      for (const id of ids) {
        await page.click(`#inspect [data-action="${id}"]`); await idle(page);
        const proto = await page.$eval("#protocol", e => e.innerText);
        const rows = await page.$$eval("#monitor li .lvl", e => e.length);
        check(rows >= 1 && /\S/.test(proto), `${lang}/${broker}/${id}: flow shown`);
        if (broker === "cedalo") check(/nicht gemessen|not measured|kein Lauf|no run/i.test(proto), `${lang}/cedalo/${id}: shown as not measured`);
        else check(await page.$(".stamp") !== null, `${lang}/${broker}/${id}: verdict stamp`);
        // Kein Symbolzeichen-Rest im Ablauf
        check(!/[✓✕]/.test(proto + await page.$eval("#monitor", e => e.innerText)), `${lang}/${broker}/${id}: no ✓/✕ glyphs`);
      }
      // Broker-Aktionen
      await page.click('[data-node="broker"]');
      for (const id of await page.$$eval('#inspect [data-action]:not([disabled])', e => e.map(b => b.dataset.action))) {
        await page.click(`#inspect [data-action="${id}"]`); await idle(page);
        check((await page.$$eval("#monitor li", e => e.length)) >= 1, `${lang}/${broker}/broker:${id}: flow shown`);
      }
      // Legacy-Gateway
      await page.click('[data-gw="0000000000000005"]');
      for (const id of await page.$$eval('#inspect [data-action]:not([disabled])', e => e.map(b => b.dataset.action))) {
        await page.click(`#inspect [data-action="${id}"]`); await idle(page);
        check((await page.$$eval("#monitor li", e => e.length)) >= 1, `${lang}/${broker}/legacy:${id}: flow shown`);
      }
    }
    // Lernpfad
    for (let i = 0; i < 7; i++) { await page.click(`[data-lesson="${i}"]`); await idle(page); await page.waitForTimeout(50); }
    const prog = await page.$eval("#lesson-progress", e => e.innerText);
    check(/7 (von|of) 7/.test(prog), `${lang}: all lessons done (${prog.trim()})`);
    // Pult-Reiter
    for (const tab of ["vergleich", "konfiguration", "export", "glossar"]) {
      await page.click(`#tabs [data-tab="${tab}"]`);
      check((await page.$eval("#tabpanel", e => e.innerText.length)) > 200, `${lang}: tab ${tab} has content`);
    }
    await page.click('#tabs [data-tab="vergleich"]');
    await page.click('table.cmp [data-cmp^="R06|"]');
    check(/ID-01/.test(await page.$eval("#tabpanel", e => e.innerText)), `${lang}: compare detail lists ID-01`);
    // Topic-Schema umschalten
    await page.click('[data-wire="lab-eicp"]');
    check(/lab-eicp/.test(await page.$eval("#plate", e => e.innerText)), `${lang}: wire profile switches`);
    await page.click('[data-wire="v13"]');
    // Bausteinleiste: Gateway antippen fügt eines hinzu
    await page.click('[data-select-plant="plt_sim_001"]');
    const before = await page.$$eval("[data-gw]", e => e.length);
    await page.click('.pblock[data-idx="2"]');
    check((await page.$$eval("[data-gw]", e => e.length)) === before + 1, `${lang}: palette adds a gateway`);
    // Leer beginnen
    await page.click("#btn-empty");
    check((await page.$$eval(".slot-empty", e => e.length)) >= 2, `${lang}: empty state shows drop slots`);
    check(!/Erklärfilm/.test(await page.content()), `${lang}: no "Erklärfilm" left`);
    await page.click("#btn-lab");
    await shot(page, `test-${lang}.png`, { fullPage: true });
    await clean(page, lang);
    await ctx.close();
  }
  // Breiten
  for (const w of [360, 390, 600, 780, 1024, 1240, 1440, 1680]) {
    const { ctx, page } = await newPage(browser, { viewport: { width: w, height: 900 } });
    await page.goto(`${PAGE}?lang=de`);
    await page.click("#btn-lab");
    await page.click('[data-gw="gw-sim-000001"]');
    await page.click('#inspect [data-action="pub_other"]'); await idle(page);
    const ov = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    check(ov <= 0, `width ${w}: horizontal overflow ${ov}px`);
    // Inspektor und Leiste überlappen sich nicht
    const overlap = await page.evaluate(() => {
      const a = document.querySelector(".palette").getBoundingClientRect(), b = document.querySelector(".inspector").getBoundingClientRect();
      return !(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top);
    });
    check(!overlap, `width ${w}: palette overlaps inspector`);
    if (w === 390 || w === 1024) await shot(page, `w${w}.png`, { fullPage: true });
    await clean(page, `width ${w}`);
    await ctx.close();
  }
  // Animation: Pakete liegen über den Bausteinen
  {
    const { ctx, page } = await newPage(browser, { reducedMotion: "no-preference" });
    await page.goto(`${PAGE}?lang=de`);
    await page.click("#btn-lab");
    await page.click('[data-gw="gw-sim-000001"]');
    await page.click('#inspect [data-action="pub_own"]');
    await page.waitForFunction(() => document.querySelector("#packets .pkt"), null, { timeout: 5000 });
    check(true, "packet drawn in #packets layer");
    await idle(page);
    check((await page.$$eval("#packets .pkt", e => e.length)) === 0, "packets cleaned up");
    await clean(page, "animation");
    await ctx.close();
  }
  await browser.close();
  console.log(`${checks} checks, ${failures ? failures + " FAILURES" : "ALL OK"}`);
  process.exit(failures ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
