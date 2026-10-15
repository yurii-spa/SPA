"""P1 Wave 2 r3 (2026-10-10). Rendered-text check of the 4,85 % claim AFTER client scripts run (headless Chrome via CDP).

usage: check_rendered_estimate_label.py <dist_dir> <out_json>
The figure is read from landing/src/data/site_numbers.json (headline.apy.value, two decimals).
Serves <dist_dir> on 127.0.0.1 (python http.server), opens pages in headless Chrome, drives /snapshot
(initial open, finishing the quiz, a different amount, EN<->RU language switch both ways) and reads
document.body.innerText. A finding = an occurrence of the estimated annualised figure whose
surroundings (±160 chars) lack the «estimated / оценочн» label, or carry «realized / реализованн /
фактическ» next to it.
"""
import base64, json, os, re, socket, struct, subprocess, sys, tempfile, time, urllib.request

CH = os.environ.get("SPA_CHROME") or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DIST, OUT = sys.argv[1], sys.argv[2]
HTTP_PORT, CDP_PORT = 8823, 9341

srv = subprocess.Popen([sys.executable, "-m", "http.server", str(HTTP_PORT), "--bind", "127.0.0.1", "--directory", DIST],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
prof = tempfile.mkdtemp(prefix="claude_render_")
chrome = subprocess.Popen([CH, "--headless=new", "--disable-gpu", f"--remote-debugging-port={CDP_PORT}",
                           f"--user-data-dir={prof}", "--window-size=390,844", "about:blank"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(60):
        try:
            tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json")); break
        except Exception:
            time.sleep(0.25)
    ws_url = [t for t in tabs if t.get("type") == "page"][0]["webSocketDebuggerUrl"]
    host, rest = ws_url[5:].split("/", 1); h, pt = host.split(":")
    s = socket.create_connection((h, int(pt)))
    key = base64.b64encode(os.urandom(16)).decode()
    s.send(f"GET /{rest} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += s.recv(4096)
    buf = buf.split(b"\r\n\r\n", 1)[1]

    def send(obj):
        data = json.dumps(obj).encode(); mask = os.urandom(4); n = len(data)
        if n < 126: hdr = bytes([0x81, 0x80 | n])
        elif n < 65536: hdr = bytes([0x81, 0x80 | 126]) + struct.pack(">H", n)
        else: hdr = bytes([0x81, 0x80 | 127]) + struct.pack(">Q", n)
        s.send(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv():
        global buf
        def need(k):
            global buf
            while len(buf) < k:
                buf += s.recv(65536)
        need(2); ln = buf[1] & 0x7f; off = 2
        if ln == 126: need(4); ln = struct.unpack(">H", buf[2:4])[0]; off = 4
        elif ln == 127: need(10); ln = struct.unpack(">Q", buf[2:10])[0]; off = 10
        need(off + ln); msg = buf[off:off + ln]; buf = buf[off + ln:]
        return json.loads(msg)

    mid = [0]
    def call(method, params=None):
        mid[0] += 1; send({"id": mid[0], "method": method, "params": params or {}})
        while True:
            m = recv()
            if m.get("id") == mid[0]:
                return m.get("result", m.get("error"))

    def ev(expr):
        r = call("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True})
        return (r or {}).get("result", {}).get("value")

    BASE = f"http://127.0.0.1:{HTTP_PORT}"
    def goto(path, lang):
        call("Page.navigate", {"url": BASE + "/"})
        time.sleep(0.8)
        ev(f"localStorage.setItem('spa_lang','{lang}')")
        call("Page.navigate", {"url": BASE + path})
        time.sleep(1.6)

    def text(sel="body"):
        return ev(f"(document.querySelector({json.dumps(sel)})||{{innerText:''}}).innerText") or ""

    def switch(lang):
        ok = ev(f"""(function(){{var b=document.querySelector('#spa-lang-toggle [data-lang="{lang}"]');
                  if(!b) return false; b.click(); return true;}})()""")
        time.sleep(0.6)
        return bool(ok)

    def click_opt(q, v):
        return ev(f"""(function(){{var b=document.querySelector('.sn-q[data-q="{q}"] .sn-opt[data-v="{v}"]');
                  if(!b) return false; b.click(); return true;}})()""")

    def click_next():
        return ev("""(function(){var q=[...document.querySelectorAll('.sn-q')].find(function(s){return !s.hidden;});
                  if(!q) return false; var n=q.querySelector('.sn-next'); if(!n) return false; n.click(); return true;})()""")

    def quiz(band):
        steps = [click_opt(1, band), click_opt(2, "idle"), click_opt(2, "cex"), click_next(),
                 click_opt(3, "usdt"), click_next(), click_opt(4, "safe")]
        time.sleep(0.5)
        return all(steps)

    _shelf = json.load(open(os.path.join(DIST, "..", "src", "data", "site_numbers.json"), encoding="utf-8"))
    _v = _shelf["headline"]["apy"]["value"]
    from decimal import Decimal, ROUND_HALF_UP
    _q = str(Decimal(repr(_v)).quantize(Decimal("0.01"), ROUND_HALF_UP))
    _ip, _fp = _q.split(".")
    NUM = _ip + r"[.,]" + _fp
    FIG = re.compile(NUM + r"\s?%")
    LABEL = re.compile(r"estimated|оценочн", re.I)

    # the figure, its (possibly long) parenthesised label, then a «realized»-class word — or that word
    # right before the figure. A ±N-char window misses the first form (the label is ~150 chars long).
    AFTER = re.compile(NUM + r"\s?%\s*(\([^)]*\))?\s*[,;]?\s*(годовых\s+)?(annualised\s+)?(realized|реализованн|фактическ)", re.I)
    BEFORE = re.compile(r"(realized|реализованн|фактическ)\w*\W{0,12}~?" + NUM + r"\s?%", re.I)

    def findings(t):
        out = []
        for m in list(AFTER.finditer(t)) + list(BEFORE.finditer(t)):
            out.append({"kind": "realized_next_to_estimate", "ctx": t[max(0, m.start() - 80): m.end() + 40]})
        for m in FIG.finditer(t):
            ctx = t[max(0, m.start() - 160): m.end() + 160]
            if not LABEL.search(ctx):
                out.append({"kind": "unlabelled_estimate", "ctx": ctx})
        return out

    report = {"snapshot": [], "pages": []}
    for start, other in (("en", "ru"), ("ru", "en")):
        goto("/snapshot/", start)
        t0 = text()
        ok = quiz("50_250k")
        r1 = text("#sn-result")
        sw = switch(other)
        r2 = text("#sn-result")
        sw_back = switch(start)
        r3 = text("#sn-result")
        goto("/snapshot/", start)
        ok2 = quiz("lt10k")
        r4 = text("#sn-result")
        amt = lambda t: re.findall(r"~\$[\d,]+\s*/\s*(?:yr|год)", t)
        report["snapshot"].append({
            "start": start, "quiz_ok": ok, "switch_ok": sw, "switch_back_ok": sw_back, "quiz2_ok": ok2,
            "initial_findings": findings(t0),
            "result_start": {"amounts": amt(r1), "findings": findings(r1), "has_label": bool(LABEL.search(r1)),
                             "ru_text": bool(re.search(r"[а-я]{4}", r1))},
            "result_after_switch": {"lang": other, "amounts": amt(r2), "findings": findings(r2),
                                    "ru_text": bool(re.search(r"[а-я]{4}", r2)),
                                    "en_text": bool(re.search(r"Idle stables|Your priority", r2))},
            "result_switch_back": {"amounts": amt(r3), "findings": findings(r3)},
            "result_other_amount": {"amounts": amt(r4), "findings": findings(r4)},
            "sample_result": r1[:600], "sample_after_switch": r2[:600],
        })
    for path in ["/how-we-think/", "/annual-contrast/", "/methodology/", "/faq/", "/system/", "/packages/",
                 "/pilot/", "/strategies/leverage-loops/", "/tournament/", "/track-record/", "/due-diligence/", "/"]:
        for lang in ("en", "ru"):
            goto(path, lang)
            t = text()
            report["pages"].append({"path": path, "lang": lang, "findings": findings(t),
                                    "estimate_mentions": len(FIG.findall(t))})
    json.dump(report, open(OUT, "w"), ensure_ascii=False, indent=1)
    tot = sum(len(x["initial_findings"]) + sum(len(x[k]["findings"]) for k in
              ("result_start", "result_after_switch", "result_switch_back", "result_other_amount"))
              for x in report["snapshot"]) + sum(len(p["findings"]) for p in report["pages"])
    rerender = all(x["result_after_switch"]["ru_text" if x["start"] == "en" else "en_text"] for x in report["snapshot"])
    report["snapshot_rerenders_on_language_switch"] = rerender
    report["figure"] = _q
    json.dump(report, open(OUT, "w"), ensure_ascii=False, indent=1)
    print("TOTAL_FINDINGS", tot)
    print("SNAPSHOT_RERENDER", rerender)
finally:
    chrome.terminate(); srv.terminate()
