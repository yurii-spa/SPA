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
            status_probe=status, mtime_probe=_stamps(stamps), now=NOW)
        assert doc["tally"]["run"]["green"] == 2, doc["tally"]
        assert doc["tally"]["cross"]["green×run_covers_work"] == 1
        assert doc["tally"]["cross"]["green×run_predates_work"] == 1
        assert doc["subject"] == sorted([str(covered), str(predates)])

    def test_a_clean_tree_is_no_subject_and_asks_no_run_question(self, tmp_path):
        clean = _scene(tmp_path, "clean", nodeids=["m::t"])
        doc = census_mod.census(
            tmp_path, trees=[str(clean)], journal=tmp_path / "none.jsonl",
            status_probe=_status({str(clean): (0, "")}),
            mtime_probe=_stamps({}), now=NOW)
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
            mtime_probe=_stamps({}), now=NOW)
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
            mtime_probe=_stamps(stamps), now=NOW)
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
