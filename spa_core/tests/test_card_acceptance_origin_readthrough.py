"""Сторож приёмки карточек не выдаёт «прочитано столько» за «столько и есть».

Карточка `inbox-storozh-priemki-kartochek-chitaet-tolko`, цикл #467.

**Предмет.** `card_acceptance.audit()` (ADR-208) читал ТОЛЬКО каталог того дерева, в
котором запущен. Обязательный шаг 0-офис ходит из ПРОД-дерева, а `nimbalyst-local/`
туда не синхронизируется. Замер 03.09: в проде 599 карточек, на `origin/main` — 882;
283 сторож не видел ВООБЩЕ и о слепоте не говорил ни строкой. Живое следствие: из пяти
объявленных на origin проб прод-дерево видело ОДНУ — механизм ADR-209 работал, а до
места, где принимается решение, не доезжал. Тот же класс уже чинили в очереди (ADR-153).

**Герметичность.** Все проверки идут по СВОЕМУ временному репозиторию: в worktree от
`origin/main` все карточки лежат локально, поэтому дочитывание там не находит ничего —
зелёный прогон против живого репозитория был бы ВАКУУМНЫМ и не отличал бы «работает»
от «предмета нет». Живой репозиторий тут не читается ни разу.

**Времени в тестах нет.** Пробы подменяются реестром: предмет — популяция, а не то,
что показывает конкретная проба.
"""
import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "_card_acceptance_under_test",
    _ROOT / "spa_core" / "monitoring" / "card_acceptance.py")
ca = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ca)

CARD = """---
trackerStatus:
  type: inbox
title: {title}
status: {status}
acceptance_probe: {probe}
---

тело карточки
"""


def _git(repo, *args):
    subprocess.run(["git", "-C", repo] + list(args), check=True,
                   capture_output=True, text=True)


class Fixture:
    """Репозиторий с веткой `origin/main` и рабочим деревом, где карточек МЕНЬШЕ."""

    def __init__(self, on_ref: dict, in_tree: dict):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = self.tmp.name
        self.tracker = os.path.join(self.repo, "nimbalyst-local", "tracker")
        os.makedirs(self.tracker)
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "config", "user.email", "t@t")
        _git(self.repo, "config", "user.name", "t")
        for name, body in on_ref.items():
            Path(self.tracker, name).write_text(body, encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "ref")
        # ветка доставки, затем дерево ОБЕДНЯЕТСЯ — как прод, куда карточки не возят
        _git(self.repo, "branch", "-f", "origin/main", "main")
        for name in on_ref:
            if name not in in_tree:
                os.remove(os.path.join(self.tracker, name))
        for name, body in in_tree.items():
            Path(self.tracker, name).write_text(body, encoding="utf-8")

    def audit(self, **kw):
        return ca.audit(self.tracker, repo_root=self.repo, **kw)

    def close(self):
        self.tmp.cleanup()


class InvisibleCardsAreReadFromTheRef(unittest.TestCase):
    """ПРЯМОЙ контроль — ровно та слепота, ради которой карточка заведена."""

    def setUp(self):
        self.fx = Fixture(
            on_ref={
                "a-here.md": CARD.format(title="есть в дереве", status="new",
                                         probe="contract_manifest_parity"),
                "b-invisible.md": CARD.format(title="дереву невидима", status="new",
                                              probe="contract_manifest_parity"),
            },
            in_tree={"a-here.md": CARD.format(title="есть в дереве", status="new",
                                              probe="contract_manifest_parity")})
        self.addCleanup(self.fx.close)

    def test_without_readthrough_the_invisible_card_is_missing(self):
        """Состояние ДО правки — фиксируем его же как контроль."""
        res = self.fx.audit(origin_readthrough=False)
        self.assertEqual({r["card"] for r in res["rows"]}, {"a-here"})
        self.assertEqual(res["origin"]["state"], "off")

    def test_with_readthrough_the_invisible_card_enters_the_population(self):
        res = self.fx.audit()
        self.assertEqual({r["card"] for r in res["rows"]}, {"a-here", "b-invisible"})
        self.assertEqual(res["origin"]["state"], "read")
        self.assertEqual(res["origin"]["read"], 1)

    def test_the_report_names_the_readthrough_and_the_provenance(self):
        lines = "\n".join(ca.report_lines(self.fx.audit()))
        self.assertIn("дочитана с `origin/main`", lines)
        row = next(r for r in self.fx.audit()["rows"] if r["card"] == "b-invisible")
        self.assertTrue(row["from_origin"],
                        "карточка без файла в дереве не помечена — строка читается "
                        "как «файл рядом, посмотри»")

    def test_a_card_present_locally_is_not_counted_twice(self):
        res = self.fx.audit()
        self.assertEqual(len([r for r in res["rows"] if r["card"] == "a-here"]), 1)
        self.assertFalse(next(r for r in res["rows"]
                              if r["card"] == "a-here")["from_origin"])


class NothingInvisibleIsSilence(unittest.TestCase):
    """ОБРАТНЫЙ контроль: без него «нечего добирать» = «добирать разучились»."""

    def test_a_complete_tree_produces_no_readthrough_line(self):
        card = CARD.format(title="одна", status="new", probe="contract_manifest_parity")
        fx = Fixture(on_ref={"a.md": card}, in_tree={"a.md": card})
        self.addCleanup(fx.close)
        res = fx.audit()
        self.assertEqual(res["origin"]["read"], 0)
        self.assertNotIn("дочитана с", "\n".join(ca.report_lines(res)))


class UnreadablePopulationIsRefusedLoudly(unittest.TestCase):
    """Дочитать не смогли ⇒ сказать вслух. Молчание неотличимо от «все на месте»."""

    def test_a_missing_ref_is_unmeasured_not_zero(self):
        card = CARD.format(title="одна", status="new", probe="contract_manifest_parity")
        fx = Fixture(on_ref={"a.md": card}, in_tree={"a.md": card})
        self.addCleanup(fx.close)
        res = fx.audit(ref="origin/no-such-branch")
        self.assertEqual(res["origin"]["state"], "unmeasured")
        self.assertIn("НЕ ИЗМЕРЕНО", "\n".join(ca.report_lines(res)))

    def test_not_a_repository_is_its_OWN_third_outcome(self):
        """«Тут нет репозитория» ≠ «репозиторий есть, а прочитать не вышло».

        Смешать их значит либо утопить настоящий отказ в шуме (каталог карточек
        вне репозитория — обычное дело в тестах и разовых прогонах), либо, если
        зайти с другой стороны, промолчать о настоящем. Поэтому исходов три.
        """
        card = CARD.format(title="одна", status="new", probe="contract_manifest_parity")
        fx = Fixture(on_ref={"a.md": card}, in_tree={"a.md": card})
        self.addCleanup(fx.close)
        with tempfile.TemporaryDirectory() as outside:
            res = ca.audit(fx.tracker, repo_root=outside)
        self.assertEqual(res["origin"]["state"], "no_repo")
        self.assertEqual(res["origin"]["read"], 0)
        # и это НЕ выдаётся за прочитанную популяцию
        self.assertNotIn("дочитана с", "\n".join(ca.report_lines(res)))

    def test_the_repo_is_derived_from_the_tracker_dir_not_from_the_live_tree(self):
        """Чужой каталог карточек не тянет за собой популяцию ЖИВОГО дерева.

        Первая редакция брала `REPO_ROOT` по умолчанию — и четыре соседних теста,
        читавших временный каталог, получили пять живых карточек с `origin/main`.
        Их герметичность была ЗАНЯТА у субъекта (он читал только свой каталог).
        """
        with tempfile.TemporaryDirectory() as outside:
            tracker = os.path.join(outside, "nimbalyst-local", "tracker")
            os.makedirs(tracker)
            res = ca.audit(tracker)          # repo_root НЕ передан — выводится сам
        self.assertEqual(res["origin"]["state"], "no_repo")
        self.assertEqual(res["counts"]["declared"], 0,
                         "в популяцию попали карточки постороннего дерева")

    def test_a_partially_read_population_is_not_a_population(self):
        """Один блоб не прочитался ⇒ весь ответ «не измерено», а не «остальные ок»."""
        real = ca._git
        try:
            calls = {"n": 0}

            def flaky(args, **kw):
                if args and args[0] == "show":
                    calls["n"] += 1
                    return None
                return real(args, **kw)
            ca._git = flaky
            card = CARD.format(title="одна", status="new",
                               probe="contract_manifest_parity")
            fx = Fixture(on_ref={"a.md": card, "b.md": card}, in_tree={"a.md": card})
            self.addCleanup(fx.close)
            res = fx.audit()
        finally:
            ca._git = real
        self.assertGreater(calls["n"], 0, "мутация не сработала — замер недействителен")
        self.assertEqual(res["origin"]["state"], "unmeasured")


class ReadthroughStaysCheap(unittest.TestCase):
    """Цена сторожа однажды его и выключила (ADR-211) — держим её измеряемой."""

    def test_one_listing_call_plus_one_show_per_invisible_card(self):
        real = ca._git
        seen: list = []
        try:
            def counting(args, **kw):
                seen.append(args[0])
                return real(args, **kw)
            ca._git = counting
            card = CARD.format(title="x", status="new", probe="contract_manifest_parity")
            # ПРОБ НЕ ОБЪЯВЛЯЮТ подавляющее большинство карточек — популяция
            # трекера 882, объявивших пробу пять. Без такого большинства в
            # фикстуре утверждение «предмет узкий» не проверяется ничем:
            # расширение отбора до всех карточек проходило бы ЗЕЛЁНЫМ (замер
            # мутацией F, #467), а это ровно та цена, которая однажды выключила
            # сторожа (ADR-211: 107 с и ~1041 процесс git).
            plain = "---\ntitle: без пробы\nstatus: new\n---\n\nтело\n"
            on_ref = {f"c{i}.md": card for i in range(3)}
            on_ref.update({f"p{i}.md": plain for i in range(20)})
            fx = Fixture(on_ref=on_ref, in_tree={"c0.md": card})
            self.addCleanup(fx.close)
            fx.audit()
        finally:
            ca._git = real
        self.assertEqual(seen.count("grep"), 1,
                         "перечисление популяции обязано стоить ОДНУ команду")
        # `show` — по одному на карточку, ОБЪЯВИВШУЮ пробу (3), а не на всю
        # популяцию ref (23). Предмет узкий по построению, и это измеряется.
        self.assertEqual(seen.count("show"), 3,
                         f"читаем больше, чем объявивших пробу: {seen}")
        # `rev-parse` — один: отличить «тут нет репозитория» от «есть, но не
        # прочитался». Итог — ФИКСИРОВАННАЯ цена 2 + (объявивших пробу), и
        # именно её держит это число: цена сторожа однажды его и выключила.
        self.assertEqual(seen.count("rev-parse"), 1)
        self.assertEqual(len(seen), 5, f"лишние вызовы git: {seen}")


if __name__ == "__main__":
    unittest.main()
