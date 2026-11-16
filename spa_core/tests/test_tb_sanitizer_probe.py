# LLM_FORBIDDEN
"""Контроль пробы `tb_sanitizer_sees_the_report_excinfo` (ADR-1036, цикл #1175).

Проба объявлена критерием карточки `inbox-sessiya-pytest-umerla-iznutri-na-sharde`.
Предмет карточки — обморок САМОЙ сессии `pytest` (`exit 3`): `_pytest/_code/code.py:214`
считает `self._rawentry.tb_lineno - 1`, а у звена, где SIGALRM застал кадр без номера
строки, `tb_lineno is None`. Санитар трассы ADR-768 для этого и писался — и у
`unittest`-тестов НЕ РАБОТАЛ: `_pytest/unittest.py::pytest_runtest_makereport`
подставляет `call.excinfo = item._excinfo.pop(0)` ПОСЛЕ нашей обёртки `tryfirst`.

**Почему проба мерит проводку, а не `error == 0`.** Критерий, записанный в карточке
(«в следующем прогоне `error` вернулось к 0»), был выполнен 16.11 прогоном
`43952453112` БЕЗ правок кода: род стенных часов ротируется между шардами, и обморок
просто не попал туда же. Проба на таком числе объявила бы работу сделанной за счёт
удачи — поэтому мерится ОСМОТР объекта, из которого собирается отчёт.

ЧЕТЫРЕ сцены, и каждая отличается РОВНО одним звеном:

1. **весь контур** (настоящее дерево) ⇒ `satisfied`;
2. **снят осмотр очереди `unittest`** — ровно форма прежней редакции ⇒
   `not_satisfied`, и это же контроль «проба не проходит ПОДСТРОКОЙ»: в сцене есть и
   `sanitize_excinfo`, и `_unittest_queue`, и весь абзац про безномерные звенья;
   нет только самого ОСМОТРА. (Подлинные байты `origin/main` дали тот же вердикт —
   дифференциальный замер цикла #1175, ADR-1036.)
3. **санитар не зовётся вовсе** ⇒ `unmeasured` со СВОИМИ словами («сломан шпион
   сцены»), а не `not_satisfied`: «обе формы не осмотрены» и «осмотрена одна из
   двух» чинятся разным;
4. **плагина в дереве нет** ⇒ `unmeasured` с названной причиной.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import card_acceptance as ca

_PROBE = "tb_sanitizer_sees_the_report_excinfo"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLUGIN_REL = Path("spa_core") / "ci" / "pytest_stream_record.py"


def _fake_tree(plugin_source: str | None) -> Path:
    """Одноразовое дерево с ОДНИМ модулем: больше пробе и не нужно.

    Копировать настоящее дерево было бы и дорого, и неверно — сцена обязана
    отличаться от соседней РОВНО одним звеном, а не всем содержимым.
    """
    root = Path(tempfile.mkdtemp(prefix="tb_probe_scene_"))
    (root / "spa_core" / "ci").mkdir(parents=True)
    (root / "spa_core" / "__init__.py").write_text("", encoding="utf-8")
    (root / "spa_core" / "ci" / "__init__.py").write_text("", encoding="utf-8")
    if plugin_source is not None:
        (root / _PLUGIN_REL).write_text(plugin_source, encoding="utf-8")
    return root


def _plugin_source() -> str:
    return (_REPO_ROOT / _PLUGIN_REL).read_text(encoding="utf-8")


def _with_one_link_cut(anchor: str, replacement: str) -> str:
    """Сцена отличается от контура РОВНО одним звеном — и якорь обязан существовать.

    Форма прежней редакции воспроизводится СНЯТИЕМ звена, а не «похожим» кодом:
    якорь берётся из живого исходника, и его исчезновение краснит сцену, а не
    молча превращает её в украшение (урок заказа G1024 п. 6).
    """
    source = _plugin_source()
    assert anchor in source, f"якорь сцены исчез: {anchor!r}"
    return source.replace(anchor, replacement, 1)


class TbSanitizerProbeDiscriminates(unittest.TestCase):

    def test_the_whole_contour_is_satisfied(self):
        verdict, detail = ca.PROBES[_PROBE](None, repo_root=str(_REPO_ROOT))
        self.assertEqual(ca.SATISFIED, verdict, detail)
        self.assertIn("очередь", detail, "вердикт не называет, ЧТО осмотрено")

    def test_the_unittest_queue_cut_out_is_refused_and_not_by_substring(self):
        """Снято ОДНО звено — осмотр очереди `unittest`; это и есть прежняя редакция."""
        source = _with_one_link_cut(
            'for candidate in (getattr(call, "excinfo", None), *_unittest_queue(item)):',
            'for candidate in (getattr(call, "excinfo", None),):')
        # Предпосылка сцены: слова на месте — значит отказ пробы будет НЕ о словах.
        self.assertIn("sanitize_excinfo", source)
        self.assertIn("tb_lineno", source)
        self.assertIn("_unittest_queue", source)
        root = _fake_tree(source)
        try:
            verdict, detail = ca.PROBES[_PROBE](None, repo_root=str(root))
        finally:
            shutil.rmtree(root, ignore_errors=True)
        self.assertEqual(ca.NOT_SATISFIED, verdict, detail)
        self.assertIn("unittest", detail)

    def test_a_sanitizer_that_is_never_called_is_unmeasured_not_refused(self):
        broken = _with_one_link_cut(
            "        for excinfo in excinfos_awaiting_report(item, call):",
            "        for excinfo in ():")
        root = _fake_tree(broken)
        try:
            verdict, detail = ca.PROBES[_PROBE](None, repo_root=str(root))
        finally:
            shutil.rmtree(root, ignore_errors=True)
        self.assertEqual(ca.UNMEASURED, verdict, detail)
        self.assertIn("шпион", detail,
                      "проба обязана назвать сломанную СЦЕНУ, а не обвинить предмет")

    def test_an_absent_plugin_is_a_named_third_outcome(self):
        root = _fake_tree(None)
        try:
            verdict, detail = ca.PROBES[_PROBE](None, repo_root=str(root))
        finally:
            shutil.rmtree(root, ignore_errors=True)
        self.assertEqual(ca.UNMEASURED, verdict, detail)
        self.assertIn("НЕ ИЗМЕРЕНО", detail)
        self.assertIn(str(root), detail, "причина не называет путь, которого нет")

    def test_the_probe_is_registered_under_the_name_the_card_declares(self):
        self.assertIn(_PROBE, ca.PROBES)
        card = (_REPO_ROOT / "nimbalyst-local" / "tracker"
                / "inbox-sessiya-pytest-umerla-iznutri-na-sharde.md")
        self.assertTrue(card.exists(), f"карточка не найдена: {card}")
        self.assertIn(f"acceptance_probe: {_PROBE}",
                      card.read_text(encoding="utf-8"),
                      "карточка объявляет ДРУГУЮ пробу — критерий и работа разошлись")


if __name__ == "__main__":                                       # pragma: no cover
    unittest.main()
