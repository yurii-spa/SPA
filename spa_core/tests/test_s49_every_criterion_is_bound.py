"""Храповик: у КАЖДОГО критерия §49 приёмки объявлена мера с тактом.

Это положительный контроль исхода **ADR-811** (цикл #934, заказ G810 п. 2): в
тот день `Architecture` был ПОСЛЕДНИМ критерием, у которого привязки не было
вовсе, и замер звучал так — `bound 12 · bound_without_slo 0 · unbound 1`. После
проводки писателя и объявления артефакта `data/cio_decision_owner.json` счёт стал
**13 · 0 · 0**.

## Зачем это сторожу, если привязка уже стои́т

Привязка держится **формой строки в `notes` конституции**, и форма эта хрупкая:
разбор (`s49_criterion_price.parse_bindings`) считает кандидатом КАЖДОЕ вхождение
`§49` в заметку, и вхождение, не подошедшее ни к одной объявленной формулировке,
уводит критерий в `unparsed` — то есть в НЕ ИЗМЕРЕНО. Это не теория: первая
редакция заметки ADR-811 упоминала раздел приёмки ЧЕТЫРЕ раза в прозе и дала
**три `unparsed` вместо одной привязки** — критерий остался `unbound`, а запись в
манифесте при этом выглядела сделанной.

Поэтому переписать заметку и молча расстроить привязку может любая правка
конституции, не трогая ни строки кода. Храповик ловит ровно это.

## Население НЕ ведётся руками (урок `test_cio_acceptance_guards_are_wired`)

Список критериев берётся из живого реестра проб
(`card_acceptance.probes_by_s49_criterion`) — того же, которым пользуется сама
сводка, — а не из перечня рядом. Сторож, чьё население ведут руками, отказывает
ровно тогда, когда кто-то забыл дописать, а забыть и есть предмет сторожа.

Вердикт считает НАСТОЯЩИЙ прибор (`s49_tally_tact.tact_floor`): второй копии
правила «что считается привязкой» здесь нет (ADR-220).

Времени, pid и живого ``data/`` здесь нет: предмет — конституция и реестр.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from spa_core.monitoring import s49_tally_tact as tact
from spa_core.monitoring.card_acceptance import probes_by_s49_criterion

REPO = Path(__file__).resolve().parents[2]


class EveryCriterionIsBound(unittest.TestCase):
    """Живая конституция: критериев без объявленной меры быть не должно."""

    def setUp(self):
        self.criteria = sorted(probes_by_s49_criterion())
        self.floor = tact.tact_floor(self.criteria, repo_root=str(REPO))
        self.rows = {r["criterion"]: r for r in self.floor["rows"]}

    def test_the_population_is_not_empty(self):
        """Пустое население прошло бы все проверки ниже по своей слепоте."""
        self.assertGreaterEqual(
            len(self.criteria), 13,
            "реестр проб §49 отдал меньше критериев, чем их было 25.10 — "
            "сторож судит не о том населении")

    def test_no_criterion_is_UNBOUND(self):
        unbound = sorted(c for c, r in self.rows.items()
                         if r["state"] == tact.TACT_UNBOUND)
        self.assertEqual(
            [], unbound,
            "у критерия §49 не объявлено мерой НИ ОДНОГО артефакта конституции — "
            f"такт его входа взять неоткуда: {unbound}. Это состояние ADR-811 "
            "закрыл замером 13 · 0 · 0; дописывать исключение сюда ЗАПРЕЩЕНО "
            "(инв. #16) — объявить привязку канонической формой в `notes`")

    def test_no_binding_is_left_WITHOUT_a_declared_slo(self):
        """Привязка без числа — свой исход, и он тоже не «измерено»."""
        no_slo = sorted(c for c, r in self.rows.items()
                        if r["state"] == tact.TACT_BOUND_WITHOUT_SLO)
        self.assertEqual([], no_slo,
                         f"привязка есть, а `slo_hours` при ней нет: {no_slo}")

    def test_the_subject_of_ADR_811_is_bound_by_name(self):
        """Повод храповика — поимённо, иначе сцена потеряет предмет молча."""
        row = self.rows.get("Architecture")
        self.assertIsNotNone(row, "критерий `Architecture` ушёл из реестра проб")
        self.assertEqual(tact.TACT_BOUND, row["state"])
        self.assertEqual("data/cio_decision_owner.json", row["artifact"])
        self.assertEqual(7.0, row["slo_hours"])


class TheRatchetItself(unittest.TestCase):
    """Контроль в ОБЕ стороны: сторож, который не умеет краснеть, — украшение."""

    def _manifest(self, notes: str) -> Path:
        import tempfile
        root = Path(tempfile.mkdtemp(prefix="c934_binding_"))
        (root / "architecture").mkdir()
        (root / "architecture" / "manifest.json").write_text(json.dumps(
            {"artifacts": [{"path": "data/subject.json", "slo_hours": 7,
                            "status": "active", "notes": notes}],
             "agents": []}, ensure_ascii=False), encoding="utf-8")
        return root

    CANON = "§49 `Architecture` приказа владельца «Portfolio CIO» — мера критерия."

    def test_the_canonical_form_binds(self):
        rows = tact.tact_floor(["Architecture"],
                               repo_root=str(self._manifest(self.CANON)))["rows"]
        self.assertEqual(tact.TACT_BOUND, rows[0]["state"])

    def test_PROSE_mentioning_the_section_does_NOT_bind(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: дословная ошибка первой редакции ADR-811."""
        prose = ("Критерий §49 ТЗ «Portfolio CIO» дословно: «Architecture. "
                 "Portfolio-level decision owner существует».")
        with self.assertRaises(tact.Unmeasured):
            # пола нет вовсе: ни одной привязки с числом — прибор ОТКАЗЫВАЕТ,
            # а не объявляет пол нулевым
            tact.tact_floor(["Architecture"],
                            repo_root=str(self._manifest(prose)))

    def test_a_second_unparseable_mention_does_not_cancel_a_good_binding(self):
        """Граница названа: разбор берёт ПЕРВОЕ подошедшее вхождение.

        Сцена существует, чтобы утверждение сторожа не было шире измеренного:
        он требует, чтобы привязка НАШЛАСЬ, а не чтобы прозы рядом не было.
        """
        mixed = self.CANON + " Далее сводка §49 докладывала unbound."
        rows = tact.tact_floor(["Architecture"],
                               repo_root=str(self._manifest(mixed)))["rows"]
        self.assertEqual(tact.TACT_BOUND, rows[0]["state"])

    def test_a_criterion_absent_from_the_manifest_is_UNBOUND(self):
        rows = tact.tact_floor(["Architecture", "Nonesuch"],
                               repo_root=str(self._manifest(self.CANON)))["rows"]
        states = {r["criterion"]: r["state"] for r in rows}
        self.assertEqual(tact.TACT_UNBOUND, states["Nonesuch"])
        self.assertEqual(tact.TACT_BOUND, states["Architecture"])


if __name__ == "__main__":
    unittest.main()
