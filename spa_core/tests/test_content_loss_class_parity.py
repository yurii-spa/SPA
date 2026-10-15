"""ПЕРЕЧЕНЬ классов потери содержимого обязан сходиться с перечнем вызовов двери.

Заказ **G729 п. 3** (карточка `inbox-task-portfolio-cio-dynamic-capital-alloc`,
поставлен циклом #874 на своей же работе): «у пушера теперь ЧЕТЫРЕ единицы смысла
(запись · раздел правила · запись цикла · раздел карточки), и перечень классов нигде
не сверяется с перечнем вызовов диспетчера: новая единица, добавленная без вызова,
останется сторожем, которого нет».

**Заказ подтверждён ЗАМЕРОМ, а не прочтением кода** (цикл #876, дифференциально).
В дерево `origin/main` `a3e3b38c6` добавлен ПЯТЫЙ класс, дословно повторяющий
контракт четырёх существующих и НИКЕМ не вызванный. Радиус — все **53** файла
тестов, упоминающих пушер:

| сцена | вердикт радиуса |
|---|---|
| `origin/main` как есть | зелено |
| + пятый класс, дверью не вызванный | **зелено так же** |

То есть сторож, которого нет, не краснит ничего. Диспетчер называет эту опасность
собственным docstring с #874 («забытый вызов у новой двери — ровно тот способ,
которым сторож перестаёт существовать, оставаясь в коде») — но **проза не есть
мера**, ровно как имя в docstring не есть вызов (урок #467).

**Две оси, и ни одна не покрывает другую** — это утверждение здесь ИЗМЕРЯЕТСЯ, а не
объявляется (два теста ниже, каждый проверяет молчание СОСЕДНЕЙ оси на своей сцене):

* ось **СИГНАТУРЫ** — несущий контракт класса обязан вызываться ДВЕРЬЮ. Ловит класс,
  приколоченный мимо двери прямо в `guard_overwrite` («четвёртая реализация»).
* ось **ИМЕНИ** — любая `guard_*_loss` обязана быть ДОСТИЖИМА из `guard_overwrite`.
  Ловит класс ИНОЙ формы, которого ось сигнатуры не видит вовсе.

Третий исход назван отдельно и падает ГРОМКО (инв. #17): пушер не разобран · двери
нет · корня нет · население пусто. «Классов найдено ноль» есть подделка
доказательства, а не зелёный ответ (урок ADR-468).
"""
from __future__ import annotations

import unittest

from spa_core.tests._pusher_wiring import (
    CONTENT_DOOR,
    CONTRACT_ARGS,
    LOSS_ROOT,
    PUSHER,
    Unmeasured,
    calls_of,
    contract_classes,
    loss_guard_names,
    reachable_from,
)


def _live() -> str:
    return PUSHER.read_text(encoding="utf-8")


#: Пятый класс замера #876 — дословный контракт, НИ ОДНОГО вызова.
FIFTH_CONFORMING = '''

def guard_fifth_unit_loss(repo_path: str, remote_bytes: Optional[bytes],
                          content_bytes: bytes, remote_sha: Optional[str],
                          allow_overwrite: bool = False) -> str:
    """Пятая единица смысла, которую забыли вписать в диспетчер."""
    return ""
'''

#: Класс ИНОЙ формы: контракт не тот, имя — то. Ось сигнатуры его не видит.
FIFTH_OFF_CONTRACT = '''

def guard_sixth_blob_loss(repo_path: str, before, after, sha, *, allow=False):
    """Сторож потери иной формы — и тоже никем не вызванный."""
    return ""
'''


def _sig_offenders(source: str) -> set:
    """Классы по контракту подписи, которых дверь НЕ зовёт."""
    return contract_classes(source) - calls_of(CONTENT_DOOR, source)


def _name_offenders(source: str) -> set:
    """Сторожа потери по имени, НЕ достижимые из корня."""
    return loss_guard_names(source) - reachable_from(LOSS_ROOT, source) - {LOSS_ROOT}


# ── ХРАПОВИК: живое дерево обязано быть зелёным по ОБЕИМ осям ────────────────

class LiveTreeParity(unittest.TestCase):
    def test_every_contract_class_is_called_by_the_door(self):
        self.assertEqual(
            _sig_offenders(_live()), set(),
            f"класс потери содержимого есть в пушере, а `{CONTENT_DOOR}` его НЕ "
            f"зовёт: сторож остался в коде и перестал существовать у двери")

    def test_every_loss_guard_is_reachable_from_the_root(self):
        self.assertEqual(
            _name_offenders(_live()), set(),
            f"функция `guard_*_loss` не достижима из `{LOSS_ROOT}` — ветка "
            f"расхождения до неё не доходит ни прямо, ни через дверь")

    def test_the_measured_population_is_the_four_units_of_meaning(self):
        """Население названо ЧИСЛОМ: молчаливая усадка перечня — тоже дефект."""
        self.assertEqual(
            contract_classes(_live()),
            {"guard_entry_loss", "guard_rules_section_loss",
             "guard_cycle_record_loss", "guard_card_section_loss"},
            "перечень единиц смысла у двери изменился: это либо новая единица "
            "(тогда её вызов обязан быть в диспетчере), либо снятая (тогда ADR)")


# ── ПОЛОЖИТЕЛЬНЫЕ КОНТРОЛИ: СЦЕНА ЗАМЕРА #876 ДОСЛОВНО ─────────────────────

class TheSceneThatWasGreenAcrossFiftyThreeFiles(unittest.TestCase):
    """Пятый класс, дверью не вызванный, в ЖИВОМ тексте пушера."""

    def setUp(self):
        self.source = _live() + FIFTH_CONFORMING

    def test_signature_axis_names_the_uncalled_class(self):
        self.assertEqual(_sig_offenders(self.source), {"guard_fifth_unit_loss"})

    def test_name_axis_names_it_too(self):
        self.assertEqual(_name_offenders(self.source), {"guard_fifth_unit_loss"})


class NeitherAxisCoversTheOther(unittest.TestCase):
    """Обе оси нужны — и это ИЗМЕРЕНО, а не объявлено в шапке."""

    def test_an_off_contract_guard_is_invisible_to_the_signature_axis(self):
        source = _live() + FIFTH_OFF_CONTRACT
        self.assertEqual(
            _sig_offenders(source), set(),
            "ось сигнатуры обязана МОЛЧАТЬ на ином контракте — иначе контроль "
            "ниже ничего не доказывает")
        self.assertEqual(_name_offenders(source), {"guard_sixth_blob_loss"})

    def test_a_class_nailed_past_the_door_is_invisible_to_the_name_axis(self):
        """Класс вписан прямо в `guard_overwrite` — «четвёртая реализация»."""
        anchor = "        base_note = guard_stale_base("
        live = _live()
        self.assertEqual(
            live.count(anchor), 1,
            "сцена не собралась: точки вставки в `guard_overwrite` больше не "
            "одна — это НЕ ИЗМЕРЕНО, а не зелёный контроль")
        source = (live + FIFTH_CONFORMING).replace(
            anchor,
            "        _ = guard_fifth_unit_loss(repo_path, verdict.get(\"base\"),\n"
            "                                  local_bytes, remote_sha,\n"
            "                                  allow_overwrite=allow_overwrite)\n"
            + anchor, 1)
        self.assertEqual(
            _name_offenders(source), set(),
            "ось имени обязана МОЛЧАТЬ: класс достижим из корня")
        self.assertEqual(
            _sig_offenders(source), {"guard_fifth_unit_loss"},
            "ось сигнатуры обязана отказать: класс минует ЕДИНУЮ дверь")


class ProseIsNotACall(unittest.TestCase):
    """Имя класса в docstring двери не есть его вызов (урок #467, ADR-333)."""

    def test_a_class_named_only_in_the_doorstring_still_fails(self):
        source = (_live() + FIFTH_CONFORMING).replace(
            '"""Одна дверь для проверок',
            '"""Одна дверь, зовущая :func:`guard_fifth_unit_loss` — на словах', 1)
        self.assertIn("guard_fifth_unit_loss` — на словах", source,
                      "сцена не собралась: docstring двери изменился — НЕ ИЗМЕРЕНО")
        self.assertEqual(_sig_offenders(source), {"guard_fifth_unit_loss"})


# ── ТРЕТИЙ ИСХОД: НЕ ИЗМЕРЕНО ≠ ЧИСТО (инв. #17) ───────────────────────────

class TheThirdOutcomeIsLoud(unittest.TestCase):
    #: Текст, который `ast` разобрать не может.
    BROKEN = "def guard_x_loss(:\n"

    def test_unparsable_pusher_is_unmeasured_through_the_signature_axis(self):
        """Без `subTest`: его падение прибор мутаций по дельте НЕ ВИДИТ.

        Первая редакция несла оба утверждения внутри `subTest`, и мутация
        «не разобрался ⇒ вернуть пустой словарь» ВЫЖИЛА: набор упавших ИМЁН
        не менялся, хотя утверждение внутри падало. Скрытое утверждение —
        та же форма, что «не измерено, выданное за ответ» (урок #465)."""
        with self.assertRaises(Unmeasured) as got:
            contract_classes(self.BROKEN)
        self.assertIn("не разобран", str(got.exception),
                      "причина подменена: разбор не удался, а сказано другое")

    def test_unparsable_pusher_is_unmeasured_through_the_name_axis(self):
        with self.assertRaises(Unmeasured) as got:
            loss_guard_names(self.BROKEN)
        self.assertIn("не разобран", str(got.exception),
                      "причина подменена: разбор не удался, а сказано другое")

    def test_a_missing_door_is_unmeasured_not_clean(self):
        with self.assertRaises(Unmeasured) as got:
            contract_classes(FIFTH_CONFORMING)
        self.assertIn(CONTENT_DOOR, str(got.exception))

    def test_a_missing_root_is_unmeasured_not_clean(self):
        with self.assertRaises(Unmeasured) as got:
            reachable_from(LOSS_ROOT, FIFTH_CONFORMING)
        self.assertIn(LOSS_ROOT, str(got.exception))

    def test_an_empty_population_is_unmeasured_not_clean(self):
        """Дверь одна и классов НОЛЬ — подделка доказательства, не чисто."""
        door_only = (
            "def guard_content_loss(repo_path: str, remote_bytes, "
            "content_bytes: bytes, remote_sha,\n"
            "                       allow_overwrite: bool = False) -> str:\n"
            "    return ''\n")
        with self.assertRaises(Unmeasured) as got:
            contract_classes(door_only)
        self.assertIn("НИ ОДНОГО", str(got.exception))
        with self.assertRaises(Unmeasured):
            loss_guard_names("def f():\n    return 1\n")

    def test_the_third_outcome_cannot_pass_as_a_skip(self):
        """Скип тоже потомок BaseException — исход обязан быть ПАДЕНИЕМ."""
        self.assertTrue(issubclass(Unmeasured, AssertionError))
        try:
            contract_classes("def guard_x_loss(:\n")
        except Unmeasured as exc:
            self.assertTrue(str(exc).startswith("НЕ ИЗМЕРЕНО"),
                            "третий исход обязан НАЗВАТЬ причину")
        else:
            self.fail("третий исход не наступил — измерять нечем")


class TheContractIsTheMeasuredOne(unittest.TestCase):
    def test_the_contract_arg_names_match_the_live_door(self):
        """Контракт в помощнике — не вторая копия: сверяется с самой дверью."""
        import ast
        tree = ast.parse(_live())
        door = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == CONTENT_DOOR)
        self.assertEqual(tuple(a.arg for a in door.args.args), CONTRACT_ARGS)


if __name__ == "__main__":
    unittest.main()
