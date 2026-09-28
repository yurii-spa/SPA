#!/usr/bin/env python3
"""Assemble a SELF-CONTAINED snapshot.html for visual review (screenshots).

Inlines styles.css + i18n.js + app.js and embeds the current read_model.json, with a
tiny fetch() shim so the exact same app code renders WITHOUT a server (file:// works;
ES-module imports and fetch/CORS do not, hence this build). This is a REVIEW ARTIFACT,
not the product: the real Shell runs via serve.py (loopback) + live fetch of read_model.
Same app logic, same design — only the transport is swapped for offline capture.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--lang', default='ru')
    ap.add_argument('--mode', default='mission')
    ap.add_argument('--page', default='overview')
    ap.add_argument('--open-task', action='store_true',
                    help='capture harness: after boot, invoke the REAL openTask() on a real '
                         'work item (prefers a failed one) to show the drill-down drawer')
    ap.add_argument('--out', default='snapshot.html')
    ns = ap.parse_args()

    css = (HERE / 'styles.css').read_text(encoding='utf-8')
    i18n = (HERE / 'i18n.js').read_text(encoding='utf-8').replace('export const', 'const').replace('export function', 'function')
    app = (HERE / 'app.js').read_text(encoding='utf-8')
    # drop the ES-module import (makeT is now a global from the inlined i18n)
    app = '\n'.join(l for l in app.splitlines() if not l.strip().startswith("import { makeT }"))
    # deterministic view for offline capture: seed STATE defaults
    app = app.replace("lang: localStorage.getItem('sos.lang') || 'ru'", f"lang: '{ns.lang}'")
    app = app.replace("mode: localStorage.getItem('sos.mode') || 'mission'", f"mode: '{ns.mode}'")
    app = app.replace("page: 'overview'", f"page: '{ns.page}'")
    model = json.loads((HERE / 'read_model.json').read_text(encoding='utf-8'))

    # capture harness only: drive the app's REAL openTask() with REAL data (no fabrication)
    open_task_script = ''
    if ns.open_task:
        open_task_script = (
            "<script>setTimeout(function(){ try {"
            " var w = (STATE.model.work||[]).find(function(x){return x.ui_state==='failed';})"
            " || (STATE.model.work||[])[0];"
            " if (w) openTask(w);"
            " } catch(e){} }, 350);</script>"
        )

    html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<title>Studio OS — snapshot</title>
<style>
{css}
</style>
</head>
<body>
<div id="app" class="app"></div>
<div id="scrim" class="scrim"></div>
<aside id="drawer" class="drawer" aria-label="Task detail">
  <div class="dh"><strong class="dtitle"></strong><button class="x" aria-label="Close">×</button></div>
  <div class="db"></div>
</aside>
<script>
// ---- inlined i18n ----
{i18n}
</script>
<script>
// ---- embedded read model + fetch shim (review artifact only) ----
window.__MODEL__ = {json.dumps(model, ensure_ascii=False)};
const __realFetch = window.fetch ? window.fetch.bind(window) : null;
window.fetch = function(url){{
  if (String(url).indexOf('read_model.json') !== -1)
    return Promise.resolve({{ ok: true, json: async () => window.__MODEL__ }});
  return __realFetch ? __realFetch(url) : Promise.reject('no fetch');
}};
</script>
<script>
// ---- inlined app (module import stripped; makeT is global) ----
{app}
</script>
{open_task_script}
</body>
</html>
"""
    out = HERE / ns.out
    out.write_text(html, encoding='utf-8')
    print(f'wrote {out} ({len(html)} bytes)')


if __name__ == '__main__':
    main()
