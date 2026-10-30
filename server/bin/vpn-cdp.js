#!/usr/bin/env node
// cdp.js <eval|secret> <js> [file]   drives the vpn-jump Chrome through its localhost debugging port (9333).
// eval: prints the JSON result of the page expression. secret: writes the string result to <file> (mode 600),
// prints only its length, so the value never reaches a terminal or a log.
const fs = require("fs");
const port = process.env.CDP_PORT || 9333;
const [mode, js, file] = process.argv.slice(2);
(async () => {
  const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  const pages = targets.filter(t => t.type === "page" && !t.url.startsWith("chrome"));
  const pick = process.env.CDP_URL ? pages.find(p => p.url.includes(process.env.CDP_URL)) : pages[0];
  if (!pick) { console.error("no page target"); process.exit(3); }
  const ws = new WebSocket(pick.webSocketDebuggerUrl);
  await new Promise(r => ws.onopen = r);
  const res = await new Promise((resolve, reject) => {
    ws.onmessage = e => resolve(JSON.parse(e.data));
    ws.onerror = reject;
    ws.send(JSON.stringify({ id: 1, method: "Runtime.evaluate", params: { expression: js, returnByValue: true, awaitPromise: true } }));
  });
  ws.close();
  if (res.result && res.result.exceptionDetails) { console.error("JS error:", res.result.exceptionDetails.text, (res.result.exceptionDetails.exception||{}).description||""); process.exit(2); }
  const v = res.result && res.result.result ? res.result.result.value : undefined;
  if (mode === "secret") { fs.writeFileSync(file, String(v ?? ""), { mode: 0o600 }); console.log("secret length", String(v ?? "").length); }
  else console.log(typeof v === "string" ? v : JSON.stringify(v));
})().catch(e => { console.error(e.message); process.exit(1); });
