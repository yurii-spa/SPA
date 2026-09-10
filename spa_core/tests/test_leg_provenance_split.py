"""Приёмка прибора «проводка или значение» (заказ #546, ADR-306).

Каждый тест — положительный контроль на свойство, на котором прибор такого рода
врёт молча. Набор писался так, чтобы мутация по координате в
`spa_core/monitoring/leg_provenance_split.py` красила хотя бы один тест.

Свойства, закрытые отдельно и намеренно:

1. **проводка берётся из ИСТОРИИ, а не из сегодняшнего списка** — ключ,
   добавленный в опрашиваемый набор позже, обязан числиться неопрошенным в дне
   ДО своего добавления. Прибор, читающий `POLLED_ADAPTERS` импортом, ответил бы
   про сегодня — ровно та ловушка, которую заказ назвал заранее;
2. **переименование списка прослежено** — до цикла #274 набор звался
   `ADAPTER_REGISTRY`, и одиннадцать первых дней журнала лежат ДО этого коммита.
   Контроль воспроизводит настоящий коммит-переименование;
3. **`None` НЕ приводится к пустому набору** — главный ОТРИЦАТЕЛЬНЫЙ контроль:
   нечитаемый состав обязан дать третий исход, а не назвать «не спрашивают»
   каждую ногу дня (на живом журнале такая ошибка стоила бы 51 пары из 179);
4. **два имени в одном коммите — тоже третий исход**, а не выбор одного из них;
5. **молчание журнала расхождений НЕ есть молчание фида** — журнал односторонен
   (род «не наблюдал никто» имеет тяжесть INFO и в него не пишется);
6. **строка журнала расхождений ДОКАЗЫВАЕТ наблюдение** — и тогда «фид молчал»
   для этой пары опровергнуто, а прибор обязан сказать это громко;
7. **множество родов ЗАМКНУТО** — род, которого прибор не знает, обязан дать
   третий исход, а не тихо стать «не наблюдали». Храповик сверяет состав родов
   с настоящим производителем по AST;
8. **`data/adapter_status.json` не читается ВОВСЕ** — ловушка заказа, проверяется
   по исходнику прибора;
9. **день не решается коммитом ИЗ БУДУЩЕГО** — состав берётся у последнего
   коммита с датой `<= generated_at` записи;
10. **проводка при рождении** — прибор объявлен и ВЫЗЫВАЕТСЯ в мосте переписей,
    прочитан шагом 0-офис и назван в манифесте ДВУМЯ записями.

FROZEN-DATE-OK: injected-clock — единственные часы прибора приходят параметром
`now=` в `measure`/`run` (константа `FIXED_NOW` ниже передаётся туда же), а все
даты фикстур ПРОИЗВОДНЫ от неё (`_day`, `_stamp`), поэтому ни одно утверждение
набора не зависит от календаря. Даты в журнале решений — ИМЕНА строк, свойством
свежести они не являются.
"""
# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — FIXED_NOW передаётся в measure(..., now=) и
# run(..., now=), а даты фикстур производятся от неё через _day()/_stamp().
from __future__ import annotations

import ast
import json
import os
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import leg_provenance_split as lps

FIXED_NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)

_MODULE = Path(lps.__file__)
_REPO = Path(__file__).resolve().parents[2]


def _day(days_ago: int) -> str:
    """Имя дня журнала, произведённое от инъектированного якоря."""
    return (FIXED_NOW - timedelta(days=days_ago)).date().isoformat()


def _stamp(days_ago: int, hour: int = 18) -> str:
    return (FIXED_NOW - timedelta(days=days_ago)).replace(
        hour=hour, minute=0, second=0, microsecond=0).isoformat()


def _record(days_ago: int, *, current: dict, target: dict, apy: dict) -> dict:
    return {
        "cycle_date": _day(days_ago),
        "generated_at": _stamp(days_ago),
        "current_positions": current,
        "target_positions": target,
        "apy_evidenced_pct": apy,
    }


def _write_journal(data_dir: Path, records) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / lps.JOURNAL_FILENAME).write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def _write_divergence(data_dir: Path, rows) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / lps.DIVERGENCE_LOG_FILENAME).write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _div_row(days_ago: int, protocol: str, kind: str) -> dict:
    return {"observed_at": _stamp(days_ago, hour=7), "protocol": protocol,
            "kind": kind, "severity": "WARN", "message": "фикстура"}


def _source_with(name: str, keys) -> str:
    body = "".join(f'    ("{k}", "T2", object),\n' for k in keys)
    return f"{name} = [\n{body}]\n"


class _GitFixture:
    """Настоящий git-репозиторий с историей файла оркестратора.

    Иначе проверялась бы не история, а её пересказ. Отметки коммитов задаются
    ЯВНО и производятся от инъектированного якоря.
    """

    def __init__(self, root: Path):
        self.root = root
        self._run("init", "-q")
        self._run("config", "user.email", "t@example.invalid")
        self._run("config", "user.name", "t")

    def _run(self, *args: str, env_extra: dict | None = None) -> None:
        env = dict(os.environ)
        env.setdefault("GIT_CONFIG_GLOBAL", str(self.root / ".gitconfig-none"))
        if env_extra:
            env.update(env_extra)
        res = subprocess.run(["git", *args], cwd=str(self.root), env=env,
                             capture_output=True, text=True, timeout=60)
        if res.returncode != 0:
            raise AssertionError(f"git {' '.join(args)}: {res.stderr.strip()}")

    def commit(self, source: str, days_ago: int) -> None:
        path = self.root / lps.ORCHESTRATOR_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        stamp = _stamp(days_ago, hour=6)
        self._run("add", lps.ORCHESTRATOR_REL)
        self._run("commit", "-q", "-m", f"состав на {_day(days_ago)}",
                  env_extra={"GIT_AUTHOR_DATE": stamp,
                             "GIT_COMMITTER_DATE": stamp})


def _require_git() -> None:
    """Отсутствие инструмента — ГРОМКИЙ отказ, а не скип и не зелёный ноль."""
    try:
        res = subprocess.run(["git", "--version"], capture_output=True,
                             text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
        raise AssertionError(f"git недоступен — предпосылка не обеспечена: {exc}")
    if res.returncode != 0:  # pragma: no cover
        raise AssertionError("git недоступен — предпосылка не обеспечена")


def _measure(tmp: Path, records, div_rows=(), *, history_sources=()) -> dict:
    """Собирает сцену целиком: репозиторий с историей + data/ + замер."""
    data_dir = tmp / "data"
    _write_journal(data_dir, records)
    _write_divergence(data_dir, list(div_rows))
    if history_sources:
        _require_git()
        git = _GitFixture(tmp)
        for source, days_ago in history_sources:
            git.commit(source, days_ago)
    return lps.measure(data_dir, root=str(tmp), now=FIXED_NOW)


def _classes(doc: dict) -> dict:
    return {(p["decision_date"], p["protocol"]): p["class"]
            for p in doc.get("pairs") or []}


class WiringComesFromHistory(unittest.TestCase):
    """Свойство 1 — состав опроса берётся ЗА ТОТ ДЕНЬ, а не сегодняшний."""

    def test_key_added_later_is_not_polled_on_the_earlier_day(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            doc = _measure(
                tmp,
                [_record(5, current={"pendle": 1.0}, target={}, apy={}),
                 _record(1, current={"pendle": 1.0}, target={}, apy={})],
                history_sources=[
                    (_source_with("POLLED_ADAPTERS", ["aave_v3"]), 9),
                    (_source_with("POLLED_ADAPTERS", ["aave_v3", "pendle"]), 3),
                ])
            cls = _classes(doc)
            self.assertEqual(cls[(_day(5), "pendle")], lps.CLASS_NOT_POLLED,
                             "день ДО добавления ключа обязан читать СВОЙ состав")
            self.assertEqual(cls[(_day(1), "pendle")],
                             lps.CLASS_VALUE_UNMEASURED,
                             "день ПОСЛЕ добавления — вопрос уходит к значению")

    def test_a_later_commit_does_not_decide_an_earlier_day(self):
        """Свойство 9 — заглядывание вперёд запрещено."""
        with TemporaryDirectory() as td:
            tmp = Path(td)
            doc = _measure(
                tmp,
                [_record(4, current={"pendle": 1.0}, target={}, apy={})],
                history_sources=[
                    (_source_with("POLLED_ADAPTERS", ["aave_v3"]), 9),
                    # коммит ПОЗЖЕ дня записи: он не смеет решать её вердикт
                    (_source_with("POLLED_ADAPTERS", ["aave_v3", "pendle"]), 2),
                ])
            self.assertEqual(_classes(doc)[(_day(4), "pendle")],
                             lps.CLASS_NOT_POLLED)


class RenameIsFollowed(unittest.TestCase):
    """Свойство 2 — список пережил переименование, и история это помнит."""

    def test_pre_274_name_is_read(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            doc = _measure(
                tmp,
                [_record(5, current={"pendle": 1.0}, target={}, apy={})],
                history_sources=[
                    (_source_with("ADAPTER_REGISTRY", ["aave_v3", "pendle"]), 9),
                ])
            self.assertEqual(_classes(doc)[(_day(5), "pendle")],
                             lps.CLASS_VALUE_UNMEASURED,
                             "состав под ДОрениеймным именем обязан быть прочитан")

    def test_both_names_at_once_is_unmeasured(self):
        """Свойство 4 — какой из двух опрашиваемый, решает не имя."""
        source = (_source_with("POLLED_ADAPTERS", ["aave_v3", "pendle"])
                  + _source_with("ADAPTER_REGISTRY", ["aave_v3"]))
        with TemporaryDirectory() as td:
            tmp = Path(td)
            doc = _measure(
                tmp,
                [_record(5, current={"pendle": 1.0}, target={}, apy={})],
                history_sources=[(source, 9)])
            self.assertEqual(_classes(doc)[(_day(5), "pendle")],
                             lps.CLASS_WIRING_UNMEASURED)


class NoneIsNotAnEmptySet(unittest.TestCase):
    """Свойство 3 — ГЛАВНЫЙ ОТРИЦАТЕЛЬНЫЙ контроль набора.

    Сцена: истории нет вовсе. Прибор, принявший «не прочитано» за «набор пуст»,
    объявил бы КАЖДУЮ ногу неопрошенной и с уверенностью назвал бы проводку
    причиной. Вердикт обязан быть третьим, и цена ошибки — напечатана.
    """

    def test_unreadable_wiring_gives_the_third_outcome(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            doc = _measure(
                tmp,
                [_record(5, current={"pendle": 1.0, "maple": 1.0},
                         target={}, apy={})])
            cls = _classes(doc)
            self.assertEqual(set(cls.values()), {lps.CLASS_WIRING_UNMEASURED})
            self.assertEqual(doc["class_counts"][lps.CLASS_NOT_POLLED], 0,
                             "нечитаемый состав НЕ есть «не спрашивают»")
            self.assertEqual(
                doc["none_coerced_to_empty_control"]["false_not_polled_pairs"], 2,
                "цена отказа от третьего исхода обязана быть НАЗВАНА числом")
            self.assertTrue(any(x.startswith("[НЕ ИЗМЕРЕНО]")
                                for x in doc["findings"]))

    def test_the_control_is_printed_even_when_it_is_zero(self):
        """Контроль, молчащий при нуле, неотличим от невыполненного."""
        with TemporaryDirectory() as td:
            tmp = Path(td)
            doc = _measure(
                tmp,
                [_record(5, current={"pendle": 1.0}, target={}, apy={})],
                history_sources=[
                    (_source_with("POLLED_ADAPTERS", ["pendle"]), 9)])
            self.assertEqual(
                doc["none_coerced_to_empty_control"]["false_not_polled_pairs"], 0)
            self.assertTrue(any(x.startswith("[КОНТРОЛЬ]")
                                for x in doc["findings"]))


class SilenceIsNotSilence(unittest.TestCase):
    """Свойства 5 и 6 — односторонний носитель читается односторонне."""

    def _scene(self, tmp: Path, div_rows):
        return _measure(
            tmp,
            [_record(2, current={"pendle": 1.0}, target={}, apy={})],
            div_rows,
            history_sources=[(_source_with("POLLED_ADAPTERS", ["pendle"]), 9)])

    def test_no_row_is_not_a_silent_feed(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            doc = self._scene(tmp, [_div_row(2, "maple", "apy_literal_vs_live")])
            self.assertEqual(_classes(doc)[(_day(2), "pendle")],
                             lps.CLASS_VALUE_UNMEASURED)
            self.assertTrue(
                any("односторонен" in x for x in doc["findings"]),
                "односторонность носителя обязана быть сказана вслух")

    def test_a_row_proves_the_value_existed(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            doc = self._scene(tmp, [_div_row(2, "pendle", "apy_literal_vs_live")])
            self.assertEqual(_classes(doc)[(_day(2), "pendle")],
                             lps.CLASS_OBSERVED)
            self.assertEqual(doc["status"], lps.STATUS_CRITICAL)

    def test_neutral_kind_does_not_prove_observation(self):
        """`tier_mismatch` — спор о тире, а не о ставке."""
        with TemporaryDirectory() as td:
            tmp = Path(td)
            doc = self._scene(tmp, [_div_row(2, "pendle", "tier_mismatch")])
            self.assertEqual(_classes(doc)[(_day(2), "pendle")],
                             lps.CLASS_VALUE_UNMEASURED)

    def test_unknown_kind_is_the_third_outcome(self):
        """Свойство 7 — род вне обоих множеств не смеет стать «не наблюдали»."""
        with TemporaryDirectory() as td:
            tmp = Path(td)
            doc = self._scene(tmp, [_div_row(2, "pendle", "apy_brand_new_kind")])
            self.assertTrue(
                any("не знает" in x and x.startswith("[НЕ ИЗМЕРЕНО]")
                    for x in doc["findings"]),
                "новый род обязан быть НАЗВАН, а не растворён")
            self.assertIn("apy_brand_new_kind",
                          " ".join(doc["findings"]))


class KindsAreClosedOverTheProducer(unittest.TestCase):
    """Свойство 7, храповик: состав родов сверяется с НАСТОЯЩИМ производителем.

    Не с копией и не по памяти: род читается из вызовов `_finding` в
    `adapter_feed_divergence` по AST. Новый род у производителя красит ЭТОТ тест,
    а не тихо уезжает в «не наблюдали».
    """

    def test_every_producer_kind_is_classified(self):
        src = (_REPO / "spa_core" / "monitoring"
               / "adapter_feed_divergence.py").read_text(encoding="utf-8")
        kinds = set()
        for node in ast.walk(ast.parse(src)):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "_finding"
                    and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)):
                kinds.add(node.args[1].value)
        self.assertTrue(kinds, "родов у производителя не нашлось — разбор сломан")
        unknown = kinds - lps.OBSERVED_KINDS - lps.NEUTRAL_KINDS
        self.assertEqual(unknown, set(),
                         f"род(ы) производителя не классифицированы: {unknown}")


class TheTrapOfTheOrder(unittest.TestCase):
    """Свойство 8 — файл «про сегодня и про дорогу» не читается ВОВСЕ."""

    def test_adapter_status_json_is_never_named(self):
        src = _MODULE.read_text(encoding="utf-8")
        code = "\n".join(line for line in src.splitlines()
                         if not line.lstrip().startswith("#"))
        # докстрока модуля называет файл, объясняя ПОЧЕМУ он не читается;
        # предмет проверки — исполняемый код, а не объяснение.
        body = code.split('"""', 2)[-1]
        self.assertNotIn("adapter_status", body,
                         "прибор не смеет спрашивать сегодняшнюю дорогу")


class EmptyJournalCollapses(unittest.TestCase):
    """Отрицательный контроль: без входа прибор не производит чисел."""

    def test_no_journal_is_unmeasured_not_ok(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "data").mkdir(parents=True)
            doc = lps.measure(tmp / "data", root=str(tmp), now=FIXED_NOW)
            self.assertEqual(doc["status"], lps.STATUS_UNMEASURED)
            self.assertEqual(doc.get("pairs"), None)
            self.assertTrue(any(x.startswith("[НЕ ИЗМЕРЕНО]")
                                for x in doc["findings"]))

    def test_declared_keys_are_present_and_are_NOT_zeros(self):
        """Схема несётся всегда, но неизмеренное — `None`, а не ноль.

        Отсутствие ключей шаг 0-офис честно назовёт расхождением схемы; ноль на
        их месте был бы хуже отсутствия — «не измерено, выданное за ответ».
        """
        with TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "data").mkdir(parents=True)
            doc = lps.measure(tmp / "data", root=str(tmp), now=FIXED_NOW)
            for key in ("population", "class_counts", "pairs", "by_leg",
                        "wiring_source", "observation_source",
                        "none_coerced_to_empty_control"):
                self.assertIn(key, doc, f"ключ схемы {key} обязан быть объявлен")
                self.assertIsNone(doc[key],
                                  f"{key} обязан быть None, а не измеренным нулём")


class PricedLegIsNotADefect(unittest.TestCase):
    def test_priced_leg_leaves_the_causes(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            doc = _measure(
                tmp,
                [_record(2, current={"pendle": 1.0}, target={},
                         apy={"pendle": 14.0})],
                history_sources=[(_source_with("POLLED_ADAPTERS", ["pendle"]), 9)])
            self.assertEqual(doc["class_counts"][lps.CLASS_PRICED], 1)
            self.assertEqual(doc["pairs"], [])
            self.assertEqual(doc["status"], lps.STATUS_OK)


class PopulationIsBOTHBooks(unittest.TestCase):
    """Нога ЦЕЛИ — тоже нога книги дня.

    Заказ сказал «по ногам КНИГИ», а книга дня есть `current ∪ target`
    (ADR-290). Прибор, считающий только удерживаемое, молча вывел бы из
    населения ровно те ноги, ради которых решение и принимается.
    """

    def test_a_leg_only_in_the_target_is_measured(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            doc = _measure(
                tmp,
                [_record(2, current={}, target={"pendle": 1.0}, apy={})],
                history_sources=[(_source_with("POLLED_ADAPTERS", ["pendle"]), 9)])
            self.assertEqual(_classes(doc)[(_day(2), "pendle")],
                             lps.CLASS_VALUE_UNMEASURED,
                             "нога цели не смеет выпасть из населения")


class RecordWithoutItsOwnStamp(unittest.TestCase):
    """Запись старой схемы без `generated_at` судится СВОИМ днём.

    Подмена отметки любой другой (нулём эпохи, сегодняшним часом) увела бы
    вердикт к чужому составу опроса — и сделала бы это молча.
    """

    def test_missing_generated_at_falls_back_to_the_records_own_day(self):
        rec = {"cycle_date": _day(2), "current_positions": {"pendle": 1.0},
               "target_positions": {}, "apy_evidenced_pct": {}}
        with TemporaryDirectory() as td:
            tmp = Path(td)
            doc = _measure(
                tmp, [rec],
                history_sources=[
                    (_source_with("POLLED_ADAPTERS", []), 9),
                    # состав с ключом появился в ТОТ ЖЕ день, но раньше по часам
                    (_source_with("POLLED_ADAPTERS", ["pendle"]), 2),
                ])
            self.assertEqual(_classes(doc)[(_day(2), "pendle")],
                             lps.CLASS_VALUE_UNMEASURED,
                             "день записи обязан читать состав СВОЕГО дня")


class ObservationIsPerDayNotPerLeg(unittest.TestCase):
    """Групповой срез по ноге НЕ есть приговор её конкретному дню.

    Наблюдение в понедельник ничего не говорит про среду. Прибор, ищущий строку
    по одному лишь имени ноги, объявил бы «значение наблюдалось» в день, когда
    его никто не видел, — и «фид молчал» было бы опровергнуто чужим днём.
    """

    def test_a_row_on_another_day_does_not_count(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            doc = _measure(
                tmp,
                [_record(2, current={"pendle": 1.0}, target={}, apy={})],
                [_div_row(5, "pendle", "apy_literal_vs_live")],
                history_sources=[(_source_with("POLLED_ADAPTERS", ["pendle"]), 9)])
            self.assertEqual(_classes(doc)[(_day(2), "pendle")],
                             lps.CLASS_VALUE_UNMEASURED,
                             "строка ЧУЖОГО дня не доказывает наблюдения в этот")


class ParseIsBoundToTheNAME(unittest.TestCase):
    """Список кортежей рядом — НЕ опрашиваемый набор.

    В файле оркестратора живут и другие списки кортежей. Разбор, берущий любое
    присваивание списком, зачёл бы соседа за состав опроса — та самая семья
    дефектов «одно имя — один объект» (`.claude/rules/adapters.md`).
    """

    def test_a_foreign_tuple_list_is_not_the_polled_set(self):
        source = (_source_with("POLLED_ADAPTERS", ["aave_v3"])
                  + _source_with("_RETIRED_CANDIDATES", ["pendle"]))
        parsed = lps.parse_polled_names(source)
        self.assertEqual(set(parsed), {"POLLED_ADAPTERS"})
        with TemporaryDirectory() as td:
            tmp = Path(td)
            doc = _measure(
                tmp,
                [_record(2, current={"pendle": 1.0}, target={}, apy={})],
                history_sources=[(source, 9)])
            self.assertEqual(_classes(doc)[(_day(2), "pendle")],
                             lps.CLASS_NOT_POLLED,
                             "сосед по файлу не смеет числиться опрашиваемым")


class ClockIsAnInput(unittest.TestCase):
    def test_now_reaches_the_artifact(self):
        other = datetime(2030, 1, 15, 3, 0, 0, tzinfo=timezone.utc)
        with TemporaryDirectory() as td:
            tmp = Path(td)
            _write_journal(tmp / "data",
                           [_record(2, current={}, target={}, apy={})])
            doc = lps.measure(tmp / "data", root=str(tmp), now=other)
            self.assertEqual(doc["generated_at"], other.isoformat())


class ReportOfAnUnmeasuredDoc(unittest.TestCase):
    """Отрисовка шага 0-офис не смеет превращать `None` в измеренный ноль."""

    def test_unmeasured_doc_renders_without_fabricating_counts(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "data").mkdir(parents=True)
            doc = lps.measure(tmp / "data", root=str(tmp), now=FIXED_NOW)
            lines = lps.format_report(doc)
            self.assertTrue(lines)
            body = "\n".join(lines)
            self.assertIn(lps.STATUS_UNMEASURED, body)
            self.assertNotIn("классы:", body,
                             "строка классов не смеет появиться без замера")


class WiredAtBirth(unittest.TestCase):
    """Свойство 10 — объявление БЕЗ вызова есть дефект ADR-259."""

    def test_declared_and_called_in_the_findings_bridge(self):
        src = (_REPO / "spa_core" / "monitoring"
               / "findings_bridge.py").read_text(encoding="utf-8")
        self.assertIn('"data/leg_provenance_split.json"', src)
        self.assertIn('"leg_provenance_split"', src)
        self.assertIn("leg_provenance_split.run(root=args.root)", src)

    def test_read_by_the_office_step(self):
        src = (_REPO / "scripts"
               / "consume_office_reports.py").read_text(encoding="utf-8")
        self.assertIn('"leg_provenance_split.json"', src)
        self.assertIn("spa_core/monitoring/leg_provenance_split.py", src)
        self.assertIn("format_report as _lps_report", src)

    def test_manifest_carries_BOTH_entries(self):
        m = json.loads((_REPO / "architecture"
                        / "manifest.json").read_text(encoding="utf-8"))
        rel = "data/leg_provenance_split.json"
        self.assertTrue(any(a.get("path") == rel for a in m["artifacts"]),
                        "нет записи в реестре артефактов")
        produced = [a for a in m["agents"]
                    if any(p.get("artifact") == rel
                           for p in (a.get("produces") or []))]
        self.assertEqual(len(produced), 1,
                         "паспорт агента обязан объявлять артефакт РОВНО один раз")


class DivergenceJournalCarriesTheSide(unittest.TestCase):
    """Аддитивная правка носителя: сторона наблюдения теперь ПОЛЕ, а не проза.

    Проверяется у ПОТРЕБИТЕЛЯ формы — в списке копируемых полей писателя, — и
    отдельно то, что прибор переживает её отсутствие (56 строк, написанных до
    правки, стороны не несут).
    """

    def test_live_side_is_copied_into_the_journal_record(self):
        from spa_core.monitoring import adapter_feed_divergence as afd

        rec = afd._journal_records(
            {"findings": [{"protocol": "pendle", "kind": "apy_literal_vs_live",
                           "severity": "WARN", "message": "m",
                           "live_side": "orchestrator", "live_apy": 13.97,
                           "literal_side": "adapter_status", "literal_apy": 8.0,
                           "delta_pp": 5.97}],
             "inputs": {}}, FIXED_NOW)[0]
        self.assertEqual(rec["live_side"], "orchestrator")
        self.assertEqual(rec["live_apy"], 13.97)
        self.assertEqual(rec["literal_side"], "adapter_status")

    def test_instrument_survives_rows_without_the_side(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            row = _div_row(2, "pendle", "apy_literal_vs_live")
            self.assertNotIn("live_side", row)
            doc = _measure(
                tmp,
                [_record(2, current={"pendle": 1.0}, target={}, apy={})],
                [row],
                history_sources=[(_source_with("POLLED_ADAPTERS", ["pendle"]), 9)])
            self.assertEqual(_classes(doc)[(_day(2), "pendle")],
                             lps.CLASS_OBSERVED)


class RunShapeMatchesTheBridge(unittest.TestCase):
    def test_run_reports_overall_and_counts(self):
        with TemporaryDirectory() as td:
            tmp = Path(td)
            _write_journal(tmp / "data",
                           [_record(2, current={"pendle": 1.0}, target={},
                                    apy={})])
            doc = lps.run(root=str(tmp), now=FIXED_NOW, write=False)
            self.assertEqual(doc["overall"], doc["status"])
            for key in ("critical", "warn", "info", "unchecked"):
                self.assertIn(key, doc["counts"])
            self.assertGreaterEqual(doc["counts"]["unchecked"], 1)
            self.assertFalse((tmp / "data" / lps.OUTPUT_FILENAME).exists(),
                             "write=False не смеет писать")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
