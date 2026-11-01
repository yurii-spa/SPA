#!/usr/bin/env python3
"""S4 K3/K9 · вёрстка блока «Два бумажных движка» на НАСТОЯЩЕМ UI Director OS — эмуляция ширины, не iPhone.

Берёт подлинные ``spa_core/studio_os/mission_ui/{index.html,app.js,i18n.js,styles.css}`` и модель
``mission.json`` (по умолчанию — ``mission_control.build()`` на данных рабочего дерева, только чтение;
либо файл ``--model``). Четыре сцены — реальные данные · длинные тексты · пропуск движка · отказ сети
(``mission.json`` недоступен) — на 390 и 430 CSS px (вьюпорт iframe: окно headless Chrome уже 500 px
не бывает). Открывается зона «Деньги» (``#money``), меряется горизонтальное переполнение страницы и
карточек движков, наличие обоих блоков и отсутствие суммы.

Сервер — петля, временный каталог; ничего не публикуется. Код 0 — всё прошло · 1 — сбой · 2 — НЕ ИЗМЕРЕНО.
"""
from __future__ import annotations

import argparse
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

REPO = Path(__file__).resolve().parents[2]
# Ручной инструмент QA (не агент и не шаг цикла): `python3 -m spa_core.tests._mission_trading_layout --model <mission.json>
# --shots <каталог>`. Лежит в тестовой инфраструктуре, потому что вызывается руками и тестом, а не по расписанию.
UI = REPO / "spa_core" / "studio_os" / "mission_ui"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
LONG = "очень-длинный-идентификатор-без-пробелов-" * 6

PROBE = """<script>
setTimeout(function () {
  var cards = Array.prototype.slice.call(document.querySelectorAll('[data-engine]'));
  var txt = (document.body.innerText || '');
  var eng = document.querySelector('.eng-wrap-all');
  var etxt = eng ? (eng.innerText || '') : '';
  window.__res = {
    viewport: window.innerWidth,
    page_overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
    engines: cards.map(function (c) { return c.getAttribute('data-engine'); }),
    card_overflow: cards.filter(function (c) { return c.scrollWidth > c.clientWidth + 1; }).map(function (c) { return c.getAttribute('data-engine'); }),
    unavailable_named: /недоступн|unavailable|НЕ ИЗМЕРЕН|NOT_MEASURED|устарел/i.test(txt),
    summed: /суммарн|итого|общая доходность|в сумме/i.test(etxt),
    no_data_named: /ДАННЫХ НЕТ|NO DATA/.test(etxt),
    goal_steps: document.querySelectorAll('[data-step]').length,
    goal_overflow: Array.prototype.slice.call(document.querySelectorAll('.goal-card')).some(function (c) { return c.scrollWidth > c.clientWidth + 1; })
  };
}, 2500);
</script>"""

OUTER = """<!doctype html><html><body style="margin:0"><iframe id="f" src="index.html#%(area)s"
style="border:0;width:%(w)dpx;height:2400px"></iframe><pre id="out"></pre><script>
var f=document.getElementById('f');
var poll=function(){var r=f.contentWindow&&f.contentWindow.__res; if(r){document.getElementById('out').textContent='RESULT:'+JSON.stringify(r);} else setTimeout(poll,100);};
f.addEventListener('load',function(){setTimeout(poll,100);});
</script></body></html>"""


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 — сигнатура базового класса
        pass


def _model(path: str | None) -> dict:
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    sys.path.insert(0, str(REPO))
    from spa_core.studio_os import mission_control as mc
    return mc.build()


def scenes(model: dict) -> dict:
    long = json.loads(json.dumps(model))
    for b in (long.get("capital", {}).get("trading_engines", {}) or {}).get("blocks", []) or []:
        b["title"] = (b.get("title") or "") + " " + LONG
        b["active_block"] = "Блокировка с очень длинной причиной " + LONG
        b["why_hold"] = LONG
    goal = ((long.get("owner_view", {}).get("sections", {}).get("work", {}) or {}).get("goal", {}) or {})
    for st in goal.get("steps", []) or []:
        st["title"] = st["title"] + " " + LONG
        st["waiting"] = (st.get("waiting") or "") + " " + LONG
        st["last_confirmed"] = st["last_confirmed"] + " " + LONG
        if (b.get("paper_result") or {}).get("rows"):
            for r in b["paper_result"]["rows"]:
                r["id"] = r["id"] + ":" + LONG
    missing = json.loads(json.dumps(model))
    te = missing.get("capital", {}).get("trading_engines", {})
    if isinstance(te, dict) and te.get("blocks"):
        te["blocks"] = [b for b in te["blocks"] if b.get("engine") != "earn_defi"]
    return {"real": model, "long_texts": long, "missing_engine": missing, "network_error": None}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--model", help="готовый mission.json вместо сборки")
    ap.add_argument("--shots", help="каталог для скриншотов")
    args = ap.parse_args(argv)
    if not Path(CHROME).exists():
        print("НЕ ИЗМЕРЕНО: Chrome не найден", CHROME)
        return 2
    try:
        model = _model(args.model)
    except Exception as exc:  # noqa: BLE001 — сборка модели не удалась: третий исход, не «чисто»
        print(f"НЕ ИЗМЕРЕНО: модель пульта не собрана — {type(exc).__name__}: {exc}")
        return 2
    rows, failed = [], False
    for name, data in scenes(model).items():
        tmp = Path(tempfile.mkdtemp(prefix=f"mission_layout_{name}_"))
        for f in ("app.js", "i18n.js", "styles.css", "icon.svg", "manifest.webmanifest"):
            if (UI / f).exists():
                shutil.copy(UI / f, tmp / f)
        html = (UI / "index.html").read_text(encoding="utf-8").replace("</body>", PROBE + "</body>")
        (tmp / "index.html").write_text(html, encoding="utf-8")
        if data is not None:
            (tmp / "mission.json").write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
        srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(_Quiet, directory=str(tmp)))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            for area, w in [(a, x) for a in ("money", "work") for x in (390, 430)]:
                (tmp / f"outer_{area}_{w}.html").write_text(OUTER % {"w": w, "area": area}, encoding="utf-8")
                url = f"http://127.0.0.1:{srv.server_address[1]}/outer_{area}_{w}.html"
                base = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=520,2400",
                        "--virtual-time-budget=6000", f"--user-data-dir={tmp / ('p' + str(w))}"]
                dom = subprocess.run(base + ["--dump-dom", url], capture_output=True, text=True, timeout=90).stdout
                m = re.search(r"RESULT:(\{.*?\})</pre>", dom)
                if not m:
                    rows.append((name, area, w, "НЕ ИЗМЕРЕНО: результат не отрисован"))
                    failed = True
                    continue
                r = json.loads(m.group(1).replace("&quot;", '"'))
                if area == "work":
                    ok = (not r["page_overflow"]) and r["viewport"] == w and not r["goal_overflow"] and (
                        r["unavailable_named"] if data is None else r["goal_steps"] >= 1)
                elif data is None:
                    ok = (not r["page_overflow"]) and r["viewport"] == w and r["unavailable_named"] and not r["engines"]
                elif name == "missing_engine":
                    ok = ((not r["page_overflow"]) and r["engines"] == ["spa_trading_research", "earn_defi"]
                          and r["viewport"] == w and r["no_data_named"] and not r["summed"])
                else:
                    ok = (not r["page_overflow"] and not r["card_overflow"] and not r["summed"] and r["viewport"] == w
                          and r["engines"] == ["spa_trading_research", "earn_defi"])
                failed |= not ok
                rows.append((name, area, w, ("OK " if ok else "FAIL ") + json.dumps(r, ensure_ascii=False)))
                if args.shots:
                    Path(args.shots).mkdir(parents=True, exist_ok=True)
                    subprocess.run(base + [f"--screenshot={Path(args.shots) / f'{name}_{area}_{w}.png'}", url],
                                   capture_output=True, timeout=90)
        finally:
            srv.shutdown()
            shutil.rmtree(tmp, ignore_errors=True)
    for row in rows:
        print(*row)
    print("эмуляция ширины в Chrome ≠ реальный iPhone; живой маршрут (туннель, вход, обновление данных) этим НЕ проверяется")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
