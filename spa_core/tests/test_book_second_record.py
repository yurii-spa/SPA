#!/usr/bin/env python3
"""Вторая запись о деньгах: сходится ли книга с журналом ходов.

Шаг 3 из трёх до go-live (ADR-286 §1), вторая половина. Первая — независимое
наблюдение — упирается в ключи владельца и здесь НЕ решается (ADR-257/349).

Сцены синтетические: живой `data/` тест не читает НИКОГДА — вердикт, зависящий от
состояния боевого дерева, отвечает не на тот вопрос (`test_verdict_decided_by_live_data_dir`).

**Главное, что здесь проверяется, — РАЗЛИЧЕНИЕ, а не обнаружение.** Прибор обязан
отличать дыру в записи о деньгах от переименования ключа пула, и обе стороны этого
различения имеют цену ошибки:

* назвать переименование дырой — ложная тревога о деньгах;
* простить дыру как переименование («суммы же сошлись») — слепота ровно на том классе,
  ради которого прибор написан.

Замер 12.09 на живой книге дал по одному экземпляру КАЖДОГО рода, и оба рода настоящие:
T008 (журнал пуст с 20.06 по 23.08, $94 999.88 → $80 000.00) и T034 (слияние ключа
`fluid_usdc` → `fluid_fusdc`, ADR-331/335, суммы равны).
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("_bsr", ROOT / "scripts" / "book_second_record.py")
bsr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bsr)


def _trade(tid, frm, to):
    return {"trade_id": tid, "ts": f"2026-06-{int(tid[1:]):02d}T00:00:00+00:00",
            "type": "rebalance", "from_allocation": frm, "to_allocation": to}


def _row(tid, kind, before, after, only_before, only_after, reason="историческое, замер в ADR-1033"):
    """Строка ОБЪЯВЛЕНИЯ в той же форме, в какой её пишет боевой перечень."""
    return {"trade_id": tid, "kind": kind, "sum_before": before, "sum_after": after,
            "gap_usd": round(after - before, 2),
            "keys_only_before": list(only_before), "keys_only_after": list(only_after),
            "reason": reason}


def _declare(where, rows, required=None, name="baseline.json"):
    """Положить объявление рядом со сценой и вернуть путь.

    Объявление подаётся ВХОДОМ всегда: умолчание указывает на боевой перечень, и
    тест, молча его прочитавший, судил бы о составе ЖИВОЙ книги.
    """
    doc = {"declared": list(rows)}
    if required is not None:
        doc["required_fields"] = list(required)
    path = Path(where) / name
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


class _Scene(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="spa_bsr_"))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def write(self, trades, positions=None):
        (self.d / "trades.json").write_text(json.dumps(trades), encoding="utf-8")
        if positions is None:
            positions = {"positions": dict(trades[-1]["to_allocation"])}
        (self.d / "current_positions.json").write_text(json.dumps(positions), encoding="utf-8")
        return bsr.measure(str(self.d))


class AContinuousChainReconciles(_Scene):
    def test_a_clean_book_reconciles(self):
        r = self.write([_trade("T1", {}, {"aave_v3": 100.0}),
                        _trade("T2", {"aave_v3": 100.0}, {"maple": 60.0, "aave_v3": 40.0})])
        self.assertTrue(r["reconciles"])
        self.assertEqual(r["chain_breaks"], [])
        self.assertIsNone(r["terminal_divergence"])


class TheTwoKindsAreTold(_Scene):
    """Оба направления ошибки различения — каждое своим контролем."""

    def test_money_that_moved_without_a_record_is_a_gap(self):
        """Положительный контроль формы T008: суммы разошлись."""
        r = self.write([_trade("T1", {}, {"aave_v3": 100.0}),
                        _trade("T2", {"aave_v3": 85.0}, {"maple": 85.0})])
        self.assertEqual([b["kind"] for b in r["chain_breaks"]], ["money_gap"])
        self.assertEqual(r["chain_breaks"][0]["gap_usd"], -15.0)
        self.assertFalse(r["reconciles"])

    def test_a_renamed_key_is_named_and_is_NOT_a_money_gap(self):
        """Форма T034: слияние ключа пула. Суммы равны — деньгами это не является."""
        r = self.write([_trade("T1", {}, {"fluid_usdc": 100.0}),
                        _trade("T2", {"fluid_fusdc": 100.0}, {"maple": 100.0})])
        self.assertEqual([b["kind"] for b in r["chain_breaks"]], ["renamed_key"])
        self.assertEqual(r["money_gaps"], [])
        self.assertEqual(r["chain_breaks"][0]["keys_only_before"], ["fluid_usdc"])
        self.assertEqual(r["chain_breaks"][0]["keys_only_after"], ["fluid_fusdc"])

    def test_a_rename_is_NOT_silently_forgiven(self):
        """Обратная сторона: «суммы сошлись» НЕ означает «сходится».

        Прощать переименование молча значило бы ослепить прибор на дефекте ИМЕНИ —
        том самом, на котором уже один раз ослеп денежный гейт (ADR-331/335).
        """
        r = self.write([_trade("T1", {}, {"fluid_usdc": 100.0}),
                        _trade("T2", {"fluid_fusdc": 100.0}, {"maple": 100.0})])
        self.assertFalse(r["reconciles"], "переименование обязано быть НАЗВАНО, а не прощено")

    def test_a_gap_hidden_behind_a_rename_is_still_a_gap(self):
        """Смешанный случай: имя сменилось И денег стало меньше. Род — дыра."""
        r = self.write([_trade("T1", {}, {"fluid_usdc": 100.0}),
                        _trade("T2", {"fluid_fusdc": 85.0}, {"maple": 85.0})])
        self.assertEqual([b["kind"] for b in r["chain_breaks"]], ["money_gap"])


class TheEndMustMeetTheBook(_Scene):
    def test_a_book_that_disagrees_with_the_last_trade_is_named(self):
        r = self.write([_trade("T1", {}, {"aave_v3": 100.0})],
                       positions={"positions": {"aave_v3": 91.0}})
        self.assertIsNotNone(r["terminal_divergence"])
        self.assertEqual(r["terminal_divergence"]["per_key"], {"aave_v3": [100.0, 91.0]})
        self.assertFalse(r["reconciles"])

    def test_a_cent_of_rounding_is_not_a_divergence(self):
        """Допуск существует, и его граница названа: книга ведётся в центах."""
        r = self.write([_trade("T1", {}, {"aave_v3": 100.0})],
                       positions={"positions": {"aave_v3": 100.004}})
        self.assertIsNone(r["terminal_divergence"])

    def test_the_tolerance_cannot_swallow_a_real_divergence(self):
        """Контроль на сам допуск: иначе он молча стал бы глушилкой."""
        r = self.write([_trade("T1", {}, {"aave_v3": 100.0})],
                       positions={"positions": {"aave_v3": 100.02}})
        self.assertIsNotNone(r["terminal_divergence"])


class NotMeasuredIsItsOwnOutcome(unittest.TestCase):
    """Инв. #17: «не смогли» никогда не выдаётся за «сходится»."""

    def test_a_missing_data_dir_is_not_a_finding(self):
        with self.assertRaises(bsr.NotMeasured) as ctx:
            bsr.measure("/nonexistent/spa/data")
        self.assertIn("ШТАТНО", str(ctx.exception))

    def test_a_missing_journal_refuses(self):
        d = Path(tempfile.mkdtemp(prefix="spa_bsr_empty_"))
        try:
            with self.assertRaises(bsr.NotMeasured) as ctx:
                bsr.measure(str(d))
            self.assertIn("trades.json", str(ctx.exception))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_an_unparsable_journal_refuses(self):
        d = Path(tempfile.mkdtemp(prefix="spa_bsr_broken_"))
        try:
            (d / "trades.json").write_text("{не json", encoding="utf-8")
            with self.assertRaises(bsr.NotMeasured) as ctx:
                bsr.measure(str(d))
            self.assertIn("не разобран", str(ctx.exception))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_an_empty_journal_refuses_rather_than_reconciling(self):
        d = Path(tempfile.mkdtemp(prefix="spa_bsr_zero_"))
        try:
            (d / "trades.json").write_text("[]", encoding="utf-8")
            (d / "current_positions.json").write_text('{"positions": {}}', encoding="utf-8")
            with self.assertRaises(bsr.NotMeasured) as ctx:
                bsr.measure(str(d))
            self.assertIn("пуст", str(ctx.exception))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_a_book_without_positions_refuses(self):
        d = Path(tempfile.mkdtemp(prefix="spa_bsr_nopos_"))
        try:
            (d / "trades.json").write_text(json.dumps([_trade("T1", {}, {"a": 1.0})]), encoding="utf-8")
            (d / "current_positions.json").write_text('{"capital_usd": 100000}', encoding="utf-8")
            with self.assertRaises(bsr.NotMeasured) as ctx:
                bsr.measure(str(d))
            self.assertIn("positions", str(ctx.exception))
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TheExitCodeSeparatesThreeOutcomes(unittest.TestCase):
    """Код возврата — носитель третьего исхода, и 1 не смешана с 2."""

    def test_not_measured_returns_two_not_one(self):
        self.assertEqual(bsr.main(["--data-dir", "/nonexistent/spa/data"]), 2)

    def test_a_clean_book_returns_zero(self):
        d = Path(tempfile.mkdtemp(prefix="spa_bsr_ok_"))
        try:
            (d / "trades.json").write_text(json.dumps([_trade("T1", {}, {"a": 1.0})]), encoding="utf-8")
            (d / "current_positions.json").write_text('{"positions": {"a": 1.0}}', encoding="utf-8")
            # Объявление подаётся ВХОДОМ и пусто: «сходится» с ADR-1033 означает
            # «расхождений нет И объявлять нечего». Умолчание тут взяло бы боевой
            # перечень из двух исторических строк, и вердикт стал бы утверждением
            # о составе ЖИВОЙ книги — то есть ответом не на тот вопрос.
            self.assertEqual(bsr.main(["--data-dir", str(d),
                                       "--baseline", str(_declare(d, []))]), 0)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_a_DECLARED_divergence_returns_one(self):
        """НАМЕРЕННОЕ изменение (инв. #16): прежде этот тест звался
        `test_a_divergence_returns_one` и требовал код 1 от ЛЮБОГО расхождения.

        Это ровно тот вердикт, который ADR-1033 расщепляет: с ним приход третьей
        дыры не менял код возврата, и рост состава был виден только глазами. Теперь
        код 1 означает УЗКОЕ «новых нет», и утверждение разложено на два теста —
        здесь объявленное расхождение, ниже такое же, но НЕ объявленное. Проверок
        стало больше, ни одна не снята.
        """
        d = Path(tempfile.mkdtemp(prefix="spa_bsr_known_"))
        try:
            (d / "trades.json").write_text(json.dumps(
                [_trade("T1", {}, {"a": 100.0}), _trade("T2", {"a": 85.0}, {"b": 85.0})]),
                encoding="utf-8")
            (d / "current_positions.json").write_text('{"positions": {"b": 85.0}}', encoding="utf-8")
            # Ключи у дыры ПУСТЫ: деньги ушли с того же ключа, разошлись только
            # суммы. Объявить здесь ['a'] значило бы описать воображаемое расхождение.
            base = _declare(d, [_row("T2", "money_gap", 100.0, 85.0, [], [])])
            self.assertEqual(bsr.main(["--data-dir", str(d), "--baseline", str(base)]), 1)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_an_UNDECLARED_divergence_returns_three_not_one(self):
        """Вторая половина расщеплённого утверждения: ТОТ ЖЕ дефект, но не объявлен.

        Если этот тест и предыдущий дают один код, прибор снова не различает
        «знакомое» и «новое» — то есть ADR-1033 не исполнен.
        """
        d = Path(tempfile.mkdtemp(prefix="spa_bsr_bad_"))
        try:
            (d / "trades.json").write_text(json.dumps(
                [_trade("T1", {}, {"a": 100.0}), _trade("T2", {"a": 85.0}, {"b": 85.0})]),
                encoding="utf-8")
            (d / "current_positions.json").write_text('{"positions": {"b": 85.0}}', encoding="utf-8")
            self.assertEqual(bsr.main(["--data-dir", str(d),
                                       "--baseline", str(_declare(d, []))]), 3)
        finally:
            shutil.rmtree(d, ignore_errors=True)



class TheRunLeavesATrace(_Scene):
    """ADR-374: прибор, не оставляющий следа, неотличим от незапускавшегося.

    Прибор проведён в цикл СТРОКОЙ В ПРОМПТЕ. Промпт — намерение, а не факт:
    по нему нельзя ответить, запускался ли шаг сегодня. Пока прибор ничего не
    писал, его молчание выглядело в точности как исправная работа.

    Честная оговорка, которую стоит держать рядом: из журнала цикла исполнение
    шага НЕ ВИДНО вовсе (туда попадает итоговая сводка агента, а не его шаги),
    поэтому вывод «шаги промпта не исполняются» был бы НЕ ИЗМЕРЕН. Артефакт и
    есть то наблюдение, которого не хватало.
    """

    def test_a_measured_run_leaves_its_verdict(self):
        self.write([_trade("T1", {}, {"a": 100.0}),
                    _trade("T2", {"a": 85.0}, {"b": 85.0})],
                   positions={"positions": {"b": 85.0}})
        base = _declare(self.d, [_row("T2", "money_gap", 100.0, 85.0, [], [])])
        self.assertEqual(bsr.main(["--data-dir", str(self.d), "--baseline", str(base)]), 1)
        doc = json.loads((self.d / bsr.ARTIFACT).read_text(encoding="utf-8"))
        self.assertEqual(doc["status"], "measured")
        self.assertIs(doc["reconciles"], False)
        self.assertEqual([b["kind"] for b in doc["money_gaps"]], ["money_gap"])
        self.assertTrue(doc["ran_at"], "без отметки времени след не отвечает «когда»")

    def test_a_REFUSAL_also_leaves_a_trace(self):
        """Инв. #17: «не смогли измерить» и «не запускались» — разные факты.

        Если след пишется только у удачного замера, то отказ снова становится
        неотличим от тишины — то есть ровно тем дефектом, который артефакт и
        закрывает, только сдвинутым на шаг.
        """
        self.assertEqual(bsr.main(["--data-dir", str(self.d)]), 2)
        doc = json.loads((self.d / bsr.ARTIFACT).read_text(encoding="utf-8"))
        self.assertEqual(doc["status"], "unmeasured")
        self.assertIn("trades.json", doc["reason"])
        self.assertIsNone(doc["reconciles"])

    def test_an_unwritable_trace_does_not_break_the_measurement(self):
        """След — свидетельство, а не цель: он не имеет права ронять замер."""
        self.assertIsNone(bsr.write_artifact({"status": "measured"}, "/nonexistent/spa/dd"))

    def test_the_trace_answers_when_it_ran(self):
        """Без отметки времени артефакт не отличает сегодняшний прогон от прошлогоднего."""
        self.write([_trade("T1", {}, {"a": 1.0})])
        bsr.main(["--data-dir", str(self.d), "--baseline", str(_declare(self.d, []))])
        doc = json.loads((self.d / bsr.ARTIFACT).read_text(encoding="utf-8"))
        from datetime import datetime, timezone
        ran = datetime.fromisoformat(doc["ran_at"])
        age = (datetime.now(timezone.utc) - ran).total_seconds()
        self.assertLess(abs(age), 300, "отметка прогона не похожа на «только что»")


class GrowthOfTheCompositionChangesTheExitCode(_Scene):
    """ADR-1033 (заказ G1021 п. 6): «новых расхождений нет» ≠ «расхождений нет».

    Шесть циклов подряд шаг 1д давал код **1** на одном и том же составе из двух
    ИСТОРИЧЕСКИХ расхождений живой книги (T008 — дыра 23.08, T034 — переименование
    ключа 11.09). Закрыть их нельзя: дописать запись задним числом значит выдумать
    наблюдение (`docs/37`), переписать журнал ходов значит правку записи о деньгах,
    которая агенту не принадлежит (инв. #14). Решение «не закрывать» принято и
    названо вслух.

    Цена решения лежала в другом месте: **третья дыра дала бы ТОТ ЖЕ КОД 1**, и
    рост состава был виден только чтением глазами. Прибор, чей вердикт не меняется
    от прихода нового дефекта, отвечает на свой вопрос, а не на нужный.

    Сцены синтетические; живой `data/` эти тесты не читают НИКОГДА, а объявление
    подаётся ВХОДОМ — иначе вердикт зависел бы от состава боевой книги.
    """

    def _book(self, *trades, positions=None):
        return self.write(list(trades), positions)

    # --- то, ради чего ADR написан: рост состава ---------------------------------

    def test_a_THIRD_divergence_changes_the_exit_code(self):
        """Дословная проба заказа G1021 п. 6: третье расхождение ⇒ код СМЕНИЛСЯ.

        Два объявленных остаются на месте и продолжают называться; меняется ровно
        вердикт. Если код остаётся 1, прибор слеп к росту — то есть к тому самому
        классу, ради которого шаг 1д стоит в цикле.
        """
        trades = [_trade("T1", {}, {"a": 100.0}),
                  _trade("T2", {"a": 90.0}, {"b": 90.0}),            # объявленная дыра
                  _trade("T3", {"b": 90.0}, {"c": 90.0}),
                  _trade("T4", {"d": 90.0}, {"d": 90.0})]            # объявленное имя
        known = [_row("T2", "money_gap", 100.0, 90.0, [], []),
                 _row("T4", "renamed_key", 90.0, 90.0, ["c"], ["d"])]
        self.write(trades, {"positions": {"d": 90.0}})
        base = _declare(self.d, known)
        self.assertEqual(bsr.main(["--data-dir", str(self.d), "--baseline", str(base)]), 1,
                         "статус-кво обязан давать 1")

        # ТРЕТЬЕ расхождение — на ходу, у которого объявленного нет, иначе проба
        # отвечала бы «знакомое подменено», а не «состав ВЫРОС».
        trades[2]["from_allocation"] = {"b": 89.0}
        self.write(trades, {"positions": {"d": 90.0}})
        rc = bsr.main(["--data-dir", str(self.d), "--baseline", str(base)])
        self.assertEqual(rc, 3, "приход третьего расхождения ОБЯЗАН сменить код возврата")
        doc = json.loads((self.d / bsr.ARTIFACT).read_text(encoding="utf-8"))
        self.assertEqual([b["trade_id"] for b in doc["new_breaks"]], ["T3"])
        self.assertEqual(doc["vanished_declared"], [],
                         "объявленные обязаны остаться объявленными")

    def test_a_gap_that_GREW_on_the_same_trade_is_new(self):
        """Личность несёт ОБЕ суммы: выросшая дыра не прячется за знакомым `trade_id`.

        Порванное звено названо прямо: сведи личность к `trade_id` — и дыра, выросшая
        с $10 до $10 000 на том же ходу, будет молча прощена как «знакомая».
        """
        self.write([_trade("T1", {}, {"a": 100.0}), _trade("T2", {"a": 50.0}, {"b": 50.0})],
                   {"positions": {"b": 50.0}})
        base = _declare(self.d, [_row("T2", "money_gap", 100.0, 90.0, [], [])])
        self.assertEqual(bsr.main(["--data-dir", str(self.d), "--baseline", str(base)]), 3)

    def test_the_same_trade_with_a_DIFFERENT_kind_is_new(self):
        """Род входит в личность: переименование, ставшее дырой, — новое расхождение."""
        self.write([_trade("T1", {}, {"a": 100.0}), _trade("T2", {"a": 90.0}, {"b": 90.0})],
                   {"positions": {"b": 90.0}})
        base = _declare(self.d, [_row("T2", "renamed_key", 100.0, 90.0, [], [])])
        self.assertEqual(bsr.main(["--data-dir", str(self.d), "--baseline", str(base)]), 3)

    def test_a_rename_of_DIFFERENT_keys_at_the_same_trade_is_new(self):
        """Разошедшиеся ключи входят в личность, и это НЕ украшение.

        Переименование не двигает сумм вовсе, поэтому у двух РАЗНЫХ переименований на
        одном ходу совпадает всё, кроме ключей. Сведи личность к «ход + род + суммы» —
        и подмена одной пары имён другой будет молча прощена как знакомая, то есть
        дефект ИМЕНИ (а на именах стои́т провенанс денег, ADR-331/335) станет невидим.
        """
        self.write([_trade("T1", {}, {"c": 90.0}), _trade("T2", {"x": 90.0}, {"x": 90.0})],
                   {"positions": {"x": 90.0}})
        base = _declare(self.d, [_row("T2", "renamed_key", 90.0, 90.0, ["c"], ["d"])])
        self.assertEqual(bsr.main(["--data-dir", str(self.d), "--baseline", str(base)]), 3)
        doc = json.loads((self.d / bsr.ARTIFACT).read_text(encoding="utf-8"))
        self.assertEqual([b["keys_only_after"] for b in doc["new_breaks"]], [["x"]])

    def test_gap_usd_is_NOT_part_of_the_identity(self):
        """`gap_usd` выводится из двух сумм, уже вошедших в личность.

        Сверять его отдельно значило бы сравнивать число с самим собой (ADR-349).
        Проверяется НАСТОЯЩЕЙ сценой: объявление несёт заведомо неверный `gap_usd`,
        а суммы верные — расхождение обязано остаться ЗНАКОМЫМ.
        """
        self.write([_trade("T1", {}, {"a": 100.0}), _trade("T2", {"a": 90.0}, {"b": 90.0})],
                   {"positions": {"b": 90.0}})
        row = _row("T2", "money_gap", 100.0, 90.0, [], [])
        row["gap_usd"] = -12345.0          # врёт, и это НЕ должно ничего решать
        base = _declare(self.d, [row])
        self.assertEqual(bsr.main(["--data-dir", str(self.d), "--baseline", str(base)]), 1)

    # --- обратная сторона: объявленное исчезло -----------------------------------

    def test_a_declared_divergence_that_VANISHED_is_a_finding_too(self):
        """Чистая книга при НЕПУСТОМ объявлении — не «сходится», а расхождение состава.

        Иначе прибор, направленный на ДРУГОЙ каталог (например на git-замороженный
        канон `data/` с 7 ходами вместо живых 34), отвечал бы «сходится» — ровно тот
        дефект, который называли девять циклов подряд.
        """
        self.write([_trade("T1", {}, {"a": 100.0})], {"positions": {"a": 100.0}})
        base = _declare(self.d, [_row("T008", "money_gap", 94999.88, 80000.0, ["x"], [])])
        self.assertEqual(bsr.main(["--data-dir", str(self.d), "--baseline", str(base)]), 3)
        doc = json.loads((self.d / bsr.ARTIFACT).read_text(encoding="utf-8"))
        self.assertEqual([b["trade_id"] for b in doc["vanished_declared"]], ["T008"])
        self.assertEqual(doc["new_breaks"], [])

    def test_a_terminal_divergence_ALONE_diverges_from_the_declaration(self):
        """Расхождение конца САМО по себе меняет вердикт — цепь при этом непрерывна.

        Объявление ПУСТО намеренно: иначе вердикт сцены несла бы пропавшая строка, а
        не конец книги, и мутант «конец не считается расхождением» прошёл бы её живым
        (так и случилось у первой редакции этого класса — дыра сцены найдена мутацией
        M8 и закрыта здесь).
        """
        self.write([_trade("T1", {}, {"a": 100.0})], {"positions": {"a": 42.0}})
        rc = bsr.main(["--data-dir", str(self.d), "--baseline", str(_declare(self.d, []))])
        self.assertEqual(rc, 3)
        doc = json.loads((self.d / bsr.ARTIFACT).read_text(encoding="utf-8"))
        self.assertIs(doc["terminal_is_new"], True)
        self.assertEqual(doc["new_breaks"], [], "цепь ходов непрерывна — расходится КОНЕЦ")
        self.assertEqual(doc["vanished_declared"], [], "объявлять тут нечего")

    def test_the_END_of_the_book_cannot_be_declared_away(self):
        """Расхождение КОНЦА объявлению не подлежит по построению.

        Оно про СЕГОДНЯШНЮЮ книгу, а не про историю: объявить его значило бы
        согласиться жить с разошедшейся книгой. Сцена кладёт его в объявление
        ОДНОЙ формой и требует, чтобы это не помогло.
        """
        self.write([_trade("T1", {}, {"a": 100.0})], {"positions": {"a": 42.0}})
        base = _declare(self.d, [_row("T1", "terminal", 100.0, 42.0, ["a"], ["a"])])
        self.assertEqual(bsr.main(["--data-dir", str(self.d), "--baseline", str(base)]), 3)
        doc = json.loads((self.d / bsr.ARTIFACT).read_text(encoding="utf-8"))
        self.assertIs(doc["terminal_is_new"], True)

    # --- третий исход у самого объявления (инв. #17) ------------------------------

    def test_a_MISSING_declaration_is_not_measured_not_silence(self):
        """Fail-CLOSED. Подстановка «перечня нет ⇒ всё знакомо» вернула бы слепоту
        ТИШЕ красного вердикта, подстановка «всё новое» кричала бы о неизмеренном."""
        self.write([_trade("T1", {}, {"a": 100.0}), _trade("T2", {"a": 90.0}, {"b": 90.0})],
                   {"positions": {"b": 90.0}})
        rc = bsr.main(["--data-dir", str(self.d),
                       "--baseline", str(self.d / "нет-такого.json")])
        self.assertEqual(rc, 2)
        doc = json.loads((self.d / bsr.ARTIFACT).read_text(encoding="utf-8"))
        self.assertEqual(doc["status"], "unmeasured")
        self.assertIn("объявления", doc["reason"])

    def test_an_UNPARSABLE_declaration_is_not_measured(self):
        self.write([_trade("T1", {}, {"a": 100.0})])
        bad = self.d / "bad.json"
        bad.write_text("{не json", encoding="utf-8")
        self.assertEqual(bsr.main(["--data-dir", str(self.d), "--baseline", str(bad)]), 2)

    def test_a_declaration_without_the_list_is_not_measured(self):
        self.write([_trade("T1", {}, {"a": 100.0})])
        bad = self.d / "noList.json"
        bad.write_text('{"required_fields": ["trade_id"]}', encoding="utf-8")
        self.assertEqual(bsr.main(["--data-dir", str(self.d), "--baseline", str(bad)]), 2)

    def test_a_declared_row_missing_a_required_field_REFUSES(self):
        """Объявление обязано нести СВОЙ контракт.

        Полуобъявленная строка — худший из исходов: она прощает расхождение, не
        сказав о нём ничего. Поэтому недостача поля — отказ с НАЗВАННЫМ полем, а не
        молчаливое принятие.
        """
        self.write([_trade("T1", {}, {"a": 100.0}), _trade("T2", {"a": 90.0}, {"b": 90.0})],
                   {"positions": {"b": 90.0}})
        row = _row("T2", "money_gap", 100.0, 90.0, [], [])
        row.pop("reason")
        base = _declare(self.d, [row])
        self.assertEqual(bsr.main(["--data-dir", str(self.d), "--baseline", str(base)]), 2)
        with self.assertRaises(bsr.NotMeasured) as ctx:
            bsr.load_declared(base)
        self.assertIn("reason", str(ctx.exception))

    def test_a_row_that_is_not_an_object_REFUSES(self):
        self.write([_trade("T1", {}, {"a": 100.0})])
        bad = self.d / "rowNotObj.json"
        bad.write_text('{"declared": ["T008"]}', encoding="utf-8")
        with self.assertRaises(bsr.NotMeasured):
            bsr.load_declared(bad)

    def test_the_contract_is_read_FROM_the_declaration(self):
        """Перечень обязательных полей берётся у самого объявления, а литерал — запас.

        Иначе контракт жил бы в ДВУХ местах, и расхождение между ними прощало бы
        строку, которую одна из копий считает полной.
        """
        self.write([_trade("T1", {}, {"a": 100.0}), _trade("T2", {"a": 90.0}, {"b": 90.0})],
                   {"positions": {"b": 90.0}})
        row = _row("T2", "money_gap", 100.0, 90.0, [], [])
        row["why_here"] = "своё имя поля причины"
        row.pop("reason")
        base = _declare(self.d, [row],
                        required=["trade_id", "kind", "sum_before", "sum_after",
                                  "keys_only_before", "keys_only_after", "why_here"])
        self.assertEqual(bsr.main(["--data-dir", str(self.d), "--baseline", str(base)]), 1)

    # --- выбор объявления ПЕЧАТАЕТСЯ ---------------------------------------------

    def test_the_declaration_in_use_is_PRINTED_including_the_default(self):
        """Читатель обязан узнать, С ЧЕМ сверяли. Умолчание печатается так же, как вход."""
        import contextlib, io
        self.write([_trade("T1", {}, {"a": 100.0})], {"positions": {"a": 100.0}})
        base = _declare(self.d, [])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            bsr.main(["--data-dir", str(self.d), "--baseline", str(base)])
        out = buf.getvalue()
        self.assertIn("объявление:", out)
        self.assertIn("НАЗВАНО входом", out)
        self.assertIn(base.name, out)

    def test_the_live_declaration_of_the_repo_satisfies_its_own_contract(self):
        """Боевой перечень обязан быть читаем ЭТИМ прибором, иначе шаг 1д даст код 2.

        Это единственный тест класса, который трогает файл дерева — и трогает он
        ОБЪЯВЛЕНИЕ, а не живой `data/`: состав книги здесь не судится ничем.
        """
        d = bsr.load_declared()
        self.assertTrue(d["rows"], "боевое объявление пусто — два исторических расхождения названы в ADR-1033")
        self.assertIn("book_second_record_baseline.json", d["source"])
        for ident, row in d["rows"].items():
            self.assertTrue(str(row["reason"]).strip(),
                            f"строка {ident[0]} объявлена без причины — тогда её нечем снять")


if __name__ == "__main__":
    unittest.main()
