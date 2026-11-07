"""Оси `empty` и `other` переписи перечней — ДВЕ ПОЛОВИНЫ ОДНОГО ВОПРОСА.

Предмет (ADR-943, цикл #1062). Отчёт `declared_collection_census` печатает четыре
оси подряд, и строка «ось empty: asked 296» читается как «296 перечней защищены».
На этом основании заказ G932 п. 3 попросил расширить `EMPTINESS_CALLS` методами
проверочных библиотек (`self.assertTrue(NAME)` и родня числятся родом `other`).
Замер цикла #1062 ответил: население такого расширения 1186 мест, а предмет при
нём 571 -> 571 — покупка РОВНО НОЛЬ. Причина не в выборе метода, а в СТРОЕНИИ
предмета: опасная сторона `empty` — «чтений рода `emptiness` нет», опасная
сторона `other` — «чтений рода `other` нет», роды замкнуты и исчерпывают всё, что
не итерация, поэтому конъюнкция говорит ровно одно — «все чтения суть итерация».

Утверждение проверяется ДВУМЯ КРАЙНОСТЯМИ на сцене, а не рассуждением:
  A — прибор как есть · B — ВСЁ `other` объявлено `emptiness` · C — наоборот.
Совпадение предмета у всех трёх и есть доказательство.

Контроль в ОБРАТНУЮ сторону обязателен (`.claude/rules/acceptance.md` п. 3): при
`SUBJECT_AXES`, сделанном ПО-НАСТОЯЩЕМУ независимым, те же крайности обязаны
РАЗОЙТИСЬ — иначе тест не умеет видеть поломку и является украшением.

Сцена — одноразовое дерево; живое `data/` и трекер не трогаются ни одним байтом.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import declared_collection_census as dcc

#: Сцена. Три перечня, по одному на каждый исход, который нас интересует:
#: читаемый ТОЛЬКО итерацией (предмет) · итерация + вопрос о непустоте ·
#: итерация + чтение рода `other`. Без всех трёх замер был бы ПУСТЫМ и тест
#: проходил бы ни о чём — поэтому непустота сцены проверяется отдельно и ГРОМКО.
SCENE = '''\
LOOP_ONLY = ["a"]
WITH_EMPTINESS = ["b"]
WITH_OTHER = ["c"]


def walk():
    for item in LOOP_ONLY:
        print(item)
    for item in WITH_EMPTINESS:
        print(item)
    if len(WITH_EMPTINESS):
        print("not empty")
    for item in WITH_OTHER:
        print(item)
    return WITH_OTHER[0]
'''


def _swap(original, frm: str, to: str):
    """Классификатор, объявляющий род `frm` родом `to`. Крайность — ВХОД."""
    def classify(node, index):
        kind = original(node, index)
        return to if kind == frm else kind
    return classify


class ReadKindAxisRedundancy(unittest.TestCase):

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="spa_kind_axis_"))
        pkg = self.root / "spa_core"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "scene_mod.py").write_text(SCENE)
        self.addCleanup(shutil.rmtree, self.root, True)
        self._classify = dcc._classify_read
        self.addCleanup(lambda: setattr(dcc, "_classify_read", self._classify))

    def _census(self):
        return dcc.census(self.root, declaration_roots=("spa_core",),
                          reader_roots=("spa_core",))

    def _verdict(self):
        res = self._census()
        return (res["surface"], res["subject"], res["not_excluded"])

    # --- предпосылка: сцена НЕПУСТА, и это измеряется, а не предполагается ----

    def test_scene_exercises_every_kind_it_claims_to(self):
        """Сцена, не предъявившая всех трёх родов, не доказывает НИЧЕГО.

        Тест обязан падать ГРОМКО, а не проходить над пустым замером: это тот же
        третий исход, что у `pyflakes` в `.claude/rules/deployment.md`.
        """
        res = self._census()
        self.assertEqual(res["surface"], 3, "сцена объявляет РОВНО три перечня")
        self.assertEqual(
            res["by_axis"]["empty"]["asked"], 1,
            "вопрос о непустоте в сцене обязан быть РОВНО у одного перечня")
        self.assertEqual(
            res["by_axis"]["other"]["other_reads"], 1,
            "чтение рода `other` в сцене обязано быть РОВНО у одного перечня")
        self.assertEqual(
            res["subject"], 1,
            "предметом в сцене обязан быть РОВНО перечень, читаемый только итерацией")
        self.assertFalse(res["unmeasured"], "сцена обязана быть прочитана целиком")

    # --- само утверждение: две крайности ------------------------------------

    def test_subject_is_unchanged_by_both_extremes(self):
        baseline = self._verdict()

        dcc._classify_read = _swap(self._classify, "other", "emptiness")
        all_emptiness = self._verdict()

        dcc._classify_read = _swap(self._classify, "emptiness", "other")
        all_other = self._verdict()

        self.assertEqual(
            baseline, all_emptiness,
            "предмет изменился, когда ВСЁ `other` объявили `emptiness` — "
            "утверждение об избыточности осей ОПРОВЕРГНУТО")
        self.assertEqual(
            baseline, all_other,
            "предмет изменился, когда ВСЁ `emptiness` объявили `other` — "
            "утверждение об избыточности осей ОПРОВЕРГНУТО")

        dcc._classify_read = self._classify
        self.assertEqual(
            baseline, self._verdict(),
            "подмена не снята — замер НЕ ИЗМЕРЕН, а не подтверждён")

    # --- контроль в ОБРАТНУЮ сторону ----------------------------------------

    def test_the_proof_goes_red_when_the_axes_are_truly_independent(self):
        """Положительный контроль: сделай оси независимыми — крайности разойдутся.

        Опасная сторона `other` переставляется на `other_reads`, то есть ось
        начинает спрашивать СВОЙ вопрос, а не половину общего. Если крайности и
        при этом совпадут, тест выше ничего не доказывает.
        """
        original_axes = dict(dcc.SUBJECT_AXES)
        self.addCleanup(lambda: dcc.SUBJECT_AXES.update(original_axes))
        try:
            dcc.SUBJECT_AXES["other"] = "other_reads"
            baseline = self._verdict()
            dcc._classify_read = _swap(self._classify, "other", "emptiness")
            all_emptiness = self._verdict()
            self.assertNotEqual(
                baseline, all_emptiness,
                "крайности совпали даже у НЕЗАВИСИМЫХ осей — значит доказательство "
                "выше слепо и поломку увидеть не способно")
        finally:
            dcc._classify_read = self._classify
            dcc.SUBJECT_AXES.clear()
            dcc.SUBJECT_AXES.update(original_axes)

    # --- почему избыточность следует из ЗАМКНУТОСТИ перечня родов ------------

    def test_non_loop_kinds_exhaust_the_closed_list(self):
        """Избыточность держится на том, что роды ЗАМКНУТЫ и исчерпывают остаток.

        Появись четвёртый род, не попавший ни в одну ось, конъюнкция перестала бы
        означать «все чтения суть итерация» — и утверждение выше потребовало бы
        ПЕРЕМЕРА, а не правки. Поэтому вывод сверяется с перечнем, а не
        переписывается руками.
        """
        self.assertEqual(
            {"loop", *dcc.NON_LOOP_KINDS}, set(dcc.READ_KINDS),
            "NON_LOOP_KINDS + `loop` обязаны исчерпывать READ_KINDS")
        self.assertNotIn("loop", dcc.NON_LOOP_KINDS)
        for kind in dcc.NON_LOOP_KINDS:
            self.assertIn(
                kind, {"emptiness", "other"},
                f"род {kind!r} не покрыт ни одной осью SUBJECT_AXES — "
                "утверждение об избыточности требует ПЕРЕМЕРА")

    # --- отчёт обязан говорить это САМ --------------------------------------

    def test_the_report_says_it_out_loud(self):
        """Умолчание и есть предмет: заказ G932 п. 3 родился из чтения отчёта."""
        text = dcc.report(self._census())
        self.assertIn(dcc.KIND_AXES_ARE_REDUNDANT, text)


if __name__ == "__main__":
    unittest.main()
