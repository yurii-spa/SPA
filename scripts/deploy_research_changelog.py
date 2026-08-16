#!/usr/bin/env python3
"""deploy_research_changelog.py — производитель публичного раздела /changelog (Site Custodian).

Почему этот файл существует
---------------------------
`scripts/generate_research_changelog.py` был написан, протестирован и доставлен — и НЕ ИМЕЛ НИ
ОДНОГО вызывающего: ни агента во флоте, ни шага цикла, ни строки в обёртках; единственное, что его
импортировало, — его собственный тест. Публичная страница `/changelog` из-за этого 23 дня показывала
дайджест от 2026-07-11, то есть выглядела заброшенным продуктом (карточка
`agent-changelog-generator-never-called`, седьмой случай класса «код есть, никто не зовёт»).

Механизм ВЗЯТ СУЩЕСТВУЮЩИЙ, второго не заведено
------------------------------------------------
Ровно тот же, которым в этом репозитории уже доставляется `track_snapshot.json`: шаг в
`scripts/run_daily_paper_cycle.sh` → пересборка из живых данных → доставка ТОЛЬКО через
`scripts/safe_site_push.py` (owner-гейт + ресит доставки, правило `site-copy.md` и протокол §3.4).
Ни нового агента во флоте, ни нового workflow, ни второго пути пуша `landing/**`.

Отдельным файлом рядом с `deploy_site_snapshot.py`, а не внутри него, намеренно: тот скрипт —
положительный контроль аварии 2026-08-08, и его тесты закрепляют «в пуше РОВНО один файл — снимок»
(`test_pushes_only_the_snapshot`) и «пуша не было вовсе» на неизменных данных. Впихнуть сюда второй
артефакт значило бы переписать чужие положительные контроли под себя — то есть ослабить проверки,
видевшие настоящую поломку (инвариант #16). Механизм от этого не раздваивается: путь доставки один
и тот же, и он один на оба артефакта.

Целиком генерируемый ≠ перезаписываемый вслепую
-----------------------------------------------
`track_snapshot.json` собирается из `data/` целиком, поэтому его версия на remote — прошлое поколение
того же генератора, и `--allow-overwrite` там безопасен. `changelog.json` НАКОПИТЕЛЬНЫЙ: генератор
дописывает запись к уже существующим. Локальное дерево дрейфует от origin (пуши идут через API), и
слепая перезапись стёрла бы записи, которых в дереве нет. Поэтому здесь порядок обратный: сначала
СЕЕМ локальный файл содержимым origin (deploy truth), и только потом дописываем. Не прочитали
origin — НЕ ПУБЛИКУЕМ (fail-CLOSED): молча стереть публичную историю хуже, чем день не обновиться.

Fail-CLOSED на пустоте
----------------------
Нечего публиковать — это НОРМАЛЬНОЕ состояние, и оно обязано быть СКАЗАНО, а не показано пустотой:
генератор в каждом прогоне пишет `changelog_status.json` (дата проверки + состояние), страница
читает его и говорит человеческой фразой «проверено тогда-то, изменений с такой-то даты нет».
Выдуманных записей не появляется никогда: при отсутствии живых данных генератор отказывает.

stdlib-only, LLM_FORBIDDEN, read-only на `data/`. Non-fatal шаг цикла: сбой доставки не имеет права
уронить трек — но причина отказа обязана попасть в ту же строку лога (дефект 3 разбора 2026-08-08).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import base64
import datetime as _dt
import hashlib
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_GEN = _ROOT / "scripts" / "generate_research_changelog.py"
# ЕДИНСТВЕННЫЙ санкционированный путь для landing/** (правило site-copy.md, протокол §3.4).
_PUSH = _ROOT / "scripts" / "safe_site_push.py"
_PY = sys.executable

_CHANGELOG_REL = "landing/src/data/changelog.json"
_STATUS_REL = "landing/src/data/changelog_status.json"
_DEPLOYED = (_CHANGELOG_REL, _STATUS_REL)

_API = "https://api.github.com/repos/yurii-spa/SPA/contents/{path}?ref={branch}"

# Возможные исходы чтения origin. «Нет файла» и «не смогли прочитать» — РАЗНЫЕ вещи:
# первого достаточно, чтобы начать историю с нуля, второе обязано остановить доставку.
OK, ABSENT, ERROR = "ok", "absent", "error"


def _both(r) -> str:
    """Оба потока подпроцесса — причина отказа живёт в stderr, а stdout к тому моменту непуст."""
    return "\n".join(s for s in ((r.stdout or "").strip(), (r.stderr or "").strip()) if s)


def _sha(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def _origin_text(rel: str, *, branch: str = "main"):
    """Содержимое файла на origin — DEPLOY TRUTH. → (text|None, OK|ABSENT|ERROR)."""
    try:
        pat = subprocess.run(
            ["security", "find-generic-password", "-s", "GITHUB_PAT_SPA", "-w"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        if not pat:
            return None, ERROR
        req = urllib.request.Request(
            _API.format(path=rel, branch=branch),
            headers={"Authorization": f"token {pat}", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.load(resp)
        return base64.b64decode(body["content"]).decode("utf-8"), OK
    except urllib.error.HTTPError as e:  # noqa: PERF203 — 404 это ответ, а не сбой
        if getattr(e, "code", None) == 404:
            return None, ABSENT
        return None, ERROR
    except Exception:  # noqa: BLE001 — сеть/keychain/битый JSON: не знаем remote ⇒ не публикуем
        return None, ERROR


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Regenerate + deploy the public research changelog")
    ap.add_argument("--date", help="ISO-дата дайджеста (по умолчанию — сегодня, UTC)")
    ap.add_argument("--branch", default="main")
    args = ap.parse_args(argv)
    date = args.date or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")

    changelog = _ROOT / _CHANGELOG_REL

    # 1. Сеем накопительный файл содержимым origin. Дописывать можно только к тому, что
    #    реально опубликовано: локальное дерево дрейфует от origin, и запись, которой в нём
    #    нет, при пуше исчезла бы со страницы навсегда.
    origin_changelog, kind = _origin_text(_CHANGELOG_REL, branch=args.branch)
    if kind == ERROR:
        print("deploy_research_changelog: origin-версию changelog.json прочитать не удалось — "
              "НЕ публикуем (fail-CLOSED: слепая перезапись стёрла бы опубликованные записи)",
              file=sys.stderr)
        return 1
    if kind == OK and origin_changelog is not None and _read(changelog) != origin_changelog:
        changelog.parent.mkdir(parents=True, exist_ok=True)
        tmp = changelog.with_suffix(".json.seed")
        tmp.write_text(origin_changelog, encoding="utf-8")
        tmp.replace(changelog)
        print("deploy_research_changelog: локальный changelog.json засеян версией с origin")
    elif kind == ABSENT:
        print("deploy_research_changelog: на origin файла ещё нет — история начинается с нуля")

    # 2. Пересборка из живых данных. Отказ генератора публикацию отменяет.
    r = subprocess.run([_PY, str(_GEN), "--date", date], capture_output=True, text=True, timeout=120)
    print(_both(r))
    if r.returncode != 0:
        print(f"deploy_research_changelog: генератор ОТКАЗАЛ (rc={r.returncode}) — не публикуем",
              file=sys.stderr)
        return 1
    generated = {rel: _sha(_ROOT / rel) for rel in _DEPLOYED}

    # 3. Публикуем только то, что отличается от origin (пустой деплой — шум).
    to_push = []
    for rel in _DEPLOYED:
        local = _read(_ROOT / rel)
        remote, k = (origin_changelog, kind) if rel == _CHANGELOG_REL \
            else _origin_text(rel, branch=args.branch)
        if k == ERROR:
            print(f"deploy_research_changelog: origin-версию {rel} прочитать не удалось — "
                  f"публикуем, чтобы не пропустить доставку молча")
        elif local == remote:
            continue
        to_push.append(rel)

    if not to_push:
        print("deploy_research_changelog: origin уже содержит эти файлы — деплой не нужен")
        return 0

    # 4. Тот же страж, что у снимка трека: осознанно перезаписываем РОВНО то, что собрали
    #    сами в этом прогоне. Тронул кто-то ещё — мы больше не знаем, что затираем.
    for rel in to_push:
        if _sha(_ROOT / rel) != generated[rel]:
            print(f"deploy_research_changelog: {rel} изменился после генерации — "
                  f"перезаписывать вслепую отказываемся", file=sys.stderr)
            return 1

    p = subprocess.run(
        [_PY, str(_PUSH), "--files", *[str(_ROOT / rel) for rel in to_push], "--allow-overwrite",
         "--branch", args.branch,
         "--message", "chore(site-custodian): refresh public research changelog after daily cycle"],
        capture_output=True, text=True, timeout=180,
    )
    print(_both(p))
    if p.returncode != 0:
        # Причина — в ЭТОЙ ЖЕ строке: шаг non-fatal, иначе в журнале останется «push FAILED»
        # без объяснения, и простой снова проживёт незамеченным (дефект 3, 2026-08-08).
        print(f"deploy_research_changelog: push FAILED (rc={p.returncode}) — "
              f"{_both(p).replace(chr(10), ' | ')[:400] or 'без вывода'}", file=sys.stderr)
        return 1
    print(f"deploy_research_changelog: опубликовано {len(to_push)} файл(ов) -> deploy-landing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
