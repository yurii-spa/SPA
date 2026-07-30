#!/usr/bin/env python3
"""scripts/check_card_claim.py — «эту карточку уже кто-то взял?» (шаг 0b протокола).

**Зачем.** 30.07 две автономные сессии независимо взяли ОДНУ карточку
(`agent-ci-ignores-golive-gate-tests`): `pid6621` в 14:04Z, `pid17579` в 15:16Z. Обе проделали
одну и ту же работу, обе правили `.github/workflows/ci.yml` и `test.yml`; доставлена была одна,
работа второй осталась в `/private/tmp/spa_wt_cycle46`. Протокол ОБЯЗЫВАЕТ объявлять владение
файлами, но `log_session_change.py` — журнал, а не проверка: он ничего не отвечает на вопрос
«эту карточку уже держат?». Ответ оставался на внимательность сессии — и ровно она отказала.
Радиус шире потерянного цикла: доставь обе сессии свои правки одних и тех же файлов, вторая
перезаписала бы первую (пуш идёт через Contents API по sha — гонка даёт 409 либо молчаливую
потерю чужой правки).

**Что делает.** Детерминированно, read-only, только stdlib, **без сети**:

1. читает frontmatter карточки — явный захват `claimed_by` / `claimed_at`;
2. читает `data/session_changes.jsonl` и ищет объявления, относящиеся к ЭТОЙ карточке:
   поле ``card:`` в записи (сильный признак) · файл карточки в списке объявленного владения
   (сильный) · упоминание идентификатора карточки в тексте (слабый);
3. по каждому найденному захвату измеряет активность объявившей сессии тем же кодом, что и
   шаг 0a (`check_undelivered_work.session_state`: `ps -p <pid> -o lstart=`) и возраст записи;
4. отдельно — **пересечение по файлам** (`--files`): свежие объявления других сессий,
   которые держат те же файлы, что я собираюсь править;
5. печатает вердикт и **отдельно** всё, что измерить не удалось.

**Вердикты.** ``free`` — захватов не найдено (и всё измерено) · ``claimed`` — карточку держит
другая сессия (свежо либо активность ПОДТВЕРЖДЕНА) ⇒ **брать НЕЛЬЗЯ, взять следующую** ·
``stale`` — сильный захват старше окна ожидания без подтверждённой активности ⇒ кандидат на
подъём осиротевшей работы, порядок прежний: **сверить вручную**, отчёту не верить, перепроверить
прогонами (авто-захвата чужой работы здесь нет и не будет) · ``unchecked`` — что-то не измерено.

**fail-CLOSED (инв. #2).** «Не смог измерить» никогда не сворачивается в «карточка свободна»:
нет карточки / нет журнала объявлений / битая метка времени захвата / `ps` не отработал у
старого захвата → раздел «НЕ ИЗМЕРЕНО» и код возврата 2. Коды: **0** — свободна (всё измерено);
**1** — есть захват (claimed/stale); **2** — что-то не измерено (перебивает 1).

**Осознанные границы (это проверка ПЕРЕД взятием, не блокировка):**
- захват в карточке — кооперативный контроль: файл держится честной записью, а не lock'ом ядра.
  Критическая секция самой записи защищена `O_EXCL`-файлом, но ничто не мешает править карточку
  мимо инструмента;
- **слабый признак (упоминание в тексте) блокирует только пока свеж.** Старое упоминание уходит
  в раздел «история», а не в находку: иначе любая когда-либо тронутая карточка была бы занята
  навсегда. Старая НЕдоставленная работа — домен шага 0a (`check_undelivered_work.py`), который
  сверяет файлы с origin; дублировать его здесь значит спорить с ним же;
- «объявленный файл» ≠ «файл, который сессия реально изменила» (владение объявляется авансом),
  поэтому пересечение по файлам — сигнал к сверке, а не доказательство конфликта;
- направление ошибки выбрано намеренно: ложная занятость стоит одной карточки (взять следующую),
  ложная свобода стоит цикла работы и рискует потерей чужой правки.

    python3 scripts/check_card_claim.py check agent-card-claim-collision-guard
    python3 scripts/check_card_claim.py check <карточка> --files /abs/a.py /abs/b.py --json
    python3 scripts/check_card_claim.py check <карточка> --session pid72474   # моё объявление
    python3 scripts/check_card_claim.py claim   <карточка>      # взять (пишет claimed_by/at)
    python3 scripts/check_card_claim.py release <карточка>      # отпустить
    python3 scripts/check_card_claim.py list                    # все занятые карточки
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG = ROOT / "data" / "session_changes.jsonl"
DEFAULT_TRACKER = ROOT / "nimbalyst-local" / "tracker"
SIBLING = ROOT / "scripts" / "check_undelivered_work.py"

DEFAULT_GRACE_HOURS = 3.0          # то же окно, что у шага 0a — одна семантика «свежести»
LOCK_STALE_SEC = 300               # старше — считаем брошенным, но НЕ удаляем молча

FREE, CLAIMED, STALE, UNCHECKED = "free", "claimed", "stale", "unchecked"
STRONG, WEAK = "strong", "weak"
_SEVERITY = {FREE: 0, STALE: 1, CLAIMED: 2, UNCHECKED: 3}

# Статусы, при которых карточку никто не «держит» по определению: работа закрыта.
# Благодаря этому забытый claimed_by не блокирует карточку вечно и его не нужно вычищать.
TERMINAL_STATUSES = {"done", "ingested", "owner-done"}

_CLAIM_KEYS = ("claimed_by", "claimed_at")


class ClaimError(RuntimeError):
    """Захват не выполнен (карточку держит другой / идёт чужая запись). Fail-CLOSED."""


# ── общий код со шагом 0a (единственный источник правды про активность сессии) ──

def load_sibling(path=SIBLING):
    """Модуль `check_undelivered_work` по явному пути (`scripts/` — не пакет).

    Логика «жива ли сессия» намеренно НЕ копируется: два расходящихся ответа на один вопрос
    хуже, чем отсутствие второго. Не загрузился — это «не измерено», а не «свободна»."""
    p = Path(path)
    if not p.exists():
        raise ImportError(f"нет соседнего модуля шага 0a: {p}")
    spec = importlib.util.spec_from_file_location("_card_claim_sibling", p)
    if spec is None or spec.loader is None:
        raise ImportError(f"не удалось загрузить {p}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for attr in ("session_state", "read_entries", "_parse_ts", "ACTIVE", "UNKNOWN"):
        if not hasattr(mod, attr):
            raise ImportError(f"{p}: нет ожидаемого символа {attr!r}")
    return mod


# ── карточка ─────────────────────────────────────────────────────────────────

def card_path(card, tracker_dir=DEFAULT_TRACKER):
    """Идентификатор карточки ИЛИ путь к ней → путь. Существование не проверяется."""
    p = Path(str(card))
    if p.suffix == ".md" and (p.is_absolute() or os.sep in str(card)):
        return p
    name = p.name
    if not name.endswith(".md"):
        name += ".md"
    return Path(tracker_dir) / name


def card_id(path) -> str:
    return Path(path).stem


def frontmatter(text: str) -> dict:
    """Плоские top-level `key: value` из YAML-frontmatter. Вложенные блоки пропускаются.

    Свой минимальный парсер (как в `build_tracker_board.py`): скрипт остаётся
    самодостаточным и stdlib-only, без импорта `spa_core`."""
    out: dict = {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return out
    for raw in lines[1:]:
        if raw.strip() == "---":
            break
        if not raw.strip() or raw[:1].isspace():
            continue
        if ":" not in raw:
            continue
        key, _, val = raw.partition(":")
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        out[key.strip()] = val
    return out


def read_card(path):
    """(meta, None) либо (None, причина). Отсутствие карточки — причина, а не пустой словарь."""
    p = Path(path)
    if not p.exists():
        return None, f"карточки нет: {p}"
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"карточка нечитаема ({exc.__class__.__name__}): {p}"
    return frontmatter(text), None


# ── разбор объявлений ────────────────────────────────────────────────────────

def _norm_path(value) -> str:
    return os.path.normpath(str(value))


def _tail2(value) -> str:
    p = Path(_norm_path(value))
    return (Path(p.parent.name) / p.name).as_posix()


def paths_overlap(a, b) -> bool:
    """Один и тот же файл в двух объявлениях.

    Сравниваются нормализованный путь целиком И хвост «каталог/имя» — объявления пишут
    абсолютные host-пути, но одна и та же работа может объявляться из разных корней
    (хост-репо / worktree). Совпадение только по имени файла намеренно НЕ считается
    совпадением (слишком много `__init__.py`)."""
    if _norm_path(a) == _norm_path(b):
        return True
    return _tail2(a) == _tail2(b)


def entry_hit(entry, cid) -> tuple:
    """(сила, чем именно) — относится ли объявление к этой карточке. ("", "") — нет."""
    card_field = str(entry.get("card") or "").strip()
    if card_field:
        if card_id(card_field) == cid:
            return STRONG, "поле `card:` в объявлении"
        # Явно названа ДРУГАЯ карточка — файлы/текст ниже всё равно проверяем: сессия могла
        # объявить владение файлом карточки, работая над соседней.
    for f in entry.get("files") or []:
        if Path(str(f)).name == f"{cid}.md":
            return STRONG, "файл карточки объявлен во владении"
    if cid and cid in str(entry.get("summary") or ""):
        return WEAK, "упоминание идентификатора в тексте объявления"
    return "", ""


# ── сборка отчёта ────────────────────────────────────────────────────────────

def _fmt_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_report(cid, path, entries, self_session, sibling, *, now=None,
                 grace_hours=DEFAULT_GRACE_HOURS, ps=None, planned_files=(),
                 log_path=None, log_error=None, malformed_lines=0, card_meta=None,
                 card_error=None):
    """Полный отчёт о занятости карточки. Чистая функция: ни git, ни файлов — всё на входе."""
    now = now or datetime.now(timezone.utc)
    grace = timedelta(hours=grace_hours)
    ps = ps or getattr(sibling, "_ps_lstart")

    report = {
        "card": cid,
        "card_path": str(path) if path else None,
        "card_status": None,
        "self_session": self_session,
        "grace_hours": grace_hours,
        "now": _fmt_ts(now),
        "log": str(log_path) if log_path else None,
        "entries_scanned": 0,
        "claims": [],       # находки: кто держит карточку
        "self_claims": [],  # мои собственные захваты — не находки
        "overlaps": [],     # пересечение по объявленным файлам
        "history": [],      # информационно: старые слабые упоминания, снятые захваты
        "unmeasured": [],   # fail-CLOSED
        "verdict": FREE,
    }

    def _unmeasured(source, reason):
        report["unmeasured"].append({"source": source, "reason": reason})

    def _classify(session, ts, source, strength, detail):
        """Захват → находка / история / «не измерено». Одинаково для карточки и журнала."""
        rec = {"source": source, "session": session, "strength": strength, "detail": detail,
               "ts": _fmt_ts(ts) if ts else None}
        if session and session == self_session:
            rec["state"] = "self"
            rec["session_state"] = "это текущая сессия"
            report["self_claims"].append(rec)
            return
        state, why = sibling.session_state({"session": session, "ts": rec["ts"]},
                                           self_session, ps=ps)
        rec["session_state"] = why
        age = (now - ts).total_seconds() / 3600.0 if ts else None
        rec["age_hours"] = round(age, 2) if age is not None else None
        if state == sibling.ACTIVE or (age is not None and age <= grace.total_seconds() / 3600.0):
            rec["state"] = "fresh"
            report["claims"].append(rec)
            return
        if state == sibling.UNKNOWN:
            # Старый захват + активность НЕ измерена ⇒ сказать «свободна» нельзя.
            _unmeasured(source, f"{session}: {why}; захват от {rec['ts']} "
                                f"({rec['age_hours']}ч назад) — занятость не измерена")
            return
        if strength == STRONG:
            rec["state"] = "stale"
            report["claims"].append(rec)
        else:
            rec["state"] = "history"
            report["history"].append(rec)

    # 1. карточка ────────────────────────────────────────────────────────────
    if card_error:
        _unmeasured("card", card_error)
    else:
        meta = card_meta or {}
        report["card_status"] = meta.get("status")
        holder = str(meta.get("claimed_by") or "").strip()
        at_raw = str(meta.get("claimed_at") or "").strip()
        if holder:
            if report["card_status"] in TERMINAL_STATUSES:
                report["history"].append({
                    "source": "frontmatter", "session": holder, "ts": at_raw or None,
                    "state": "released", "strength": STRONG,
                    "detail": f"захват игнорируется: статус карточки `{report['card_status']}` "
                              f"— работа закрыта"})
            else:
                ts = sibling._parse_ts(at_raw)
                if ts is None:
                    _unmeasured("frontmatter",
                                f"claimed_by={holder!r}, но claimed_at не разобран: "
                                f"{at_raw!r} — возраст захвата не измерен")
                else:
                    _classify(holder, ts, "frontmatter", STRONG, "поле claimed_by в карточке")

    # 2. журнал объявлений ───────────────────────────────────────────────────
    if log_error:
        _unmeasured("announce-log", log_error)
    else:
        rows = entries or []
        report["entries_scanned"] = len(rows)
        if malformed_lines:
            _unmeasured("announce-log",
                        f"{malformed_lines} нечитаемых строк журнала — часть объявлений "
                        f"не разобрана")
        latest = {}          # сессия → последний захват этой карточки
        for entry in rows:
            session = str(entry.get("session") or "")
            strength, detail = entry_hit(entry, cid)
            ts = sibling._parse_ts(entry.get("ts"))
            if strength:
                if ts is None:
                    _unmeasured("announce-log",
                                f"{session or '?'}: запись относится к карточке "
                                f"({detail}), но метка времени не разобрана: "
                                f"{entry.get('ts')!r} — возраст захвата не измерен")
                elif str(entry.get("card_state") or "").strip() == "done":
                    latest.pop(session, None)
                    report["history"].append({
                        "source": "announce-log", "session": session, "ts": _fmt_ts(ts),
                        "state": "released", "strength": strength,
                        "detail": "объявление `card_state: done` — захват снят"})
                else:
                    latest[session] = (session, ts, strength, detail)
            # пересечение по файлам — отдельное измерение, не зависит от карточки
            if planned_files and session and session != self_session and ts is not None:
                if (now - ts) <= grace:
                    shared = sorted({str(f) for f in (entry.get("files") or [])
                                     for mine in planned_files if paths_overlap(f, mine)})
                    if shared:
                        report["overlaps"].append({
                            "session": session, "ts": _fmt_ts(ts), "files": shared,
                            "summary": str(entry.get("summary") or "")[:160]})
        for session, ts, strength, detail in latest.values():
            _classify(session, ts, "announce-log", strength, detail)

    # 3. вердикт ─────────────────────────────────────────────────────────────
    verdict = FREE
    if any(c["state"] == "stale" for c in report["claims"]):
        verdict = STALE
    if any(c["state"] == "fresh" for c in report["claims"]) or report["overlaps"]:
        verdict = CLAIMED
    if report["unmeasured"]:
        verdict = UNCHECKED
    report["verdict"] = verdict
    return report


def exit_code(report) -> int:
    return {FREE: 0, STALE: 1, CLAIMED: 1, UNCHECKED: 2}[report["verdict"]]


_VERDICT_LINE = {
    FREE: "✅ СВОБОДНА — захватов не найдено, всё измерено. Карточку можно брать.",
    CLAIMED: "⛔ ЗАНЯТА — держит другая сессия. НЕ бери эту карточку, возьми следующую.",
    STALE: "🟡 СТАРЫЙ ЗАХВАТ — активность не подтверждена. Это кандидат на подъём "
           "осиротевшей работы: сверить ВРУЧНУЮ (шаг 0a + прогоны), отчёту не верить.",
    UNCHECKED: "❓ НЕ ИЗМЕРЕНО — занятость не установлена. Молчаливого «свободна» здесь нет.",
}


def render(report) -> str:
    out = [f"Карточка `{report['card']}` (статус: {report['card_status'] or '?'}) · "
           f"записей журнала просмотрено: {report['entries_scanned']} · "
           f"окно свежести: {report['grace_hours']}ч",
           _VERDICT_LINE[report["verdict"]]]

    if report["claims"]:
        out.append("")
        out.append(f"🔒 захваты ({len(report['claims'])}):")
        for c in report["claims"]:
            mark = "свежий" if c["state"] == "fresh" else "старый"
            age = f", {c['age_hours']}ч назад" if c.get("age_hours") is not None else ""
            out.append(f"  - [{mark}] {c['session']} ({c['ts']}{age}) — {c['detail']} "
                       f"[{'сильный' if c['strength'] == STRONG else 'слабый'} признак]")
            out.append(f"      активность: {c['session_state']}")

    if report["overlaps"]:
        out.append("")
        out.append(f"⚠️  пересечение по объявленным файлам ({len(report['overlaps'])}) — "
                   f"свежие объявления других сессий держат те же файлы:")
        for o in report["overlaps"]:
            out.append(f"  - {o['session']} ({o['ts']}): {', '.join(o['files'])}")
            out.append(f"      объявляла: {o['summary']}")

    if report["unmeasured"]:
        out.append("")
        out.append(f"❓ НЕ ИЗМЕРЕНО ({len(report['unmeasured'])}) — "
                   f"молчаливого «свободна» здесь не будет:")
        for u in report["unmeasured"]:
            out.append(f"  - [{u['source']}] {u['reason']}")

    if report["self_claims"]:
        out.append("")
        out.append("ℹ️  собственные захваты (не находки):")
        for c in report["self_claims"]:
            out.append(f"  - {c['session']} ({c['ts']}) — {c['detail']}")

    if report["history"]:
        out.append("")
        out.append("🕓 история (не находки):")
        for h in report["history"]:
            out.append(f"  - {h['session']} ({h.get('ts') or '-'}) — {h['detail']}")
    return "\n".join(out)


# ── чтение окружения ─────────────────────────────────────────────────────────

def self_session_id() -> str:
    return os.environ.get("SPA_SESSION_ID") or f"pid{os.getpid()}"


def gather(card, *, log=DEFAULT_LOG, tracker_dir=DEFAULT_TRACKER, sibling=None,
           self_session=None, now=None, grace_hours=DEFAULT_GRACE_HOURS,
           planned_files=(), last=None, ps=None):
    """Прочитать карточку + журнал и собрать отчёт (файловый слой над `build_report`)."""
    sibling = sibling or load_sibling()
    path = card_path(card, tracker_dir)
    meta, card_error = read_card(path)

    entries, malformed, log_error = [], 0, None
    log_path = Path(log)
    if not log_path.exists():
        log_error = f"{log_path}: журнала объявлений нет — занятость по журналу НЕ проверена"
    else:
        try:
            entries, malformed = sibling.read_entries(log_path, last)
        except OSError as exc:
            log_error = f"{log_path}: журнал нечитаем ({exc.__class__.__name__})"

    return build_report(card_id(path), path, entries,
                        self_session or self_session_id(), sibling,
                        now=now, grace_hours=grace_hours, ps=ps,
                        planned_files=planned_files, log_path=log_path,
                        log_error=log_error, malformed_lines=malformed,
                        card_meta=meta, card_error=card_error)


# ── взятие / освобождение карточки ───────────────────────────────────────────

def _atomic_write(path: Path, content: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _set_claim_fields(text: str, values) -> str:
    """Проставить/убрать `claimed_by`/`claimed_at` во frontmatter.

    `values=None` — убрать. Всё остальное содержимое сохраняется байт-в-байт (как
    `queue.set_status`): карточка — источник правды, инструмент трогает ровно свои строки."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ClaimError("во frontmatter карточки нет открывающего `---` — не трогаю файл")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise ClaimError("frontmatter карточки не закрыт `---` — не трогаю файл")

    kept = []
    for i, ln in enumerate(lines):
        if 0 < i < end and not ln[:1].isspace():
            key = ln.partition(":")[0].strip()
            if key in _CLAIM_KEYS:
                continue
        kept.append(ln)
    if values is None:
        return "".join(kept)

    end = next(i for i in range(1, len(kept)) if kept[i].strip() == "---")
    insert = [f"claimed_by: {values['claimed_by']}\n",
              f"claimed_at: {values['claimed_at']}\n"]
    return "".join(kept[:end] + insert + kept[end:])


def _lock_path(path: Path) -> Path:
    return path.with_name(path.name + ".claimlock")


def _acquire_lock(path: Path):
    """`O_EXCL`-файл на время правки карточки. Занят — отказ (а не ожидание и не снос)."""
    lock = _lock_path(path)
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        try:
            age = datetime.now(timezone.utc).timestamp() - lock.stat().st_mtime
        except OSError:
            age = 0.0
        hint = (f" Файл блокировки старше {LOCK_STALE_SEC}с ({age:.0f}с) — похоже, брошен; "
                f"проверь и удали вручную: {lock}" if age > LOCK_STALE_SEC else "")
        raise ClaimError(f"карточку сейчас правит другая сессия (есть {lock.name}).{hint}")
    os.write(fd, f"{self_session_id()}\n".encode())
    return fd, lock


def _release_lock(fd, lock: Path) -> None:
    os.close(fd)
    try:
        os.unlink(lock)
    except OSError:
        pass


def claim_card(card, *, session=None, tracker_dir=DEFAULT_TRACKER, now=None,
               grace_hours=DEFAULT_GRACE_HOURS, sibling=None, log=DEFAULT_LOG, ps=None):
    """Взять карточку. Отказ, если её держит другая сессия или занятость не измерена."""
    sibling = sibling or load_sibling()
    session = session or self_session_id()
    now = now or datetime.now(timezone.utc)
    path = card_path(card, tracker_dir)
    if not path.exists():
        raise ClaimError(f"карточки нет: {path}")

    report = gather(card, log=log, tracker_dir=tracker_dir, sibling=sibling,
                    self_session=session, now=now, grace_hours=grace_hours, ps=ps)
    if report["verdict"] in (CLAIMED, UNCHECKED, STALE):
        raise ClaimError(f"вердикт `{report['verdict']}` — карточка не взята.\n"
                         + render(report))

    fd, lock = _acquire_lock(path)
    try:
        text = path.read_text(encoding="utf-8")
        meta = frontmatter(text)
        holder = str(meta.get("claimed_by") or "").strip()
        if holder and holder != session:
            # Гонка: захват появился между проверкой и правкой.
            raise ClaimError(f"карточку успела взять сессия {holder} — не перезаписываю")
        new = _set_claim_fields(text, {"claimed_by": session, "claimed_at": _fmt_ts(now)})
        _atomic_write(path, new)
    finally:
        _release_lock(fd, lock)
    return {"card": card_id(path), "path": str(path), "claimed_by": session,
            "claimed_at": _fmt_ts(now)}


def release_card(card, *, session=None, tracker_dir=DEFAULT_TRACKER, force=False):
    """Отпустить карточку. Чужой захват без `--force` не снимается."""
    session = session or self_session_id()
    path = card_path(card, tracker_dir)
    if not path.exists():
        raise ClaimError(f"карточки нет: {path}")
    fd, lock = _acquire_lock(path)
    try:
        text = path.read_text(encoding="utf-8")
        meta = frontmatter(text)
        holder = str(meta.get("claimed_by") or "").strip()
        if not holder:
            return {"card": card_id(path), "path": str(path), "released": False,
                    "detail": "захвата не было"}
        if holder != session and not force:
            raise ClaimError(f"карточку держит {holder}, а не {session}; "
                             f"снять чужой захват можно только с --force")
        _atomic_write(path, _set_claim_fields(text, None))
    finally:
        _release_lock(fd, lock)
    return {"card": card_id(path), "path": str(path), "released": True, "was": holder}


def list_claimed(tracker_dir=DEFAULT_TRACKER):
    """Все карточки с непустым `claimed_by` (терминальные статусы отмечаются, но не скрываются)."""
    out = []
    d = Path(tracker_dir)
    if not d.exists():
        return out
    for p in sorted(d.glob("*.md")):
        meta, err = read_card(p)
        if err or not meta:
            continue
        holder = str(meta.get("claimed_by") or "").strip()
        if not holder:
            continue
        status = meta.get("status", "")
        out.append({"card": p.stem, "claimed_by": holder,
                    "claimed_at": meta.get("claimed_at", ""), "status": status,
                    "stale": status in TERMINAL_STATUSES})
    return out


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Шаг 0b: занята ли карточка другой сессией (детерминированно, read-only).")
    ap.add_argument("--tracker-dir", default=str(DEFAULT_TRACKER))
    ap.add_argument("--log", default=str(DEFAULT_LOG), help="журнал объявлений (JSONL)")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="проверить занятость (ничего не пишет)")
    c.add_argument("card", help="идентификатор карточки или путь к ней")
    c.add_argument("--files", nargs="*", default=[],
                   help="файлы, которые я собираюсь править — проверить пересечение")
    c.add_argument("--grace-hours", type=float, default=DEFAULT_GRACE_HOURS)
    c.add_argument("--last", type=int, default=None, help="сколько последних записей журнала")
    # Своя же сессия иначе читается как чужая: `log_session_change.py` пишет pid ОДНОКРАТНОГО
    # CLI-процесса, поэтому у каждой команды сессии он свой (карточка `agent-durable-session-id`).
    c.add_argument("--session", default=None,
                   help="идентификатор МОЕЙ сессии из объявления (напр. pid72474) — "
                        "иначе собственное объявление читается как чужой захват")

    k = sub.add_parser("claim", help="взять карточку (пишет claimed_by/claimed_at)")
    k.add_argument("card")
    k.add_argument("--session", default=None)
    k.add_argument("--grace-hours", type=float, default=DEFAULT_GRACE_HOURS)

    r = sub.add_parser("release", help="отпустить карточку")
    r.add_argument("card")
    r.add_argument("--session", default=None)
    r.add_argument("--force", action="store_true", help="снять ЧУЖОЙ захват")

    sub.add_parser("list", help="все карточки с активным захватом")

    args = ap.parse_args(argv)

    if args.cmd == "list":
        rows = list_claimed(args.tracker_dir)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        elif not rows:
            print("захваченных карточек нет")
        else:
            for row in rows:
                tail = "  (статус терминальный — захват не действует)" if row["stale"] else ""
                print(f"{row['card']}: {row['claimed_by']} с {row['claimed_at']} "
                      f"[{row['status']}]{tail}")
        return 0

    try:
        sibling = load_sibling()
    except (ImportError, OSError, SyntaxError) as exc:
        payload = {"verdict": UNCHECKED, "card": str(args.card),
                   "unmeasured": [{"source": "sibling", "reason": str(exc)}]}
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json
              else f"❓ НЕ ИЗМЕРЕНО — не загрузился {SIBLING}: {exc}")
        return 2

    if args.cmd == "check":
        report = gather(args.card, log=args.log, tracker_dir=args.tracker_dir,
                        sibling=sibling, self_session=args.session,
                        grace_hours=args.grace_hours,
                        planned_files=args.files, last=args.last)
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render(report))
        return exit_code(report)

    try:
        if args.cmd == "claim":
            res = claim_card(args.card, session=args.session, tracker_dir=args.tracker_dir,
                             grace_hours=args.grace_hours, sibling=sibling, log=args.log)
            print(json.dumps(res, ensure_ascii=False) if args.json
                  else f"взята: {res['card']} → {res['claimed_by']} ({res['claimed_at']})")
        else:
            res = release_card(args.card, session=args.session,
                               tracker_dir=args.tracker_dir, force=args.force)
            print(json.dumps(res, ensure_ascii=False) if args.json
                  else (f"отпущена: {res['card']}" if res.get("released")
                        else f"{res['card']}: {res['detail']}"))
    except ClaimError as exc:
        print(f"ОТКАЗ: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
