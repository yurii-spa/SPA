// Sandbox E2E of the cockpit composer: REAL mission_server (subprocess, temp bundle root, temp tracker,
// no access config ⇒ local loopback listener only) driven by headless Chrome over CDP. Never the live server.
import { spawn } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";

const WT = "/tmp/spa_wt_voice2";
const PY = "/Users/yuriikulieshov/miniconda3/bin/python3";
const BASE = process.argv[2];
const BUNDLES = path.join(BASE, "bundles"), TRACKER = path.join(BASE, "tracker"), PROFILE = path.join(BASE, "chrome");
fs.mkdirSync(TRACKER, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const freePort = () => new Promise((res) => { const s = net.createServer(); s.listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => res(p)); }); });
const log = (...a) => console.log(...a);
const results = [];
const check = (name, ok, extra = "") => { results.push([name, !!ok]); log((ok ? "PASS " : "FAIL ") + name + (extra ? "  " + extra : "")); };
const cards = () => fs.readdirSync(TRACKER).filter((f) => f.startsWith("inbox-") && f.endsWith(".md"));

const env = { ...process.env, SPA_TRACKER_DIR: TRACKER, PYTHONPATH: WT };
for (const k of Object.keys(env)) if (k.startsWith("MC_")) delete env[k];

const SRV_PORT = await freePort();
if (SRV_PORT === 8790 || SRV_PORT === 8792) throw new Error("refusing live port");
let srv = null;
async function startServer() {
  srv = spawn(PY, ["-m", "spa_core.studio_os.mission_server", "--root", BUNDLES, "--port", String(SRV_PORT),
    "--access-config", path.join(BASE, "no-access-config.json")], { cwd: WT, env, stdio: ["ignore", "pipe", "pipe"] });
  srv.stderr.on("data", (d) => fs.appendFileSync(path.join(BASE, "server.log"), d));
  for (let i = 0; i < 100; i++) {
    try { const r = await fetch(`http://127.0.0.1:${SRV_PORT}/`); if (r.ok) return; } catch (e) { /* not yet */ }
    await sleep(100);
  }
  throw new Error("server did not start");
}
async function stopServer() {
  const p = srv; srv = null;
  await new Promise((r) => { p.on("exit", r); p.kill("SIGTERM"); });
}

// build a bundle into the temp root (the real builder, --root override)
await new Promise((res, rej) => {
  const b = spawn(PY, ["-m", "spa_core.studio_os.mission_build", "--root", BUNDLES], { cwd: WT, env, stdio: "inherit" });
  b.on("exit", (c) => (c === 0 ? res() : rej(new Error("mission_build exit " + c))));
});
await startServer();
log("server on", SRV_PORT, "tracker", TRACKER);

const CDP_PORT = await freePort();
const chrome = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  ["--headless=new", `--remote-debugging-port=${CDP_PORT}`, `--user-data-dir=${PROFILE}`, "--no-first-run",
   "--no-default-browser-check", "about:blank"], { stdio: "ignore" });
let wsUrl = null;
for (let i = 0; i < 100 && !wsUrl; i++) {
  try { const l = await (await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`)).json(); const pg = l.find((t) => t.type === "page"); if (pg) wsUrl = pg.webSocketDebuggerUrl; } catch (e) { /* not yet */ }
  if (!wsUrl) await sleep(100);
}
const ws = new WebSocket(wsUrl);
await new Promise((r) => ws.addEventListener("open", r));
let seq = 0; const pending = new Map();
ws.addEventListener("message", (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } });
const cdp = (method, params = {}) => new Promise((r) => { const id = ++seq; pending.set(id, r); ws.send(JSON.stringify({ id, method, params })); });
async function ev(expr) {
  const m = await cdp("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  if (m.result && m.result.exceptionDetails) throw new Error("JS: " + JSON.stringify(m.result.exceptionDetails).slice(0, 400));
  return m.result && m.result.result ? m.result.result.value : undefined;
}
async function waitFor(expr, ms = 15000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { try { const v = await ev(expr); if (v) return v; } catch (e) { /* page loading */ } await sleep(150); }
  return null;
}
const URL0 = `http://127.0.0.1:${SRV_PORT}/`;
const OPEN = `(function(){var b=[].slice.call(document.querySelectorAll('.intake-bar button'));if(b.length<2)return false;b[1].click();return !!document.getElementById('composer-text');})()`;
const STATUS = `(function(){var s=document.querySelector('#composer-root .mk-status');return s?(s.className+' | '+s.textContent):'';})()`;
const TEXT = "Проверить песочницу пульта: черновик и повтор";
const tokenReady = `(function(){var s=document.querySelector('#composer-root .mk-modal-foot .mk-btn--primary');return !!s;})()`;

await cdp("Page.enable"); await cdp("Runtime.enable");
await cdp("Page.navigate", { url: URL0 });
check("page renders the intake bar", await waitFor(`document.querySelectorAll('.intake-bar button').length>=2`));
// 1. type text → reload → draft restored
check("composer opens", await ev(OPEN));
await ev(`(function(){var t=document.getElementById('composer-text');t.value=${JSON.stringify(TEXT)};t.dispatchEvent(new Event('input'));document.querySelector('#composer-root .mk-kind[data-kind=task]').click();})()`);
const sid1 = await ev(`JSON.parse(localStorage.getItem('spa.mission.intake.draft.v1')).submission_id`);
check("draft persisted with a submission_id", !!sid1, sid1);
await cdp("Page.reload", { ignoreCache: true });
await waitFor(`document.querySelectorAll('.intake-bar button').length>=2`);
await ev(OPEN);
const restored = await ev(`document.getElementById('composer-text').value`);
check("draft restored after reload", restored === TEXT, JSON.stringify(restored));
check("kind restored", await ev(`document.querySelector('#composer-root .mk-kind[data-kind=task]').getAttribute('aria-pressed')==='true'`));
await waitFor(`!document.querySelector('#composer-root .mk-modal-foot .mk-btn--primary').disabled`);
// 2. stop server → submit ⇒ error shown, text kept, no card
await stopServer();
await ev(`document.querySelector('#composer-root .mk-modal-foot .mk-btn--primary').click()`);
const errSt = await waitFor(`(function(){var s=document.querySelector('#composer-root .mk-status');return s&&/mk-status--problem/.test(s.className)?s.textContent:'';})()`, 40000);
check("error shown while the server is down", !!errSt, JSON.stringify(errSt));
check("text kept after the failed submit", (await ev(`document.getElementById('composer-text').value`)) === TEXT);
check("no card while down", cards().length === 0);
// 3. restart → submit ⇒ 1 card (CSRF key rotated by the restart; the page re-fetches once)
await startServer();
await waitFor(`!document.querySelector('#composer-root .mk-modal-foot .mk-btn--primary').disabled`);
await ev(`document.querySelector('#composer-root .mk-modal-foot .mk-btn--primary').click()`);
const okSt = await waitFor(`(function(){var s=document.querySelector('#composer-root .mk-status');return s&&/mk-status--ok/.test(s.className)?s.textContent:'';})()`, 40000);
check("submit after restart succeeds", !!okSt, JSON.stringify(okSt));
check("exactly 1 card after the retry-after-restart", cards().length === 1, cards().join(","));
check("card carries the composer's submission_id", fs.readFileSync(path.join(TRACKER, cards()[0]), "utf8").includes("submission_id: " + sid1));
check("draft cleared after success", (await ev(`localStorage.getItem('spa.mission.intake.draft.v1')`)) === null);
// 4. a network-level retry of the SAME request (same submission_id) ⇒ still 1
const dup = await ev(`(async function(){var tk=(await (await fetch('/api/intake/csrf',{cache:'no-store'})).json()).token;
  var r=await fetch('/api/intake/submit',{method:'POST',headers:{'Content-Type':'application/json','X-Intake-Token':tk},
  body:JSON.stringify({text:${JSON.stringify(TEXT)},kind:'task',submission_id:${JSON.stringify(sid1)}})});return await r.json();})()`);
check("retry with the same id answers duplicate", dup && dup.ok && dup.duplicate === true, JSON.stringify(dup && { duplicate: dup.duplicate, card: dup.card }));
check("still exactly 1 card", cards().length === 1);
// 5. close, open the composer anew, identical text ⇒ a deliberate second note ⇒ 2 cards
await ev(`document.querySelector('#composer-root .mk-modal-foot .mk-btn:not(.mk-btn--primary)').click()`);
await ev(OPEN);
await ev(`(function(){var t=document.getElementById('composer-text');t.value=${JSON.stringify(TEXT)};t.dispatchEvent(new Event('input'));document.querySelector('#composer-root .mk-kind[data-kind=task]').click();})()`);
const sid2 = await ev(`JSON.parse(localStorage.getItem('spa.mission.intake.draft.v1')).submission_id`);
check("new composer session has a new submission_id", sid2 && sid2 !== sid1, sid2);
await waitFor(`!document.querySelector('#composer-root .mk-modal-foot .mk-btn--primary').disabled`);
await ev(`document.querySelector('#composer-root .mk-modal-foot .mk-btn--primary').click()`);
const ok2 = await waitFor(`(function(){var s=document.querySelector('#composer-root .mk-status');return s&&/mk-status--ok/.test(s.className)?s.textContent:'';})()`, 40000);
check("second identical note accepted (not 'already recorded')", !!ok2, JSON.stringify(ok2));
check("2 cards after the deliberate identical second note", cards().length === 2, cards().join(","));

ws.close(); chrome.kill("SIGTERM"); await stopServer();
const failed = results.filter((r) => !r[1]).length;
log(`\n${results.length - failed}/${results.length} checks passed`);
process.exit(failed ? 1 : 0);
