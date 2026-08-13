#!/usr/bin/env python3
"""site_freshness_monitor.py — Site Custodian block 2+3 (ADR-YL-011): the INDEPENDENT checker.

It does NOT trust the deploy pipeline. It fetches the live site + live API + the repo snapshot from the
OUTSIDE and asserts the triple agrees, is fresh, is available, and — critically — that the site never
OVERSTATES a metric vs the live API. On any FAIL it writes data/site_freshness_report.json and alerts
through SPA's Telegram channel. Kill-rule: OVERSTATED_METRIC, or staleness > 48h on TWO consecutive runs,
flips the snapshot to degraded:true (hero shows "live data temporarily unavailable" instead of a wrong
number — refusal-first: honest absence beats a false figure).

Design: `evaluate()` is PURE (all inputs injected) so tests mock every HTTP call — no network in CI.
`run()` wires real urllib fetches. stdlib-only, deterministic, fail-CLOSED. Runs every 6h via
.github/workflows/site_freshness.yml AND can run on the Mac.

FAIL categories (each a distinct, logged reason-code):
  STALE_SNAPSHOT      — snapshot as_of older than 30h
  STALE_API           — API last evidenced bar older than 30h
  SITE_BEHIND_SNAPSHOT— live site numbers != repo snapshot (deploy lag)
  SNAPSHOT_BEHIND_API — repo snapshot != live API (cycle ran, snapshot not regenerated)
  OVERSTATED_METRIC   — site shows an APY HIGHER than the live API (critical; never allowed)
  MISSING_ASOF        — live page has no as-of label, or it disagrees with the snapshot
  UNAVAILABLE         — a sitemap URL is not 200 / redirects unexpectedly
  VERIFIER_PIN_MISMATCH — live verify_spa.py SHA-256 != the published pin
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SNAP = _ROOT / "landing" / "src" / "data" / "track_snapshot.json"
_SITEMAP = _ROOT / "landing" / "public" / "sitemap.xml"
_REPORT = _ROOT / "data" / "site_freshness_report.json"

SITE = "https://earn-defi.com"
API = "https://api.earn-defi.com"

APY_TOL_PP = 0.05          # allowed APY divergence in percentage points
STALE_HOURS = 30           # freshness bar
DEGRADE_STALE_HOURS = 48   # kill-rule staleness threshold


# ─────────────────────────────── helpers ───────────────────────────────
def _num(s):
    try:
        return float(str(s).replace(",", "").replace("$", "").replace("~", "").replace("%", "").strip())
    except (ValueError, TypeError):
        return None


def _hours_since(date_str, now):
    """Hours from a YYYY-MM-DD (or ISO) date string to `now` (utc). None if unparseable."""
    if not date_str:
        return None
    try:
        d = datetime.date.fromisoformat(str(date_str)[:10])
    except ValueError:
        return None
    delta = now - datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc)
    return delta.total_seconds() / 3600.0


def parse_site_numbers(html):
    """Extract the public headline numbers from rendered HTML (P1-6 static ids). None if absent."""
    if not html:
        return {}
    def g(pat):
        m = re.search(pat, html)
        return m.group(1) if m else None
    return {
        "evidenced_days": _num(g(r'id="sl-day">\s*~?([\d,]+)') or g(r'id="tr-days-2">\s*([\d,]+)')),
        "paper_apy_pct": _num(g(r'id="sl-apy">\s*~?([\d.]+)%') or g(r'id="tr-apy">\s*~?([\d.]+)%')),
        "gates_passed": _num(g(r'id="sl-gates">\s*([\d]+)/')),
        "end_equity": _num(g(r'id="tr-equity">\s*\$?([\d,]+)')),
        "as_of": g(r'as of (\d{4}-\d{2}-\d{2})') or g(r'static snapshot as of (\d{4}-\d{2}-\d{2})'),
    }


def api_headline(golive, facts, equity_chain):
    """Best-effort authoritative headline from the live API (defensive field extraction)."""
    g = golive or {}
    f = facts or {}
    out = {
        "evidenced_days": _num(g.get("real_track_days") if g.get("real_track_days") is not None else g.get("track_days")),
        "gates_passed": _num(g.get("passed") if g.get("passed") is not None else g.get("risk_gates_passed")),
        "paper_apy_pct": _num(f.get("apy_today_pct") if f.get("apy_today_pct") is not None else g.get("apy_today_pct")),
        "end_equity": _num(f.get("current_equity") if f.get("current_equity") is not None else f.get("equity")),
        "last_bar": None,
    }
    # last evidenced bar date from the equity chain (freshness)
    rows = equity_chain if isinstance(equity_chain, list) else (equity_chain or {}).get("rows") or (equity_chain or {}).get("data")
    if isinstance(rows, list) and rows:
        last = rows[-1] if isinstance(rows[-1], dict) else {}
        out["last_bar"] = last.get("date") or last.get("ts")
    return out


# ─────────────────────────────── the pure evaluator ───────────────────────────────
def evaluate(*, snapshot, home_html, track_html, api, sitemap_statuses, verifier_sha, pin_sha,
             now, prev_report=None):
    """Pure Site-Custodian evaluation. Returns the report dict. No I/O."""
    fails = []          # list of {code, detail, severity}
    def fail(code, detail, severity="FAIL"):
        fails.append({"code": code, "detail": detail, "severity": severity})

    snap = snapshot or {}
    site_home = parse_site_numbers(home_html)
    site_track = parse_site_numbers(track_html)
    apih = api or {}

    # 1. snapshot freshness
    snap_age = _hours_since(snap.get("as_of"), now)
    if snap_age is None:
        fail("MISSING_ASOF", "snapshot has no parseable as_of")
    elif snap_age > STALE_HOURS:
        fail("STALE_SNAPSHOT", f"snapshot as_of {snap.get('as_of')} is {snap_age:.1f}h old (> {STALE_HOURS}h)")

    # 2. API last-bar freshness
    api_age = _hours_since(apih.get("last_bar"), now)
    if apih.get("last_bar") and api_age is not None and api_age > STALE_HOURS:
        fail("STALE_API", f"API last bar {apih.get('last_bar')} is {api_age:.1f}h old (> {STALE_HOURS}h)")

    # 3. site page carries an as-of label matching the snapshot
    for name, s in (("home", site_home), ("track", site_track)):
        if s.get("as_of") is None:
            fail("MISSING_ASOF", f"{name} page has no as-of label")
        elif snap.get("as_of") and s["as_of"] != snap["as_of"]:
            fail("SITE_BEHIND_SNAPSHOT", f"{name} as-of {s['as_of']} != snapshot as_of {snap['as_of']}")

    # 4. site == snapshot (deploy lag)
    def cmp_int(label, site_v, snap_v):
        if site_v is not None and snap_v is not None and abs(site_v - snap_v) >= 1:
            fail("SITE_BEHIND_SNAPSHOT", f"site {label}={site_v} != snapshot {label}={snap_v}")
    cmp_int("evidenced_days", site_home.get("evidenced_days"), _num(snap.get("real_track_days")))
    cmp_int("gates_passed", site_home.get("gates_passed"), _num(snap.get("gates_passed")))

    # 5. snapshot == API (snapshot regenerated after cycle?)
    #    evidenced_days: robust like-for-like staleness signal (both count the same real
    #    daily-cycle bars). Kept as the SNAPSHOT_BEHIND_API detector.
    if apih.get("evidenced_days") is not None and snap.get("real_track_days") is not None:
        if abs(apih["evidenced_days"] - _num(snap["real_track_days"])) >= 1:
            fail("SNAPSHOT_BEHIND_API", f"snapshot days={snap['real_track_days']} != API days={apih['evidenced_days']}")
    #    apy leg REMOVED 2026-07-15 (OWNER-APPROVED, вариант «а»; rule #16 satisfied — owner
    #    decided via card owner-decision-20260715-212059-apy, journaled). It was a CATEGORY-ERROR
    #    false positive: the API exposes only the VOLATILE single-day apy_today_pct (api_headline
    #    maps it into paper_apy_pct), while the committed snapshot.paper_apy_pct is the STABLE
    #    track-to-date APY that generate_track_snapshot.py deliberately computes from anchor equity
    #    and explicitly does NOT source from apy_today ("volatile single-day apy_today ... swings
    #    daily"). Comparing stable-track vs volatile-daily fired SNAPSHOT_BEHIND_API almost every
    #    intraday poll though the snapshot was correctly regenerated (a fresh build_snapshot()
    #    reproduces the committed value). Real staleness stays covered by evidenced_days (above) +
    #    STALE_SNAPSHOT (as_of age). Re-enable an apy leg only when the API exposes a matching
    #    track-to-date apy (like-for-like comparison).

    # 6. OVERSTATED_METRIC — the site must NEVER show an APY higher than the live API (critical)
    api_apy = apih.get("paper_apy_pct")
    for name, s in (("home", site_home), ("track", site_track)):
        site_apy = s.get("paper_apy_pct")
        if site_apy is not None and api_apy is not None and site_apy > api_apy + APY_TOL_PP:
            fail("OVERSTATED_METRIC",
                 f"{name} shows APY {site_apy}% > live API {api_apy}% (+{APY_TOL_PP}pp tol)", severity="CRITICAL")

    # 7. availability — every sitemap URL 200, no unexpected redirect
    for url, code in (sitemap_statuses or {}).items():
        if code not in (200, 308):   # 308 = trailing-slash canonicalization, expected
            fail("UNAVAILABLE", f"{url} -> HTTP {code}")

    # 8. verifier pin
    if verifier_sha and pin_sha and verifier_sha != pin_sha:
        fail("VERIFIER_PIN_MISMATCH", f"live verify_spa.py {verifier_sha[:12]}… != pin {pin_sha[:12]}…")

    # ── kill-rule: degrade only when the SNAPSHOT ITSELF is overstated (its committed apy exceeds the live
    #    API) — that's the only case where degrading actually prevents a wrong number. A merely stale LIVE
    #    site above a CORRECT snapshot is DEPLOY LAG (the fix is to deploy the good snapshot, NOT to degrade
    #    it — degrading a correct snapshot would make the site show a plaque instead of the right number).
    #    Deploy lag still ALERTS via OVERSTATED_METRIC + SITE_BEHIND_SNAPSHOT but does NOT degrade. Also
    #    degrade on staleness > 48h across two consecutive runs.
    site_overstated = any(f["code"] == "OVERSTATED_METRIC" for f in fails)
    snap_apy = _num(snap.get("paper_apy_pct"))
    snapshot_overstated = (snap_apy is not None and api_apy is not None and snap_apy > api_apy + APY_TOL_PP)
    stale_48 = (snap_age is not None and snap_age > DEGRADE_STALE_HOURS)
    prev_stale_48 = bool(prev_report and prev_report.get("stale_48h"))
    degrade = snapshot_overstated or (stale_48 and prev_stale_48)

    return {
        "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ok": not fails,
        "fails": fails,
        "n_fails": len(fails),
        "snapshot_age_h": round(snap_age, 2) if snap_age is not None else None,
        "api_age_h": round(api_age, 2) if api_age is not None else None,
        "stale_48h": stale_48,
        "degrade_triggered": degrade,
        "degrade_reason": ("SNAPSHOT_OVERSTATED" if snapshot_overstated else
                           "STALE_48H_TWO_RUNS" if degrade else None),
        "site_overstated": site_overstated,          # live site shows APY > API (may be deploy lag)
        "snapshot_overstated": snapshot_overstated,  # committed snapshot itself is overstated -> degrade
        "site_home": site_home,
        "site_track": site_track,
        "snapshot": {k: snap.get(k) for k in ("as_of", "real_track_days", "paper_apy_pct", "gates_passed", "end_equity")},
        "api": apih,
    }


# ─────────────────────────────── I/O wrappers ───────────────────────────────
def _get(url, timeout=15):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SPA-SiteCustodian/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception:
        return None, None


def _get_json(url):
    _, body = _get(url)
    if not body:
        return None
    try:
        return json.loads(body)
    except ValueError:
        return None


def _sitemap_urls():
    if not _SITEMAP.exists():
        return []
    return re.findall(r"<loc>([^<]+)</loc>", _SITEMAP.read_text())


def _atomic_write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2))
    import os
    os.replace(tmp, path)


def _humanize_body(msg):
    """Перевести тело алерта на простой русский. Сбой перевода → исходный текст.

    Почему не хватает обычного ``from spa_core.telegram.humanize import ...``:
    CI зовёт этот файл как ``python scripts/site_freshness_monitor.py``
    (`.github/workflows/site_freshness.yml`), поэтому ``sys.path[0]`` — каталог
    ``scripts/``, а НЕ корень репозитория (рабочий каталог в ``sys.path`` при
    запуске файла не попадает). Корневого пакета ``spa_core`` на пути нет, импорт
    падал ``ModuleNotFoundError``, ``except`` его глотал — и владельцу уезжал сырой
    английский: прогон 2026-08-04T08:51:36Z → алерт «🛡️ SITE CUSTODIAN — 1 FAIL(s)»
    в 08:51:55Z. На Маке (`scripts/site_content_audit.py` импортирует ``_alert``
    пакетом) путь был исправен — поэтому дефект и жил только в CI.

    Загрузка идёт ПО ПУТИ К ФАЙЛУ и намеренно НЕ трогает ``sys.path``: лестница
    доставки (``telegram_manager`` с его дедупом/кулдауном → сырой Telegram API)
    обязана остаться ровно такой, как сегодня. Сделать в CI достижимым ещё и
    ``telegram_manager`` — это изменение того, каким каналом и с каким подавлением
    уходит ТРЕВОГА (риск fail-open), а не оформления текста; отдельное решение.

    Контракт ``humanize`` не меняется: нераспознанная строка проходит вербатим,
    числа/коды переносятся как есть, ничего не выдумывается.
    """
    humanize_body = None
    try:  # обычный путь: корень репозитория уже на sys.path
        from spa_core.telegram.humanize import humanize_body  # type: ignore[no-redef]
    except Exception:  # noqa: BLE001 — ниже загрузка по файлу
        try:
            import importlib.util
            _hpath = _ROOT / "spa_core" / "telegram" / "humanize.py"
            _spec = importlib.util.spec_from_file_location("_spa_humanize", _hpath)
            if _spec is not None and _spec.loader is not None:
                _mod = importlib.util.module_from_spec(_spec)
                _spec.loader.exec_module(_mod)
                humanize_body = _mod.humanize_body
        except Exception:  # noqa: BLE001 — доставка важнее оформления
            humanize_body = None
    if humanize_body is None:
        return msg
    try:
        return humanize_body(msg)
    except Exception:  # noqa: BLE001 — алерт обязан дойти даже без перевода
        return msg


#: Хвост, который дописывается к тревоге, когда отправка идёт МИМО журнала канала.
#: Владелец обязан видеть это в самом сообщении: иначе следующий разбор «кто это шлёт»
#: снова упрётся в пустую историю и потратит круг (08–09.08 потрачено два).
OFF_JOURNAL_NOTE = ("\n⚠️ отправлено из CI мимо журнала канала "
                    "(живого дерева нет — эта отправка в истории не сохранится)")


def _live_journal():
    """Канонический заслон+журнал (`telegram_client`) — или ``(None, причина)``.

    Почему проверка идёт по ЖИВОМУ ДЕРЕВУ, а не по импортируемости модуля
    ------------------------------------------------------------------------------
    Модуль в CI загрузить можно (репозиторий выкачан), но `alert_history.json` и файл
    лимита потока он разрешает через `live_data_dir` — то есть в `data/` того дерева,
    из которого запущен. В GitHub Actions это каталог раннера: запись туда умирает
    вместе с job'ом. Это был бы не журнал, а его ИМИТАЦИЯ — ровно тот класс, который
    проект закрывает годами («сторож честно отвечает на свой вопрос, а читают его как
    ответ на нужный»). Поэтому: нет живого дерева ⇒ журнала нет, и мы говорим это
    вслух, а не делаем вид.

    sys.path НЕ трогаем (см. `_humanize_body`): загрузка идёт по пути к файлу, а его
    единственная пакетная зависимость (`spa_core.utils.live_paths`, чистый stdlib)
    подкладывается в `sys.modules` вручную. Достижимым становится РОВНО один модуль —
    канал доставки тревоги не меняется.
    """
    import os
    # Порядок разрешения — тот же, что в `spa_core/utils/live_paths.py`. Проверяем именно
    # СУЩЕСТВОВАНИЕ каталога, а не наличие переменной: `live_data_dir` вернёт указанный
    # путь как есть, а `_record_history` создаёт каталоги — то есть при указателе в пустоту
    # журнал был бы «создан» на пустом месте и опять оказался бы имитацией.
    sandbox = os.environ.get("SPA_DATA_DIR")
    explicit_root = os.environ.get("SPA_LIVE_ROOT")
    if sandbox:
        live = Path(sandbox).is_dir()
    elif explicit_root:
        live = Path(explicit_root).is_dir()
    else:
        live = (Path.home() / "Documents" / "SPA_Claude").is_dir()
    if not live:
        return None, "live_tree_absent"
    try:  # обычный путь: корень репозитория уже на sys.path (Мак, тесты)
        from spa_core.alerts import telegram_client
        return telegram_client, ""
    except Exception:  # noqa: BLE001 — ниже загрузка по файлу
        pass
    try:
        import importlib.machinery
        import importlib.util
        import types

        def _stub_pkg(name: str, directory: Path) -> None:
            """Пакет-заглушка с НАСТОЯЩИМ ``__path__``.

            Без ``__path__``/``__spec__`` заглушка ломала бы обычный
            ``import spa_core.<что-угодно>`` дальше в этом же процессе (а `_humanize_body`
            им и пользуется) и роняла бы ``importlib.util.find_spec``. Поэтому пакет
            остаётся полноценным: машинерия импорта продолжит искать подмодули на диске.
            """
            if name in sys.modules:
                return
            mod = types.ModuleType(name)
            mod.__path__ = [str(directory)]  # type: ignore[attr-defined]
            mod.__spec__ = importlib.machinery.ModuleSpec(
                name, None, is_package=True)
            mod.__spec__.submodule_search_locations = [str(directory)]  # type: ignore[union-attr]
            sys.modules[name] = mod

        def _by_path(name, path):
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                raise ImportError(name)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
            return mod

        _stub_pkg("spa_core", _ROOT / "spa_core")
        _stub_pkg("spa_core.utils", _ROOT / "spa_core" / "utils")
        _stub_pkg("spa_core.alerts", _ROOT / "spa_core" / "alerts")
        if "spa_core.utils.live_paths" not in sys.modules:
            _by_path("spa_core.utils.live_paths", _ROOT / "spa_core" / "utils" / "live_paths.py")
        if "spa_core.alerts.telegram_client" not in sys.modules:
            _by_path("spa_core.alerts.telegram_client",
                     _ROOT / "spa_core" / "alerts" / "telegram_client.py")
        return sys.modules["spa_core.alerts.telegram_client"], ""
    except Exception as exc:  # noqa: BLE001 — доставка тревоги важнее наблюдения
        return None, f"client_unavailable: {type(exc).__name__}"


def _alert(report):
    """Тревога Site Custodian владельцу — через ЕДИНСТВЕННЫЙ заслон канала.

    Что здесь изменено 13.08 (цикл #218) и почему
    ------------------------------------------------------------------------------
    Эта дверь была третьей и последней, которая шла в чат владельца сырым POST: ни
    лимита потока, ни дедупа, ни записи в историю. Запускается она из GitHub Actions
    каждые 6 часов боевыми секретами — то есть её сообщения не попадали в
    `alert_history.json` НИКОГДА, и вопрос владельца «кто это шлёт» был неотвечаем по
    построению (13.08, дословно: «параллельная история, которую ты не видишь»).

    Отдельно снят `telegram_manager.send(...)`, стоявший первой ступенью: менеджер
    ВЫВЕДЕН ИЗ СТРОЯ (`_send_raw` кладёт текст в дайджест и ВСЕГДА возвращает False),
    поэтому управление всегда проваливалось в сырой POST ниже — подавление там
    выглядело существующим и не работало ни разу, а на Маке владелец получал ещё и
    копию в дайджесте. Тот же класс, что и починенный 13.08 ключ дедупа.

    Порядок теперь: спросить заслон (он же и запишет отказ) → доставить → записать
    исход. Доставка НЕ ослаблена: лестница «env-секреты → Keychain → сырой POST»
    осталась ровно та же, а когда заслон недоступен, сообщение всё равно уходит —
    молчащая тревога хуже неучтённой. Возвращает словарь исхода (он же уезжает в
    отчёт, а тот — в артефакт CI).
    """
    if report.get("ok"):
        return {"attempted": False, "reason": "report_ok"}
    # Форма отчёта у двух звонящих РАЗНАЯ, и вторая никогда не доезжала (замер #218).
    # `_deploy_snapshot` зовёт нас со словарём `{"severity", "failures"}`, а тело читало
    # `report['n_fails']` и `report['fails']` ⇒ KeyError, который call-site глотал бы
    # `except Exception: pass`. То есть тревога «табличка честности НЕ уехала на сайт»
    # (публично видно завышенное число) не уходила владельцу НИ РАЗУ.
    # Тест 09.08 этого не видел: он подменял сам `_alert` и проверял, что его ПОЗВАЛИ, —
    # тот же класс «сторож отвечает не на тот вопрос», только уровнем ниже.
    fails = report.get("fails")
    if not isinstance(fails, list):
        fails = report.get("failures") or []
    n_fails = report.get("n_fails", len(fails))
    ts = report.get("ts") or datetime.datetime.now(datetime.timezone.utc).isoformat()
    lines = [f"🛡️ SITE CUSTODIAN — {n_fails} FAIL(s) @ {ts}"]
    for f in fails[:8]:
        lines.append(f"  [{f.get('severity', report.get('severity', 'FAIL'))}] "
                     f"{f.get('code', '?')}: {f.get('detail', '')}")
    if report.get("degrade_triggered"):
        lines.append(f"  ⛔ KILL-RULE: site set to DEGRADED ({report['degrade_reason']})")
    msg = "\n".join(lines)
    # Владельцу — простым русским (owner-задание 2026-07-20, повторено 2026-08-04).
    # Перевод чисто текстовый: нераспознанная строка проходит вербатим, технический
    # detail сохраняется, сбой перевода отдаёт исходный текст (алерт обязан дойти).
    # Загрузчик — `_humanize_body`: в CI пакета `spa_core` нет на sys.path (см. там).
    msg = _humanize_body(msg)

    # 1. ЕДИНСТВЕННЫЙ заслон канала: лимит потока + дедуп. Отказ он пишет в историю САМ —
    #    «подавлено» и «канал сломан» не имеют права выглядеть одинаково.
    client, why = _live_journal()
    if client is None:
        # Журнала нет — говорим об этом ВСЛУХ, в самом сообщении и в отчёте.
        msg += OFF_JOURNAL_NOTE
        print(f"site_freshness_monitor: отправка МИМО журнала канала ({why})", file=sys.stderr)
    else:
        reason = client.guard_outbound(msg)
        if reason is not None:
            print(f"site_freshness_monitor: тревога подавлена заслоном ({reason})", file=sys.stderr)
            return {"attempted": False, "journaled": True, "reason": reason}

    # 2. Доставка. Секреты — из env (CI) или Keychain (Мак). Никогда не в коде.
    import os
    tok = os.environ.get("TELEGRAM_BOT_TOKEN_SPA")
    chat = os.environ.get("TELEGRAM_CHAT_ID_SPA")
    if not (tok and chat):
        try:
            tok = tok or subprocess.run(["security", "find-generic-password", "-s", "TELEGRAM_BOT_TOKEN_SPA", "-w"],
                                        capture_output=True, text=True, timeout=5).stdout.strip()
            chat = chat or subprocess.run(["security", "find-generic-password", "-s", "TELEGRAM_CHAT_ID_SPA", "-w"],
                                          capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:
            pass

    def _journal(ok, message_id=None, error=None):
        """Записать исход в общий журнал канала. Наблюдение не роняет доставку."""
        if client is None:
            return False
        try:
            client._record_history(msg, ok=ok, message_id=message_id, error=error)
            return True
        except Exception:  # noqa: BLE001
            return False

    if tok and chat:
        try:
            data = json.dumps({"chat_id": chat, "text": msg}).encode()
            req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage",
                                         data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                message_id = None
                try:
                    message_id = (json.loads(resp.read().decode()).get("result") or {}).get("message_id")
                except Exception:  # noqa: BLE001 — разбор тела best-effort
                    pass
            journaled = _journal(True, message_id=message_id)
            return {"attempted": True, "sent": True, "journaled": journaled,
                    "message_id": message_id, "off_journal_note": client is None}
        except Exception as e:
            print(f"site_freshness_monitor: raw telegram alert failed ({e})", file=sys.stderr)
            _journal(False, error=str(e))
            return {"attempted": True, "sent": False, "journaled": client is not None,
                    "error": str(e)[:200]}
    print("site_freshness_monitor: no alert channel available; report written (CI failure = the alert)",
          file=sys.stderr)
    _journal(False, error="no_alert_channel")
    return {"attempted": True, "sent": False, "journaled": client is not None,
            "error": "no_alert_channel"}


def _deploy_snapshot(message: str, what: str) -> bool:
    """Отправить снимок и ЧЕСТНО сказать, уехал он или нет.

    Дефект, измеренный 09.08: обе ветки ниже звали пушер и НЕ читали код возврата,
    а затем печатали «+ pushed» безусловно. Пуш упирался в стража перезаписи,
    возвращал отказ — и отказ не читал никто. На публичном сайте оставалось 5.2 %
    там, где живой расчёт давал 4.83 %, а у нас на диске лежало `degraded: true`,
    то есть система считала сайт уже помеченным.

    Это ровно тот класс, который проект закрывает годами: сторож честно отвечает на
    свой вопрос («я записал флаг»), а читают его как ответ на нужный («табличка на
    сайте»). Лечится не эскалацией, а тем, что провал перестаёт быть тихим.

    Возвращает True только при коде 0. Ничего не решает про owner-gate — пропуск
    таблички через гейт остаётся решением владельца.
    """
    try:
        rc = subprocess.run(
            [sys.executable, str(_ROOT / "push_to_github_batch.py"),
             "--files", str(_SNAP), "--message", message],
            timeout=180).returncode
    except Exception as e:  # noqa: BLE001
        print(f"site_freshness_monitor: КРИТИЧНО — {what}: пушер не запустился ({e})",
              file=sys.stderr)
        return False
    if rc != 0:
        print(f"site_freshness_monitor: КРИТИЧНО — {what}: доставка ОТКАЗАНА (код {rc}). "
              f"Локальный снимок изменён, публичный сайт — НЕТ. Правило честности "
              f"не исполнено.", file=sys.stderr)
        try:
            _alert({"severity": "FAIL", "failures": [{
                "code": "HONESTY_PLAQUE_UNDELIVERED",
                "detail": f"{what}: push rc={rc} — сайт не обновлён, расхождение остаётся видимым публично",
            }]})
        except Exception:  # noqa: BLE001
            pass
        return False
    return True


def _apply_degrade():
    """Kill-rule: flip the snapshot to degraded:true + deploy it (refusal-first showcase)."""
    try:
        snap = json.loads(_SNAP.read_text())
        if snap.get("degraded") is True:
            return
        snap["degraded"] = True
        _atomic_write(_SNAP, snap)
        ok = _deploy_snapshot(
            "chore(site-custodian): KILL-RULE degrade site (stale/overstated metric)",
            "постановка таблички честности")
        print(f"site_freshness_monitor: DEGRADED flag set + "
              f"{'pushed' if ok else 'НЕ ДОСТАВЛЕНО'}")
    except Exception as e:
        print(f"site_freshness_monitor: degrade apply failed ({e})", file=sys.stderr)


def _clear_degrade():
    """Recovery: all checks pass and the snapshot is degraded -> lift the plaque (set False + deploy)."""
    try:
        snap = json.loads(_SNAP.read_text())
        if snap.get("degraded") is not True:
            return
        snap["degraded"] = False
        _atomic_write(_SNAP, snap)
        ok = _deploy_snapshot(
            "chore(site-custodian): recover — checks pass, lift degraded plaque",
            "снятие таблички честности")
        print(f"site_freshness_monitor: recovered — degraded cleared + "
              f"{'pushed' if ok else 'НЕ ДОСТАВЛЕНО'}")
    except Exception as e:
        print(f"site_freshness_monitor: clear-degrade failed ({e})", file=sys.stderr)


def run():
    now = datetime.datetime.now(datetime.timezone.utc)
    prev = None
    if _REPORT.exists():
        try:
            prev = json.loads(_REPORT.read_text())
        except ValueError:
            prev = None
    snapshot = json.loads(_SNAP.read_text()) if _SNAP.exists() else {}

    _, home_html = _get(SITE + "/")
    _, track_html = _get(SITE + "/track-record/")
    api = api_headline(
        _get_json(API + "/api/v1/golive"),
        _get_json(API + "/api/ssot/facts") or _get_json(API + "/api/live/portfolio"),
        _get_json(API + "/api/rates-desk/full-chain/equity_track"),
    )
    sitemap_statuses = {}
    for url in _sitemap_urls():
        code, _ = _get(url, timeout=12)
        sitemap_statuses[url] = code
    # verifier pin
    pin = None
    m = re.search(r"VERIFIER_SHA256\s*=\s*'([0-9a-f]{64})'",
                  (_ROOT / "landing" / "src" / "pages" / "verify.astro").read_text())
    pin = m.group(1) if m else None
    _, live_verifier = _get("https://raw.githubusercontent.com/yurii-spa/SPA/main/scripts/verify_spa.py")
    verifier_sha = hashlib.sha256(live_verifier.encode()).hexdigest() if live_verifier else None

    report = evaluate(snapshot=snapshot, home_html=home_html, track_html=track_html, api=api,
                      sitemap_statuses=sitemap_statuses, verifier_sha=verifier_sha, pin_sha=pin,
                      now=now, prev_report=prev)
    _atomic_write(_REPORT, report)
    print(json.dumps({k: report[k] for k in ("ok", "n_fails", "degrade_triggered", "snapshot_age_h")}, indent=2))
    if not report["ok"]:
        # Исход доставки — В ОТЧЁТ: из CI живого журнала канала не видно, а отчёт
        # уезжает артефактом job'а. Иначе следы отправки не остаётся вообще нигде.
        report["alert_delivery"] = _alert(report)
        _atomic_write(_REPORT, report)
    if report["degrade_triggered"]:
        _apply_degrade()
    elif snapshot.get("degraded") is True:
        # recovery: the kill-rule no longer fires (snapshot not overstated, not 48h-stale) -> lift the
        # plaque even if other non-degrading fails remain (e.g. deploy-lag OVERSTATED alerts, which must
        # NOT keep a correct snapshot degraded).
        _clear_degrade()
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(run())
