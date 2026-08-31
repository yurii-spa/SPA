"""Цена ошибки инструмента, которым собираются списывать модули.

ЗАЧЕМ ЭТОТ ФАЙЛ. ADR-190 записал: «второй, более строгий инструмент подтвердил
BLIND у 71 из 82». Сила улики там названа честно — «подтверждение на другом
ВХОДЕ, не независимый метод». Не названа ВЕЛИЧИНА: сколько раз этот инструмент
говорит BLIND про модуль, который протокол читает. Решение о списании 71
готовилось так, как если бы она была нулевой. Замер 2026-08-31: **9 из 115 = 7,8 %**.

ГРАНИЦА. Файл не объявляет второй инструмент сломанным. Инструменты кормят модуль
разными входами, и разные числа законны. Проверяется ровно одно утверждение:
вердикт `BLIND` второго инструмента НЕ УСТАНАВЛИВАЕТ, что модуль не читает
протокол в проде.

КОНТРОЛИ. К каждому положительному контролю есть обратный: проверка, которая
краснеет всегда, стоит столько же, сколько зелёная всегда.
"""
import importlib.util
import os
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SPEC = importlib.util.spec_from_file_location(
    "audit_instrument_error_rate",
    os.path.join(_ROOT, "scripts", "audit_instrument_error_rate.py"))
aier = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(aier)


def blind_entry(module, cls, scores):
    """Запись отчёта о слепоте: имя → классификация → score по тройке."""
    return {"module": module, "classification": cls,
            "runs": {p: {"score": s} for p, s in zip(aier.TRIO, scores)}}


def feas_entry(module, verdict):
    return {"module": module, "verdict": verdict}


class InstrumentErrorRateTest(unittest.TestCase):

    # ---------- эталон строится честно ----------

    def test_protocol_reading_module_called_blind_is_counted(self):
        """Ядро: модуль различает протоколы, второй инструмент зовёт его BLIND."""
        rep = aier.measure(
            [blind_entry("m_reads", "sensitive", [10.0, 20.0, 30.0])],
            [feas_entry("m_reads", "BLIND")])
        self.assertEqual(rep["false_blind"], ["m_reads"])
        self.assertEqual(rep["reference_size"], 1)
        self.assertAlmostEqual(rep["false_blind_rate"], 1.0)

    def test_wide_ok_module_is_not_counted_as_false_blind(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ подтасовки в свою пользу.

        `blind_equal_wide_ok` равен на тройке ПО ПОСТРОЕНИЮ — он различает
        только на широкой вселенной, которой второй инструмент не видит.
        Засчитать ему BLIND как ошибку значило бы раздуть обвинение.

        Ось изолирована НАРОЧНО. Первая версия давала wide_ok равные числа
        [7, 7, 7] — и проходила бы даже БЕЗ исключения wide_ok: такой модуль
        отсеяло бы СОСЕДНЕЕ условие, порог шума float, и мутация «эталон
        впускает wide_ok» оставалась зелёной. Здесь число-против-None: порог
        шума на таком случае молчит, красит ровно отсутствие исключения.
        """
        rep = aier.measure(
            [blind_entry("m_wide", "blind_equal_wide_ok", [7.0, None, None])],
            [feas_entry("m_wide", "BLIND")])
        self.assertEqual(rep["false_blind"], [])
        self.assertEqual(rep["reference_size"], 0)

    def test_float_noise_is_not_protocol_reading(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: 62.8 против 62.800000000000004 — не сигнал.

        Реальный случай: `defi_protocol_yield_after_tax_drag_analyzer` числится
        `sensitive` из-за разброса 7.1e-15. В эталон он входить не должен —
        иначе ложное обвинение второму инструменту.
        """
        rep = aier.measure(
            [blind_entry("m_noise", "sensitive",
                         [62.8, 62.800000000000004, 62.8])],
            [feas_entry("m_noise", "BLIND")])
        self.assertEqual(rep["false_blind"], [])
        self.assertEqual(rep["float_noise_in_first_instrument"], ["m_noise"])

    def test_number_versus_none_counts_as_reading_the_protocol(self):
        """Модуль, отвечающий на один протокол и молчащий на другом, читает его."""
        e = blind_entry("m_mixed", "sensitive", [25.0, None, None])
        rep = aier.measure([e], [feas_entry("m_mixed", "BLIND")])
        self.assertEqual(rep["false_blind"], ["m_mixed"])

    # ---------- контроль ловит плохой инструмент ----------

    def test_instrument_that_says_blind_to_everything_is_caught(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: инструмент-заглушка обязан дать 100 %."""
        ref = [blind_entry(f"m{i}", "sensitive", [1.0, 2.0, 3.0])
               for i in range(20)]
        rep = aier.measure(ref, [feas_entry(f"m{i}", "BLIND") for i in range(20)])
        self.assertAlmostEqual(rep["false_blind_rate"], 1.0)
        self.assertEqual(len(rep["false_blind"]), 20)

    def test_agreeing_instrument_scores_zero(self):
        """ОБРАТНЫЙ КОНТРОЛЬ: проверка, краснеющая всегда, ничего не проверяет."""
        ref = [blind_entry(f"m{i}", "sensitive", [1.0, 2.0, 3.0])
               for i in range(20)]
        rep = aier.measure(ref, [feas_entry(f"m{i}", "WIRABLE") for i in range(20)])
        self.assertEqual(rep["false_blind"], [])
        self.assertAlmostEqual(rep["false_blind_rate"], 0.0)

    def test_empty_reference_is_a_finding_not_a_clean_pass(self):
        """fail-CLOSED: пустой эталон обязан быть виден, а не выглядеть как 0 %."""
        rep = aier.measure([], [feas_entry("m", "BLIND")])
        self.assertEqual(rep["reference_size"], 0)
        self.assertIsNone(rep["false_blind_rate"])

    def test_reference_module_the_second_instrument_never_ran_is_named(self):
        """Не прогнанный эталонный модуль — не «согласие», он называется отдельно."""
        rep = aier.measure(
            [blind_entry("m_seen", "sensitive", [1.0, 2.0, 3.0]),
             blind_entry("m_unseen", "sensitive", [1.0, 2.0, 3.0])],
            [feas_entry("m_seen", "WIRABLE")])
        self.assertEqual(rep["reference_not_probed"], ["m_unseen"])
        self.assertEqual(rep["reference_size"], 1)


if __name__ == "__main__":
    unittest.main()
