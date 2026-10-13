// Browser check of web/erklaerung/index.html: stations, actions, target model, CSP, no requests, layout.
// Run: make web-check (needs Node.js and Playwright: npm install -g playwright, then
// npx playwright install chromium). SHOTS=<dir> also writes screenshots there.
const path = require("path");
const { chromium } = require("playwright");
const PAGE = "file://" + path.resolve(__dirname, "../erklaerung/index.html");
const OUT = process.env.SHOTS || "";
if (OUT) require("fs").mkdirSync(OUT, { recursive: true });
const shot = (page, name, opts = {}) => OUT ? page.screenshot({ path: path.join(OUT, name), ...opts }) : Promise.resolve();
let failures = 0;
const check = (ok, msg) => { if (!ok) { failures++; console.log("FAIL", msg); } };

async function settle(page) {
  await page.waitForFunction(() => busy === 0, null, { timeout: 30000 });
}
async function station(page, id) {
  await page.evaluate(i => showStation(STATIONS.findIndex(s => s.id === i)), id);
}
async function act(page, sel) {
  await page.click(sel); await settle(page);
  return page.$eval("#result-list", el => el.innerText);
}

(async () => {
  const browser = await chromium.launch();
  for (const [lang, scheme] of [["de", "light"], ["en", "dark"]]) {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: "reduce", colorScheme: scheme });
    const page = await ctx.newPage();
    const requests = [], errors = [];
    page.on("request", r => { if (!/^(file|data):/.test(r.url())) requests.push(r.url()); });
    page.on("pageerror", e => errors.push(String(e)));
    page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
    await page.addInitScript(() => document.addEventListener("securitypolicyviolation", e => console.error("CSP " + e.violatedDirective)));
    await page.goto(`${PAGE}?lang=${lang}`);
    check(await page.evaluate(() => deriveClientId("2150551891")) === "c4b06565c3cea7d66c4a6", "client ID derivation gw1");
    check(await page.evaluate(() => GW.every(g => deriveClientId(g.serial) === g.cid)), "client ID derivation all GW");
    check(await page.evaluate(() => deriveClientId("1") === "c" + "" + sha256hex("enetec-lab-v0:1").slice(0, 20)), "derivation shape");
    check(await page.evaluate(() => sha256hex("abc")) === "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", "sha256 abc");
    check(await page.evaluate(() => sha256hex("a".repeat(1000))) === "41edece42d63e8d9bf515a9ba6932e1c20cbc9f5a5d134645adb5db1b9737ea3", "sha256 1000a");

    // Stationen durchklicken
    const n = await page.evaluate(() => STATIONS.length);
    for (let i = 0; i < n; i++) {
      await page.click(`#stations [data-station="${i}"]`);
      const h2 = await page.$eval("#panel h2", el => el.textContent);
      check(h2.length > 2, `station ${i} heading`);
      const ov = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
      check(ov <= 0, `station ${i} horizontal overflow ${ov}`);
      if (lang === "de") await shot(page, `${lang}-s${i + 1}.png`);
    }
    // Bauteil im Bild anklicken
    await page.evaluate(() => showStation(1));
    await page.click('#plant [data-id="valve"] circle.plastic-ring');
    check(await page.evaluate(() => STATIONS[current].id) === "switch", "click on valve opens switch");

    const R = {};
    await station(page, "idea");
    R.round = await act(page, '[data-act="round"]');
    check(/PUBACK 0x00/.test(R.round) && /R13|R09/.test(R.round), "round: " + R.round);

    await station(page, "idcheck");
    for (const cert of ["none", "rogue", "expired", "revoked"]) {
      await page.selectOption("#f-cert", cert);
      const t = await act(page, '[data-act="idcheck"]');
      check(/CONNACK/.test(t) === false || /kein CONNACK|no CONNACK/.test(t), `${cert}: no CONNACK claimed`);
      check(/R0[234]/.test(t), `${cert}: requirement`);
      check(await page.evaluate(() => sim.gws[0].online), `${cert}: existing connection stays`);
    }
    await page.selectOption("#f-cert", "valid");
    R.dup = await act(page, '[data-act="idcheck"]');
    check(/R11/.test(R.dup) && /0x8E/.test(R.dup) && await page.evaluate(() => sim.gws[0].online), "duplicate client ID R11: " + R.dup);
    await page.selectOption("#f-cid", "other");
    R.foreign = await act(page, '[data-act="idcheck"]');
    check(/0x85/.test(R.foreign) && /R06/.test(R.foreign), "foreign client ID: " + R.foreign);
    await page.selectOption("#f-cid", "own");
    await act(page, '[data-act="drop:0"]');
    await page.selectOption("#f-cert", "expired");
    await act(page, '[data-act="idcheck"]');
    check(await page.evaluate(() => sim.gws[0].rejected && !sim.gws[0].online), "offline gateway turned away becomes red");
    await page.selectOption("#f-cert", "valid");
    R.reconn = await act(page, '[data-act="idcheck"]');
    check(/session_present = 1/.test(R.reconn) && await page.evaluate(() => sim.gws[0].online && !sim.gws[0].rejected), "reconnect: " + R.reconn);

    await station(page, "switch");
    for (const [op, topics] of [["pub", ["own_state", "own_cmd", "other_state", "outside"]], ["sub", ["own_cmd", "own_state", "other_cmd", "wildcard"]]]) {
      await page.selectOption("#f-op", op);
      for (const tp of topics) {
        await page.selectOption("#f-topic", tp);
        const hit = await page.$$eval("pre.acl .hit", e => e.length), miss = await page.$$eval("pre.acl .miss", e => e.length);
        const allowed = (op === "pub" && tp === "own_state") || (op === "sub" && tp === "own_cmd");
        check(allowed ? hit === 1 && miss === 0 : hit === 0 && miss === 1, `${op}/${tp} ACL highlight`);
        const t = await act(page, '[data-act="acl"]');
        const code = allowed ? (op === "pub" ? "PUBACK 0x00" : "SUBACK 0x01") : (op === "pub" ? "PUBACK 0x87" : "SUBACK 0x87");
        check(t.includes(code), `${op}/${tp}: expected ${code}: ${t}`);
      }
    }

    await station(page, "bypass");
    await act(page, '[data-act="drop:1"]');
    await act(page, '[data-act="cmd:1"]');
    await act(page, '[data-act="cmd:1"]');
    check(await page.evaluate(() => sim.gws[1].queue === 2), "two commands parked");
    R.back = await act(page, '[data-act="conn:1"]');
    check(/session_present = 1/.test(R.back) && /2 waiting|2 wartende/.test(R.back), "back with Clean Start false delivers: " + R.back);
    await act(page, '[data-act="drop:1"]');
    await act(page, '[data-act="cmd:1"]');
    R.clean = await act(page, '[data-act="connclean:1"]');
    check(/session_present = 0/.test(R.clean) && /1 waiting|1 wartende/.test(R.clean) && /SUBACK 0x01/.test(R.clean), "Clean Start true drops: " + R.clean);
    await act(page, '[data-act="drop:1"]');
    R.exp = await act(page, '[data-act="expire:1"]');
    R.lost = await act(page, '[data-act="cmd:1"]');
    check(/0x10/.test(R.lost), "command after expiry: " + R.lost);
    R.new = await act(page, '[data-act="conn:1"]');
    check(/session_present = 0/.test(R.new) && /SUBACK 0x01/.test(R.new), "new session after expiry: " + R.new);

    await station(page, "cloud");
    const before = await page.evaluate(() => sim.ingest);
    await act(page, '[data-act="allstate"]');
    check(await page.evaluate(b => sim.ingest === b + sim.gws.filter(g => g.online).length, before), "all connected gateways reach ingest");

    await station(page, "return");
    await page.selectOption("#f-target", "2");
    R.cmd = await act(page, '[data-act="cmdsel"]');
    check(/gw-sim-000003/.test(R.cmd), "command to gw3: " + R.cmd);

    await station(page, "clientid");
    await page.fill("#f-serial", "280218189");
    check(await page.$eval("#out-cid", e => e.textContent) === "c446bfb561d0c4245c0e7", "serial input derives gw2 client ID");
    check(await page.$eval("#card-cid", e => e.textContent) === "c446bfb561d0c4245c0e7", "card follows input");
    await page.fill("#f-serial", "4294967296");
    check(!/^c[0-9a-f]{20}$/.test(await page.$eval("#out-cid", e => e.textContent)), "out of range serial refused");
    await page.fill("#f-serial", "2150551891");

    await station(page, "who");
    check(await page.$eval("#to-kit-2", e => e.getAttribute("href")) === await page.$eval("#to-kit", e => e.getAttribute("href")), "who links the kit like the header");

    const log = await page.$eval("#log", e => e.innerText);
    for (const want of ["New client connected from", "OpenSSL Error[0]", "Denied PUBLISH", "has exceeded timeout", "Expiring client"]) check(log.includes(want), "log has " + want);
    const times = await page.evaluate(() => logLines.map(l => l.t));
    check(times.every((t, k) => !k || t >= times[k - 1]), "log clock is monotonic");
    await station(page, "measure");
    await shot(page, `${lang}-measure-after.png`, { fullPage: true });

    // Sprache umschalten mitten im Zustand
    await page.click(`#lang-seg [data-lang="${lang === "de" ? "en" : "de"}"]`);
    check(await page.evaluate(() => document.documentElement.lang) === (lang === "de" ? "en" : "de"), "language toggles");
    check(await page.evaluate(() => logLines.length > 0), "state survives language switch");

    await page.click('[data-act="reset"]');
    check(await page.evaluate(() => sim.gws.every(g => g.online && g.session && !g.queue) && logLines.length === 0), "reset");

    check(requests.length === 0, "external requests: " + requests.join(", "));
    check(errors.length === 0, "errors: " + errors.join(" | "));
    await ctx.close();
  }

  // Breiten
  for (const w of [360, 390, 768, 1024, 1440]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: 860 }, reducedMotion: "reduce" });
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", e => errors.push(String(e)));
    await page.goto(`${PAGE}?lang=de#s7`);
    const ov = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
    check(ov <= 0, `width ${w}: page overflow ${ov}`);
    await shot(page, `w${w}.png`, { fullPage: w <= 390 });
    check(errors.length === 0, `width ${w} errors ` + errors.join("|"));
    await ctx.close();
  }

  // Animation (ohne reduzierte Bewegung): Paket unterwegs
  {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await ctx.newPage();
    await page.goto(`${PAGE}?lang=de#s2`);
    await page.click('[data-act="round"]');
    await page.waitForTimeout(1500);
    check(await page.$$eval("#tokens > g", e => e.length) >= 1, "token in flight");
    await shot(page, "anim.png");
    await settle(page);
    check(await page.$$eval("#tokens > g", e => e.length) === 0, "tokens cleaned up");
    await ctx.close();
  }
  await browser.close();
  console.log(failures ? `${failures} FAILURES` : "ALL OK");
  process.exit(failures ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
