"""Тесты прибора «у кого квитанция read-only проверки окажется читателем» — G88 п. 1.

Каждый тест — положительный контроль: он краснеет, если порвать ровно то звено, о
котором говорит. Батарея закрывает обе стороны каждого правила (след есть / следа
нет · читает вердикт / берёт константу / зовёт и не читает · квитанцию читают /
не читают · наивный канал вредит / безвреден) и третий исход КАЖДОЙ из четырёх осей.

# FROZEN-DATE-OK: injected-clock — у оси C часы идут ВХОДОМ
# (`measure_receipt_reader(now=)`, `build_report(now=)`), и тест передаёт
# фиксированный `now`; отметки записей сцены прибор выводит ИЗ него, поэтому
# закреплены обе стороны. Осям A и D часы не нужны вовсе: их сцену пишет
# настоящий писатель журнала, и запись свежа ПО ПОСТРОЕНИЮ — как `os.getpid()`
# жив по построению у личности процесса. Параметра `now=` у них нет намеренно:
# расписка без инъекции и есть класс ADR-479.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import claim_guard_receipt_readers as M

REPO = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)


# ───────────────────────── вспомогательное ─────────────────────────

class _Done:
    """Ответ `ps`, подставленный целиком: обе двери к ОС закрыты для теста."""

    def __init__(self, stdout: str = "", returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode


def _fake_guard(behaviour):
    """Сторож-заглушка. ``behaviour(tracker, log, subject) -> (code, report)``."""

    class _Announcer:
        @staticmethod
        def record(summary, files, verified, card="", card_state="", log=None,
                   session="", process=None, dropped=()):
            entry = {"ts": datetime.now(timezone.utc).strftime(M._WRITER_STAMP),
                     "session": session or "pidX", "summary": summary,
                     "files": list(files), "verified": verified}
            if card:
                entry["card"] = card
                entry["card_state"] = card_state or "claim"
            if process is not None:
                entry.update(process[0])
            Path(log).parent.mkdir(parents=True, exist_ok=True)
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return entry

    class _Guard:
        @staticmethod
        def load_announcer():
            return _Announcer

        @staticmethod
        def main(argv):
            opts = dict(zip(argv[::2], argv[1::2]))
            tracker = Path(opts["--tracker-dir"])
            log = Path(opts["--log"])
            code, report = behaviour(tracker, log, argv[-1])
            print(json.dumps(report, ensure_ascii=False))
            return code

    return lambda _root: _Guard


# ───────── ось A: оставляет ли `check` след (и контроль в обе стороны) ─────────

def test_axis_a_real_guard_leaves_no_trace_and_the_verdict_was_produced():
    """Настоящая дверь `check` сцену не меняет — и это сказано ВМЕСТЕ с вердиктом."""
    out = M.measure_trace(REPO)
    assert out["measured"] is True, out["reason"]
    assert out["outcome"] == "no_trace"
    assert out["files_changed"] == [] and out["files_added"] == []
    # «Следа нет» заявляется только при ОТКРЫТОЙ двери: вердикт обязан быть произведён.
    assert out["verdict"] in M.VERDICTS
    assert out["exit_code"] in (0, 1, 2)


def test_axis_a_turns_red_when_the_door_writes_even_one_byte():
    """Положительный контроль: дверь, оставившая файл, названа `trace_written`."""
    def writes(tracker, log, subject):
        (log.parent / "receipt.jsonl").write_text("{}\n", encoding="utf-8")
        return 0, {"verdict": "free"}

    out = M.measure_trace(REPO, guard_loader=_fake_guard(writes))
    assert out["outcome"] == "trace_written"
    assert out["files_added"] == ["receipt.jsonl"]


def test_axis_a_sees_a_changed_file_not_only_a_new_one():
    """Квитанция, дописанная в СУЩЕСТВУЮЩИЙ журнал, — тоже след."""
    def appends(tracker, log, subject):
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": "x", "summary": "[check_card_claim] спросили"}) + "\n")
        return 0, {"verdict": "free"}

    out = M.measure_trace(REPO, guard_loader=_fake_guard(appends))
    assert out["outcome"] == "trace_written"
    assert out["files_changed"] == ["session_changes.jsonl"]
    assert out["files_added"] == []


def test_axis_a_without_a_verdict_is_unmeasured_not_clean():
    """Дверь не открылась ⇒ «следа нет» не утверждается. Третий исход оси A."""
    out = M.measure_trace(REPO, guard_loader=_fake_guard(lambda t, l, s: (2, {})))
    assert out["measured"] is False
    assert out["outcome"] is None
    assert "вердикт не произведён" in out["reason"]


def test_axis_a_unmeasured_when_the_guard_itself_is_absent():
    """Сторожа нет по пути ⇒ громкий третий исход с НАЗВАННОЙ причиной."""
    out = M.measure_trace(Path("/nonexistent-tree-for-the-probe"))
    assert out["measured"] is False
    assert "сцена пробы не отработала" in out["reason"]
    assert "FileNotFoundError" in out["reason"]


def test_axis_a_leaves_no_temporary_directory_behind():
    """Сцена одноразовая: после замера её каталога нет."""
    import tempfile
    before = set(Path(tempfile.gettempdir()).glob("spa_receipt_probe_*"))
    M.measure_trace(REPO)
    after = set(Path(tempfile.gettempdir()).glob("spa_receipt_probe_*"))
    assert after == before


def test_the_scene_journal_is_written_by_the_real_writer_so_the_stamp_cannot_drift():
    """Регрессия на МОЙ дефект: сцена, собранная строками, писала микросекунды.

    Сторож разбирает секундную точность, и сцена с микросекундами получала
    «метка времени не разобрана» — то есть прибор мерил СВОЮ сцену, а не дверь.
    Поэтому журнал сцены пишет настоящий писатель, и формат сверяется с ним.
    """
    import tempfile
    guard = M._load_guard(REPO)
    scene = Path(tempfile.mkdtemp())
    try:
        _tracker, log = M._write_sandbox(scene, M._SANDBOX_CARD,
                                         announcer=guard.load_announcer())
        rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    finally:
        import shutil
        shutil.rmtree(scene, ignore_errors=True)
    assert rows, "писатель не оставил ни одной записи"
    for row in rows:
        # Та же форма, что у писателя: микросекунд нет, суффикс Z.
        datetime.strptime(row["ts"], M._WRITER_STAMP)


# ───────── ось B: кто читает ВЕРДИКТ (форма потребления) ─────────

SPEC_READER = '''
import importlib.util
CLAIM_ABSENT = ("free", "stale")
spec = importlib.util.spec_from_file_location("x", "scripts/check_card_claim.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
report = mod.gather("card")
verdict = str(report["verdict"])
if verdict in CLAIM_ABSENT:
    pass
'''

CONSTANT_READER = '''
from check_card_claim import _CLAIM_KEYS
def main():
    return sorted(_CLAIM_KEYS)
main()
'''

CALL_ONLY_READER = '''
import check_card_claim
check_card_claim.gather("card")
'''

LITERAL_COMPARE_READER = '''
import check_card_claim
report = check_card_claim.build_report("c", "p", [], None, None)
if report["verdict"] == "unchecked":
    pass
'''


def test_axis_b_spec_loaded_module_reading_a_vocabulary_is_a_verdict_reader():
    """Форма шага 0a-ГОЛОД: модуль загружен по пути, вердикт сверен с НАБОРОМ имён."""
    klass, detail = M._classify_reader(SPEC_READER)
    assert klass == M.READER_VERDICT
    assert detail["verdict_key_read"] is True
    assert "CLAIM_ABSENT" in detail["compared_against"]
    assert "mod.gather" in detail["producers_called"]


def test_axis_b_a_literal_comparison_counts_as_reading_too():
    """Сравнение с ЛИТЕРАЛОМ вердикта — тоже чтение; обе формы, не одна."""
    klass, detail = M._classify_reader(LITERAL_COMPARE_READER)
    assert klass == M.READER_VERDICT
    assert "unchecked" in detail["compared_against"]


def test_axis_b_taking_only_a_constant_is_not_reading_the_verdict():
    """Регрессия на МОЙ дефект: СВОЙ `main()` файла не есть вызов сторожа.

    Первая редакция считала вызовом сторожа любой вызов с подходящим ИМЕНЕМ, и
    `check_tracker_drift`, берущий у сторожа одну константу, был объявлен
    «вызывает, но не читает». Тот же класс, что у соседа (литерал в
    `lines.append` сходил за проводку), только с другой стороны.
    """
    klass, detail = M._classify_reader(CONSTANT_READER)
    assert klass == M.READER_CONSTANT
    assert detail["producers_called"] == []


def test_axis_b_calling_the_guard_without_reading_the_verdict_is_its_own_class():
    """Третий класс существует и не сворачивается ни в один из двух соседних."""
    klass, detail = M._classify_reader(CALL_ONLY_READER)
    assert klass == M.READER_CALL_ONLY
    assert detail["producers_called"] == ["check_card_claim.gather"]
    assert detail["verdict_key_read"] is False


def test_axis_b_a_vocabulary_must_consist_only_of_verdicts():
    """Набор с посторонней строкой словарём вердиктов НЕ является.

    Иначе любой кортеж строк рядом с чтением отчёта делал бы файл читателем.
    """
    source = '''
import check_card_claim
STATUSES = ("free", "backlog")
report = check_card_claim.gather("c")
v = report["verdict"]
if v in STATUSES:
    pass
'''
    klass, detail = M._classify_reader(source)
    assert detail["vocabularies"] == []
    assert klass == M.READER_CALL_ONLY


def test_axis_b_unparsable_file_is_unmeasured_not_a_class():
    """Третий исход оси B: файл не разобран ⇒ `unmeasured` с причиной."""
    klass, detail = M._classify_reader("def broken(:\n")
    assert klass == M.READER_UNMEASURED
    assert "не разобран" in detail["reason"]


def test_axis_b_on_the_live_tree_names_one_reader_and_one_constant_taker():
    """Положительный контроль на НАСТОЯЩЕМ населении — ответ заказа G88 п. 1.

    Посылка заказа («вердикт не читает никто») измеренно НЕВЕРНА: читатель есть,
    и это шаг 0a-ГОЛОД. Второй загрузивший берёт одну константу.
    """
    out = M.measure_verdict_readers(REPO)
    assert out["measured"] is True, out["reason"]
    assert out["readers"] == ["scripts/check_owner_order_starvation.py"]
    assert out["by_class"][M.READER_VERDICT] == 1
    assert out["by_class"][M.READER_CONSTANT] == 1
    assert out["by_class"][M.READER_UNMEASURED] == 0
    # Вслух: форма — не исполнение.
    assert "исполнялась ли ветка" in out["form_not_execution"]


def test_axis_b_unmeasured_when_the_neighbour_could_not_measure_the_loaders():
    """Перечень загрузивших НЕ ИЗМЕРЕН у соседа ⇒ ноль не выдаётся за чистоту."""
    out = M.measure_verdict_readers(REPO, wiring={"measured": False,
                                                  "reason": "дерево не осмотрено"})
    assert out["measured"] is False
    assert "НЕ ИЗМЕРЕН у соседа" in out["reason"]


def test_axis_b_zero_loaders_is_a_broken_read_not_an_answer():
    """Ноль загрузивших — поломка чтения: сосед измерил, что их двое."""
    out = M.measure_verdict_readers(REPO, wiring={"measured": True, "loads": []})
    assert out["measured"] is False
    assert "классифицировать нечего" in out["reason"]
    assert out["loaders_measured"] == 0


def test_axis_b_unreadable_door_is_counted_as_unmeasured_by_name():
    """Файл из перечня не прочитан ⇒ он назван `unmeasured`, а не пропущен."""
    out = M.measure_verdict_readers(
        REPO, wiring={"measured": True, "loads": ["scripts/does-not-exist.py"]})
    assert out["measured"] is True
    assert out["by_class"][M.READER_UNMEASURED] == 1
    assert out["readers"] == []


def test_axis_b_does_not_recount_the_loaders_with_its_own_code():
    """Перечень загрузивших берётся у соседа — второй экземпляр мерки запрещён.

    Контроль формы: подсунутый перечень и есть то, что прибор классифицирует.
    Расхождение двух мерок одного вопроса — урок ADR-220.
    """
    out = M.measure_verdict_readers(
        REPO, wiring={"measured": True, "loads": ["scripts/check_tracker_drift.py"]})
    assert [d["door"] for d in out["doors"]] == ["scripts/check_tracker_drift.py"]
    assert out["loaders_measured"] == 1


# ───────── ось C: есть ли у квитанции читатель (дифференциально) ─────────

def test_axis_c_proves_the_reader_by_outcome_on_the_real_neighbour():
    """ОТВЕТ заказа: читатель квитанции существует и доказан ИСХОДОМ."""
    out = M.measure_receipt_reader(now=NOW)
    assert out["measured"] is True, out["reason"]
    assert out["outcome"] == "reader_proven"
    assert out["without_receipt"] == 1 and out["with_receipt"] == 0
    assert "duplicate_subject_census" in out["reader"]


def test_axis_c_calls_the_reader_with_the_injected_clock():
    """Часы идут ВХОДОМ до самого читателя: обе стороны закреплены."""
    seen = {}

    def reader(records, now=None, **kw):
        seen["now"] = now
        return {"window_takings_without_receipt": 1}

    M.measure_receipt_reader(now=NOW, reader=reader)
    assert seen["now"] == NOW


def test_axis_c_reader_absent_when_the_field_does_not_move():
    """Положительный контроль обратной стороны: поле не изменилось ⇒ читателя нет."""
    out = M.measure_receipt_reader(
        now=NOW, reader=lambda recs, now=None, **kw: {"window_takings_without_receipt": 7})
    assert out["measured"] is True
    assert out["outcome"] == "reader_absent"


def test_axis_c_unmeasured_when_the_candidate_reader_raises():
    """Третий исход оси C: читатель не отработал ⇒ не «читателя нет»."""
    def boom(records, now=None, **kw):
        raise RuntimeError("перепись упала")

    out = M.measure_receipt_reader(now=NOW, reader=boom)
    assert out["measured"] is False
    assert "не отработал" in out["reason"] and "RuntimeError" in out["reason"]


def test_axis_c_unmeasured_when_the_reader_has_no_such_field():
    """Поля нет ⇒ сравнивать нечего, и это НЕ «не изменилось»."""
    out = M.measure_receipt_reader(now=NOW,
                                   reader=lambda recs, now=None, **kw: {"other": 1})
    assert out["measured"] is False
    assert "нет поля" in out["reason"]


def test_axis_c_the_receipt_is_the_only_difference_between_the_two_record_sets():
    """Сцена честна: наборы отличаются РОВНО одной записью-квитанцией."""
    captured = []

    def reader(records, now=None, **kw):
        captured.append(list(records))
        return {"window_takings_without_receipt": len(records)}

    M.measure_receipt_reader(now=NOW, reader=reader)
    without, with_one = captured
    assert len(with_one) - len(without) == 1
    extra = [r for r in with_one if r not in without]
    assert len(extra) == 1
    assert extra[0]["summary"].startswith("[check_card_claim]")


# ───────── ось D: цена наивного канала ─────────

def test_axis_d_the_naive_channel_turns_a_question_into_a_claim():
    """ГЛАВНЫЙ замер оси D на НАСТОЯЩЕМ стороже: `free` → `claimed`."""
    out = M.measure_naive_channel(REPO)
    assert out["measured"] is True, out["reason"]
    assert out["verdict_without"] == "free"
    assert out["outcome"] == "question_becomes_claim"
    assert out["verdict_with"] == "claimed"
    # Коды возврата расходятся вместе с вердиктом: 0 (свободна) → 1 (занята).
    assert (out["code_without"], out["code_with"]) == (0, 1)


def test_axis_d_refuses_to_measure_the_harm_on_its_own_anchor():
    """Замер нашёл это сам: с МОИМ якорем исход был бы `harmless` — самозахват.

    Сторож узнаёт свою сессию по подтверждённой паре (pid, старт) и СВОЙ захват
    блокирующим не считает. Значит, попади в сцену мой собственный якорь, прибор
    объявил бы наивный канал безвредным, померив не то. Теперь это третий исход с
    названной причиной, а не тихий зелёный.
    """
    out = M.measure_naive_channel(REPO, anchor=M.live_other_anchor(pid=os.getpid()))
    assert out["measured"] is False
    assert "опознан сторожем как МОЙ" in out["reason"]
    assert out["outcome"] is None


def test_axis_d_harm_is_asymmetric_the_asker_never_sees_its_own_lock():
    """И это свойство самого вреда, а не прибора: замок видят только ОСТАЛЬНЫЕ.

    Чужая живая личность ⇒ `claimed`. Своя ⇒ сторож молчит. То есть сессия,
    оставившая квитанцию, последствий своего поступка не наблюдает никогда — худшая
    из форм, потому что писатель лишён обратной связи.
    """
    foreign = M.measure_naive_channel(REPO, anchor=M.live_other_anchor(pid=os.getppid()))
    own = M.measure_naive_channel(REPO, anchor=M.live_other_anchor(pid=os.getpid()))
    assert foreign["outcome"] == "question_becomes_claim"
    assert own["measured"] is False and own["outcome"] is None


def test_axis_d_unmeasured_when_the_foreign_anchor_was_not_measured():
    """Третий исход оси D: личность не измерена ⇒ о перевороте не судим."""
    out = M.measure_naive_channel(REPO, anchor={"measured": False, "pid": 7,
                                                "reason": "`ps` промолчал"})
    assert out["measured"] is False
    assert "НЕ ИЗМЕРЕНА" in out["reason"]
    assert out["anchor"] == {"pid": 7, "measured": False}


def test_axis_d_unmeasured_when_the_baseline_is_not_free():
    """Базовый вердикт не `free` ⇒ переворот нечем увидеть, и это не «вреда нет»."""
    out = M.measure_naive_channel(
        REPO, guard_loader=_fake_guard(lambda t, l, s: (1, {"verdict": "claimed"})),
        anchor={"measured": True, "pid": os.getpid(), "start": "x"})
    assert out["measured"] is False
    assert "базовый вердикт" in out["reason"]


def test_axis_d_harmless_is_reachable_and_named():
    """Обратная сторона: вердикт не сдвинулся ⇒ `harmless`. Контроль не односторонний."""
    calls = {"n": 0}

    def steady(tracker, log, subject):
        calls["n"] += 1
        return 0, {"verdict": "free"}

    out = M.measure_naive_channel(
        REPO, guard_loader=_fake_guard(steady),
        anchor={"measured": True, "pid": os.getpid(), "start": "x"})
    assert out["measured"] is True
    assert out["outcome"] == "harmless"
    assert calls["n"] == 2, "сцены должно быть ДВЕ — без квитанции и с ней"


def test_axis_d_names_unchecked_separately_from_claimed():
    """Два лица вреда не сворачиваются в одно: `unchecked` — свой исход.

    `claimed` запирает карточку для других, `unchecked` — fail-CLOSED «не
    измерено», от которого отказывается и берущая сессия, и шаг 0a.
    """
    answers = iter([(0, {"verdict": "free"}), (2, {"verdict": "unchecked"})])
    out = M.measure_naive_channel(
        REPO, guard_loader=_fake_guard(lambda t, l, s: next(answers)),
        anchor={"measured": True, "pid": os.getpid(), "start": "x"})
    assert out["outcome"] == "question_becomes_unchecked"


# ───────── личность чужой живой сессии ─────────

def test_live_other_anchor_measures_the_start_at_the_same_door():
    """Отметка снимается у `ps` — той же двери, которой ответит проверяемый код."""
    out = M.live_other_anchor()
    assert out["measured"] is True, out["reason"]
    assert out["pid"] == os.getppid()
    assert out["start"]


def test_live_other_anchor_refuses_loudly_when_ps_says_nothing():
    """Не нашли отметку ⇒ ГРОМКИЙ отказ, а не «кажется, подойдёт»."""
    out = M.live_other_anchor(ps=lambda argv: _Done(stdout="", returncode=0))
    assert out["measured"] is False
    assert out["start"] is None
    assert "НЕ ИЗМЕРЕНА" in out["reason"]


def test_live_other_anchor_refuses_when_ps_returns_nonzero():
    """Ненулевой код `ps` — тоже «не измерено», даже если что-то напечатал."""
    out = M.live_other_anchor(ps=lambda argv: _Done(stdout="Mon Oct 1", returncode=1))
    assert out["measured"] is False


def test_live_other_anchor_refuses_when_ps_raises():
    """Исключение у двери к ОС ⇒ третий исход с НАЗВАННОЙ причиной."""
    def boom(argv):
        raise OSError("ps нет")

    out = M.live_other_anchor(ps=boom)
    assert out["measured"] is False
    assert "`ps` не отработал" in out["reason"]
    assert "OSError" in out["reason"]


def test_live_other_anchor_asks_ps_about_one_named_pid():
    """Вопрос к ОС — про КОНКРЕТНЫЙ номер, а не перечисление процессов."""
    seen = {}

    def spy(argv):
        seen["argv"] = argv
        return _Done(stdout="Mon Oct  1 00:00:00 2026", returncode=0)

    M.live_other_anchor(ps=spy, pid=4242)
    assert seen["argv"] == ["ps", "-p", "4242", "-o", "lstart="]


# ───────── сборка отчёта, вердикт и коды возврата ─────────

def _axes(*, trace="no_trace", receipt="reader_proven"):
    return {
        "trace": {"measured": True, "outcome": trace, "verdict": "free",
                  "exit_code": 0, "files_before": 2, "files_changed": [], "files_added": []},
        "readers": {"measured": True, "by_class": {M.READER_VERDICT: 1},
                    "readers": ["scripts/check_owner_order_starvation.py"],
                    "loaders_measured": 2, "doors": [],
                    "form_not_execution": "форма, не исполнение"},
        "receipt": {"measured": True, "outcome": receipt, "reader": "сосед",
                    "field": "window_takings_without_receipt",
                    "without_receipt": 1, "with_receipt": 0},
        "naive": {"measured": True, "outcome": "question_becomes_claim",
                  "verdict_without": "free", "verdict_with": "claimed",
                  "code_without": 0, "code_with": 1},
    }


def test_status_is_reader_without_writer_when_the_receipt_has_a_reader_and_no_writer():
    """Сегодняшнее состояние: читатель есть, писателя нет ⇒ находка, код 1."""
    report = M.build_report(REPO, now=NOW, **_axes())
    assert report["status"] == M.STATUS_READER_WITHOUT_WRITER
    assert M.exit_code_for(report) == 1


def test_status_is_wired_when_both_writer_and_reader_exist():
    """Обратная сторона: след появился ⇒ проводка, код 0."""
    report = M.build_report(REPO, now=NOW, **_axes(trace="trace_written"))
    assert report["status"] == M.STATUS_WIRED
    assert M.exit_code_for(report) == 0


def test_status_is_without_reader_when_nobody_would_read_the_receipt():
    """Читателя нет ⇒ канал заводить рано, и это ОТДЕЛЬНЫЙ вердикт."""
    report = M.build_report(REPO, now=NOW, **_axes(receipt="reader_absent"))
    assert report["status"] == M.STATUS_WITHOUT_READER
    assert M.exit_code_for(report) == 1


def test_a_writer_without_a_reader_is_not_called_wired():
    """След есть, читателя нет — «проводка» была бы ложью."""
    report = M.build_report(REPO, now=NOW,
                            **_axes(trace="trace_written", receipt="reader_absent"))
    assert report["status"] == M.STATUS_WITHOUT_READER


@pytest.mark.parametrize("axis", ["trace", "readers", "receipt", "naive"])
def test_any_unmeasured_axis_makes_the_whole_report_unmeasured_and_names_it(axis):
    """Третий исход перебивает вердикт, и НАЗЫВАЕТ, какая ось молчит."""
    axes = _axes()
    axes[axis] = {"measured": False, "reason": "сцена не собралась"}
    report = M.build_report(REPO, now=NOW, **axes)
    assert report["measured"] is False
    assert report["status"] == M.STATUS_UNMEASURED
    assert M.exit_code_for(report) == 2
    key = {"readers": "verdict_readers", "receipt": "receipt_reader",
           "naive": "naive_channel"}.get(axis, axis)
    assert key in report["reason"]
    assert "сцена не собралась" in report["reason"]


def test_report_shape_is_constant_even_when_unmeasured():
    """Форма отчёта ПОСТОЯННА: «не вычислено» — `None`, а не отсутствие ключа.

    Иначе шаг 0-офис не отличит уехавшего производителя от невычисленного поля.
    """
    axes = _axes()
    axes["trace"] = {"measured": False, "reason": "нет сторожа"}
    report = M.build_report(REPO, now=NOW, **axes)
    for key in ("generated_at", "order", "measured", "status", "reason", "applied",
                "trace", "verdict_readers", "receipt_reader", "naive_channel"):
        assert key in report


def test_the_instrument_declares_itself_read_only():
    """`applied=False` объявлен в самом отчёте, а не только в прозе."""
    report = M.build_report(REPO, now=NOW, **_axes())
    assert report["applied"] is False


def test_generated_at_comes_from_the_injected_clock():
    """Отметка отчёта — из переданных часов, а не из стенных."""
    report = M.build_report(REPO, now=NOW, **_axes())
    assert report["generated_at"] == "2026-10-02T12:00:00Z"


def test_the_order_is_named_in_the_artifact():
    """Артефакт сам говорит, на какой заказ он отвечает."""
    report = M.build_report(REPO, now=NOW, **_axes())
    assert "G88 п. 1" in report["order"]


# ───────── печать ─────────

def test_format_report_prints_all_four_axes_and_the_conclusion():
    text = "\n".join(M.format_report(M.build_report(REPO, now=NOW, **_axes())))
    for marker in ("[ОСЬ A]", "[ОСЬ B]", "[ОСЬ C]", "[ОСЬ D]", "ВЫВОД:",
                   "НЕ ДОКЛАДЫВАЕТ:", "ADVISORY:"):
        assert marker in text


def test_format_report_of_an_unmeasured_run_prints_the_reason_and_nothing_else():
    axes = _axes()
    axes["receipt"] = {"measured": False, "reason": "читатель не загружен"}
    lines = M.format_report(M.build_report(REPO, now=NOW, **axes))
    assert len(lines) == 1
    assert "НЕ ИЗМЕРЕНО" in lines[0]
    assert "читатель не загружен" in lines[0]


def test_format_report_names_every_door_of_axis_b():
    axes = _axes()
    axes["readers"]["doors"] = [
        {"door": "scripts/a.py", "class": M.READER_VERDICT,
         "detail": {"compared_against": ["CLAIM_ABSENT"]}},
        {"door": "scripts/b.py", "class": M.READER_UNMEASURED,
         "detail": {"reason": "файл не разобран"}}]
    text = "\n".join(M.format_report(M.build_report(REPO, now=NOW, **axes)))
    assert "scripts/a.py" in text and "CLAIM_ABSENT" in text
    assert "scripts/b.py" in text and "файл не разобран" in text


# ───────── ступень моста и артефакт ─────────

def test_run_leaves_the_artifact_even_when_unmeasured(tmp_path, monkeypatch):
    """Артефакт пишется ВСЕГДА: отсутствие файла неотличимо от «ступень не шла»."""
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(M, "build_report",
                        lambda root, now=None: {"measured": False, "status": M.STATUS_UNMEASURED,
                                                "reason": "нет сторожа"})
    out = M.run(root=str(tmp_path))
    assert out["measured"] is False
    saved = json.loads((tmp_path / "data" / M.ARTIFACT_NAME).read_text(encoding="utf-8"))
    assert saved["reason"] == "нет сторожа"


def test_run_does_not_break_the_bridge_when_the_artifact_cannot_be_written(tmp_path,
                                                                          monkeypatch):
    """Прибор не смеет валить мост — но и молчать о незаписанном артефакте тоже."""
    monkeypatch.setattr(M, "build_report",
                        lambda root, now=None: {"measured": True, "status": M.STATUS_WIRED})
    monkeypatch.setattr(M, "save_artifact",
                        lambda report, data_dir: (_ for _ in ()).throw(OSError("нет места")))
    out = M.run(root=str(tmp_path))
    assert out["measured"] is True
    assert "OSError" in out["doc"]["artifact_not_written"]


def test_main_returns_the_verdict_code_and_prints_json(capsys, monkeypatch):
    real = M.build_report
    monkeypatch.setattr(M, "build_report",
                        lambda root, **kw: real(REPO, now=NOW, **_axes()))
    code = M.main(["--repo-root", str(REPO), "--json"])
    assert code == 1
    assert json.loads(capsys.readouterr().out)["status"] == M.STATUS_READER_WITHOUT_WRITER


def test_main_does_not_write_the_artifact_without_save(tmp_path, monkeypatch):
    """Без `--save` прибор остаётся чистым читателем."""
    (tmp_path / "data").mkdir()
    real = M.build_report
    monkeypatch.setattr(M, "build_report",
                        lambda root, **kw: real(REPO, now=NOW, **_axes()))
    M.main(["--repo-root", str(tmp_path)])
    assert not (tmp_path / "data" / M.ARTIFACT_NAME).exists()


# ───────── словарь вердиктов закрыт ─────────

def test_the_verdict_vocabulary_matches_the_guard_docstring():
    """Перечень вердиктов ЗАКРЫТ и совпадает с тем, что сторож умеет отдавать.

    Сторож завёл пятый вердикт ⇒ тест краснеет, и прибор не делает вид, что
    классифицировал его молча.
    """
    guard_src = (REPO / "scripts" / "check_card_claim.py").read_text(encoding="utf-8")
    for verdict in M.VERDICTS:
        assert f'"{verdict}"' in guard_src or f"'{verdict}'" in guard_src


def test_the_guard_still_produces_a_verdict_from_the_closed_vocabulary():
    """Живая дверь отвечает словом ИЗ словаря — иначе ось A судила бы ни о чём."""
    out = M.measure_trace(REPO)
    assert out["verdict"] in M.VERDICTS
