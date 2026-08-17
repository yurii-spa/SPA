#!/usr/bin/env python3
"""deploy_site_snapshot.py — Site Custodian block 1: auto-deploy the fresh snapshot after each cycle.

The daily cycle writes data/golive_status.json + data/equity_curve_daily.json (+ paper_trading_status).
This regenerates landing/src/data/track_snapshot.json from them and, if it CHANGED, commits + pushes it
so the existing .github/workflows/deploy-landing.yml (triggers on `landing/**`) rebuilds the public site
with no manual step — target lag <= 30 min after the cycle.

Deterministic, fail-safe, logged. No push if the snapshot is unchanged (avoid empty deploys). Delivery
goes through scripts/safe_site_push.py — the ONLY sanctioned path for `landing/**` (PAT from Keychain,
never in code). Called from scripts/run_daily_paper_cycle.sh after the cycle. Safe to run standalone.

Разбор простоя 2026-08-08 (сайт замёрз на 2026-08-06, цикл при этом зелёный). Три дефекта,
и нужны были ВСЕ ТРИ, чтобы простой прожил двое суток незамеченным:

1. **Пуш шёл в обход.** Файл сайта уезжал напрямую через `push_to_github_batch.py`, минуя
   `safe_site_push.py` — единственный санкционированный путь для `landing/**` (протокол §3.4).
   Отсюда же второе следствие: ресит доставки (ADR-066 B3) пишет ИМЕННО обёртка, значит его
   не было, и сторож не мог спросить «продукт ДОШЁЛ до публики?».
2. **Страж перезаписи запирал доставку навсегда (rc=4).** `track_snapshot.json` целиком
   генерируется из `data/`; его версия на remote — не чужая правка, а предыдущее поколение
   того же генератора. Страж, написанный для файлов, которые правят руками, честно краснел
   на ВЕРНОЕ состояние. Лечится не отключением стража, а объявлением намерения: мы пересобрали
   файл в этом же прогоне, поэтому перезапись здесь ОСОЗНАННАЯ (`--allow-overwrite`).
3. **Причина отказа выбрасывалась.** `print(stdout or stderr)`: при непустом stdout текст отказа
   (он идёт в stderr) не печатался никогда. В логе оставалось «push FAILED» без причины —
   а шаг помечен non-fatal, поэтому цикл рапортовал успех. Сторож сайта был единственным,
   кто сказал правду, и то владельцу в Telegram.

Дефект 4 — КАНОН НЕ ЕХАЛ ВМЕСТЕ СО СНИМКОМ (ADR-070 п.2; решение владельца по карточке
`owner-decision-storozh-saita-ne-kladet-v-git-dannye-iz`, вариант 1, 2026-08-16).

Кастодиан пушил РОВНО один файл — готовый снимок, — а исходники, из которых он посчитан,
оставались только на Маке. Замер: шесть последних коммитов кастодиана содержат НОЛЬ файлов
из `data/`; сайт публиковал `real_track_days: 53` и `gates_passed: 29/29`, а свежайший канон
в git был от 04.07 с `real_track_days: 13` и `passed: 27/29`. Две беды из одной причины:

* **Числа сайта нельзя проверить из репозитория** — ровно тот ответ «поверьте на слово»,
  ради отказа от которого честный трек и затевался.
* **Owner-gate краснел каждую ночь на верной работе.** Он умеет пересчитать изменившееся
  число из канона того же коммита и пропустить только совпавшее
  (`check_owner_gate._canon_reproduced_fields`, ADR-070 п.3) — но пересчитывать было
  НЕ ИЗ ЧЕГО, и по fail-CLOSED он заворачивал честную ночную доставку. Сторож, ежедневно
  краснеющий на честной работе, будет отключён людьми ровно до первого настоящего нарушения.

Поэтому доставка идёт ОДНИМ коммитом: снимок + три файла канона, из которых `build_snapshot`
его и считает. Список закрыт и обязан совпадать с `check_owner_gate._TS_CANON_FILES` — лишние
файлы из `data/` (живой трек целиком) сюда не возят. `--allow-overwrite` распространяется на
весь набор осознанно: канон, как и снимок, целиком производит дневной цикл на этой же машине,
его remote-версия — прошлое поколение того же цикла, а не чужая правка (дефект 2 выше). Канон
отсутствует на диске ⇒ доставки нет вовсе (fail-CLOSED): публиковать число, которое нечем
подтвердить, — это и есть исходная авария.
"""
# LLM_FORBIDDEN
import hashlib
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SNAP = _ROOT / "landing" / "src" / "data" / "track_snapshot.json"
_GEN = _ROOT / "scripts" / "generate_track_snapshot.py"
# ЕДИНСТВЕННЫЙ санкционированный путь для landing/** — обёртка с owner-гейтом и реситом
# доставки. Прямой batch-пушер отсюда не вызывается: см. дефект 1 в шапке модуля.
_PUSH = _ROOT / "scripts" / "safe_site_push.py"
_PY = sys.executable

# КАНОН ТРЕКА — ровно те файлы, которые читает `generate_track_snapshot.build_snapshot`
# (её параметры `golive_path` / `equity_path` / `pts_path`). Едут в ТОТ ЖЕ коммит, что и
# снимок: без них owner-gate не может пересчитать изменившееся число, а человек — сойтись
# с сайтом из репозитория (ADR-070 п.2, дефект 4 в шапке модуля). Список ЗАКРЫТ: остальной
# `data/` — живой трек, его сюда не возят. Совпадение с `check_owner_gate._TS_CANON_FILES`
# держит тест `spa_core/tests/test_site_custodian_commits_canon.py`.
_CANON = (
    "data/golive_status.json",
    "data/equity_curve_daily.json",
    "data/paper_trading_status.json",
)


def _sha(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def _both(r) -> str:
    """Оба потока подпроцесса, а НЕ `stdout or stderr`.

    Отказы пушера (страж перезаписи, owner-гейт, расхождение инструмента) печатаются в
    stderr, а stdout к этому моменту уже непустой («Batch-пуш … base commit …»). Прежняя
    форма `stdout or stderr` поэтому выбрасывала ровно ту строку, ради которой лог и читают:
    двое суток в журнале цикла стояло «push FAILED» без единого слова о причине.
    """
    return "\n".join(s for s in ((r.stdout or "").strip(), (r.stderr or "").strip()) if s)


# Volatile fields that change every regeneration (wall-clock stamps) and must be IGNORED when
# deciding whether a deploy is warranted — otherwise every run looks "changed" and pushes noise.
_VOLATILE = ("generated_at",)


def _meaningful(d: dict) -> dict:
    """Snapshot content minus volatile wall-clock fields, for change detection."""
    return {k: v for k, v in d.items() if k not in _VOLATILE}


def _origin_snapshot():
    """track_snapshot.json as it currently exists on origin/main — the DEPLOY TRUTH (parsed), or None.

    We compare the freshly-generated snapshot against ORIGIN, not against the previous LOCAL copy:
    the local working tree drifts from origin (pushes go via the GitHub API, not `git push`), so a
    local file that is already fresh while origin is stale would otherwise read as "unchanged" and
    the push would be skipped forever — origin stuck a day behind (the recurring stale-site bug).
    Returns None if origin can't be read → caller pushes to be safe (never silently skip).
    """
    try:
        import base64
        import json as _json
        import urllib.request

        pat = subprocess.run(
            ["security", "find-generic-password", "-s", "GITHUB_PAT_SPA", "-w"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        if not pat:
            return None
        req = urllib.request.Request(
            "https://api.github.com/repos/yurii-spa/SPA/contents/"
            "landing/src/data/track_snapshot.json?ref=main",
            headers={"Authorization": f"token {pat}", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return _json.loads(base64.b64decode(_json.load(resp)["content"]))
    except Exception as e:  # noqa: BLE001 — fail-safe: unreadable origin => push (don't silently skip)
        print(f"deploy_site_snapshot: could not read origin snapshot ({e}) — will push to be safe")
        return None


def main() -> int:
    import json

    # 1. regenerate from the freshly-written committed data
    r = subprocess.run([_PY, str(_GEN)], capture_output=True, text=True, timeout=120)
    print(_both(r))
    if r.returncode != 0:
        print("deploy_site_snapshot: generator FAILED — not deploying", file=sys.stderr)
        return 1
    # Отпечаток ровно того, что произвёл генератор в ЭТОМ прогоне. Осознанная перезапись
    # (шаг 3) разрешена только для него: если файл на диске после генерации кто-то тронул,
    # мы больше не знаем, что именно перезаписываем, и отказываем (fail-CLOSED).
    generated_sha = _sha(_SNAP)
    # Канон обязан быть НА ДИСКЕ и обязан остаться тем же до момента доставки: снимок и
    # исходники едут одним коммитом, и разъехавшаяся пара хуже отсутствующей — она
    # выглядит проверяемой, не будучи ею. Нет файла ⇒ не публикуем (fail-CLOSED).
    canon_paths = [_ROOT / rel for rel in _CANON]
    missing = [rel for rel, pth in zip(_CANON, canon_paths) if not pth.is_file()]
    if missing:
        print(f"deploy_site_snapshot: канона нет на диске ({', '.join(missing)}) — "
              f"снимок нечем подтвердить, не деплоим", file=sys.stderr)
        return 1
    canon_shas = [_sha(p) for p in canon_paths]
    # 2. deploy only if the MEANINGFUL content differs from ORIGIN (deploy truth), ignoring the
    #    volatile generated_at stamp — and NOT vs the previous local copy (local drifts from origin).
    local = json.loads(_SNAP.read_text())
    origin = _origin_snapshot()
    if origin is not None and _meaningful(origin) == _meaningful(local):
        print("deploy_site_snapshot: snapshot matches origin/main (data identical) — no deploy needed")
        return 0
    # 3. push ONLY the snapshot -> deploy-landing.yml rebuilds the site (landing/** trigger).
    #    Через safe_site_push.py: owner-гейт + ресит доставки. `--allow-overwrite` объявляет
    #    намерение перед стражем расхождения — remote-версия этого файла всегда «наша прошлая»,
    #    чужих правок в целиком генерируемом артефакте не бывает (дефект 2 в шапке модуля).
    if _sha(_SNAP) != generated_sha:
        print("deploy_site_snapshot: snapshot changed after generation — refusing to overwrite blindly",
              file=sys.stderr)
        return 1
    if [_sha(pth) for pth in canon_paths] != canon_shas:
        # Канон сдвинулся между генерацией и пушем ⇒ снимок посчитан НЕ ИЗ ТОГО, что уедет
        # рядом. Такой коммит гейт честно завернёт, а сайту достанется непроверяемое число.
        print("deploy_site_snapshot: канон изменился после генерации снимка — пара «снимок ↔ канон» "
              "разъехалась, не деплоим (следующий цикл соберёт согласованную)", file=sys.stderr)
        return 1
    p = subprocess.run(
        [_PY, str(_PUSH), "--files", str(_SNAP), *[str(c) for c in canon_paths],
         "--allow-overwrite",
         "--message", "chore(site-custodian): auto-deploy fresh track_snapshot after daily cycle "
                      "(+ канон трека, ADR-070 п.2)"],
        capture_output=True, text=True, timeout=180,
    )
    print(_both(p))
    if p.returncode != 0:
        # Причина обязана быть В ЭТОЙ ЖЕ строке: шаг помечен non-fatal, и без неё
        # в логе цикла остаётся «push FAILED» без объяснения (дефект 3 в шапке модуля).
        print(f"deploy_site_snapshot: push FAILED (rc={p.returncode}) — "
              f"{_both(p).replace(chr(10), ' | ')[:400] or 'без вывода'}", file=sys.stderr)
        return 1
    print("deploy_site_snapshot: pushed fresh snapshot -> deploy-landing triggered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
