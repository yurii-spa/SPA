#!/usr/bin/env python3
"""Layout check of the TRADING surface (S3 E7.4) in headless Chrome at phone widths — EMULATION, not an iPhone.

Renders ``surfaces.renderTrading`` with the real projection plus three stress fixtures (long texts, missing
data, network error) at 390 and 430 CSS px, with the cockpit's own stylesheet, and reports per case:
horizontal page overflow, a card wider than its box, and that both engine blocks are present and separate.
Loopback-only server in a temp dir; nothing is published. Exit 0 — all pass, 1 — a failure, 2 — not measured.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
LONG = "очень-длинный-идентификатор-без-пробелов-" * 6
HARNESS = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>%(css)s body{margin:0;background:var(--bg);color:var(--ink)} #m{position:relative;min-height:100vh}</style></head>
<body class="view-trading"><div id="m"></div><script type="module">
import { renderTrading } from './surfaces.js';
const t = %(data)s;
const m = document.getElementById('m');
renderTrading(m, t, 'ru');
const surf = m.querySelector('.surf'); surf.style.position = 'static';
const cards = [...m.querySelectorAll('.tr-card')];
const res = {page_overflow: document.documentElement.scrollWidth > window.innerWidth,
  viewport: window.innerWidth, cards: cards.map(c => c.dataset.engine),
  card_overflow: cards.filter(c => c.scrollWidth > c.clientWidth + 1).map(c => c.dataset.engine),
  empty: !!m.querySelector('.surf-empty'), summed_text: /сумм|итого|total/i.test(m.innerText.replace(/не суммируется|НЕ суммируются/g, ''))};
window.__res = res;
</script></body></html>"""
#: headless Chrome will not size a WINDOW below 500 px — the phone width is the iframe's own viewport
OUTER = """<!doctype html><html><body style="margin:0"><iframe id="f" src="%(inner)s" style="border:0;width:%(w)dpx;height:1400px"></iframe>
<pre id="out"></pre><script>
const f = document.getElementById('f');
const poll = () => { const r = f.contentWindow && f.contentWindow.__res;
  if (r) document.getElementById('out').textContent = 'RESULT:' + JSON.stringify(r); else setTimeout(poll, 50); };
f.addEventListener('load', poll);
</script></body></html>"""


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def fixtures(real: dict) -> dict:
    long = json.loads(json.dumps(real))
    for b in long["blocks"]:
        b["title"] = (b.get("title") or "") + " " + LONG
        b["active_block"] = "Блокировка с очень длинным описанием причины " + LONG
        b["why_hold"] = LONG
        b["provenance"] = LONG
        if (b.get("paper_result") or {}).get("rows"):
            for r in b["paper_result"]["rows"]:
                r["id"] = r["id"] + ":" + LONG
        if b.get("last_decision") and b["last_decision"].get("reasons"):
            b["last_decision"]["reasons"].append(LONG)
    missing = {"schema": real.get("schema"), "note": real.get("note"),
               "blocks": [{"engine": "spa_trading_research", "title": "SPA Trading Research", "present": False,
                           "freshness": "UNKNOWN", "why_no_result": "status.json недоступен — данных нет"}]}
    return {"real": real, "long_texts": long, "missing_data": missing, "network_error": None}


def main(argv) -> int:
    real = json.loads(Path(argv[1]).read_text()) if len(argv) > 1 else json.loads((HERE / "trading.json").read_text())
    shots = Path(argv[2]) if len(argv) > 2 else None
    if not Path(CHROME).exists():
        print("НЕ ИЗМЕРЕНО: Chrome не найден", CHROME)
        return 2
    css = "\n".join(re.findall(r"<style>(.*?)</style>", (HERE / "graph.html").read_text(), re.S))
    tmp = Path(tempfile.mkdtemp(prefix="trading_layout_"))
    shutil.copy(HERE / "surfaces.js", tmp / "surfaces.js")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(_Quiet, directory=str(tmp)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port, failed, rows = srv.server_address[1], False, []
    try:
        for name, data in fixtures(real).items():
            (tmp / f"{name}.html").write_text(HARNESS % {"css": css, "data": json.dumps(data, ensure_ascii=False)})
            for w in (390, 430):
                (tmp / f"{name}_{w}.html").write_text(OUTER % {"inner": f"{name}.html", "w": w})
                url = f"http://127.0.0.1:{port}/{name}_{w}.html"
                base = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=520,1400",
                        "--virtual-time-budget=3000", f"--user-data-dir={tmp / ('prof_' + name + str(w))}"]
                dom = subprocess.run(base + ["--dump-dom", url], capture_output=True, text=True, timeout=60).stdout
                mres = re.search(r"RESULT:(\{.*?\})</pre>", dom)
                if not mres:
                    rows.append((name, w, "НЕ ИЗМЕРЕНО: результат не отрисован"))
                    failed = True
                    continue
                r = json.loads(mres.group(1).replace("&quot;", '"'))
                ok = (not r["page_overflow"] and not r["card_overflow"] and not r["summed_text"] and r["viewport"] == w
                      and (r["empty"] if data is None else r["cards"] == ["spa_trading_research", "earn_defi"]))
                failed |= not ok
                rows.append((name, w, ("OK " if ok else "FAIL ") + json.dumps(r, ensure_ascii=False)))
                if shots:
                    shots.mkdir(parents=True, exist_ok=True)
                    subprocess.run(base + [f"--screenshot={shots / f'{name}_{w}.png'}", url],
                                   capture_output=True, timeout=60)
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    for r in rows:
        print(*r)
    print("эмуляция ширины в Chrome ≠ реальный iPhone (Safari, safe-area, шрифты) — на устройстве НЕ ИЗМЕРЕНО")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
