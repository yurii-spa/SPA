"""DIRECTOR-OS-UX-03 step 1 — an open card must survive the periodic refresh (owner 13.10: «карточка
раскрывается, но затем периодически самостоятельно сворачивается прямо во время чтения»).

Real browser, real app.js, the FIXED fixture: the page refreshes every 300 ms (test-only meta), the test
opens a decision card, scrolls, waits ≥ 3 refresh cycles and requires the card still open and the scroll
kept. Positive control: the same page with the state keeper disabled collapses the card — so the test can
fail. No Chrome on the host ⇒ НЕ ИЗМЕРЕНО, named (never a pass).
"""
# FROZEN-DATE-OK: injected-clock — the preview pins the reader clock with <meta dos-fixed-now>; owner_view.build gets NOW
import copy
import functools
import http.server
import json
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.studio_os import owner_view as ov

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "spa_core" / "studio_os" / "mission_ui"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "owner_view" / "mission_fixture.json"
NOW = datetime(2026, 10, 9, 7, 15, tzinfo=timezone.utc)


def _chrome_or_skip():
    from spa_core.tests import _cdp
    if not os.path.exists(_cdp.CH):
        pytest.skip("НЕ ИЗМЕРЕНО: headless Chrome на этом хосте отсутствует (SPA_TEST_CHROME не задан)")
    return _cdp


def _site(tmp: Path, *, disable_keeper: bool = False) -> Path:
    d = tmp / "site"
    shutil.copytree(UI, d)
    html = (d / "index.html").read_text(encoding="utf-8")
    html = html.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n<meta name="dos-fixed-now" content="'
                        + NOW.strftime("%Y-%m-%dT%H:%M:%SZ") + '">\n<meta name="dos-refresh-ms" content="300">', 1)
    (d / "index.html").write_text(html, encoding="utf-8")
    if disable_keeper:   # positive control: refresh without the state keeper
        js = (d / "app.js").read_text(encoding="utf-8")
        js = js.replace("renderAll({ keepState: true });", "renderAll();")
        (d / "app.js").write_text(js, encoding="utf-8")
    m = json.loads(FIXTURE.read_text(encoding="utf-8"))
    m["owner_view"] = ov.build(copy.deepcopy(m), NOW)
    (d / "mission.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    return d


def _serve(d: Path):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(d))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _open_card_and_wait(cdp, url):
    c = cdp.Chrome()
    try:
        c.viewport(390)
        c.go(url, 1.5)
        assert c.ev("document.querySelectorAll('details.ux-dec').length") >= 1
        c.ev("var d=document.querySelector('details.ux-dec'); d.open=true; d.scrollIntoView(); window.scrollBy(0,120);")
        time.sleep(0.3)
        y0 = c.ev("window.scrollY")
        time.sleep(1.6)            # ≥ 3 refresh cycles of 300 ms (plus fetch time)
        return {"open": c.ev("document.querySelector('details.ux-dec').open"), "y0": y0,
                "y1": c.ev("window.scrollY")}
    finally:
        c.close()


def test_open_decision_card_survives_three_refreshes(tmp_path):
    cdp = _chrome_or_skip()
    srv = _serve(_site(tmp_path))
    try:
        r = _open_card_and_wait(cdp, f"http://127.0.0.1:{srv.server_address[1]}/index.html#decisions")
    finally:
        srv.shutdown()
    assert r["open"] is True
    assert abs(r["y1"] - r["y0"]) <= 2, r


def test_positive_control_without_the_keeper_the_card_collapses(tmp_path):
    cdp = _chrome_or_skip()
    srv = _serve(_site(tmp_path, disable_keeper=True))
    try:
        r = _open_card_and_wait(cdp, f"http://127.0.0.1:{srv.server_address[1]}/index.html#decisions")
    finally:
        srv.shutdown()
    assert r["open"] is False, "the control must reproduce the owner's bug — otherwise the test proves nothing"
