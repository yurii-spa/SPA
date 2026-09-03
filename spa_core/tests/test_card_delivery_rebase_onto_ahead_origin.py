# FROZEN-DATE-OK: incident-replay — даты внутри фикстур это БАЙТЫ двух живых
# карточек 03.09 (отметки захвата `claimed_at`, чей ПОРЯДОК и есть предмет
# проверки) плюс отметка следа, которую написал настоящий писатель в тот день.
# Часов в проверяемом коде нет вовсе: `rebase_card` — чистая функция над байтами,
# ей нечего инъектировать, и сдвиг календаря её вердикт не меняет.
"""Перенос закрытия на ОБОГНАВШИЙ origin — доказательство ПОКРЫТИЕМ.

Авария 2026-09-03 (цикл #470), два живых пути. Мост нашёл, что находка
`B1:reboot_unsafe:com.spa.gas_price_agent` исчезла из отчёта сторожа, закрыл в
прод-дереве две карточки — и ЧЕТЫРЕ прогона подряд не смог довезти закрытие на
origin. Причина в квитанции звучала так:

    расхождение с origin не сводится к строке status: и следу status_trail: —
    перенести правку автоматически нечем; сделать это вручную из worktree на
    origin/main

Замер побайтовым разбором обеих карточек против `origin/main` c3735515e:

| что расходится | у нас (прод) | на origin |
|---|---|---|
| `status:` | `done` (наша правка) | `new` |
| `claimed_by`/`claimed_at` | `cycle-94385` · 23:40:00Z | `cycle-32111` · **01:13:24Z** (новее) |
| `claim_takeover_reason` | старая либо нет вовсе | перебой захвата циклом #464 |
| тело | как родилось мостом | **+67 строк** разбора циклов #462/#463/#464 |

То есть origin ОБОГНАЛ слепую прод-копию (прод-дерево не синкает
`nimbalyst-local/`, CLAUDE.md §1), а доказательство переноса требовало
ПОБАЙТОВОГО равенства `candidate == local`. Равенство было недостижимо НАВСЕГДА:
чем богаче origin, тем вернее отказ, — при том что кандидат строится ИЗ origin и
всё дописанное уже несёт. Отказ был честен по своему контракту и отвечал не на
тот вопрос — тот самый класс, ради которого сторожей и разделяют.

Тесты ниже — положительные контроли (форма живой аварии; краснеют без ветки
`rebase_onto_ahead_origin`) и обратные контроли на КАЖДЫЙ запрет: ветка не смеет
откатить чужой статус, стереть чужое тело, затереть более свежий захват или
принять след, началом которого origin не является.
"""
import unittest

from spa_core.monitoring import card_delivery as cd

# Отметки захвата — дословно из двух живых карточек: наша старше origin'ной.
OUR_CLAIM_AT = "2026-09-02T23:40:00Z"
ORIGIN_CLAIM_AT = "2026-09-03T01:13:24Z"
TRAIL = '  - "2026-09-03T11:46:08.754476+00:00 new -> done · queue.set_status"\n'

_HEAD = ("---\ntrackerStatus:\n  type: inbox\n"
         'title: "Находка петли: com.spa.gas_price_agent работает, но plist не персистентен"\n')
_TAIL = ("source: nimbalyst\ncreated: 2026-09-01\n"
         'finding_key: "B1:reboot_unsafe:com.spa.gas_price_agent"\n')

#: Тело, которое мост написал и которое видит НАША копия.
BODY_AS_BORN = ("\nНаходка петли ADR-066 (architecture_conformance, WARN):\n\n"
                "com.spa.gas_price_agent работает, но plist не персистентен\n")

#: То же тело плюс разбор, дописанный на origin циклами #462/#463/#464 —
#: 67 строк, которых наша копия не получит НИКОГДА.
BODY_AHEAD = BODY_AS_BORN + "\n---\n\n" + "".join(
    f"**Цикл #46{2 + i % 3}.** строка разбора {i}, которой в прод-копии нет\n"
    for i in range(67))


def ours(status="done", claim_at=OUR_CLAIM_AT, trail=TRAIL, body=BODY_AS_BORN,
         claimed_by="cycle-94385", takeover=""):
    """Наша (прод) копия: закрыта мостом, слепая к тому, что дописал origin."""
    claim = f"claimed_by: {claimed_by}\nclaimed_at: {claim_at}\n" if claim_at else ""
    claim += takeover
    trail_block = f"status_trail:\n{trail}" if trail else ""
    return (_HEAD + f"status: {status}\n" + _TAIL + claim + trail_block
            + "---\n" + body).encode("utf-8")


def theirs(status="new", claim_at=ORIGIN_CLAIM_AT, body=BODY_AHEAD, trail="",
           claimed_by="cycle-32111", takeover="claim_takeover_reason: Цикл #464: захват осиротел\n"):
    """Версия origin: тело богаче на 67 строк, захват перебит и НОВЕЕ нашего."""
    claim = f"claimed_by: {claimed_by}\nclaimed_at: {claim_at}\n" if claim_at else ""
    claim += takeover
    trail_block = f"status_trail:\n{trail}" if trail else ""
    return (_HEAD + f"status: {status}\n" + _TAIL + claim + trail_block
            + "---\n" + body).encode("utf-8")


class TheLiveIncidentIsCarried(unittest.TestCase):
    """Положительные контроли: без новой ветки каждый из них КРАСНЫЙ."""

    def test_the_closure_is_carried_onto_the_ahead_origin(self):
        carried, why = cd.rebase_card(ours(), theirs())
        self.assertIsNotNone(carried, f"живая авария снова не переносится: {why}")
        self.assertEqual(why, "")

    def test_our_status_and_trail_land_on_the_card(self):
        carried, _ = cd.rebase_card(ours(), theirs())
        fm = cd.card_parts(carried)[0].decode()
        self.assertIn("status: done", fm)
        self.assertIn("11:46:08.754476+00:00 new -> done", fm)

    def test_the_67_lines_origin_added_are_not_lost(self):
        """Худшая ошибка ветки — стереть разбор, которого мы не видели."""
        carried, _ = cd.rebase_card(ours(), theirs())
        self.assertEqual(cd.card_parts(carried)[1], cd.card_parts(theirs())[1])
        self.assertIn("строка разбора 66", carried.decode())

    def test_the_newer_claim_on_origin_wins_over_our_stale_one(self):
        carried, _ = cd.rebase_card(ours(), theirs())
        fm = cd.card_parts(carried)[0].decode()
        self.assertIn("claimed_by: cycle-32111", fm)
        self.assertIn(ORIGIN_CLAIM_AT, fm)
        self.assertNotIn("cycle-94385", fm)
        self.assertIn("claim_takeover_reason", fm)

    def test_nothing_of_ours_is_dropped_outside_the_claim_block(self):
        """Доказательство ветки — покрытие; проверяем его же по результату."""
        carried, _ = cd.rebase_card(ours(), theirs())
        kept, _trail = cd.split_trail_block(cd.card_parts(carried)[0])
        mine, _t = cd.split_trail_block(cd.card_parts(ours())[0])
        ok, _extra = cd._covered_lines(cd._CLAIM_LINE.sub(b"", mine),
                                       cd._CLAIM_LINE.sub(b"", kept))
        self.assertTrue(ok)


class TheBranchRefusesEverythingElse(unittest.TestCase):
    """Обратные контроли. Каждый запрет назван вслух в причине отказа."""

    def _refused(self, local, remote):
        carried, why = cd.rebase_card(local, remote)
        self.assertIsNone(carried, "перенос состоялся там, где обязан был отказать")
        return why

    def test_origin_moved_to_another_status_is_refused(self):
        """Владелец двинул карточку — слепая копия НЕ смеет вернуть её назад."""
        why = self._refused(ours(), theirs(status="ingested"))
        self.assertIn("origin стоит в статусе ingested", why)

    def test_origin_body_that_lost_our_line_is_refused(self):
        """Обгон и расхождение — разные вещи: пропала НАША строка ⇒ отказ."""
        why = self._refused(ours(), theirs(body=BODY_AHEAD.replace(
            "com.spa.gas_price_agent работает, но plist не персистентен\n", "")))
        self.assertIn("тело origin не содержит наших строк", why)

    def test_an_older_claim_on_origin_is_refused(self):
        """Вперёд ушли МЫ ⇒ перенос затёр бы более свежую отметку."""
        why = self._refused(ours(claim_at="2026-09-03T05:00:00Z"), theirs())
        self.assertIn("захват на origin СТАРШЕ нашего", why)

    def test_a_claim_absent_on_origin_is_refused(self):
        why = self._refused(ours(), theirs(claim_at="", takeover=""))
        self.assertIn("на origin его нет", why)

    def test_an_unparsable_claim_stamp_is_not_measured(self):
        why = self._refused(ours(claim_at="вчера"), theirs())
        self.assertIn("НЕ ИЗМЕРЕНО", why)

    def test_a_trail_origin_is_not_the_start_of_is_refused(self):
        """След origin обязан быть НАЧАЛОМ нашего, иначе мы стёрли бы переход.

        Форма выбрана так, чтобы дойти ДО новой ветки: прежний отказ второй
        попытки (`trail_only_appends`) ловит только НЕподпоследовательность, а
        здесь след origin — подпоследовательность нашего, но не его начало.
        Без этой проверки ветка сочла бы дописанным то, что origin уже видел.
        """
        first = '  - "2026-09-03T10:00:00+00:00 new -> in-progress · queue.set_status"\n'
        why = self._refused(ours(trail=first + TRAIL), theirs(trail=TRAIL))
        self.assertIn("не является началом нашего", why)

    def test_a_trail_that_origin_moved_past_is_refused_by_the_old_branch(self):
        """Обратная сторона той же пары: НЕподпоследовательность — прежний отказ."""
        alien = '  - "2026-09-03T09:00:00+00:00 new -> in-progress · queue.set_status"\n'
        why = self._refused(ours(), theirs(trail=alien))
        self.assertIn("status_trail", why)

    def test_two_appended_transitions_that_do_not_link_are_refused(self):
        """Дописать можно ЦЕПОЧКУ, а не два несвязанных перехода.

        Крайние звенья при этом сходятся с обеими копиями (`new` у origin,
        `ingested` у нас) — то есть проверка концов такую пару пропускает, и
        без проверки стыка мы применили бы переход из состояния, которого
        карточка не проходила.
        """
        broken = ('  - "2026-09-03T10:00:00+00:00 new -> in-progress · queue.set_status"\n'
                  '  - "2026-09-03T11:00:00+00:00 done -> ingested · queue.set_status"\n')
        why = self._refused(ours(status="ingested", trail=broken), theirs())
        self.assertIn("не состыковываются в цепочку", why)

    def test_an_unknown_frontmatter_field_on_origin_is_still_refused(self):
        """Обгонять можно ТЕЛОМ, не машинной частью — прежний отказ цел.

        Frontmatter читают программы, и незнакомое поле там способно изменить
        смысл карточки; тело — проза, машинного вердикта она не меняет. Поэтому
        ветка сознательно НЕ снимает отказ
        `test_refuses_when_origin_gained_a_field_we_never_saw` (инв. #16: этот
        тест не ослаблен ни на строку, что и проверяется прогоном его файла).
        """
        remote = theirs().replace(b"source: nimbalyst\n",
                                  b"source: nimbalyst\npriority: high\n")
        why = self._refused(ours(), remote)
        self.assertIn("которых мы не видели", why)
        self.assertIn("priority: high", why)

    def test_origin_frontmatter_that_dropped_our_line_is_refused(self):
        """Вне блока захвата frontmatter тоже доказывается ПОКРЫТИЕМ, не верой."""
        remote = theirs().replace(
            b'finding_key: "B1:reboot_unsafe:com.spa.gas_price_agent"\n', b"")
        why = self._refused(ours(), remote)
        self.assertIn("frontmatter origin не содержит наших строк", why)

    def test_a_copy_without_a_trail_does_not_reach_the_branch(self):
        why = self._refused(ours(trail=""), theirs())
        self.assertIn("нет следа перехода", why)

    def test_a_status_that_disagrees_with_our_own_trail_is_refused(self):
        why = self._refused(ours(status="in-progress"), theirs())
        self.assertIn("не совпадает с целью нашего же", why)

    def test_owner_answer_seen_only_on_origin_still_cancels_the_closure(self):
        """Прежний отказ ADR-080 п.3 не ослаблен и стоит ВЫШЕ новой ветки."""
        remote = theirs().replace(b"source: nimbalyst\n",
                                  b"source: nimbalyst\nowner_choice: variant_2\n")
        why = self._refused(ours(), remote)
        self.assertIn("owner_choice", why)
        self.assertIn("закрытие отменено", why)

    def test_a_claim_seen_only_on_origin_still_cancels_the_closure(self):
        """Захвата мы не видели ВОВСЕ ⇒ карточку не закрывают за спиной сессии."""
        why = self._refused(ours(claim_at="", takeover=""), theirs())
        self.assertIn("claimed_by", why)
        self.assertIn("закрытие отменено", why)

    def test_the_old_refusal_still_names_why_the_ahead_branch_declined(self):
        """Отказ обязан НАЗЫВАТЬ обе причины, иначе разбор руками слепой."""
        why = self._refused(ours(), theirs(status="ingested"))
        self.assertIn("вручную из worktree", why)
        self.assertIn("перенос на обогнавший origin тоже отказал", why)


class ByteExactBranchesAreUntouched(unittest.TestCase):
    """Новая ветка стоит ТРЕТЬЕЙ: обе побайтовые обязаны работать как раньше."""

    def test_identical_except_status_still_carries(self):
        carried, why = cd.rebase_card(ours(trail="", claim_at=""),
                                      theirs(status="new", body=BODY_AS_BORN,
                                             claim_at="", takeover=""))
        self.assertIsNotNone(carried, why)

    def test_identical_except_status_and_trail_still_carries(self):
        carried, why = cd.rebase_card(ours(claim_at=""),
                                      theirs(status="new", body=BODY_AS_BORN,
                                             claim_at="", takeover=""))
        self.assertIsNotNone(carried, why)


if __name__ == "__main__":
    unittest.main()
