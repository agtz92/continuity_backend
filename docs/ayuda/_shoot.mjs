// Screenshots de las "shots" del HTML de ayuda usando Chrome via CDP.
// Node 26 trae WebSocket global → cero dependencias.
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, rmSync } from "node:fs";
import { setTimeout as sleep } from "node:timers/promises";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PORT = 9333;
const HERE = new URL(".", import.meta.url).pathname;
const SRC_FILE = process.argv[2] || "today.html";
const OUT_DIR = process.argv[3] || "es/img";
const PREFIX = process.argv[4] ||
  SRC_FILE.split("/").pop().replace(/\.html$/, "").replace(/\.en$/, "").replace(/-view$/, "");
const SRC = `file://${HERE}${SRC_FILE}`;
const OUT = `${HERE}${OUT_DIR}`;
const SCALE = 2;            // retina
const LAYOUT_WIDTH = 820;   // < 860 → una columna, sin TOC

mkdirSync(OUT, { recursive: true });
const tmp = `${HERE}.chrome-tmp-${PREFIX}-${OUT_DIR.replace(/\//g, "_")}`;
rmSync(tmp, { recursive: true, force: true });

const chrome = spawn(CHROME, [
  "--headless=new", "--disable-gpu", "--hide-scrollbars",
  "--no-first-run", "--no-default-browser-check",
  `--user-data-dir=${tmp}`, `--remote-debugging-port=${PORT}`,
], { stdio: "ignore" });

// --- esperar a que el endpoint esté listo ---
async function getJSON(path) {
  for (let i = 0; i < 100; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}${path}`);
      if (r.ok) return await r.json();
    } catch {}
    await sleep(100);
  }
  throw new Error("Chrome no respondió en " + path);
}
const version = await getJSON("/json/version");

// --- cliente CDP mínimo sobre WebSocket, con soporte de sessionId ---
function cdpClient(wsUrl) {
  const ws = new WebSocket(wsUrl);
  let id = 0;
  const pending = new Map();
  const ready = new Promise((res) => (ws.onopen = res));
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
    }
  };
  const send = (method, params = {}, sessionId) =>
    new Promise((resolve, reject) => {
      const m = { id: ++id, method, params };
      if (sessionId) m.sessionId = sessionId;
      pending.set(m.id, { resolve, reject });
      ws.send(JSON.stringify(m));
    });
  return { ready, send, ws };
}

const browser = cdpClient(version.webSocketDebuggerUrl);
await browser.ready;

const { targetId } = await browser.send("Target.createTarget", { url: "about:blank" });
const { sessionId } = await browser.send("Target.attachToTarget", { targetId, flatten: true });
const S = (method, params) => browser.send(method, params, sessionId);

await S("Page.enable");
await S("Emulation.setDeviceMetricsOverride", {
  width: LAYOUT_WIDTH, height: 3000, deviceScaleFactor: 1, mobile: false,
});

// navegar + esperar load
const loaded = new Promise((res) => {
  const handler = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.method === "Page.loadEventFired") { browser.ws.removeEventListener("message", handler); res(); }
  };
  browser.ws.addEventListener("message", handler);
});
await S("Page.navigate", { url: SRC });
await loaded;
await sleep(400); // fuentes/layout

// medir cada .shot + nombre de sección
const { result } = await S("Runtime.evaluate", {
  returnByValue: true,
  expression: `(() => {
    const slug = (s)=>s||"shot";
    const shots = [...document.querySelectorAll('.shot')];
    let n = 0;
    return shots.map((el) => {
      const sec = el.closest('section.step');
      const id = sec ? sec.id : 'misc';
      const r = el.getBoundingClientRect();
      n++;
      return { id, n, x:r.left, y:r.top, w:r.width, h:r.height };
    });
  })()`,
});
const shots = result.value;
console.log(`Encontradas ${shots.length} capturas`);

const pad2 = (x) => String(x).padStart(2, "0");
let idx = 0;
for (const s of shots) {
  idx++;
  const data = await S("Page.captureScreenshot", {
    format: "png",
    captureBeyondViewport: true,
    clip: { x: s.x, y: s.y, width: s.w, height: s.h, scale: SCALE },
  });
  const name = `${PREFIX}-${pad2(idx)}-${s.id}.png`;
  writeFileSync(`${OUT}/${name}`, Buffer.from(data.data, "base64"));
  console.log(`  ✓ ${name}  (${Math.round(s.w*SCALE)}×${Math.round(s.h*SCALE)})`);
}

browser.ws.close();
chrome.kill("SIGTERM");
rmSync(tmp, { recursive: true, force: true });
console.log("Listo →", OUT);
