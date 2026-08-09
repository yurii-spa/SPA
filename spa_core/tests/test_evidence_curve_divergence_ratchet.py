"""Храповик: расхождений между доказательной базой и кривой может стать только меньше.

Найдено 09.08 при разборе скриптов без вызывающего. Две записи об одних и тех же
деньгах спорят: `paper_evidence.json` (доказательная база, её читают проверки перед
выходом на живые деньги) и `equity_curve_daily.json` (основная кривая).

**Механизм — `own-32`:** кривую пишут ДВА пути. В обычный день оба дают одно число.
В день остановки её пишет `_write_equity`, беря предыдущее закрытие ИЗ САМОЙ КРИВОЙ,
а доказательная база в тот же день получает «вчера» ИЗ ОБЪЕКТА РЕЗУЛЬТАТА. Два «вчера»
из двух источников — вот и расхождение.

**Почему храповик, а не проверка равенства.** Равенство сегодня красное: 16 дат из 51.
Починка — money-path и ждёт решения владельца (`own-32`), а держать CI красным ради
известного дефекта значит приучить всех его игнорировать. Та же конструкция, что для
литеральных дат и для скриптов без вызывающего: база зафиксирована и может только
уменьшаться.

**Что этот храповик ловит уже сейчас:** появление НОВОЙ расходящейся даты. Между двумя
замерами (08.08 и 09.08) их стало 15 → 16, то есть дефект живой, а не исторический.
"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_BASELINE = Path(__file__).resolve().parent / "evidence_curve_divergence_baseline.json"
_EVIDENCE = _REPO / "data" / "paper_evidence.json"
_CURVE = _REPO / "data" / "equity_curve_daily.json"


def _divergent(tolerance: float) -> list:
    ev = json.loads(_EVIDENCE.read_text(encoding="utf-8"))
    cu = json.loads(_CURVE.read_text(encoding="utf-8"))
    a = {x["date"]: x.get("equity_value") for x in ev.get("days", []) if "date" in x}
    b = {x["date"]: x.get("close_equity") for x in (cu.get("daily") or []) if "date" in x}
    return sorted(k for k in set(a) & set(b)
                  if a[k] and b[k] and abs(a[k] - b[k]) > tolerance)


class TestDivergenceRatchet(unittest.TestCase):

    def setUp(self):
        # База построена по ЖИВОМУ треку. В CI `data/` — версия с origin, и она
        # отстаёт: замер 10.08 показал, что три августовских дня там ещё сходятся,
        # а на живом дереве уже разошлись. Прогон против отставших данных ответил
        # бы на другой вопрос — и первая версия этого теста именно так и уронила бы
        # CI (поймано ДО того, как покраснело, сверкой базы с origin).
        #
        # Поэтому проверка требует ЯВНОГО согласия: `SPA_LIVE_TRACK=1`. Это не
        # выключатель «чтобы не мешало» — без живого трека вопрос неразрешим, и
        # молчаливый зелёный был бы хуже пропуска.
        if os.environ.get("SPA_LIVE_TRACK") != "1":
            self.skipTest("нужен живой трек: запускать с SPA_LIVE_TRACK=1 из прод-дерева")

        from spa_core.monitoring.deployment_acceptance import measuring_from_worktree

        if measuring_from_worktree(_REPO):
            # В worktree `data/` — git-копия, а не живое состояние трека. Судить по
            # ней о расхождении нельзя: ответ будет про чужое дерево. Тот же капкан,
            # что ловит приёмка (правка 09.08) — здесь он ловит и меня самого:
            # первая версия этого теста упала именно на нём.
            self.skipTest("измерено из worktree — data/ здесь checkout, а не живой трек")
        if not (_EVIDENCE.is_file() and _CURVE.is_file()):
            # Живого трека в чистой копии нет — проверять нечего. Пропуск честнее
            # выдумывания данных: подставленные числа доказали бы только сами себя.
            self.skipTest("нет живых артефактов трека (обычно в CI)")
        self.doc = json.loads(_BASELINE.read_text(encoding="utf-8"))

    def test_no_NEW_divergent_day_appears(self):
        """Главное: завтрашний день обязан сойтись."""
        new = sorted(set(_divergent(self.doc["tolerance_usd"])) - set(self.doc["dates"]))
        self.assertEqual(new, [], (
            f"новые даты, где доказательная база разошлась с кривой: {new}. "
            "Механизм описан в own-32 (два писателя кривой). НЕ добавляй даты в базу, "
            "чтобы погасить падение."))

    def test_the_baseline_does_not_list_days_that_now_agree(self):
        """Половина, без которой храповик не храповик.

        Как только день сошёлся, он обязан уйти из базы — иначе она превратится
        в мусорный список и первая проверка перестанет что-либо значить.
        """
        stale = sorted(set(self.doc["dates"]) - set(_divergent(self.doc["tolerance_usd"])))
        self.assertEqual(stale, [], f"эти дни уже сходятся — удали их из базы: {stale}")

    def test_the_tolerance_is_not_quietly_widened(self):
        """Допуск — это определение слова «сошлось». Расширить его тихо = погасить сигнал."""
        self.assertLessEqual(self.doc["tolerance_usd"], 0.01,
                             "допуск больше цента означал бы новое определение согласия")


if __name__ == "__main__":
    unittest.main()
