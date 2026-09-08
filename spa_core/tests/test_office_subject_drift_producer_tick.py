"""Смена предмета — находка ТОЛЬКО после того, как производитель просрочил такт.

Замер цикла #526 (2026-09-08, живой, на настоящем прод-дереве):

  06:54Z  `com.spa.architecture_conformance` производит отчёт (`generated_at`);
  ~11:5xZ обязательный шаг 0-офис читает его и печатает
          «⚠️ ВЕРДИКТ О ПРЕЖНЕМ ПРЕДМЕТЕ … Это находка (карточка), а не деталь»
          — при том, что расписание производителя объявлено `interval:21600s`
          (6 ч), отчёту 5.0 ч, и СЛЕДУЮЩИЙ ТАКТ перемерил бы предмет сам.

Утверждение о незнании было верным, слово «находка» — нет: карточка звала бы
сессию действовать на ИСПРАВНОМ контуре. Ровно тот класс, что ADR-261/262
закрыли для ОТСУТСТВИЯ артефакта («файла нет» — находка только после того, как
производитель отработал); форму контроля применили там к своему поводу и не
перенесли на СМЕНУ ПРЕДМЕТА — третий случай урока #519 подряд.

Каждая сцена ниже — положительный контроль: на дереве `origin/main` 98247f7d8
`_drift_is_a_finding` не существует вовсе, а строка о смене предмета приходит
одна и та же в ОБОИХ состояниях.
"""
# FROZEN-DATE-OK: injected-clock — отметки 2026-09-08 06:54Z/11:58Z и есть
# ПРЕДМЕТ проверки (замер #526), а часы проверяемого кода передаются
# аргументом `now=` в `_subject_drift`/`_drift_is_a_finding`/`main(now=)`;
# обе стороны сравнения закреплены литералами сцены.
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "consume_office_reports.py"


def _load():
    spec = importlib.util.spec_from_file_location("_cor_tick", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = _load()

NAME = "architecture_conformance.json"
REL = "architecture/manifest.json"
LABEL = "com.spa.architecture_conformance"

VERDICT_AT = "2026-09-08T06:54:00+00:00"                       # отчёт сторожа
NOW = dt.datetime(2026, 9, 8, 11, 58, tzinfo=dt.timezone.utc)  # шаг читает его
LATE = dt.datetime(2026, 9, 8, 13, 58, tzinfo=dt.timezone.utc)  # такт ПРОШЁЛ


def _tree(root: Path, *, agents=None, artifacts=None, body=None) -> Path:
    """Конституция сцены. По умолчанию — та же пара объявлений, что в проде."""
    if body is None:
        body = {
            "agents": agents if agents is not None else [
                {"label": LABEL, "schedule": "interval:21600s"}],
            "artifacts": artifacts if artifacts is not None else [
                {"path": f"data/{NAME}", "producer": LABEL, "status": "active",
                 "consumers": ["orchestrator_protocol"]}],
        }
    path = root / "architecture" / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _report(*, generated_at=VERDICT_AT, sha="0" * 64, inputs=True) -> dict:
    r = {"generated_at": generated_at, "overall": "OK",
         "counts": {"critical": 0, "warn": 0, "aged": 0, "unchecked": 0},
         "findings": []}
    if generated_at is None:
        del r["generated_at"]
    if inputs:
        r["inputs"] = [{"path": REL, "role": "subject", "measured": True,
                        "sha256": sha}]
    return r


def _drift(root: Path, report: dict, *, now=NOW) -> str:
    return "\n".join(MOD._subject_drift(NAME, report, root=str(root), now=now))


# ── 1. авария 08.09 дословно: не находка, потому что такт ещё не прошёл ──────

def test_subject_changed_but_the_tick_has_not_passed_is_not_a_finding(tmp_path):
    """Живое состояние #526: отчёту 5.1ч при такте 6ч ⇒ карточка НЕ нужна."""
    _tree(tmp_path)
    out = _drift(tmp_path, _report())
    assert MOD._NOT_DUE in out, out
    assert "НЕ находка" in out and "карточка НЕ нужна" in out, out
    assert "Это находка (карточка)" not in out, out
    # ОБА числа названы в самой строке: и такт, и возраст (урок #222 —
    # «сошлось» и «сошлось, потому что мерить было нечем» обязаны различаться).
    assert "6.0ч" in out and "5.1ч" in out, out
    # Признак ОБЪЯВЛЕННЫЙ, а не выведенный: расписание названо дословно.
    assert "interval:21600s" in out and LABEL in out, out


def test_the_claim_of_ignorance_survives_in_both_outcomes(tmp_path):
    """#527 меняет КЛАССИФИКАЦИЮ, а не утверждение: знание правда отстаёт.

    Соблазн был «раз не находка — молчать». Это вернуло бы аварию 21.08
    (`test_office_verdict_about_previous_subject`): оркестратор прочёл бы
    вердикт о ПРЕЖНЕЙ конституции как вердикт о текущей.
    """
    _tree(tmp_path)
    quiet = _drift(tmp_path, _report())
    loud = _drift(tmp_path, _report(), now=LATE)
    for out in (quiet, loud):
        assert "ВЕРДИКТ О ПРЕЖНЕМ ПРЕДМЕТЕ" in out, out
        assert "не измерено ничего" in out, out
    assert quiet.lstrip().startswith("⏳"), quiet
    assert loud.lstrip().startswith("⚠️"), loud


def test_unchanged_subject_still_says_nothing_at_all(tmp_path):
    """Обратный контроль: такт тут ни при чём, если предмет не менялся."""
    path = _tree(tmp_path)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    assert MOD._subject_drift(NAME, _report(sha=sha), root=str(tmp_path),
                              now=NOW) == []


# ── 2. такт ПРОШЁЛ — находка, и это надо было сказать ────────────────────────

def test_overdue_producer_is_a_finding(tmp_path):
    """Отчёту 7.1ч при такте 6ч: сам он строку уже не снимет ⇒ карточка."""
    _tree(tmp_path)
    out = _drift(tmp_path, _report(), now=LATE)
    assert "Это находка (карточка)" in out, out
    assert "ПРОСРОЧИЛ" in out, out
    assert "6.0ч" in out and "7.1ч" in out, out


def test_the_third_outcome_closes_itself_and_is_not_an_eternal_unchecked(tmp_path):
    """Третий исход обязан истекать САМ — иначе это `UNCHECKED` навсегда.

    Одна и та же сцена, один и тот же код, разница только в часах: до срока —
    не находка, после срока — находка. Ни правки кода, ни записи в базу.
    """
    _tree(tmp_path)
    due = dt.datetime(2026, 9, 8, 12, 54, tzinfo=dt.timezone.utc)
    before = _drift(tmp_path, _report(), now=due - dt.timedelta(minutes=1))
    after = _drift(tmp_path, _report(), now=due + dt.timedelta(minutes=1))
    assert MOD._NOT_DUE in before, before
    assert "Это находка (карточка)" in after, after


def test_a_daemon_producer_is_never_not_due(tmp_path):
    """`daemon` = такт 0: непрерывный производитель обязан был перемерить сразу."""
    _tree(tmp_path, agents=[{"label": LABEL, "schedule": "daemon"}])
    out = _drift(tmp_path, _report())
    assert "Это находка (карточка)" in out, out
    assert MOD._NOT_DUE not in out, out


# ── 3. fail-CLOSED: четыре двери незнания, и у каждой СВОЯ причина ───────────

def _finding_reason(root: Path, **kw) -> str:
    """Дверь незнания обязана дать находку — И СЛОВАМИ, И ЗНАЧКОМ.

    Проверять только слова было мало: батарея #527 подменила вердикт на
    `False` у обеих дверей, слова остались прежними (они лежали внутри
    строки-причины), и ни один тест не покраснел. Направление вреда —
    fail-OPEN, тише красной строки и потому опаснее.
    """
    out = _drift(root, _report(**kw))
    assert "Это находка (карточка)" in out, out
    assert out.lstrip().startswith("⚠️"), out
    assert MOD._NOT_DUE not in out, out
    return out


def test_unreadable_constitution_stays_a_finding(tmp_path):
    (tmp_path / "architecture").mkdir(parents=True)
    (tmp_path / "architecture" / "manifest.json").write_text("{не json",
                                                             encoding="utf-8")
    out = _finding_reason(tmp_path)
    assert "конституция не прочитана" in out, out


def test_artifact_absent_from_the_constitution_stays_a_finding(tmp_path):
    _tree(tmp_path, artifacts=[])
    out = _finding_reason(tmp_path)
    assert "не объявлен в `artifacts[]`" in out, out


def test_producer_absent_from_the_constitution_stays_a_finding(tmp_path):
    _tree(tmp_path, agents=[])
    out = _finding_reason(tmp_path)
    assert f"производителя {LABEL} нет" in out, out


def test_unparseable_schedule_stays_a_finding(tmp_path):
    _tree(tmp_path, agents=[{"label": LABEL, "schedule": "manual"}])
    out = _finding_reason(tmp_path)
    assert "в такт не переводится" in out and "'manual'" in out, out


def test_undated_verdict_stays_a_finding_with_its_own_reason(tmp_path):
    """Вердикт нечем датировать ⇒ возраст не с чем сравнить ⇒ находка."""
    _tree(tmp_path)
    out = _finding_reason(tmp_path, generated_at=None)
    assert "нечем датировать" in out, out
    # Причина ИМЕННО эта, а не «такт не измерен»: такт-то как раз объявлен.
    assert "такт производителя" not in out, out


def test_the_four_doors_of_ignorance_say_four_different_things(tmp_path):
    """Общая причина «не смог» соврала бы, ГДЕ оборвалось объявление.

    Проверка, которую нельзя покрасить, — украшение: без этой сцены мутация
    «одна причина на все двери» осталась бы зелёной.
    """
    seen = set()
    for i, prep in enumerate((
            lambda r: (r / "architecture").mkdir(parents=True) or
                      (r / "architecture" / "manifest.json").write_text("{"),
            lambda r: _tree(r, artifacts=[]),
            lambda r: _tree(r, agents=[]),
            lambda r: _tree(r, agents=[{"label": LABEL, "schedule": "manual"}]),
    )):
        root = tmp_path / f"case{i}"
        root.mkdir()
        prep(root)
        seen.add(_drift(root, _report()))
    assert len(seen) == 4, seen


# ── 4. форма контроля перенесена на ВЕСЬ класс, а не на свой повод ───────────

def test_the_mtime_branch_gets_the_same_gate(tmp_path):
    """Урок #519: соседняя ветка сверки — тот же класс, и её тоже чиним.

    Отчёт СТАРОГО образца (без блока `inputs`) сверяется по mtime. Это ДРУГОЙ
    признак — и собственный дефект той ветки (свежий worktree датирует все
    файлы чекаутом, поэтому строка приходит всегда) здесь НЕ лечится и назван
    в ADR-264. Но вопрос «обязан ли читатель действовать» у обеих ветвей ОДИН.
    """
    path = _tree(tmp_path)
    ts = dt.datetime(2026, 9, 8, 9, 0, tzinfo=dt.timezone.utc).timestamp()
    os.utime(path, (ts, ts))                      # предмет правлен ПОСЛЕ отчёта
    out = _drift(tmp_path, _report(inputs=False))
    assert "ВЕРДИКТ О ПРЕЖНЕМ ПРЕДМЕТЕ" in out, out
    assert "Сверка по mtime" in out, out
    assert MOD._NOT_DUE in out, out
    assert "Это находка (карточка)" not in out, out


def test_the_mtime_branch_also_becomes_a_finding_when_overdue(tmp_path):
    """Обратный контроль той же ветки — иначе «не находка» стало бы всегда."""
    path = _tree(tmp_path)
    ts = dt.datetime(2026, 9, 8, 9, 0, tzinfo=dt.timezone.utc).timestamp()
    os.utime(path, (ts, ts))
    out = _drift(tmp_path, _report(inputs=False), now=LATE)
    assert "Это находка (карточка)" in out and "ПРОСРОЧИЛ" in out, out


# ── 5. такт разбирает ОБЪЯВЛЕННЫЙ разборщик, а не вторая копия понятия ───────

def test_the_tick_parser_is_the_one_the_constitution_uses(tmp_path, monkeypatch):
    """«Одно имя — один объект»: второго определения такта здесь нет.

    Подменяем разборщик у ЕГО хозяина (`architecture_conformance`) — если бы
    шаг нёс свою копию, вердикт не сдвинулся бы.
    """
    from spa_core.monitoring import architecture_conformance as ac

    _tree(tmp_path)
    monkeypatch.setattr(ac, "producer_tick_hours", lambda schedule: 0.0)
    out = _drift(tmp_path, _report())
    assert "Это находка (карточка)" in out, out
    assert MOD._NOT_DUE not in out, out


def test_tick_lookup_reads_the_artifacts_producer_not_a_guess(tmp_path):
    """Производитель берётся из `artifacts[].producer`, а не угадывается."""
    _tree(tmp_path,
          artifacts=[{"path": f"data/{NAME}", "producer": "com.spa.other",
                      "status": "active", "consumers": ["orchestrator_protocol"]}],
          agents=[{"label": LABEL, "schedule": "interval:21600s"},
                  {"label": "com.spa.other", "schedule": "interval:3600s"}])
    tick, why = MOD._producer_tick_hours(NAME, str(tmp_path))
    assert tick == 1.0, (tick, why)
    assert "com.spa.other" in why, why


# ── 6. проводка: третий исход обязан ЗВУЧАТЬ в самом шаге ────────────────────

def test_the_step_prints_the_third_outcome_out_loud(tmp_path):
    """Исход, живущий только внутри функции, — молчащий канал (урок #526).

    Гоняется `main()` тем же путём, каким его зовёт протокол.
    """
    root = tmp_path
    (root / "data").mkdir(parents=True)
    _tree(root)
    (root / "data" / NAME).write_text(json.dumps(_report()), encoding="utf-8")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = MOD.main(["--root", str(root), "--no-receipts"], now=NOW)
    out = buf.getvalue()
    assert rc == 0, out
    assert MOD._NOT_DUE in out, out
    assert "Это находка (карточка)" not in out, out
    # Читатель узнаёт об отставании РАНЬШЕ, чем прочтёт вердикт (порядок #337).
    assert out.index("ВЕРДИКТ О ПРЕЖНЕМ ПРЕДМЕТЕ") < out.index("вердикт: OK"), out


def test_the_step_still_prints_the_finding_when_overdue(tmp_path):
    """Обратный контроль проводки: просрочка доходит до печати шага."""
    root = tmp_path
    (root / "data").mkdir(parents=True)
    _tree(root)
    (root / "data" / NAME).write_text(json.dumps(_report()), encoding="utf-8")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        MOD.main(["--root", str(root), "--no-receipts"], now=LATE)
    out = buf.getvalue()
    assert "Это находка (карточка)" in out, out


# ── 7. храповик: у каждого объявленного предмета такт ДОЛЖЕН быть измерим ────

def test_every_declared_subject_has_a_measurable_producer_tick():
    """Иначе третий исход недостижим по построению, а строка вечно «находка».

    Живая конституция этого репозитория, а не фикстура: объявить предмет и не
    объявить его производителя значит вернуть состояние до #527 — молча.
    """
    for name in MOD._SUBJECT:
        tick, why = MOD._producer_tick_hours(name, str(_REPO))
        assert tick is not None, f"{name}: такт производителя не измерим — {why}"


# ── 8. значок и слова — ОДНО следствие одного вердикта ───────────────────────

def test_mark_and_words_cannot_contradict_each_other():
    """Классификация берётся в одном месте, иначе разойдётся молча.

    Положительный контроль на саму развязку: `_drift_words` — единственный
    источник и значка, и слов, поэтому «⏳ … Это находка (карточка)» и
    «⚠️ … карточка НЕ нужна» невозможны ПО ПОСТРОЕНИЮ.
    """
    mark, words = MOD._drift_words(True)
    assert mark == "⚠️" and "Это находка (карточка)" in words, (mark, words)
    mark, words = MOD._drift_words(False)
    assert mark == "⏳" and "НЕ находка" in words, (mark, words)
    assert MOD._NOT_DUE in words, words


def test_every_outcome_agrees_with_its_own_mark(tmp_path):
    """Тот же вопрос, но замером по ВСЕМ пяти исходам разом, а не по двум."""
    scenes = {
        "не должен был": (lambda r: _tree(r), {}, NOW, False),
        "просрочил": (lambda r: _tree(r), {}, LATE, True),
        "такта нет": (lambda r: _tree(r, agents=[]), {}, NOW, True),
        "нечем датировать": (lambda r: _tree(r), {"generated_at": None}, NOW, True),
        # Предмет ЧИТАЕТСЯ (байты есть, sha считается), но как объявление
        # не разбирается — это дверь такта, а не дверь предмета: последнюю
        # держит своя, более ранняя ветка `_subject_drift` (её сцена — в
        # `test_office_verdict_about_previous_subject`).
        "объявление не разбирается": (
            lambda r: (r / "architecture" / "manifest.json").write_text("{"),
            {}, NOW, True),
    }
    for i, (label, (prep, kw, now, expect_finding)) in enumerate(scenes.items()):
        root = tmp_path / f"s{i}"
        (root / "architecture").mkdir(parents=True)
        prep(root)
        out = _drift(root, _report(**kw), now=now)
        assert out, f"{label}: строка пропала совсем"
        if expect_finding:
            assert out.lstrip().startswith("⚠️"), (label, out)
            assert "Это находка (карточка)" in out, (label, out)
        else:
            assert out.lstrip().startswith("⏳"), (label, out)
            assert "карточка НЕ нужна" in out, (label, out)
