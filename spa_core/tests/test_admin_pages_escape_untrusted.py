#!/usr/bin/env python3
"""/admin renders API data as TEXT: no value from JSON may reach innerHTML unescaped.

Замер 09–10.11.2026 (RECON-02): `admin/analytics.astro` и `admin/index.astro` вставляли в innerHTML имена событий `k` и
пути страниц `p.page` без экранирования; `admin/agents.astro` — счётчик `byRole[r]`. Имена событий и пути страниц пишет
неаутентифицированный `POST /api/analytics/event` (spa_core/api/routers/analytics.py), то есть любой посетитель сайта мог
положить `<img src=x onerror=…>` в счётчик, а оператор получил бы исполнение в своей админке.

Две меры, обе офлайн (без сайта, без сети, без модели):
  1. СТАТИЧЕСКАЯ: в inline-скриптах трёх страниц каждое значение, подставляемое в строковый шаблон innerHTML через `'+…+'`,
     обязано проходить через `esc(…)`; допускаются только числа-литералы, `.length`, булевы тернарии с литералами и
     константы страницы (ico/cls из badge()). Правило точное для этих трёх страниц; остальные страницы /admin — в §KNOWN
     как измеренный остаток, не как «закрыто».
  2. ДИНАМИЧЕСКАЯ (если есть `node`): скрипт страницы исполняется в Node с подменой document/fetch/location; API отдаёт
     строки с HTML и обработчиками событий; проверяется, что в итоговом innerHTML нет ни одного тега из данных и ни одного
     обработчика событий, а текст виден как `&lt;img …&gt;`. Таблицы/списки при этом рендерятся (строки присутствуют).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADMIN = ROOT / "landing" / "src" / "pages" / "admin"
FIXED = ("analytics.astro", "agents.astro", "index.astro")

_SCRIPT = re.compile(r"<script\b[^>]*>([\s\S]*?)</script>")
#: оператор присваивания innerHTML и его правая часть до конца инструкции
_ASSIGN = re.compile(r"\.innerHTML\s*=\s*([\s\S]*?);\s*\n")
#: подстановка в строковый шаблон: '…'+EXPR+'…'  (EXPR без кавычек)
_INTERP = re.compile(r"'\s*\+\s*([^'+][^']*?)\s*\+\s*'")
_SAFE = re.compile(r"^(esc\(.*\)|\d+|[\w.\[\]]+\.length|b\.ico|b\.cls|\(.*\?'[^']*':'[^']*'\)|\(a\.reboot_safe\?.*\))$")

PAYLOADS = ["<img src=x onerror=alert(1)>", "<svg onload=alert(2)>", "\"><script>alert(3)</script>", "javascript:alert(4)",
            "a' onmouseover='alert(5)", "</span><b onclick=alert(6)>x</b>"]


def _interpolations(src: str) -> list[tuple[str, str]]:
    out = []
    for block in _SCRIPT.findall(src):
        for m in _ASSIGN.finditer(block):
            rhs = m.group(1)
            for e in _INTERP.findall(rhs):
                out.append((e.strip(), rhs.strip()[:80]))
    return out


class AdminEscapeStaticTest(unittest.TestCase):
    def test_fixed_pages_escape_every_interpolated_value(self):
        bad = []
        for name in FIXED:
            src = (ADMIN / name).read_text(encoding="utf-8")
            self.assertIn("function esc(", src, f"{name}: нет esc()")
            for expr, where in _interpolations(src):
                if not _SAFE.match(expr):
                    bad.append(f"{name}: {expr}  ←  {where}")
        self.assertEqual(bad, [], "в innerHTML попадают неэкранированные значения:\n" + "\n".join(bad))

    def test_esc_covers_text_and_attribute_contexts(self):
        for name in FIXED:
            src = (ADMIN / name).read_text(encoding="utf-8")
            m = re.search(r"function esc\(s\)\{return String\(s==null\?'':s\)\.replace\(/\[([^\]]+)\]/g", src)
            self.assertIsNotNone(m, f"{name}: нестандартный esc()")
            for ch in ("&", "<", ">", '"', "'"):
                self.assertIn(ch, m.group(1).replace("\\", ""), f"{name}: esc() не экранирует {ch!r}")

    def test_known_remaining_pages_are_measured_not_declared_safe(self):
        # §KNOWN: остальные страницы /admin не входят в это исправление. Здесь фиксируется измеренное число
        # неэкранированных подстановок, чтобы оно не росло молча; уменьшение — обновить константу вместе с правкой.
        known = {}
        for f in sorted(ADMIN.glob("*.astro")):
            if f.name in FIXED:
                continue
            n = sum(1 for e, _ in _interpolations(f.read_text(encoding="utf-8")) if not _SAFE.match(e))
            if n:
                known[f.name] = n
        self.assertLessEqual(sum(known.values()), 40, f"неэкранированных подстановок стало больше: {known}")


# --------------------------------------------------------------------------- runtime (node)
_HARNESS = r"""
const RETIRED={events:['retired_evt'],retired_at:'2026-01-01'};
const els={}; const made=[];
function el(id){ if(!els[id]) els[id]={id,innerHTML:'',textContent:'',hidden:false,
  classList:{toggle(){}}, querySelector(){return {classList:{toggle(){}}};}}; return els[id]; }
const document={getElementById:el, createElement(t){const e={tag:t,innerHTML:'',textContent:'',children:[],appendChild(c){this.children.push(c);},
  classList:{add(){},toggle(){}}}; made.push(e); return e;}};
const location={hostname:'localhost'};
const PAYLOAD=__PAYLOAD__;
function fetch(){ return Promise.resolve({json:()=>Promise.resolve(PAYLOAD)}); }
const setInterval=function(){}; const window={};
__SCRIPT__
setTimeout(()=>{ const out={}; for (const [k,v] of Object.entries(els)) out[k]={h:v.innerHTML,t:v.textContent};
  out.__made=made.map(m=>m.innerHTML); console.log(JSON.stringify(out)); }, 20);
"""


def _run_page(name: str, payload: dict) -> dict:
    src = (ADMIN / name).read_text(encoding="utf-8")
    scripts = _SCRIPT.findall(src)
    body = next(s for s in scripts if "innerHTML" in s)
    js = _HARNESS.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False)).replace("__SCRIPT__", body)
    r = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def _assert_no_live_markup(tc, html: str):
    # ни один тег из данных не стал разметкой: «<» из данных экранирован, поэтому любой настоящий тег с
    # обработчиком события или javascript:-ссылкой может появиться только из шаблона страницы — которых там нет
    tc.assertNotRegex(html, r"<(img|svg|script)\b", html[:300])
    tc.assertNotRegex(html, r"<[^>]*\son[a-z]+\s*=", html[:300])          # on*= внутри настоящего тега
    tc.assertNotRegex(html, r"<[^>]*(href|src)\s*=\s*['\"]?javascript:", html[:300])
    tc.assertIn("&lt;img src=x onerror=alert(1)&gt;", html)                 # нагрузка видна как текст
    tc.assertIn("&lt;svg onload=alert(2)&gt;", html)


@unittest.skipUnless(shutil.which("node"), "node недоступен — динамическая проверка пропущена, статическая выполнена")
class AdminEscapeRuntimeTest(unittest.TestCase):
    def test_analytics_renders_hostile_events_and_pages_as_text(self):
        ev = {p: 7 for p in PAYLOADS}; ev["retired_evt"] = 3; ev["analyze_wallet"] = 1
        out = _run_page("analytics.astro", {"views_today": 1, "views_7d": 2, "total_views": 3, "events": ev,
                                            "top_pages": [{"page": p, "views": 9} for p in PAYLOADS] + [{"page": "/ok", "views": "<b>1</b>"}]})
        for key in ("a-events", "a-pages"):
            _assert_no_live_markup(self, out[key]["h"])
        self.assertEqual(out["a-events"]["h"].count('<div class="ac-pg">'), len(PAYLOADS) + 2)   # список отрисован целиком
        self.assertEqual(out["a-pages"]["h"].count('<div class="ac-pg">'), len(PAYLOADS) + 1)
        self.assertIn("&lt;b&gt;1&lt;/b&gt;", out["a-pages"]["h"])                                # и числовое поле — текст
        self.assertEqual(out["an-state"]["t"], "live")

    def test_index_top_pages_are_text(self):
        out = _run_page("index.astro", {"views_today": 1, "views_7d": 2, "events": {}, "top_pages": [{"page": p, "views": 1} for p in PAYLOADS]})
        _assert_no_live_markup(self, out["an-pages"]["h"])
        self.assertEqual(out["an-pages"]["h"].count('<div class="ac-pg">'), len(PAYLOADS))

    def test_agents_registry_hostile_values_are_text(self):
        hostile = PAYLOADS[0]
        payload = {"generated_at": "2026-11-10T10:00:00Z", "roles": ["infra", hostile],
                   "by_role": {"infra": "<img src=x onerror=alert(1)>", hostile: 2},
                   "agents": [{"short": hostile, "role": "infra", "loaded": True, "pid": "<svg onload=alert(2)>", "schedule": PAYLOADS[1],
                               "problems": [PAYLOADS[2], PAYLOADS[4]], "reboot_safe": True},
                              {"short": "ok-agent", "role": hostile, "loaded": False, "schedule": "daily", "problems": [], "reboot_safe": False}]}
        out = _run_page("agents.astro", payload)
        for key in ("ag-roles", "ag-prob-list", "ag-roles-wrap"):
            html = out[key]["h"]
            self.assertNotRegex(html, r"<(img|svg|script)\b", f"{key}: {html[:200]}")
            self.assertNotRegex(html, r"<[^>]*\son(error|load|mouseover|click)\s*=", f"{key}: {html[:200]}")
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", out["ag-roles"]["h"])
        self.assertIn("&lt;svg onload=alert(2)&gt;", out["ag-roles-wrap"]["h"])                   # pid попадает в title= — экранирован
        self.assertEqual(out["ag-roles-wrap"]["h"].count('<div class="ag-card'), 2)                # карточки флота отрисованы
        self.assertEqual(out["ag-prob-list"]["h"].count('<div class="ag-prob">'), 1)
        self.assertEqual(out["ag-state"]["t"], "live")


if __name__ == "__main__":
    unittest.main()
