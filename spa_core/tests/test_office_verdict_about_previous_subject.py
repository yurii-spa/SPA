"""Вердикт о ПРЕЖНЕЙ конституции не смеет читаться как вердикт о текущей.

Замер цикла #337 (21.08.2026), живой и воспроизведённый на настоящих файлах:

  07:44Z  решение **ADR-104** меняет в конституции такт `com.spa.io_chief_investment`
          `interval:86400s → interval:300s` (коммит `1dfbfa5bb`);
  16:19Z  `com.spa.architecture_conformance` производит отчёт — по ЕЩЁ СТАРОМУ
          манифесту прод-дерева: `OK · critical=0 warn=0 aged=0 unchecked=0`;
  19:21Z  правка конституции доезжает в прод-дерево (`architecture/` не входит в
          автосинк — он возит только `spa_core/ scripts/ tests/`);
  21:28Z  обязательный шаг 0-офис печатает этот отчёт как **OK**, и оркестратор
          читает «флот соответствует конституции». Перепрогон сторожа руками в
          ту же минуту: `WARN · warn=2` — дрейф `interval:300s → interval:86400s`
          и `chief_investment.json: возраст 12.3ч > SLO 1ч`.

Карточка `inbox-test-manifesta-flota-krasnyi-na-make-kon` предполагала, что два
сторожа расходятся между собой. ЗАМЕР этого НЕ подтвердил: `architecture_conformance`
зовёт `gen.measure()` — тот же код, что и красный тест манифеста, и на одном входе
даёт тот же ответ. Расходились не сторожа, а **отчёт и предмет**: у артефакта есть
возраст, но не было ответа на вопрос «а предмет с тех пор менялся?».

Тот же класс, что #222 (сверка офис↔книга судила по снимкам РАЗНЫХ тактов) и
#235 (один бюджет свежести на производителей с тактами в два порядка). Правило
класса: зелёный ответ сторожа на СВОЙ вопрос никогда не есть ответ на нужный.

Каждый тест ниже — положительный контроль: он краснеет на неисправленном дереве
(там `_subject_drift`/`subject_inputs` не существует вовсе) и воспроизводит
настоящую аварию 21.08, а не воображаемую.
"""
# FROZEN-DATE-OK: исторический инцидент — отметки 2026-08-21 16:19Z/19:21Z и есть
# ПРЕДМЕТ проверки (правило `.claude/rules/deployment.md`, преференция #3). Часы
# при этом инъектируются (`now=NOW`), обе стороны сравнения закреплены.
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path

from spa_core.tests._freshness import at

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "consume_office_reports.py"


def _load():
    spec = importlib.util.spec_from_file_location("_cor_subject", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = _load()

NAME = "architecture_conformance.json"
REL = "architecture/manifest.json"

# Отметки настоящей аварии 21.08 (см. модульный докстринг).
VERDICT_AT = "2026-08-21T16:19:47+00:00"     # отчёт сторожа
SUBJECT_AT = "2026-08-21T19:21:00+00:00"     # правка конституции доехала в прод
NOW = at("2026-08-21T21:28:00+00:00")        # шаг 0-офис читает отчёт


def _stamp(path: Path, iso: str) -> None:
    """Время правки предмета — ВХОД проверки, поэтому задаётся явно."""
    ts = at(iso).timestamp()
    os.utime(path, (ts, ts))


def _tree(root: Path, manifest_body: str = '{"agents": [], "artifacts": []}',
          *, mtime: str = SUBJECT_AT) -> Path:
    path = root / "architecture" / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest_body, encoding="utf-8")
    _stamp(path, mtime)
    return path


def _report(generated_at: str = VERDICT_AT, *, inputs=None) -> dict:
    r = {"generated_at": generated_at, "overall": "OK",
         "counts": {"critical": 0, "warn": 0, "aged": 0, "unchecked": 0},
         "findings": []}
    if inputs is not None:
        r["inputs"] = inputs
    return r


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text(lines) -> str:
    return "\n".join(lines)


# ── 1. авария 21.08 дословно ─────────────────────────────────────────────────

def test_subject_changed_after_the_verdict_is_a_finding(tmp_path) -> None:
    """Отчёт 16:19Z о манифесте, правленном в 19:21Z — находка, а не OK."""
    _tree(tmp_path)
    lines = MOD._subject_drift(NAME, _report(), root=str(tmp_path), now=NOW)
    out = _text(lines)
    assert lines, "вердикт о прежней конституции прошёл молча — это авария 21.08"
    assert "ВЕРДИКТ О ПРЕЖНЕМ ПРЕДМЕТЕ" in out, out
    # ОБЕ стороны сравнения названы числами в самой строке (урок #222).
    assert "19:21" in out and "16:19" in out, out
    assert REL in out, out
    assert "находка" in out, out


def test_verdict_about_the_current_subject_stays_silent(tmp_path) -> None:
    """Обратный контроль: предмет не менялся ⇒ ни строки (иначе шаг зашумлён)."""
    _tree(tmp_path, mtime="2026-08-21T10:00:00+00:00")
    assert MOD._subject_drift(NAME, _report(), root=str(tmp_path), now=NOW) == []


# ── 2. основание сравнения: содержимое, а не отметка времени ─────────────────

def test_idle_regeneration_with_identical_bytes_is_not_a_finding(tmp_path) -> None:
    """Капкан, в который упала бы сверка по одному mtime.

    Генератор манифеста идемпотентен по построению (`test_idempotent_write`):
    повторный `--write` без смены фактов переписывает файл байт-в-байт. По mtime
    это неотличимо от настоящей правки — и шаг 0-офис печатал бы находку после
    каждой холостой перегенерации, приучая её пролистывать.
    """
    path = _tree(tmp_path, mtime="2026-08-21T10:00:00+00:00")
    sha = _sha(path)
    _stamp(path, SUBJECT_AT)          # переписали тем же содержимым — ПОЗЖЕ отчёта
    rep = _report(inputs=[{"path": REL, "role": "subject", "measured": True,
                           "mtime": "2026-08-21T10:00:00+00:00", "sha256": sha}])
    assert MOD._subject_drift(NAME, rep, root=str(tmp_path), now=NOW) == [], (
        "холостая перегенерация объявлена находкой — сверка идёт по mtime, "
        "а не по содержимому")


def test_changed_content_is_a_finding_even_when_mtime_looks_older(tmp_path) -> None:
    """Обратная сторона того же: содержимое главнее отметки времени.

    `git checkout` старого манифеста ставит СВЕЖИЙ mtime, а `os.utime` из любого
    инструмента — произвольный. Единственное, чему можно верить, — байты.
    """
    _tree(tmp_path, mtime="2026-08-21T10:00:00+00:00")   # mtime СТАРШЕ отчёта
    rep = _report(inputs=[{"path": REL, "role": "subject", "measured": True,
                           "mtime": "2026-08-21T09:00:00+00:00",
                           "sha256": "0" * 64}])
    out = _text(MOD._subject_drift(NAME, rep, root=str(tmp_path), now=NOW))
    assert "ВЕРДИКТ О ПРЕЖНЕМ ПРЕДМЕТЕ" in out, out
    assert "по содержимому" in out, out


def test_the_basis_of_comparison_is_named_out_loud(tmp_path) -> None:
    """«Сошлось по хэшу» и «сошлось, потому что мерить было нечем» — разное."""
    _tree(tmp_path)
    by_mtime = _text(MOD._subject_drift(NAME, _report(), root=str(tmp_path), now=NOW))
    assert "mtime" in by_mtime and "старого образца" in by_mtime, by_mtime


# ── 3. fail-CLOSED: неизмеримое называется, а не молчит ──────────────────────

def test_unreadable_subject_is_unmeasured_not_silence(tmp_path) -> None:
    """Манифеста нет ⇒ «НЕ ИЗМЕРЕНО» вслух (инвариант 2), а не тишина.

    Причина названа ИМЕННО та, что случилась: «не прочитан», а не «не измерено
    время правки». Первая редакция теста проверяла только `_UNMEASURED` — и
    оставалась ЗЕЛЁНОЙ, когда мутация сносила ветку целиком: пропавший файл
    сваливался в сверку по mtime, где `getmtime` тоже падает, и строка выходила
    похожая, но о другом. Проверка, которую нельзя покрасить, — украшение.
    """
    out = _text(MOD._subject_drift(NAME, _report(), root=str(tmp_path), now=NOW))
    assert MOD._UNMEASURED in out, out
    assert REL in out, out
    assert "не прочитан" in out, out
    assert "время правки" not in out, out


def test_report_without_generated_at_and_without_inputs_is_unmeasured(tmp_path) -> None:
    """Нечем датировать вердикт ⇒ сравнить нечем, и это НАЗЫВАЕТСЯ."""
    _tree(tmp_path)
    rep = {"overall": "OK", "counts": {}, "findings": []}
    out = _text(MOD._subject_drift(NAME, rep, root=str(tmp_path), now=NOW))
    assert MOD._UNMEASURED in out, out


def test_artifact_without_declared_subject_makes_no_claim(tmp_path) -> None:
    """Про артефакт, чей предмет не объявлен, проверка молчит — а не выдумывает."""
    assert MOD._subject_drift("house_view_gap.json", _report(),
                              root=str(tmp_path), now=NOW) == []


# ── 4. проводка целиком (мутировать проводку, а не только деталь) ────────────

def test_step_prints_the_finding_before_the_verdict(tmp_path) -> None:
    """Тот же путь, каким шаг зовёт протокол: находка обязана стоять ДО вердикта.

    Проверка ветки в отрыве бывала зелёной при мёртвой проводке (урок #144),
    поэтому здесь гоняется `main()` над настоящим манифестом-фикстурой.
    """
    root = tmp_path
    (root / "data").mkdir(parents=True)
    (root / "architecture").mkdir(parents=True, exist_ok=True)
    manifest = {"agents": [], "artifacts": [
        {"path": "data/architecture_conformance.json", "status": "active",
         "consumers": ["orchestrator_protocol"]}]}
    mpath = root / "architecture" / "manifest.json"
    mpath.write_text(json.dumps(manifest), encoding="utf-8")
    _stamp(mpath, SUBJECT_AT)
    (root / "data" / "architecture_conformance.json").write_text(
        json.dumps(_report()), encoding="utf-8")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = MOD.main(["--root", str(root), "--no-receipts"], now=NOW)
    out = buf.getvalue()

    assert rc == 0, out
    assert "ВЕРДИКТ О ПРЕЖНЕМ ПРЕДМЕТЕ" in out, out
    # Читатель узнаёт о смене предмета РАНЬШЕ, чем прочтёт вердикт о нём.
    assert out.index("ВЕРДИКТ О ПРЕЖНЕМ ПРЕДМЕТЕ") < out.index("вердикт: OK"), out


def test_subject_follows_the_artifacts_tree_not_the_root(tmp_path) -> None:
    """Капкан #267 в новом месте: сверить прод-отчёт с манифестом СВОЕГО дерева.

    В режиме `--data-dir` (читаем офис прода из worktree) конституция прода и
    конституция worktree — разные файлы. Судить прод-вердикт по своей копии
    значило бы выдумать расхождение из границы синхронизации.
    """
    prod = tmp_path / "prod"
    (prod / "data").mkdir(parents=True)
    _tree(prod, mtime="2026-08-21T10:00:00+00:00")       # прод: предмет СТАРШЕ отчёта
    (prod / "data" / "architecture_conformance.json").write_text(
        json.dumps(_report()), encoding="utf-8")

    wt = tmp_path / "wt"
    (wt / "architecture").mkdir(parents=True)
    (wt / "architecture" / "manifest.json").write_text(json.dumps({"artifacts": [
        {"path": "data/architecture_conformance.json", "status": "active",
         "consumers": ["orchestrator_protocol"]}]}), encoding="utf-8")
    _stamp(wt / "architecture" / "manifest.json", SUBJECT_AT)   # своя копия СВЕЖАЯ

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = MOD.main(["--root", str(wt), "--data-dir", str(prod / "data"),
                       "--no-receipts"], now=NOW)
    out = buf.getvalue()
    assert rc == 0, out
    assert "ВЕРДИКТ О ПРЕЖНЕМ ПРЕДМЕТЕ" not in out, (
        "прод-вердикт судим по манифесту СВОЕГО дерева — выдуманное расхождение\n"
        + out)


# ── 5. производитель кладёт провенанс предмета машинно ───────────────────────

def test_producer_records_the_subject_it_judged(tmp_path) -> None:
    """`architecture_conformance` обязан сказать, ПО КАКОЙ копии вынес вердикт."""
    from spa_core.monitoring import architecture_conformance as ac

    path = _tree(tmp_path, '{"agents": [], "artifacts": []}')
    rows = ac.subject_inputs(str(tmp_path))
    row = next(r for r in rows if r["path"] == REL)
    assert row["measured"] is True, row
    assert row["sha256"] == _sha(path), row
    assert row["mtime"], row


def test_producer_subject_provenance_is_fail_closed(tmp_path) -> None:
    """Предмет не прочитан ⇒ `measured: false` с причиной, а не «сошлось»."""
    from spa_core.monitoring import architecture_conformance as ac

    row = next(r for r in ac.subject_inputs(str(tmp_path)) if r["path"] == REL)
    assert row["measured"] is False, row
    assert row["sha256"] is None and row["reason"], row


def test_report_carries_inputs(tmp_path) -> None:
    """Блок `inputs` доезжает до отчёта — иначе читателю нечем сверять байты."""
    from spa_core.monitoring import architecture_conformance as ac

    _tree(tmp_path)
    rows = ac.subject_inputs(str(tmp_path))
    report = ac.run_checks({"agents": []}, set(), lambda rel: None, {},
                           dt.datetime(2026, 8, 21, 21, 28, tzinfo=dt.timezone.utc),
                           inputs=rows)
    assert report["inputs"] == rows, report.get("inputs")


# ── 6. храповик: объявленный предмет обязан существовать ─────────────────────

def test_every_declared_subject_exists_in_this_repo() -> None:
    """Опечатка в `_SUBJECT` дала бы вечное «НЕ ИЗМЕРЕНО» вместо проверки."""
    for name, subjects in MOD._SUBJECT.items():
        assert name in MOD._READ_SCHEMA, (
            f"{name}: предмет объявлен у артефакта, которого шаг не разбирает")
        for rel in subjects:
            assert (_REPO / rel).exists(), f"{name}: предмет {rel} не найден в репо"
