"""Сторож прибора «был ли у НЕДОСТАВЛЕННОЙ работы зелёный прогон» (ADR-937).

Каждая сцена — ОДНА настоящая авария в её настоящей форме либо обратный контроль на
тишину. Главная из них — авария цикла #1053: в дереве доставки лежал зелёный прогон,
завершившийся **за 79,1 с ДО** последнего байта работы. Наивный счёт («в дереве зелёный
кэш ⇒ зелёный прогон недоставленной работы») назвал бы его предметом заказа, и это было бы
неверно: прогон измерил ПРЕДЫДУЩУЮ редакцию, а байты, которые не уехали, не мерены ничем.
Замер 06.11: так устроены **16 из 27** зелёных следов, то есть 59 % наивного ответа.

Сцены СИНТЕТИЧЕСКИЕ намеренно. Живые деревья `/private/tmp/spa_c10*` исчезают с уборкой, и
тест, читающий их, краснел бы от СОДЕРЖИМОГО дерева, а не от кода — класс, измеренный
ADR-905 (15 предметов). Форма аварии воспроизводится здесь дословно, её источник назван.

Часы и состояние git — ВХОДЫ (`.claude/rules/deployment.md`, приём №1): отметки задаются
``mtime_probe``, ответ git — ``status_probe``. Литеральной даты в файле нет вовсе, поэтому
календарь на вердикт не влияет ни в одну сторону.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.monitoring import undelivered_run_trace as census_mod  # noqa: E402

NOW = datetime(2026, 11, 6, 23, 0, 0, tzinfo=timezone.utc)

# Якорь сцены в секундах эпохи. Привязан к NOW, а не к стенным часам: обе стороны
# любого сравнения в этом файле происходят от него.
T0 = NOW.timestamp()


def _scene(tmp_path: Path, name: str, *, nodeids=None, lastfailed=None,
           nodeids_raw: str | None = None, lastfailed_raw: str | None = None) -> Path:
    """Дерево-сцена: кладёт ровно тот кэш, о котором спрашивает прибор."""
    tree = tmp_path / name
    cache = tree / census_mod.CACHE_REL
    cache.mkdir(parents=True, exist_ok=True)
    if nodeids_raw is not None:
        (cache / "nodeids").write_text(nodeids_raw, encoding="utf-8")
    elif nodeids is not None:
        (cache / "nodeids").write_text(json.dumps(nodeids), encoding="utf-8")
    if lastfailed_raw is not None:
        (cache / "lastfailed").write_text(lastfailed_raw, encoding="utf-8")
    elif lastfailed is not None:
        (cache / "lastfailed").write_text(json.dumps(lastfailed), encoding="utf-8")
    return tree


def _stamps(mapping: dict[Path, float]):
    """Отметка — ВХОД. Путь без объявленной отметки отвечает ``None``, то есть
    «не прочитана», а не нулём: подстановка нуля сделала бы «не измерено» давним
    прошлым и дала бы сравнению ложную сторону."""
    def probe(path: Path):
        return mapping.get(Path(path))
    return probe


def _status(mapping: dict[str, tuple[int, str]]):
    def probe(tree: Path):
        return mapping.get(str(tree), (0, ""))
    return probe


def _snapshot(*, cwd_rows=None, argv_rows=None, cwd_reason=None, argv_reason=None,
              self_pid: int = 4242) -> dict:
    """Снимок таблицы процессов — ВХОД сцены, а не живая ОС.

    Без этого входа каждая сцена спрашивала бы о процессах НАСТОЯЩУЮ машину, и её
    вердикт стал бы свойством ХОСТА — ровно тот класс, который
    `.claude/rules/deployment.md` разбирает у номера процесса и у имени ветки.
    ``None`` в строках = проба НЕ ОТВЕТИЛА, и это не то же, что пустой список: пустой
    список есть «спросили, никого нет».
    """
    return {
        "argv": ({"ok": False, "reason": argv_reason or "проба не ответила", "rows": []}
                 if argv_rows is None
                 else {"ok": True, "reason": None, "rows": list(argv_rows)}),
        "cwd": ({"ok": False, "reason": cwd_reason or "проба не ответила", "rows": []}
                if cwd_rows is None
                else {"ok": True, "reason": None, "rows": list(cwd_rows)}),
        "self_pid": self_pid,
    }


def _blind():
    """Ни одна проба не ответила: ось процессов обязана сказать «НЕ ИЗМЕРЕНО»."""
    return lambda: _snapshot()


def _quiet(self_pid: int = 4242):
    """Обе пробы ОТВЕТИЛИ и никого в деревьях не нашли — «измерено и равно нулю».

    Унаследованные сцены этого файла зовут ``census`` именно так НАМЕРЕННО: ось
    процессов у них не предмет, а живая ОС в вердикте — дверь, которую сцена обязана
    закрыть. Ослаблением это не является: проверок не убавилось, убавилось число
    входов, о которых сцена не объявляет (инв. #16, запись в `docs/journal/2026-W45.md`).
    """
    return lambda: _snapshot(cwd_rows=[(self_pid, "/elsewhere")],
                             argv_rows=[(self_pid, "pytest -q")], self_pid=self_pid)


# ─────────────────────── дверь прогона: green · red · unmeasured ───────────────────────

class TestTheRunDoorSeparatesThreeWorlds:
    def test_green_when_cache_has_nodeids_and_no_lastfailed(self, tmp_path):
        tree = _scene(tmp_path, "g", nodeids=["a::t1", "a::t2"])
        got = census_mod.run_door(
            tree, mtime_probe=_stamps({tree / census_mod.NODEIDS: T0}))
        assert got["run"] == "green", got
        assert got["run_failed"] == 0
        assert got["run_finished"] == "2026-11-06T23:00:00Z"

    def test_red_names_the_failures_it_found(self, tmp_path):
        """Положительный контроль НА НАСТОЯЩЕМ следе: мутационный прогон #1053 в
        `/private/tmp/spa_c1052_mut3` оставил `lastfailed` 107 байт с ровно одним
        именем — `test_no_call_site_inverts_a_canonical_door`. Форма дословная."""
        tree = _scene(
            tmp_path, "r", nodeids=["x::t"],
            lastfailed={"spa_core/tests/test_write_helper_path_argument.py"
                        "::test_no_call_site_inverts_a_canonical_door": True})
        got = census_mod.run_door(
            tree, mtime_probe=_stamps({tree / census_mod.NODEIDS: T0}))
        assert got["run"] == "red", got
        assert got["run_failed"] == 1
        assert "test_no_call_site_inverts_a_canonical_door" in got["run_failed_examples"][0]

    def test_absent_cache_is_unmeasured_not_green_and_not_no_run(self, tmp_path):
        """Убитый прогон кэша НЕ ПИШЕТ (плагин зовётся в ``pytest_sessionfinish``), и
        `-p no:cacheprovider` тоже. Значит «следа нет» покрывает два разных мира, и
        выдать его за «зелено» или за «прогона не было» — ровно тот fail-OPEN, который
        тише красного теста (инв. #17)."""
        tree = tmp_path / "nocache"
        tree.mkdir()
        got = census_mod.run_door(tree, mtime_probe=_stamps({}))
        assert got["run"] == "unmeasured", got
        assert got["run_reason"] and "не прочитан" in got["run_reason"]
        assert got["run_failed"] is None

    def test_empty_lastfailed_is_green_not_red(self, tmp_path):
        tree = _scene(tmp_path, "e", nodeids=["x::t"], lastfailed_raw="{}")
        got = census_mod.run_door(
            tree, mtime_probe=_stamps({tree / census_mod.NODEIDS: T0}))
        assert got["run"] == "green", got

    def test_unparseable_lastfailed_is_unmeasured_not_green(self, tmp_path):
        """Обратный контроль на тишину: мусор в `lastfailed` обязан ОТКАЗАТЬ отвечать,
        а не превратиться в «падений не нашли»."""
        tree = _scene(tmp_path, "junk", nodeids=["x::t"], lastfailed_raw="{не json")
        got = census_mod.run_door(
            tree, mtime_probe=_stamps({tree / census_mod.NODEIDS: T0}))
        assert got["run"] == "unmeasured", got
        assert got["run_reason"] and "JSON" in got["run_reason"]


# ───────── дверь порядка: ЭТО и есть авария #1053, воспроизведённая дословно ─────────

class TestTheOrderDoorIsTheAccidentOfCycle1053:
    def test_green_run_79_seconds_before_the_last_byte_does_not_cover_it(self):
        """Авария #1053 в её настоящих числах: прогон завершён 18:33:07Z, последний байт
        работы 18:34:27Z — разрыв **−79,1 с**. Прибор обязан сказать
        ``run_predates_work``; сказать ``green`` и замолчать значило бы утверждать, что
        недоставленные байты измерены, тогда как их не видел никто."""
        got = census_mod.order_door(T0, T0 + 79.1)
        assert got["order"] == "run_predates_work", got
        assert got["order_gap_s"] == -79.1

    def test_run_after_the_last_byte_covers_it(self):
        got = census_mod.order_door(T0 + 58.3, T0)
        assert got["order"] == "run_covers_work", got
        assert got["order_gap_s"] == 58.3

    def test_equal_stamps_count_as_covering(self):
        """Граница включительная и объявлена: прогон, завершившийся В ТУ ЖЕ секунду,
        последние байты видел. Решение, а не недосмотр."""
        assert census_mod.order_door(T0, T0)["order"] == "run_covers_work"

    @pytest.mark.parametrize("run_at,work_at", [(None, T0), (T0, None), (None, None)])
    def test_a_missing_stamp_refuses_instead_of_guessing(self, run_at, work_at):
        got = census_mod.order_door(run_at, work_at)
        assert got["order"] == "unmeasured", got
        assert got["order_reason"] and "нет" in got["order_reason"]
        assert got["order_gap_s"] is None


# ─────────────────── дверь охвата: называет и НЕ судит ───────────────────

class TestTheScopeDoorNamesWithoutJudging:
    def test_scope_is_the_number_of_collected_names(self, tmp_path):
        tree = _scene(tmp_path, "s", nodeids=[f"m::t{i}" for i in range(13)])
        got = census_mod.scope_door(tree)
        assert got == {"scope": "named", "scope_reason": None, "scope_collected": 13}

    def test_a_thirteen_name_battery_and_a_full_set_are_both_named_not_ranked(self, tmp_path):
        """Зелёное у батареи из 13 имён и зелёное у предписанного набора — РАЗНЫЕ
        утверждения (замер 06.11: охваты в населении от 10 до 139 364). Прибор их
        НАЗЫВАЕТ и порога не вводит: выдуманный порог превратил бы измерение в суждение
        (`docs/37`), а замера такого порога нет ни у кого."""
        small = _scene(tmp_path, "small", nodeids=[f"m::t{i}" for i in range(13)])
        big = _scene(tmp_path, "big", nodeids=[f"m::t{i}" for i in range(139364)])
        a, b = census_mod.scope_door(small), census_mod.scope_door(big)
        assert (a["scope"], b["scope"]) == ("named", "named")
        assert (a["scope_collected"], b["scope_collected"]) == (13, 139364)

    def test_unparseable_nodeids_is_unmeasured_not_zero(self, tmp_path):
        tree = _scene(tmp_path, "bad", nodeids_raw="[не json")
        got = census_mod.scope_door(tree)
        assert got["scope"] == "unmeasured" and got["scope_collected"] is None

    def test_nodeids_that_is_not_a_list_is_unmeasured(self, tmp_path):
        tree = _scene(tmp_path, "dict", nodeids_raw='{"a": 1}')
        got = census_mod.scope_door(tree)
        assert got["scope"] == "unmeasured" and "не список" in got["scope_reason"]


# ───── дверь намерения: ПО ПОЛЮ, а не грепом по тексту — ошибка, давшая ложь дважды ─────

class TestTheIntentDoorAsksTheFieldNotTheProse:
    def test_a_declared_dropped_path_is_a_measured_decline(self):
        tree = "/private/tmp/spa_cX"
        entries = [{"session": "cycle-1", "files": [f"{tree}/a.py"],
                    "dropped": [{"path": f"{tree}/a.py", "reason": "дубль отвеченного"}]}]
        got = census_mod.intent_door(tree, entries)
        assert got["intent"] == "declined", got
        assert got["intent_dropped"][0]["reason"] == "дубль отвеченного"

    def test_the_tree_named_only_in_the_summary_text_is_not_a_decline(self):
        """Дословно дефект, давший ложный ответ ДВА цикла подряд (#1051: «needs-owner 5
        против 4» — строка внутри блока кода; #1052: «три объявления вместо одного» —
        греп поймал имена мёртвых держателей в резюме). Вопрос задаётся ПОЛЮ ``files`` /
        ``dropped``; упоминание дерева в прозе резюме наблюдением НЕ является."""
        tree = "/private/tmp/spa_cX"
        entries = [{"session": "cycle-2", "files": ["/other/tree/b.py"],
                    "summary": f"снял осиротевший прогон в {tree}, доставлять не буду",
                    "verified": f"прогон в {tree} зелёный"}]
        got = census_mod.intent_door(tree, entries)
        assert got["intent"] == "undeclared", got
        assert got["intent_dropped"] == []
        assert got["intent_sessions"] == []

    def test_absence_of_a_decline_is_not_death(self):
        """«Умерла» исходом НЕ является: номер процесса переработан ОС, объявления о
        смерти не пишет никто. Тот же порядок, что у ``flight_verdict`` (ADR-924)."""
        tree = "/private/tmp/spa_cX"
        got = census_mod.intent_door(tree, [{"session": "c", "files": [f"{tree}/a.py"]}])
        assert got["intent"] == "undeclared", got
        assert "доказать её нечем" in got["intent_reason"]
        assert got["intent_sessions"] == ["c"]
        assert "died" not in json.dumps(got)

    def test_an_unreadable_journal_is_unmeasured_not_undeclared(self):
        got = census_mod.intent_door("/private/tmp/spa_cX", None)
        assert got["intent"] == "unmeasured", got
        assert got["intent_reason"] and "не прочитан" in got["intent_reason"]


# ─────────────── перекрёстная клетка: предмет заказа НЕ равен числу зелёных ───────────────

class TestTheSubjectIsTheCrossCellNotTheGreenCount:
    def _two_tree_scene(self, tmp_path):
        covered = _scene(tmp_path, "covered", nodeids=["m::t"])
        predates = _scene(tmp_path, "predates", nodeids=["m::t"])
        stamps = {
            covered / census_mod.NODEIDS: T0 + 58.3,
            covered / "work.py": T0,
            predates / census_mod.NODEIDS: T0,
            predates / "work.py": T0 + 79.1,
        }
        for t in (covered, predates):
            (t / "work.py").write_text("x = 1\n", encoding="utf-8")
        status = _status({str(covered): (0, " M work.py"),
                          str(predates): (0, " M work.py")})
        return covered, predates, stamps, status

    def test_two_green_trees_yield_a_subject_of_one(self, tmp_path):
        """Оба дерева «зелёные», и наивный счёт дал бы 2. Предмет — ОДИН: у второго
        прогон старше последней правки. Замер на живом населении 06.11 повторяет это в
        большом: зелёных 27, предмет 11, то есть **16** зелёных следов отвечают о чужих
        байтах."""
        covered, predates, stamps, status = self._two_tree_scene(tmp_path)
        doc = census_mod.census(
            tmp_path, trees=[str(covered), str(predates)], journal=tmp_path / "none.jsonl",
            status_probe=status, mtime_probe=_stamps(stamps), process_snapshot_probe=_quiet(), now=NOW)
        assert doc["tally"]["run"]["green"] == 2, doc["tally"]
        assert doc["tally"]["cross"]["green×run_covers_work"] == 1
        assert doc["tally"]["cross"]["green×run_predates_work"] == 1
        assert doc["subject"] == sorted([str(covered), str(predates)])

    def test_a_clean_tree_is_no_subject_and_asks_no_run_question(self, tmp_path):
        clean = _scene(tmp_path, "clean", nodeids=["m::t"])
        doc = census_mod.census(
            tmp_path, trees=[str(clean)], journal=tmp_path / "none.jsonl",
            status_probe=_status({str(clean): (0, "")}),
            mtime_probe=_stamps({}), process_snapshot_probe=_quiet(), now=NOW)
        assert doc["tally"]["carries"] == 0 and doc["tally"]["clean"] == 1
        row = doc["rows"][0]
        assert row["worktree"] == "clean"
        assert "run" not in row, "у чистого дерева вопрос о прогоне не возникает"

    def test_a_git_that_did_not_answer_leaves_the_tree_unmeasured(self, tmp_path):
        """Унаследованная дверь `orphan_sweep.worktree_door`: git не ответил ⇒
        ``unmeasured``, а не ``clean``. Своей копии разбора `git status` у прибора нет —
        второе объявление поверхности расходилось бы с первым молча (урок ADR-930)."""
        tree = _scene(tmp_path, "broken", nodeids=["m::t"])
        doc = census_mod.census(
            tmp_path, trees=[str(tree)], journal=tmp_path / "none.jsonl",
            status_probe=_status({str(tree): (128, "not a git repository")}),
            mtime_probe=_stamps({}), process_snapshot_probe=_quiet(), now=NOW)
        assert doc["tally"]["worktree_unmeasured"] == 1
        assert doc["tally"]["carries"] == 0

    def test_exit_code_separates_empty_subject_from_unmeasured_surface(self):
        assert census_mod.exit_code({"surface": {"reason": None}, "subject": []}) == 0
        assert census_mod.exit_code({"surface": {"reason": None}, "subject": ["/t"]}) == 1
        assert census_mod.exit_code({"surface": {"reason": "нет деревьев"},
                                     "subject": []}) == 2


# ─────────────── объявление есть мерка, и прибор сверяется с НИМ ───────────────

class TestEveryDoorStaysInsideItsDeclaredVocabulary:
    def test_live_doors_return_only_declared_outcome_names(self, tmp_path):
        """Перечень исходов объявлен в модуле, и сводка строится ПО НЕМУ. Дверь, начавшая
        возвращать имя вне своего списка, обязана краснить сторожа, а не проезжать в отчёт
        тихой нулевой клеткой (урок «объявление обязано нести СВОЙ контракт»)."""
        green = _scene(tmp_path, "v", nodeids=["m::t"])
        (green / "work.py").write_text("x = 1\n", encoding="utf-8")
        stamps = {green / census_mod.NODEIDS: T0 + 1, green / "work.py": T0}
        doc = census_mod.census(
            tmp_path, trees=[str(green)], journal=tmp_path / "none.jsonl",
            status_probe=_status({str(green): (0, " M work.py")}),
            mtime_probe=_stamps(stamps), process_snapshot_probe=_quiet(), now=NOW)
        row = doc["rows"][0]
        assert row["run"] in census_mod.RUN_OUTCOMES
        assert row["order"] in census_mod.ORDER_OUTCOMES
        assert row["scope"] in census_mod.SCOPE_OUTCOMES
        assert row["intent"] in census_mod.INTENT_OUTCOMES
        assert set(doc["tally"]["run"]) == set(census_mod.RUN_OUTCOMES)
        assert set(doc["tally"]["order"]) == set(census_mod.ORDER_OUTCOMES)
        assert set(doc["tally"]["intent"]) == set(census_mod.INTENT_OUTCOMES)

    def test_report_of_an_unmeasured_surface_says_so_and_names_nothing_else(self):
        lines = census_mod.format_report(
            {"surface": {"trees": 0, "reason": "discover_trees не назвал ни одного дерева"},
             "tally": {}, "rows": [], "journal": {}, "subject": []})
        assert len(lines) == 1 and "НЕ ИЗМЕРЕНО" in lines[0]


# ─────────────── момент — ВХОД, и неразбираемый вход ОТКАЗЫВАЕТ ───────────────

class TestTheMomentIsAnInputAndARefusalNotAFallback:
    def test_an_absent_now_means_the_wall_clock(self):
        assert census_mod.parse_now(None).tzinfo is not None

    def test_a_named_now_is_taken_verbatim_and_made_aware(self):
        got = census_mod.parse_now("2026-11-06T23:00:00Z")
        assert got == NOW and got.tzinfo is not None
        assert census_mod.parse_now("2026-11-06T23:00:00").tzinfo == timezone.utc

    @pytest.mark.parametrize("raw", ["", "   ", "вчера", "2026-13-45"])
    def test_an_unparseable_now_refuses_instead_of_returning_to_the_clock(self, raw):
        """Молчаливый возврат к стенным часам сделал бы «якорь не приняли»
        неотличимым от «якорь приняли» — дословно дефект ADR-897/898."""
        with pytest.raises(ValueError):
            census_mod.parse_now(raw)

    def test_a_refusing_moment_never_reaches_a_measurement(self):
        """CLI у прибора нет НАМЕРЕННО (точка входа без вызывающего есть предмет
        храповика сирот), поэтому претензия мерится у библиотечной двери: отказ
        `parse_now` и перевод его в «НЕ ИЗМЕРЕНО» суть два РАЗНЫХ утверждения, и
        второе принадлежит `exit_code`, а не печати."""
        with pytest.raises(ValueError):
            census_mod.parse_now("вчера")
        assert census_mod.exit_code(
            {"surface": {"reason": "момент не разобран"}, "subject": []}) == 2


# ─────────── ПЯТАЯ дверь: идёт ли прогон ПРЯМО СЕЙЧАС (заказ G926 п. 3, ADR-938) ───────────

class TestTheProcessDoorNarrowsTheMissingTraceWithoutCancellingIt:
    """«Следа прогона нет» покрывало ДВА мира (ADR-937 назвал это и не развёл):
    прогона не было ВОВСЕ и прогон НЕ ДОЕХАЛ до вердикта. Один из двух измерим прямо
    сейчас — идущий прогон держит живой процесс. Именно такой прогон был у #1053:
    четырёхчасовой pytest в соседнем дереве `_run` был ЖИВ и вердикта не дал."""

    TREE = "/scene/tree"

    def test_a_process_whose_working_directory_is_inside_the_tree_is_live(self):
        got = census_mod.process_door(
            self.TREE, _snapshot(cwd_rows=[(777, self.TREE + "/spa_core")],
                                 argv_rows=[]))
        assert got["process"] == "live"
        assert got["process_pids"] == [777]
        assert got["process_self"] is False

    def test_the_tree_itself_counts_as_inside_itself(self):
        got = census_mod.process_door(
            self.TREE, _snapshot(cwd_rows=[(778, self.TREE)], argv_rows=[]))
        assert got["process"] == "live" and got["process_pids"] == [778]

    def test_an_answering_probe_that_found_nobody_says_none_not_unmeasured(self):
        """«Измерено и равно нулю» ОБЯЗАНО отличаться от «не измерено» (инв. #17):
        склей их — и отсутствие пробы читалось бы как спокойное дерево."""
        got = census_mod.process_door(
            self.TREE, _snapshot(cwd_rows=[(779, "/somewhere/else")], argv_rows=[]))
        assert got["process"] == "none"
        assert got["process_pids"] == []
        assert "не внутри" in (got["process_reason"] or "")

    def test_a_silent_probe_says_unmeasured_and_names_why(self):
        got = census_mod.process_door(
            self.TREE, _snapshot(argv_rows=[], cwd_reason="инструмента нет: lsof"))
        assert got["process"] == "unmeasured"
        assert "lsof" in got["process_reason"]

    def test_no_snapshot_at_all_is_unmeasured_not_quiet(self):
        for snap in (None, _snapshot()):
            got = census_mod.process_door(self.TREE, snap)
            assert got["process"] == "unmeasured", got


class TestTheCommandLineIsACandidateNotAVerdict:
    """АВАРИЯ ЭТОГО ЦИКЛА, восстановленная в её настоящей форме.

    Первая редакция двери считала ``live`` любой процесс, чья командная строка НАЗЫВАЕТ
    дерево. Проба на живой машине немедленно дала ложное срабатывание: о дереве
    ``/private/tmp/spa_c1052`` ответ был ``live`` двумя процессами, и оба были
    СОБСТВЕННЫЕ процессы прибора — они дерево только НАЗВАЛИ аргументом, работая в
    другом. То есть ось argv отвечает на вопрос «кто ПРОИЗНОСИТ имя», а МЕРЯЮЩИЙ
    произносит его по построению: прибор ответил бы о СЕБЕ, а не о мире."""

    TREE = "/private/tmp/spa_c1052"

    def test_a_process_that_only_names_the_tree_is_not_live(self):
        got = census_mod.process_door(
            self.TREE,
            _snapshot(cwd_rows=[(4242, "/private/tmp/other")],
                      argv_rows=[(4242, "python3 -c census('/private/tmp/spa_c1052')")],
                      self_pid=4242))
        assert got["process"] == "none", "произносит ≠ работает"
        assert got["naming"] == "named"
        assert got["naming_pids"] == [4242]
        assert got["naming_self"] is True, "свой процесс НАЗВАН, а не вычтен"

    def test_the_two_axes_are_never_merged_into_one_cell(self):
        got = census_mod.process_door(
            self.TREE,
            _snapshot(cwd_rows=[(10, self.TREE)], argv_rows=[(11, "pytest -q")],
                      self_pid=99))
        assert got["process"] == "live" and got["process_pids"] == [10]
        assert got["naming"] == "none" and got["naming_pids"] == []

    def test_a_sibling_tree_name_is_not_a_prefix_match(self):
        """``/private/tmp/spa_c1052`` целиком содержится в
        ``/private/tmp/spa_c1052_run``. Подстрочное совпадение приписало бы прогон
        соседнего дерева этому — ошибка ФОРМЫ ИМЕНИ, уже дававшая ложный ответ рядом."""
        assert census_mod._names_tree("pytest /private/tmp/spa_c1052/x", self.TREE)
        assert census_mod._names_tree("cd /private/tmp/spa_c1052", self.TREE)
        assert not census_mod._names_tree("pytest /private/tmp/spa_c1052_run/x", self.TREE)
        assert not census_mod._names_tree("pytest /private/tmp/spa_c1052x", self.TREE)

    def test_the_cwd_axis_matches_on_a_path_boundary_too(self):
        got = census_mod.process_door(
            self.TREE, _snapshot(cwd_rows=[(12, self.TREE + "_run")], argv_rows=[]))
        assert got["process"] == "none", "каталог соседнего дерева — не это дерево"

    def test_a_silent_argv_probe_leaves_the_candidate_axis_unmeasured(self):
        got = census_mod.process_door(
            self.TREE, _snapshot(cwd_rows=[], argv_reason="инструмента нет: /bin/ps"))
        assert got["process"] == "none", "каталоги спросили — вердикт есть"
        assert got["naming"] == "unmeasured", "командные строки НЕ спрашивали"
        assert "/bin/ps" in got["naming_reason"]


class TestTheCanaryTellsAnEmptyAnswerFromNoAnswer:
    """Проба, вернувшая бессмысленную выдачу, обязана сказать «НЕ ИЗМЕРЕНО», а не
    «в деревьях никого». Канарейка — СВОЙ номер процесса: он обязан быть в снимке
    таблицы процессов ВСЕГДА. Код возврата на этот вопрос не отвечает — дословный
    урок `pyflakes` (`.claude/rules/deployment.md`)."""

    @staticmethod
    def _tool(code, out, err=""):
        def probe(argv, timeout=180.0):
            return code, out, err
        return probe

    def test_an_argv_snapshot_without_our_own_pid_fails_the_canary(self):
        got = census_mod._probe_argv(self._tool(0, "  1 /sbin/launchd\n"),
                                     canary_pid=4242)
        assert got["ok"] is False
        assert "канарейка" in got["reason"] and "4242" in got["reason"]
        assert got["rows"] == []

    def test_an_argv_snapshot_with_our_own_pid_passes(self):
        got = census_mod._probe_argv(
            self._tool(0, "  1 /sbin/launchd\n4242 pytest -q\n"), canary_pid=4242)
        assert got["ok"] is True and (4242, "pytest -q") in got["rows"]

    def test_a_nonzero_exit_with_a_full_snapshot_is_still_measured(self):
        """Рабочая проба может выйти ненулевой и при полной выдаче — судить по коду
        возврата значило бы объявить «не измерено» измеренному снимку."""
        got = census_mod._probe_argv(self._tool(1, "4242 pytest -q\n", "warning"),
                                     canary_pid=4242)
        assert got["ok"] is True

    def test_an_absent_tool_is_a_third_outcome_not_an_empty_answer(self):
        got = census_mod._probe_argv(
            self._tool(None, "", "инструмента нет: /bin/ps"), canary_pid=4242)
        assert got["ok"] is False and "инструмента нет" in got["reason"]

    def test_a_cwd_snapshot_without_our_own_pid_fails_the_canary(self):
        got = census_mod._probe_cwd(self._tool(0, "p1\nfcwd\nn/\n"), canary_pid=4242)
        assert got["ok"] is False and "канарейка" in got["reason"]

    def test_the_cwd_probe_parses_the_declared_lsof_field_form(self):
        got = census_mod._probe_cwd(
            self._tool(0, "p4242\nfcwd\nn/tmp/here\np7\nfcwd\nn/tmp/there\n"),
            canary_pid=4242)
        assert got["ok"] is True
        assert (4242, "/tmp/here") in got["rows"] and (7, "/tmp/there") in got["rows"]

    def test_a_failure_of_both_probes_leaves_every_axis_unmeasured(self):
        snap = census_mod.process_snapshot(
            argv_probe=lambda *, canary_pid=None: {"ok": False, "reason": "нет ps",
                                                   "rows": []},
            cwd_probe=lambda *, canary_pid=None: {"ok": False, "reason": "нет lsof",
                                                  "rows": []})
        assert snap["argv"]["ok"] is False and snap["cwd"]["ok"] is False
        got = census_mod.process_door("/t", snap)
        assert got["process"] == "unmeasured" and got["naming"] == "unmeasured"
        assert "нет lsof" in got["process_reason"] and "нет ps" in got["naming_reason"]


class TestTheCensusSplitsTheMissingTraceByProcess:
    """Та самая клетка, которую заказ G926 п. 3 просит измерить."""

    def _two_trees_without_a_trace(self, tmp_path):
        running = tmp_path / "running"
        silent = tmp_path / "silent"
        for t in (running, silent):
            t.mkdir()
            (t / "work.py").write_text("x = 1\n", encoding="utf-8")
        status = _status({str(running): (0, " M work.py"),
                          str(silent): (0, " M work.py")})
        return running, silent, status

    def test_a_live_process_separates_two_traceless_trees(self, tmp_path):
        running, silent, status = self._two_trees_without_a_trace(tmp_path)
        doc = census_mod.census(
            tmp_path, trees=[str(running), str(silent)],
            journal=tmp_path / "none.jsonl", status_probe=status,
            mtime_probe=_stamps({running / "work.py": T0, silent / "work.py": T0}),
            process_snapshot_probe=lambda: _snapshot(
                cwd_rows=[(4242, "/elsewhere"), (555, str(running))],
                argv_rows=[(4242, "pytest -q")], self_pid=4242),
            now=NOW)
        assert doc["tally"]["run"]["unmeasured"] == 2, doc["tally"]["run"]
        split = doc["tally"]["trace_absent_by_process"]
        assert split == {"live": 1, "none": 1, "unmeasured": 0}, split
        assert doc["trace_absent"] == sorted([str(running), str(silent)])
        assert doc["trace_absent_live"] == [str(running)]

    def test_a_blind_snapshot_leaves_the_split_unmeasured_not_zero(self, tmp_path):
        """Прибор без пробы обязан сказать «НЕ ИЗМЕРЕНО» у ОБОИХ деревьев, а не
        записать их в «сейчас не идёт»: иначе отсутствие инструмента читалось бы как
        доказанная тишина — fail-OPEN тише красного и потому опаснее."""
        running, silent, status = self._two_trees_without_a_trace(tmp_path)
        doc = census_mod.census(
            tmp_path, trees=[str(running), str(silent)],
            journal=tmp_path / "none.jsonl", status_probe=status,
            mtime_probe=_stamps({running / "work.py": T0, silent / "work.py": T0}),
            process_snapshot_probe=_blind(), now=NOW)
        split = doc["tally"]["trace_absent_by_process"]
        assert split == {"live": 0, "none": 0, "unmeasured": 2}, split
        assert doc["trace_absent_live"] == []
        assert doc["process_probes"]["cwd"]["ok"] is False
        assert doc["process_probes"]["argv"]["ok"] is False

    def test_the_subject_of_adr937_is_untouched_by_the_fifth_door(self, tmp_path):
        """Пятая дверь СУЖАЕТ третий исход первой, а предмет заказа G925 (зелёный
        прогон ИМЕННО по недоставленным байтам) не трогает ни одной клеткой."""
        tree = _scene(tmp_path, "g5", nodeids=["m::t"])
        (tree / "work.py").write_text("x = 1\n", encoding="utf-8")
        stamps = {tree / census_mod.NODEIDS: T0 + 5, tree / "work.py": T0}
        kw = dict(trees=[str(tree)], journal=tmp_path / "none.jsonl",
                  status_probe=_status({str(tree): (0, " M work.py")}),
                  mtime_probe=_stamps(stamps), now=NOW)
        live = census_mod.census(tmp_path, process_snapshot_probe=lambda: _snapshot(
            cwd_rows=[(4242, "/x"), (9, str(tree))], argv_rows=[], self_pid=4242), **kw)
        blind = census_mod.census(tmp_path, process_snapshot_probe=_blind(), **kw)
        for doc in (live, blind):
            assert doc["tally"]["cross"]["green×run_covers_work"] == 1
            assert doc["subject"] == [str(tree)]
        assert live["rows"][0]["process"] == "live"
        assert blind["rows"][0]["process"] == "unmeasured"

    def test_the_report_names_both_axes_and_never_prints_a_bare_zero(self, tmp_path):
        running, silent, status = self._two_trees_without_a_trace(tmp_path)
        doc = census_mod.census(
            tmp_path, trees=[str(running), str(silent)],
            journal=tmp_path / "none.jsonl", status_probe=status,
            mtime_probe=_stamps({running / "work.py": T0, silent / "work.py": T0}),
            process_snapshot_probe=_blind(), now=NOW)
        text = "\n".join(census_mod.format_report(doc))
        assert "СЛЕДА ПРОГОНА НЕТ" in text
        assert "НЕ ИЗМЕРЕНО 2" in text
        assert "проба не ответила" in text
        assert "вердикт — РАБОЧИЙ КАТАЛОГ" in text
        assert "вердиктом НЕ является" in text


class TestTheFifthDoorStaysInsideItsDeclaredVocabulary:
    def test_process_and_naming_return_only_declared_names(self, tmp_path):
        tree = tmp_path / "v5"
        tree.mkdir()
        (tree / "work.py").write_text("x = 1\n", encoding="utf-8")
        probes = [_blind(), _quiet(),
                  lambda: _snapshot(cwd_rows=[(4242, str(tree))],
                                    argv_rows=[(4242, "pytest " + str(tree))],
                                    self_pid=4242)]
        for probe in probes:
            doc = census_mod.census(
                tmp_path, trees=[str(tree)], journal=tmp_path / "none.jsonl",
                status_probe=_status({str(tree): (0, " M work.py")}),
                mtime_probe=_stamps({tree / "work.py": T0}),
                process_snapshot_probe=probe, now=NOW)
            row = doc["rows"][0]
            assert row["process"] in census_mod.PROCESS_OUTCOMES, row
            assert row["naming"] in census_mod.NAMING_OUTCOMES, row
            assert set(doc["tally"]["process"]) == set(census_mod.PROCESS_OUTCOMES)
            assert set(doc["tally"]["naming"]) == set(census_mod.NAMING_OUTCOMES)
            expected = set(census_mod.PROCESS_OUTCOMES)
            assert set(doc["tally"]["trace_absent_by_process"]) == expected


class TestTheNumberThatGetsQuotedCarriesItsMembers:
    """G926 п. 2 требует перемерить число 11 и назвать расхождение. Расхождение нашлось
    (11 → 10), а ОТНЕСТИ его не к чему: оба наблюдения #1054 опубликовали СЧЁТ без
    ПЕРЕЧНЯ. Поэтому предмет получает своё имя и своих членов.

    Заодно названа ловушка имени: поле ``subject`` принадлежит контракту ADR-937 и
    `exit_code` — это деревья с ЗАВЕРШЁННЫМ прогоном, знаменатель, а не предмет. Замер
    07.11: 63 против 10. Тихо переименовать его нельзя (на нём код возврата), и имя
    «предмет» для знаменателя — ровно та ошибка, ради которой заведено второе поле."""

    def _scene(self, tmp_path):
        covered = _scene(tmp_path, "cov", nodeids=["m::t"])
        predates = _scene(tmp_path, "pre", nodeids=["m::t"])
        red = _scene(tmp_path, "red", nodeids=["m::t"], lastfailed={"m::t": True})
        for t in (covered, predates, red):
            (t / "work.py").write_text("x = 1\n", encoding="utf-8")
        stamps = {
            covered / census_mod.NODEIDS: T0 + 58.3, covered / "work.py": T0,
            predates / census_mod.NODEIDS: T0, predates / "work.py": T0 + 79.1,
            red / census_mod.NODEIDS: T0 + 5, red / "work.py": T0,
        }
        status = _status({str(t): (0, " M work.py") for t in (covered, predates, red)})
        return covered, predates, red, stamps, status

    def test_the_order_subject_names_its_members_and_is_not_the_denominator(self, tmp_path):
        covered, predates, red, stamps, status = self._scene(tmp_path)
        doc = census_mod.census(
            tmp_path, trees=[str(covered), str(predates), str(red)],
            journal=tmp_path / "none.jsonl", status_probe=status,
            mtime_probe=_stamps(stamps), process_snapshot_probe=_quiet(), now=NOW)
        assert doc["order_subject"] == [str(covered)]
        assert len(doc["subject"]) == 3, "знаменатель — все завершённые прогоны"
        assert doc["tally"]["cross"]["green×run_covers_work"] == len(doc["order_subject"])

    def test_the_order_subject_is_always_inside_the_denominator(self, tmp_path):
        covered, predates, red, stamps, status = self._scene(tmp_path)
        doc = census_mod.census(
            tmp_path, trees=[str(covered), str(predates), str(red)],
            journal=tmp_path / "none.jsonl", status_probe=status,
            mtime_probe=_stamps(stamps), process_snapshot_probe=_quiet(), now=NOW)
        assert set(doc["order_subject"]) <= set(doc["subject"])

    def test_the_exit_code_contract_of_adr937_is_untouched(self, tmp_path):
        """Код возврата по-прежнему спрашивает ``subject``. Переставить его на предмет
        значило бы сменить контракт ADR-937 молча — отдельное решение, не прицеп."""
        covered, predates, red, stamps, status = self._scene(tmp_path)
        doc = census_mod.census(
            tmp_path, trees=[str(predates)], journal=tmp_path / "none.jsonl",
            status_probe=status, mtime_probe=_stamps(stamps),
            process_snapshot_probe=_quiet(), now=NOW)
        assert doc["order_subject"] == [], "предмет пуст: прогон старше правки"
        assert doc["subject"] == [str(predates)]
        assert census_mod.exit_code(doc) == 1, "код возврата считает знаменатель"


class TestALiveHolderIsNotARunningTest:
    """НАХОДКА ЭТОГО ЦИКЛА, и она опровергает посылку заказа на его же членах.

    G926 п. 3 исходит из того, что живой процесс в дереве означает недоехавший прогон.
    Замер 07.11: живых держателей нашлось в пяти деревьях, и у трёх дисковых `_run`
    ВСЕ 54 держателя оказались безголовым `Google Chrome` (12 сирот, ppid 1, старейший
    жив 1 сут 10 ч) — браузер унаследовал рабочий каталог от прогона, который давно
    кончился. Ни один держатель прогоном не был.

    Поэтому дверь обязана НАЗЫВАТЬ команду держателя: без неё «держат 5» читается как
    «идут 5 прогонов», то есть прибор отвечал бы на свой вопрос вместо нужного."""

    TREE = "/scene/live"

    def test_the_holder_command_is_named_so_the_reader_can_see_it_is_not_pytest(self):
        got = census_mod.process_door(
            self.TREE,
            _snapshot(cwd_rows=[(900, self.TREE)],
                      argv_rows=[(900, "/Applications/Google Chrome.app/Contents/"
                                       "MacOS/Google Chrome --headless=new")],
                      self_pid=4242))
        assert got["process"] == "live"
        assert any("Chrome" in line for line in got["process_commands"])

    def test_a_holder_whose_command_is_unknown_says_so_instead_of_guessing(self):
        got = census_mod.process_door(
            self.TREE, _snapshot(cwd_rows=[(901, self.TREE)],
                                 argv_reason="инструмента нет: /bin/ps"))
        assert got["process"] == "live"
        assert all("НЕ ИЗМЕРЕНА" in line for line in got["process_commands"])

    def test_a_holder_absent_from_the_argv_snapshot_is_named_absent_not_blank(self):
        """Процесс, успевший выйти между двумя пробами, обязан сказать «команды нет в
        снимке»: пустая строка читалась бы как процесс без команды."""
        got = census_mod.process_door(
            self.TREE, _snapshot(cwd_rows=[(902, self.TREE)],
                                 argv_rows=[(4242, "pytest -q")], self_pid=4242))
        assert got["process"] == "live"
        assert any("команды нет в снимке" in line for line in got["process_commands"])

    def test_no_holders_means_an_empty_command_list_not_a_missing_field(self):
        got = census_mod.process_door(
            self.TREE, _snapshot(cwd_rows=[(903, "/elsewhere")], argv_rows=[]))
        assert got["process"] == "none"
        assert got["process_commands"] == []

    def test_the_report_refuses_to_call_a_holder_a_running_test(self, tmp_path):
        tree = tmp_path / "held"
        tree.mkdir()
        (tree / "work.py").write_text("x = 1\n", encoding="utf-8")
        doc = census_mod.census(
            tmp_path, trees=[str(tree)], journal=tmp_path / "none.jsonl",
            status_probe=_status({str(tree): (0, " M work.py")}),
            mtime_probe=_stamps({tree / "work.py": T0}),
            process_snapshot_probe=lambda: _snapshot(
                cwd_rows=[(904, str(tree))],
                argv_rows=[(904, "Google Chrome --headless=new")], self_pid=4242),
            now=NOW)
        text = "\n".join(census_mod.format_report(doc))
        assert "держат 1" in text
        assert "«держит» НЕ значит «идёт прогон»" in text
        assert "держатель 904" in text and "Chrome" in text


class TestTheMutationSurvivorsOfThisCycleAreClosed:
    """ЧЕТЫРЕ мутанта пережили первую редакцию сторожа, и каждый был НАСТОЯЩЕЙ дырой,
    а не «непокрытой строкой». Замер и починка — в ADR-938.

    Пятый урок того же прогона относится к самой пробе: первая её редакция обрезала
    окружение дочернего процесса, системный `python3` не имел `pytest`, и ВСЕ 14
    мутаций «умерли» с `No module named pytest`. Вердикт «14 из 14 убито» был
    ОТСУТСТВИЕМ ИНСТРУМЕНТА, выданным за число. Лечение — обязательный положительный
    контроль на эталоне ДО первой мутации и требование СВОДКИ прогона у каждого
    мутанта; без сводки исход `НЕ ИЗМЕРЕНО`, а не «убит»."""

    def test_the_real_tool_door_tells_absence_from_a_working_run(self, tmp_path):
        """ВЫЖИВШИЙ №6. Третий исход «инструмента нет» объявляла ЕДИНСТВЕННАЯ дверь
        `_run_tool`, и сцены её обходили стороной, подавая свой runner, — то есть
        различение проверялось везде, кроме места, где оно СДЕЛАНО. Мутация
        «FileNotFoundError ⇒ код 1» проезжала молча."""
        missing = str(tmp_path / "net-takogo-instrumenta")
        code, out, err = census_mod._run_tool([missing])
        assert code is None, "отсутствие инструмента — НЕ код возврата"
        assert "инструмента нет" in err and missing in err

        code, out, err = census_mod._run_tool(["/bin/echo", "ok"])
        assert code == 0 and out.strip() == "ok", "рабочая проба отвечает ЧИСЛОМ"

    def test_the_absent_tool_reaches_the_probe_verdict_through_the_real_door(self):
        """И та же дверь, пройденная пробой целиком: канарейка не может пройти, потому
        что выдачи нет вовсе, и причина несёт имя инструмента."""
        got = census_mod._probe_argv(canary_pid=4242, run=lambda argv, timeout=180.0:
                                     census_mod._run_tool(["/net/takogo/puti"]))
        assert got["ok"] is False and "инструмента нет" in got["reason"]

    def test_the_holder_command_list_is_never_vacuously_empty(self):
        """ВЫЖИВШИЙ №8, и он был дырой В САМОМ ТЕСТЕ: утверждение
        ``all("НЕ ИЗМЕРЕНА" in line for line in commands)`` на ПУСТОМ списке истинно,
        поэтому мутация «вместо причины вернуть []» оставалась зелёной. Пустота
        проверяется ОТДЕЛЬНО от содержимого — иначе утверждение про содержимое
        заверяет отсутствие содержимого."""
        got = census_mod.process_door(
            "/scene/tree", _snapshot(cwd_rows=[(901, "/scene/tree")],
                                     argv_reason="инструмента нет: /bin/ps"))
        commands = got["process_commands"]
        assert len(commands) == 1, "у каждого держателя строка есть, даже без команды"
        assert all("НЕ ИЗМЕРЕНА" in line for line in commands)
        assert all("/bin/ps" in line for line in commands)

    def test_the_split_counts_only_traceless_trees_and_a_mixed_scene_proves_it(self, tmp_path):
        """ВЫЖИВШИЙ №11. Сцена из ОДНИХ бесследных деревьев не различает «считать по
        бесследным» и «считать по всем» — оба определения на ней совпадают, и мутация
        проезжает. Различает ТОЛЬКО смешанная сцена: дерево с кэшем, которое ТОЖЕ
        держит живой процесс, обязано в разводку НЕ попасть."""
        held_with_cache = _scene(tmp_path, "cached", nodeids=["m::t"])
        traceless = tmp_path / "traceless"
        traceless.mkdir()
        for t in (held_with_cache, traceless):
            (t / "work.py").write_text("x = 1\n", encoding="utf-8")
        stamps = {held_with_cache / census_mod.NODEIDS: T0 + 5,
                  held_with_cache / "work.py": T0, traceless / "work.py": T0}
        doc = census_mod.census(
            tmp_path, trees=[str(held_with_cache), str(traceless)],
            journal=tmp_path / "none.jsonl",
            status_probe=_status({str(held_with_cache): (0, " M work.py"),
                                  str(traceless): (0, " M work.py")}),
            mtime_probe=_stamps(stamps),
            process_snapshot_probe=lambda: _snapshot(
                cwd_rows=[(4242, "/elsewhere"),
                          (500, str(held_with_cache)), (501, str(traceless))],
                argv_rows=[(4242, "pytest -q")], self_pid=4242),
            now=NOW)
        assert doc["tally"]["process"]["live"] == 2, "держат ОБА дерева"
        assert doc["tally"]["run"]["unmeasured"] == 1, "бесследное — одно"
        split = doc["tally"]["trace_absent_by_process"]
        assert split == {"live": 1, "none": 0, "unmeasured": 0}, split
        assert doc["trace_absent_live"] == [str(traceless)]
        assert str(held_with_cache) not in doc["trace_absent"]

    def test_the_snapshot_carries_no_unread_summary_field(self):
        """ВЫЖИВШИЙ №12 оказался МЁРТВЫМ ПОЛЕМ: после переписи двери сводное «снимок
        годен» не читал никто, и мутация его смысла вердикта не меняла. Поле снято, а
        не покрыто тестом — заверять значение, которого никто не спрашивает, значит
        заверять вакуум. Сторож держит это свойство: вернётся поле — вернётся и
        мутант, проезжающий молча."""
        snap = census_mod.process_snapshot(
            argv_probe=lambda *, canary_pid=None: {"ok": True, "reason": None,
                                                   "rows": [(1, "x")]},
            cwd_probe=lambda *, canary_pid=None: {"ok": False, "reason": "нет lsof",
                                                  "rows": []})
        assert set(snap) == {"argv", "cwd", "self_pid"}, snap.keys()
        # и ОДНА ответившая проба даёт вердикт своей оси, а не общее «не измерено»
        got = census_mod.process_door("/t", snap)
        assert got["process"] == "unmeasured", "каталоги молчат — вердикта нет"
        assert got["naming"] == "none", "командные строки ОТВЕТИЛИ: имя не названо"
