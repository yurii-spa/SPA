# -*- coding: utf-8 -*-
"""Храповик: карточка трекера может только ХУДЕТЬ (цикл #1209, ADR-1066).

**Положительный контроль — настоящая авария, и она про приказ ВЛАДЕЛЬЦА.** Замер
2026-11-19 на `origin/main`, стоячий приказ
`nimbalyst-local/tracker/inbox-task-portfolio-cio-dynamic-capital-alloc.md`:

| ось | было | предел-сосед для сравнения |
|---|---|---|
| символов | **3 273 543** | `docs/STATE.md` — 30 000 (ADR-837), то есть **109×** |
| строк | **49 764** | `docs/STATE.md` — 150 |
| записей цикла | **374** (канонической дверью `CYCLE_RECORD_RE`) | — |
| ТЗ ВЛАДЕЛЬЦА | 33 623 символа = **1.03 %** файла | — |
| хроника циклов | **98.97 %** файла | — |

`CLAUDE.md` велит прочитать карточку ПЕРЕД работой (`.claude/rules/acceptance.md`),
а 3,27 млн символов не помещаются в окно сессии ВООБЩЕ. Приказ с приоритетом
`critical` простоял `in-progress` **2152 часа**, и мимо прошло **488** циклов.
Причина механическая: приказ нельзя было ПРОЧИТАТЬ — его можно было только
дописать, и каждый цикл, который его «брал», дописывал ещё одну запись. Последние
ТРИ записи весили 444 777 символов — в 13 раз больше, чем всё ТЗ владельца.

**Почему этого не сказал ни один сторож.** Их у карточек много
(`test_card_section_loss_guard`, `test_tracker_cycle_record_loss_guard`,
`test_tracker_board_matches_cards`, …), и каждый честно отвечает на свой вопрос:
не исчез ли раздел · не исчезла ли запись цикла · называет ли карточку доска. Ни
один не спрашивает **«можно ли эту карточку прочитать»**, и зелёный ответ на один
вопрос никогда не есть ответ на другой.

**Почему храповик, а не жёсткий предел.** Дословно причина `test_state_md_length_ratchet`:
жёсткое `<= N` покраснело бы в момент, когда очередная сессия дописала бы по делу,
— и его бы отключили (cry-wolf, за который репозиторий уже платил). Храповик
разрешает «сейчас», запрещает ухудшение и вознаграждает сокращение.

**Почему осей ТРИ, а не одна.** Урок ADR-837, воспроизведённый дословно: предел
СТРОК держался 42 коммита подряд, пока файл рос в 3,29 раза — число строк есть
ПРОКСИ цены чтения, и обходится он дописыванием в ТУ ЖЕ строку. Поэтому меряются
символы, строки И самая длинная строка.

**`_BOARD.md` исключён ПОИМЁННО.** Он производная проекция, пересобирается
целиком генератором; его вес — свойство населения карточек, а не его собственное,
и запрет на рост заставлял бы править генератор вместо причины.

**Третий исход назван** (инв. #17): каталога карточек нет / база не прочитана ⇒
ГРОМКОЕ падение с причиной, а не «чисто». Скип здесь сделал бы «не измерено»
неотличимым от «прошло» (`.claude/rules/deployment.md`).

Времени в тестах нет: вес файла от календаря не зависит.
"""
import json
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
TRACKER = _ROOT / "nimbalyst-local" / "tracker"
BASELINE = Path(__file__).resolve().parent / "tracker_card_weight_baseline.json"

#: Производные проекции — не карточки. Расширять этот набор «на всякий случай»
#: ЗАПРЕЩЕНО: каждое имя здесь снимает охрану с реального файла.
EXCLUDED = ("_BOARD.md",)

#: Оси веса — ОДИН перечень, и он СВЕРЯЕТСЯ С БАЗОЙ (`test_axes_match_the_baseline`).
#: Мутационный замер цикла #1209 нашёл это место дважды: пока перечень жил
#: ВНУТРИ проверки, ось, выпавшая из него, перестала бы проверяться МОЛЧА —
#: мутант «мерить только строки» ВЫЖИЛ, потому что положительные контроли зовут
#: `measure_cards` напрямую и мимо той проверки. Объявление обязано нести свой
#: контракт, а не быть переписываемым списком внутри одного теста.
WEIGHT_AXES = ("max_chars", "max_lines", "max_longest_line")


def over_ceiling(got: dict, base: dict) -> list:
    """Оси, где факт ВЫШЕ объявленного потолка. Пустой список = в пределе."""
    return [k for k in WEIGHT_AXES if got[k] > base[k]]


def stale_upward(got: dict, base: dict) -> list:
    """Оси, где база висит ВЫШЕ факта: потолок фиктивен, починку не зафиксировали.

    Отдельная функция, а не сравнение внутри теста, по той же причине, что и
    `WEIGHT_AXES`: различающая сцена этому вопросу нужна с ИНЪЕКЦИЕЙ (сегодня
    факт равен базе, поэтому `==` и `<=` на живом дереве неразличимы, и мутант
    `assertEqual → assertLessEqual` ВЫЖИЛ).
    """
    return [k for k in WEIGHT_AXES if got[k] < base[k]]


def measure_cards(tracker_dir: Path) -> dict:
    """Максимум по трём осям + держатель каждой. Пустой набор — НЕ ноль.

    Возвращает ``{"cards": N, "max_chars": …, "max_chars_holder": …, …}``.
    Нечитаемый файл попадает в ``unreadable`` с названной причиной: подставить
    ноль значило бы выдать непрочитанное за «лёгкое».
    """
    axes = {"max_chars": (0, None), "max_lines": (0, None),
            "max_longest_line": (0, None)}
    unreadable, cards = {}, 0
    for p in sorted(tracker_dir.glob("*.md")):
        if p.name in EXCLUDED:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            unreadable[p.name] = f"{type(e).__name__}: {e}"
            continue
        cards += 1
        lines = text.split("\n")
        for key, value in (("max_chars", len(text)),
                           ("max_lines", text.count("\n") + 1),
                           ("max_longest_line", max((len(l) for l in lines), default=0))):
            if value > axes[key][0]:
                axes[key] = (value, p.name)
    out = {"cards": cards, "unreadable": unreadable}
    for key, (value, holder) in axes.items():
        out[key] = value
        out[f"{key}_holder"] = holder
    return out


class TrackerCardWeightRatchet(unittest.TestCase):

    def setUp(self):
        self.assertTrue(
            TRACKER.is_dir(),
            f"каталога карточек нет: {TRACKER} — это НЕ «чисто», а НЕ ИЗМЕРЕНО "
            f"(инв. #17): судить о весе карточек, не найдя ни одной, нельзя")
        try:
            self.base = json.loads(BASELINE.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            self.fail(f"база {BASELINE.name} НЕ ПРОЧИТАНА ({type(e).__name__}: {e}) "
                      f"— fail-CLOSED: без объявленного потолка «не выросло» "
                      f"утверждать нечем")

    def test_tracker_is_measurable_at_all(self):
        """Предпосылка обеспечена ВСЛУХ: карточки есть и они читаются."""
        got = measure_cards(TRACKER)
        self.assertGreater(got["cards"], 100,
                           f"карточек найдено {got['cards']} — для этого репозитория "
                           f"это не замер, а сбой чтения")
        self.assertEqual(got["unreadable"], {},
                         f"карточки НЕ ПРОЧИТАНЫ: {got['unreadable']}")

    def test_no_card_is_heavier_than_the_baseline(self):
        got = measure_cards(TRACKER)
        for key in over_ceiling(got, self.base):
            ceiling = self.base[key]
            self.fail(
                f"\nКАРТОЧКА ПОТЯЖЕЛЕЛА по оси `{key}`: {got[key]:,} > {ceiling:,}\n"
                f"  держатель: {got[key + '_holder']}\n"
                f"Эта ось — цена ЧТЕНИЯ карточки, и платит её каждая сессия, которой "
                f"`.claude/rules/acceptance.md` велит прочитать карточку ПЕРЕД работой. "
                f"Так стоячий приказ владельца дорос до 3 273 543 символов и голодал "
                f"488 циклов, потому что прочитать его было НЕЛЬЗЯ.\n"
                f"Что делать: вынести хронику в архив `docs/journal/*.md` — записи "
                f"цикла переносятся ПОБАЙТОВО, и дверь доставки это проверяет "
                f"(`guard_cycle_record_loss` + `classify_relocated_entries`, ADR-1066), "
                f"то есть ни одна строка не теряется. Починил — ОПУСТИ базу.\n"
                f"Дописывать базу, чтобы погасить падение, ЗАПРЕЩЕНО (инв. #16).")

    def test_baseline_is_not_stale_upward(self):
        """База не висит ВЫШЕ факта: починил — опусти, иначе потолок фиктивен."""
        got = measure_cards(TRACKER)
        for key in stale_upward(got, self.base):
            self.fail(
                f"база по оси `{key}` объявлена {self.base[key]:,}, а факт "
                f"{got[key]:,} (держатель {got[key + '_holder']}). Храповик, чья "
                f"база выше факта, разрешает молча вернуть разницу — то есть "
                f"перестаёт быть храповиком. Опусти базу до факта.")


class AxesOwnTheirOwnContract(unittest.TestCase):
    """РАЗЛИЧАЮЩИЕ сцены для двух мутантов, выживших в замере #1209.

    Оба выжили не потому, что код верен, а потому, что сцены не могли их
    различить: перечень осей жил внутри одной проверки, мимо которой идут
    положительные контроли, а «база выше факта» на живом дереве неразличима с
    «база равна факту», пока починку фиксируют сразу. Инъекция обоим вопросам
    обязательна — ровно урок #1202: мутация без различающей сцены выживает.
    """

    def setUp(self):
        self.base = json.loads(BASELINE.read_text(encoding="utf-8"))

    def test_axes_match_the_baseline(self):
        """Ось, выпавшая из перечня, перестала бы проверяться МОЛЧА."""
        declared = set(WEIGHT_AXES)
        in_base = {k for k in self.base if k.startswith("max_") and not k.endswith("_holder")}
        self.assertEqual(
            declared, in_base,
            f"перечень осей и база разошлись: объявлено {sorted(declared)}, в базе "
            f"{sorted(in_base)}. Ось, которой нет в перечне, не проверяется ВООБЩЕ, "
            f"а потолок для неё в базе стои́т — то есть сторож выглядит полным и не "
            f"является им (мутант M08 замера #1209 выжил ровно здесь).")

    def test_over_ceiling_names_the_axis_that_grew(self):
        base = {"max_chars": 100, "max_lines": 10, "max_longest_line": 5}
        self.assertEqual(over_ceiling(dict(base), base), [])
        for axis in WEIGHT_AXES:
            got = dict(base)
            got[axis] += 1
            self.assertEqual(
                over_ceiling(got, base), [axis],
                f"рост по оси `{axis}` обязан быть НАЗВАН: если ось выпала из "
                f"перечня, здесь придёт пустой список")

    def test_stale_upward_names_the_axis_left_unlowered(self):
        """Различающая сцена: факт НИЖЕ базы — та, которой на живом дереве нет."""
        base = {"max_chars": 100, "max_lines": 10, "max_longest_line": 5}
        self.assertEqual(stale_upward(dict(base), base), [],
                         "равенство фиктивным потолком не является")
        for axis in WEIGHT_AXES:
            got = dict(base)
            got[axis] -= 1
            self.assertEqual(
                stale_upward(got, base), [axis],
                f"база по оси `{axis}` висит выше факта — храповик, который это "
                f"терпит, разрешает молча вернуть разницу и перестаёт быть "
                f"храповиком (мутант M10 замера #1209 выжил ровно здесь)")


class PositiveControlReplaysTheRealAccident(unittest.TestCase):
    """Сторож ОБЯЗАН покраснеть на настоящей аварии — иначе он украшение.

    Вес воспроизводится НАСТОЯЩИЙ (3 273 543 символа, 49 764 строки, замер
    2026-11-19 на `origin/main`); текст синтетический, и это сказано вслух:
    предмет меры — ВЕС, а не буквы, и 5 МиБ фикстуры в репозитории были бы
    той же болезнью, против которой мера написана.
    """
    ACCIDENT_CHARS = 3_273_543
    ACCIDENT_LINES = 49_764

    def setUp(self):
        self.dir = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def _card(self, name: str, chars: int, lines: int) -> None:
        per = max(1, chars // max(1, lines) - 1)
        body = "\n".join("x" * per for _ in range(lines))
        (self.dir / name).write_text(body[:chars], encoding="utf-8")

    def test_the_real_order_would_redden_every_axis(self):
        self._card("inbox-task-portfolio-cio-dynamic-capital-alloc.md",
                   self.ACCIDENT_CHARS, self.ACCIDENT_LINES)
        got = measure_cards(self.dir)
        base = json.loads(BASELINE.read_text(encoding="utf-8"))
        self.assertGreater(got["max_chars"], base["max_chars"])
        self.assertGreater(got["max_lines"], base["max_lines"])
        self.assertEqual(got["max_chars_holder"],
                         "inbox-task-portfolio-cio-dynamic-capital-alloc.md")

    def test_long_line_axis_catches_what_the_line_axis_cannot(self):
        """Дословный обход ADR-837: одна строка, весь вес в ней."""
        self._card("inbox-one-fat-line.md", 200_000, 1)
        got = measure_cards(self.dir)
        base = json.loads(BASELINE.read_text(encoding="utf-8"))
        self.assertLessEqual(got["max_lines"], base["max_lines"],
                             "ось СТРОК на такой карточке молчит — в этом и смысл")
        self.assertGreater(got["max_longest_line"], base["max_longest_line"],
                           "ось САМОЙ ДЛИННОЙ строки обязана поймать то, что ось "
                           "строк пропускает по построению")

    def test_board_is_excluded_and_a_card_is_not(self):
        """Исключение действует ТОЧНО по имени, а не на всё похожее."""
        self._card("_BOARD.md", 400_000, 5_000)
        got = measure_cards(self.dir)
        self.assertEqual(got["cards"], 0, "_BOARD.md карточкой не считается")
        self._card("inbox-not-the-board.md", 400_000, 5_000)
        got = measure_cards(self.dir)
        self.assertEqual(got["cards"], 1)
        self.assertEqual(got["max_chars_holder"], "inbox-not-the-board.md")

    def test_unreadable_card_is_named_not_counted_as_light(self):
        p = self.dir / "inbox-broken-bytes.md"
        p.write_bytes(b"\xff\xfe\x00 not utf-8 \xff")
        got = measure_cards(self.dir)
        self.assertIn("inbox-broken-bytes.md", got["unreadable"],
                      "непрочитанная карточка обязана быть НАЗВАНА: ноль вместо "
                      "неё выдал бы «не измерено» за «легкая»")
        self.assertEqual(got["cards"], 0)


if __name__ == "__main__":
    unittest.main()
