# -*- coding: utf-8 -*-
"""Запись цикла может быть ПЕРЕНЕСЕНА, и это третий исход, а не потеря (#1209, ADR-1066).

**Что было.** `guard_cycle_record_loss` (#858, ADR-714) отказывает, если пуш
стирает запись `## Цикл #N`, которая есть на remote. Сторож прав: две доставки
молча унесли 56 и 9 записей стоячего приказа владельца.

**Цена этой меры, измеренная на том же файле.** Замер 2026-11-19 на `origin/main`:
приказ `inbox-task-portfolio-cio-dynamic-capital-alloc` — **3 273 543 символа**
(109× предела `docs/STATE.md`), **49 764** строки, **266** записей цикла, из них
ТЗ владельца = **1.03 %** файла, хроника = **98.97 %**. Приказ `critical` стоял
`in-progress` 2152 ч, мимо прошло 488 циклов: `CLAUDE.md` велит прочитать
карточку ПЕРЕД работой, а 3,27 млн символов не помещаются в окно сессии вовсе.
Единственный выход, который называл сторож, — `--allow-overwrite`, то есть
снятие проверки ЦЕЛИКОМ; под ним «снял и положил в архив» неотличимо от
«принёс устаревшую копию и унёс 56 записей». Это предмет инварианта #17.

**Что закреплено здесь — ОБЕ стороны.** Контроль каждой двери поставлен так,
чтобы порванное звено краснело ПОИМЁННО:

* авария #858 воспроизведена БЕЗ архива ⇒ отказ (мера не ослаблена);
* записи уехали в архив `docs/journal/*.md` ЭТИМ же пушем ⇒ отказа нет, перенос
  НАЗВАН нотой;
* **подделка заголовком** ⇒ отказ: архив из одних заголовков без тел не
  доказывает ничего, и дверь, верящая заголовку, разрешила бы ровно ту потерю,
  против которой написана;
* архив ЕСТЬ в дереве, но НЕ в наборе `--files` ⇒ отказ (на origin он не
  попадёт, записи исчезли бы насовсем);
* архив лежит под `nimbalyst-local/tracker/` ⇒ архивом НЕ считается (там его
  подобрал бы генератор доски и сам `is_tracker_card`);
* слепок переноса НЕ снимался ⇒ поведение РОВНО как до правки, и причина
  названа третьим исходом, а не выдана за «сверено»;
* кратность: две записи с одним номером и один двойник в архиве ⇒ одна
  перенесена, другая потеряна ⇒ отказ.

**Подстрокой проверка не проходит** (ADR-333): у каждой сцены спрашивается
ВЕРДИКТ (исключение/его отсутствие), а у ноты — ЧИСЛО перенесённых записей.

**Фикстуры.** Номера записей взяты из `LOST_359` соседнего сторожа — замер по
блобам истории аварии 08.10, не список из головы. Тела синтетические и короткие:
предмет сторожа — ЗАПИСЬ, а настоящая редакция весит 5,09 МиБ; это сказано
вслух, потому что тела в фикстуре аварию побайтово НЕ воспроизводят, а номера,
их кратность и порядок — воспроизводят.

Времени в тестах нет: сравнение чисто содержательное, якорей календаря у него
не бывает по построению.
"""
import importlib.util
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "_pusher_relocation_under_test", _ROOT / "push_to_github.py")
pusher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pusher)

ORDER = "nimbalyst-local/tracker/inbox-task-portfolio-cio-dynamic-capital-alloc.md"
ARCHIVE = "docs/journal/CARD-archive-portfolio-cio-chronicle-2026-11-19.md"
SHA = "359ce9406aa"

#: Номера из аварии 08.10 — подмножество `LOST_359` соседнего сторожа.
NUMS = [716, 717, 720, 721, 722, 723, 724, 725, 726, 727, 728, 729]

HEAD = "---\nstatus: in-progress\n---\n\n## Задание владельца\n\nтекст ТЗ\n"


def record(n: int, body: str = "") -> str:
    """Одна запись цикла. Тело непустое всегда: пустое совпало бы с чем угодно."""
    return f"\n## Цикл #{n} (2026-10-08) — работа цикла\n\nсделано {body or n}\n"


def card_with(nums) -> bytes:
    return (HEAD + "".join(record(n) for n in nums)).encode("utf-8")


def archive_with(nums, bodies: bool = True) -> bytes:
    """Архив хроники. ``bodies=False`` — ПОДДЕЛКА: одни заголовки без тел."""
    head = "# Архив хроники приказа\n\n> снято циклом #1209\n"
    if bodies:
        return (head + "".join(record(n) for n in nums)).encode("utf-8")
    return (head + "".join(f"\n## Цикл #{n} (2026-10-08) — работа цикла\n"
                           for n in nums)).encode("utf-8")


class RelocationDoorTest(unittest.TestCase):
    """Сцены ставятся на НАСТОЯЩЕМ приборе: пин снимается его же функцией."""

    def setUp(self):
        self.root = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        self._reset_pins()
        # Регистрируется РОВНО ОДИН раз и НЕ внутри `_reset_pins`: `doCleanups`
        # опустошает список в цикле, поэтому обработчик, дописывающий себя сам,
        # зацикливает уборку намертво (найдено замером: тест висел, напечатав
        # слепок байтов, и это читалось как «медленный», а не «вечный»).
        self.addCleanup(self._reset_pins)
        self._prev_root = pusher.PROJECT_ROOT
        pusher.PROJECT_ROOT = self.root
        self.addCleanup(setattr, pusher, "PROJECT_ROOT", self._prev_root)

    def _reset_pins(self):
        pusher._DELIVERY_PIN.update({"taken": False, "digests": {}, "unreadable": {},
                                     "modes": {}, "mode_unreadable": {},
                                     "allow_drift": False, "at": None})
        pusher._PIN_VERDICTS.clear()
        pusher._MODE_VERDICTS.clear()
        pusher._RELOCATION_PIN.update({"taken": False, "blocks": [],
                                       "unmeasured": [], "sources": {}})

    def _write(self, rel: str, data: bytes) -> str:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return str(p)

    def _pin(self, *abs_paths):
        """Снять ОБА слепка тем же порядком, что `main()`: байты, затем перенос."""
        pusher.pin_delivery_bytes(list(abs_paths))
        return pusher.pin_relocated_records(list(abs_paths))

    def _verdict(self, ours: bytes, remote: bytes):
        """``(нота, исключение|None)`` — вердикт настоящего сторожа."""
        try:
            return pusher.guard_cycle_record_loss(ORDER, remote, ours, SHA), None
        except pusher.CycleRecordLossRefused as e:
            return None, e

    # ── 1. авария #858 без архива: мера НЕ ослаблена ─────────────────────────
    def test_records_lost_with_no_archive_still_refuses(self):
        card = self._write(ORDER, card_with(NUMS[:2]))
        self._pin(card)
        note, exc = self._verdict(card_with(NUMS[:2]), card_with(NUMS))
        self.assertIsNotNone(exc, "потеря 10 записей БЕЗ архива обязана быть отказом")
        self.assertIn("стёр бы 10", str(exc))

    # ── 2. перенос ИЗМЕРЕН: отказа нет, перенос НАЗВАН ───────────────────────
    def test_records_relocated_into_codelivered_archive_are_not_lost(self):
        card = self._write(ORDER, card_with(NUMS[:2]))
        arch = self._write(ARCHIVE, archive_with(NUMS[2:]))
        self._pin(card, arch)
        note, exc = self._verdict(card_with(NUMS[:2]), card_with(NUMS))
        self.assertIsNone(exc, f"перенос доказан телами, отказа быть не должно: {exc}")
        self.assertIn("ПЕРЕНЕСЕНО", note)
        # ЧИСЛО, а не подстрока: перенесено ровно столько, сколько снято.
        self.assertIn(f"— {len(NUMS) - 2} ", note)

    # ── 3. ПОДДЕЛКА ЗАГОЛОВКОМ: архив без тел не доказывает ничего ───────────
    def test_archive_of_bare_headers_is_not_a_proof(self):
        card = self._write(ORDER, card_with(NUMS[:2]))
        arch = self._write(ARCHIVE, archive_with(NUMS[2:], bodies=False))
        self._pin(card, arch)
        note, exc = self._verdict(card_with(NUMS[:2]), card_with(NUMS))
        self.assertIsNotNone(
            exc, "архив из ОДНИХ заголовков обязан остаться потерей: иначе дверь "
                 "разрешает ровно ту аварию, против которой написана")
        self.assertIn("стёр бы 10", str(exc))

    # ── 3б. ПУСТОЕ ТЕЛО: равенство под ТЕМ ЖЕ заголовком — зачёт ────────────
    def test_an_empty_body_counts_only_under_the_same_header(self):
        """Поправка, ИЗМЕРЕННАЯ на живом пуше (#1209).

        Первая редакция двери пустое тело в доказательство не брала — по
        аналогии с `classify_missing_entries`. Аналогия оказалась ложной: у
        соседа пустота исключена потому, что он ищет тело под ДРУГИМ
        заголовком (там «совпало» значит «переименовано»), а здесь заголовок и
        есть тождество. Цена запрета измерена: **32** раздела из 2098 остались
        «потерянными», хотя лежат в архиве, — это записи, у которых сразу за
        заголовком идёт ПОДзаголовок, то есть тело раздела пусто ПО ПОСТРОЕНИЮ.

        Подделку держит РАВЕНСТВО: пустое с непустым не совпадает — это
        отдельная сцена ниже, и она обязана остаться красной при подделке.
        """
        bare = "\n## Цикл #716\n"
        remote = (HEAD + bare).encode("utf-8")
        card = self._write(ORDER, HEAD.encode("utf-8"))
        arch = self._write(ARCHIVE, ("# Архив\n" + bare).encode("utf-8"))
        self._pin(card, arch)
        note, exc = self._verdict(HEAD.encode("utf-8"), remote)
        self.assertIsNone(
            exc, f"запись, чьё тело пусто и в remote, и в архиве, содержимого не "
                 f"несёт вовсе — терять в ней нечего: {exc}")
        self.assertIn("ПЕРЕНЕСЕНО", note)

    def test_an_empty_archive_body_never_matches_a_real_one(self):
        """Обратная половина: пустое НЕ гасит непустое. Контроль подделки."""
        remote = card_with([716])                      # тело непустое
        card = self._write(ORDER, HEAD.encode("utf-8"))
        arch = self._write(ARCHIVE, ("# Архив\n\n## Цикл #716\n").encode("utf-8"))
        self._pin(card, arch)
        note, exc = self._verdict(HEAD.encode("utf-8"), remote)
        self.assertIsNotNone(
            exc, "пустое тело в архиве не может погасить НЕПУСТУЮ запись remote — "
                 "иначе архив из одних заголовков снова стал бы доказательством")

    # ── 4. архив ЕСТЬ в дереве, но НЕ в наборе доставки ──────────────────────
    def test_archive_not_in_the_delivery_set_does_not_count(self):
        card = self._write(ORDER, card_with(NUMS[:2]))
        self._write(ARCHIVE, archive_with(NUMS[2:]))      # лежит, но не в --files
        self._pin(card)
        note, exc = self._verdict(card_with(NUMS[:2]), card_with(NUMS))
        self.assertIsNotNone(
            exc, "архив, не включённый в набор, на origin не попадёт — записи "
                 "исчезли бы насовсем")

    # ── 5. архив НЕ ТАМ: под tracker/ он сам стал бы карточкой ───────────────
    def test_archive_under_tracker_prefix_is_not_an_archive(self):
        wrong = "nimbalyst-local/tracker/archive-chronicle.md"
        card = self._write(ORDER, card_with(NUMS[:2]))
        arch = self._write(wrong, archive_with(NUMS[2:]))
        self._pin(card, arch)
        self.assertFalse(pusher.is_chronicle_archive(wrong))
        note, exc = self._verdict(card_with(NUMS[:2]), card_with(NUMS))
        self.assertIsNotNone(exc, "под tracker/ архив подобрал бы генератор доски")

    # ── 6. слепок НЕ снимался: поведение как до правки, причина НАЗВАНА ──────
    def test_unpinned_relocation_is_unmeasured_not_clean(self):
        blocks, why = pusher.relocated_records()
        self.assertIsNone(blocks, "без пина перенос НЕ ИЗМЕРЕН, а не «переноса нет»")
        self.assertTrue(why and "не зван" in why[0])
        note, exc = self._verdict(card_with(NUMS[:2]), card_with(NUMS))
        self.assertIsNotNone(exc, "без пина сторож обязан вести себя как до правки")
        self.assertIn("НЕ ИЗМЕРЕН", str(exc))

    # ── 7. КРАТНОСТЬ: два номера, один двойник ⇒ одна перенесена, одна нет ───
    def test_multiplicity_is_consumed_not_shared(self):
        twice = card_with([716]) + record(716, "второе тело").encode("utf-8")
        card = self._write(ORDER, HEAD.encode("utf-8"))
        arch = self._write(ARCHIVE, archive_with([716]))   # только ПЕРВОЕ тело
        self._pin(card, arch)
        note, exc = self._verdict(HEAD.encode("utf-8"), twice)
        self.assertIsNotNone(
            exc, "один архивный двойник не может погасить ДВЕ записи с тем же "
                 "номером: кратность расходуется, а не делится")
        self.assertIn("стёр бы 1 ", str(exc))

    # ── 7б. РОД ВТОРОЙ: раздел. Половина починки — не починка ───────────────
    def test_section_axis_gets_the_same_door(self):
        """Карточка мерится ДВУМЯ родами, и дверь обязана служить обоим.

        Замер цикла #1209 на живом пуше: дверь по записи цикла сжатие приказа
        ПРОПУСТИЛА, а `guard_card_section_loss` отказал на **2098** разделах той
        же самой правки — каждый `###` внутри снятой записи для него тоже
        раздел. Это ровно та «половина починки», которую репозиторий уже
        оплачивал: один сайт закрыт, второй молчит или краснеет.
        """
        card_text = HEAD + "".join(record(n) + f"### Подраздел {n}\n\nтело {n}\n"
                                   for n in NUMS[:4])
        remote = card_text.encode("utf-8")
        ours = HEAD.encode("utf-8")
        # Архив несёт ВСЁ снятое побайтово — и записи, и их подразделы.
        arch_text = "# Архив\n" + "".join(record(n) + f"### Подраздел {n}\n\nтело {n}\n"
                                           for n in NUMS[:4])
        card = self._write(ORDER, ours)
        arch = self._write(ARCHIVE, arch_text.encode("utf-8"))
        self._pin(card, arch)

        # ось РАЗДЕЛ: отказа быть не должно, перенос НАЗВАН
        note = pusher.guard_card_section_loss(ORDER, remote, ours, SHA)
        self.assertIn("ПЕРЕНЕСЕНО", note,
                      "ось РАЗДЕЛ обязана получить тот же третий исход, иначе "
                      "починена ровно половина")
        # и та же правка без архива в наборе — по-прежнему ОТКАЗ
        self._reset_pins()
        pusher.pin_delivery_bytes([card])
        pusher.pin_relocated_records([card])
        with self.assertRaises(pusher.CardSectionLossRefused):
            pusher.guard_card_section_loss(ORDER, remote, ours, SHA)

    # ── 8. проводка: обе двери доставки зовут пин, своей копии нет ───────────
    def test_both_delivery_doors_pin_relocation(self):
        for rel in ("push_to_github.py", "push_to_github_batch.py"):
            src = (_ROOT / rel).read_text(encoding="utf-8")
            self.assertIn("pin_relocated_records(all_files)", src,
                          f"{rel} не снимает слепок переноса — гейт у этой двери "
                          f"перестал существовать, оставшись в коде")
        batch = (_ROOT / "push_to_github_batch.py").read_text(encoding="utf-8")
        self.assertIn("pin_relocated_records = _root_push.pin_relocated_records", batch,
                      "batch обязан ВВЕЗТИ дверь, а не держать свою копию")
        self.assertNotIn("def pin_relocated_records", batch)


if __name__ == "__main__":
    unittest.main()
