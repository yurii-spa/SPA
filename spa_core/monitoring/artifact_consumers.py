"""artifact_consumers.py — кто ПОТРЕБЛЯЕТ продукт агента. Четыре канала, не один.

Нужен для карантина (`scripts/agent_quarantine.py`): агента откладывают, только если его
продукт никем не потребляется. Цена ошибки здесь высокая, поэтому вопрос «кто потребляет»
задаётся ЧЕТЫРЬМЯ способами — первая версия задавала один и едва не отправила в карантин
`artifact_freshness`, `watchdog`, `self_heal` и `cycle_health`.

Почему один способ не годится: у монитора потребитель — **не код, а человек**. Файл
`watchdog_status.json` не читает ни один модуль, и это ничего не говорит о нужности сторожа:
его результат уезжает владельцу в Телеграм. Спрашивать только «кто открывает этот файл» —
значит объявить ненужными ровно тех, кто и должен кричать.

Каналы:

* ``code``     — модуль проекта ЧИТАЕТ артефакт (разбор синтаксиса, не текстовый поиск);
* ``receipts`` — квитанции потребления `data/consumption_receipts.jsonl` (рантайм-факт);
* ``manifest`` — объявленные потребители в `artifacts[].consumers`;
* ``owner``    — агент шлёт результат владельцу (Телеграм/тревога): потребитель — человек.

`measured=False` означает «спросить не удалось», и это НЕ «никто»: карантин при таком ответе
обязан отказать (fail-CLOSED).

LLM_FORBIDDEN. Только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_RECEIPTS_REL = "data/consumption_receipts.jsonl"

#: Признаки того, что результат уезжает ЧЕЛОВЕКУ.
_OWNER_CHANNEL = re.compile(
    r"push_critical|push_policy|telegram_client|telegram_manager|_post_message|send_message")


def _basename(p: str) -> str:
    return p.rsplit("/", 1)[-1]


def code_readers(artifacts: set[str], repo: Path | None = None,
                 *, exclude_module: str | None = None) -> set[str]:
    from spa_core.monitoring.artifact_io_scan import READ, scan_file
    repo = repo or _REPO
    want = {_basename(a) for a in artifacts}
    out: set[str] = set()
    for base in ("spa_core", "scripts"):
        root = repo / base
        if not root.is_dir():
            continue
        for f in root.rglob("*.py"):
            if "tests" in f.parts or "__pycache__" in f.parts:
                continue
            mod = str(f.relative_to(repo))[:-3].replace("/", ".")
            if mod == exclude_module:
                continue
            try:
                io = scan_file(f)
            except Exception:                                   # noqa: BLE001
                continue
            for art, kinds in io.items():
                if READ in kinds and _basename(art) in want:
                    out.add(mod)
    return out


def receipt_consumers(artifacts: set[str], receipts_path: Path | None = None) -> set[str]:
    p = receipts_path or _REPO / _RECEIPTS_REL
    if not p.is_file():
        return set()
    want = {_basename(a) for a in artifacts}
    out: set[str] = set()
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    for line in text.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        a, c = d.get("artifact"), d.get("consumer")
        if a and c and _basename(a) in want:
            out.add(c)
    return out


def manifest_consumers(artifacts: set[str], manifest: dict) -> set[str]:
    want = {_basename(a) for a in artifacts}
    out: set[str] = set()
    for a in manifest.get("artifacts") or []:
        if _basename(a.get("path", "")) in want:
            out.update(a.get("consumers") or [])
    return out


def reaches_owner(module: str, repo: Path | None = None, depth: int = 1) -> bool:
    """Уезжает ли результат агента ЧЕЛОВЕКУ (Телеграм/тревога)."""
    from spa_core.monitoring.artifact_io_scan import closure
    repo = repo or _REPO
    for m in closure(module, repo, depth=depth):
        f = repo / (m.replace(".", "/") + ".py")
        if not f.is_file():
            continue
        try:
            if _OWNER_CHANNEL.search(f.read_text(encoding="utf-8", errors="replace")):
                return True
        except OSError:
            continue
    return False


def consumers_of(label: str, repo: Path | None = None) -> dict:
    """Полный ответ по агенту. Никогда не бросает — но честно ставит measured=False."""
    repo = repo or _REPO
    out = {"label": label, "measured": False, "applicable": True,
           "consumers": 0, "by_channel": {}, "note": ""}
    try:
        from spa_core.monitoring.artifact_contract import _entry_modules, declared_produces
        mods = _entry_modules(repo)
        module = mods.get(label)
        if not module:
            out["note"] = "точка входа агента не читается — спросить не у кого"
            return out
        f = repo / (module.replace(".", "/") + ".py")
        declared = declared_produces(f) if f.is_file() else None
        if declared is None:
            out["note"] = "агент не объявил PRODUCES — что он производит, неизвестно"
            return out
        if not declared:
            # ЧЕТВЁРТЫЙ исход, и он не «никто». Агент ЯВНО объявил, что артефактов
            # не производит (`PRODUCES = ()`), — значит потребления файлов у него
            # нет по построению, и ноль читателей ничего о его нужности не говорит.
            # Без этой развилки замер выдавал «продукт не потребляет никто» там, где
            # продукта нет вовсе, и `cmo_editorial` попал в кандидаты на отключение
            # по тавтологии (замер 29.08). Годность такой службы меряется другим
            # признаком — доступностью или фактом отправки (ADR-154).
            out.update(measured=True, applicable=False, declared=[],
                       note="агент ЯВНО объявил PRODUCES = () — потребление файлов "
                            "к нему НЕПРИМЕНИМО; годность мерится доступностью/фактом отправки")
            return out
        arts = set(declared)
        manifest = json.loads((repo / "architecture" / "manifest.json").read_text(encoding="utf-8"))
        ch = {
            "code": sorted(code_readers(arts, repo, exclude_module=module)),
            "receipts": sorted(receipt_consumers(arts, repo / _RECEIPTS_REL)),
            "manifest": sorted(manifest_consumers(arts, manifest)),
            "owner": ["владелец (телеграм/тревога)"] if reaches_owner(module, repo) else [],
        }
        out.update(measured=True, by_channel=ch, declared=sorted(arts),
                   consumers=sum(len(v) for v in ch.values()))
        if not out["consumers"]:
            out["note"] = "продукт не потребляет никто: ни код, ни квитанции, ни манифест, ни владелец"
        return out
    except Exception as exc:                                    # noqa: BLE001
        out["note"] = f"замер не состоялся: {exc}"
        return out
