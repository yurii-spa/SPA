"""test_owner_answer_superseded_is_not_a_clash.py — положительные контроли к ADR-210.

Авария воспроизводится ДОСЛОВНО: карточка `owner-decision-partiya-2-karantina-…` носит
`owner_choice: 1`, копия в мёртвом рабочем дереве — `owner_choice: 4`, а сама карточка
прямо называет четвёрку вытесненной (`owner_choice_superseded: "4"`). Шаг 2 протокола
(`set-status … ingested`) отказывал на этом с 31.08 — «копии несут РАЗНЫЕ ответы владельца
(owner_choice: ['1', '4'])» — при том что владелец сторону уже выбрал и это записано
машинно (ADR-163). Соседний сторож доставки регистр читал, эта дверь — нет.

Контроль обязан работать в ОБЕ стороны: без объявленного вытеснения отказ остаётся
дословно, иначе «починка» была бы снятием проверки (инвариант #16).
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spa_core.owner_queue import owner_answer as oa

MINE, RETIRED = "1", "4"


def _card(path: Path, *, choice: str, superseded: str | None = None) -> Path:
    fm = ["trackerStatus:", "  type: owner-decision", 'title: "партия 2 карантина"',
          "status: owner-done", f"owner_choice: {choice}",
          "owner_answered_at: 2026-08-29T21:01:45.526638+00:00",
          "owner_answer_via: telegram"]
    if superseded is not None:
        fm.append(f'owner_choice_superseded: "{superseded}"')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\n" + "\n".join(fm) + "\n---\n\n## тело\n", encoding="utf-8")
    return path


class SupersededValueDoesNotObject(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.target = _card(root / "here" / "owner-decision-partiya.md", choice=MINE,
                            superseded=RETIRED)
        self.dead = _card(root / "dead_worktree" / "owner-decision-partiya.md",
                          choice=RETIRED)
        self.extra = [str(self.dead.parent)]

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_avariya_reproduces_when_the_register_is_absent(self):
        """Обратный контроль: НЕ объявлено вытеснение ⇒ отказ прежний, сторону не выбираем."""
        _card(self.target, choice=MINE)  # переписываем БЕЗ регистра
        with self.assertRaises(oa.AnswerConflict) as ctx:
            oa.carry_owner_answer(self.target, extra_dirs=self.extra)
        self.assertIn("owner_choice", str(ctx.exception))

    def test_declared_superseded_dissolves_the_clash(self):
        res = oa.carry_owner_answer(self.target, extra_dirs=self.extra)
        self.assertNotEqual(res.get("verdict"), oa.CARRY_CONFLICT)
        self.assertEqual(res["fields"]["owner_choice"], MINE,
                         "уцелевший ответ обязан остаться НАШИМ, а не вытесненным")

    def test_register_is_read_from_every_copy_not_only_from_the_target(self):
        """Регистр мог лечь на ЛЮБУЮ сторону — порядок «доставили → нажал второй раз»
        кладёт его к нам, обратный порядок — к ним."""
        _card(self.target, choice=MINE)
        _card(self.dead, choice=RETIRED, superseded=RETIRED)
        res = oa.carry_owner_answer(self.target, extra_dirs=self.extra)
        self.assertNotEqual(res.get("verdict"), oa.CARRY_CONFLICT)

    def test_a_third_unretired_value_still_stops_everything(self):
        """Вытеснено ОДНО значение, спорит ДРУГОЕ — это по-прежнему спор."""
        root = Path(self._tmp.name)
        _card(root / "third" / "owner-decision-partiya.md", choice="7")
        with self.assertRaises(oa.AnswerConflict):
            oa.carry_owner_answer(self.target,
                                  extra_dirs=self.extra + [str(root / "third")])

    def test_retired_values_are_declared_never_inferred(self):
        """«Вытеснено» не выводится из «одно значение новее» — только из объявления."""
        _card(self.target, choice=MINE)
        self.assertEqual(oa.retired_answer_values(self.target, self.extra), {})

    def test_empty_scalar_in_the_register_is_not_a_declaration(self):
        """Пустой скаляр — «вытеснять нечего», а не «вытеснено пустое».

        Значение выбрано ЗАМЕРОМ, а не на глаз: `""` и `''` до сторожа не доходят вовсе —
        разборщик frontmatter отдаёт их как начало вложенного блока (dict), и проверка на
        них была бы ВАКУУМНОЙ. До сторожа доходят строковые `null` / `Null` / `~` —
        на них он и обязан отказать.
        """
        for scalar in ("null", "Null", "~"):
            with self.subTest(scalar=scalar):
                _card(self.target, choice=MINE, superseded=None)
                self.target.write_text(
                    self.target.read_text(encoding="utf-8").replace(
                        "owner_answer_via: telegram",
                        f"owner_answer_via: telegram\nowner_choice_superseded: {scalar}"),
                    encoding="utf-8")
                self.assertEqual(oa.retired_answer_values(self.target, self.extra), {})
                with self.assertRaises(oa.AnswerConflict):
                    oa.carry_owner_answer(self.target, extra_dirs=self.extra)


class OneWalkFeedsBothReaders(unittest.TestCase):
    """Спор считается по одному множеству копий, а разрешается по нему же.
    Второй обход разошёлся бы по составу источников — и это ровно тот класс."""

    def test_both_readers_see_the_same_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = _card(root / "here" / "c.md", choice=MINE, superseded=RETIRED)
            other = _card(root / "there" / "c.md", choice=RETIRED)
            extra = [str(other.parent)]
            walked = {p for p, _ in oa._answer_copy_texts(target, extra)}
            copies = {p for p, _ in oa.find_answer_copies(target, extra)}
            self.assertEqual(copies, walked)
            self.assertIn(other.resolve(), walked)


if __name__ == "__main__":
    unittest.main()
