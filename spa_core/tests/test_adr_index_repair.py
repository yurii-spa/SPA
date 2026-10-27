"""Приведение строк реестра решений к объявленной форме (ADR-831).

**Что измерено 2026-10-27 (цикл #957).** ADR-830 построил ПЕРЕПИСЬ формы и назвал 187
строк `docs/decisions/INDEX.md` вне объявленной шапкой формы
`| ADR | Заголовок | Статус | Файл |`. Переписать их руками нечем: строка реестра — до
8400 символов, и правка касается ровно того, что в этих символах затерялось. Поэтому
починка — детерминированный писатель, а МЕРА осталась одна (`form_scan`).

**Поправка к самой мере, и её цена названа замером.** ADR-830 вылечил «статус берётся по
номеру колонки от конца», но ячейку по-прежнему отделяла ЛЮБАЯ чёрточка — то есть мера
отвечала «сколько в строке чёрточек», только на шаг позже. У markdown ответ другой: `\\|`
— литеральная чёрточка ВНУТРИ ячейки. Дифференциальный прогон обоих разборов на живом
реестре (683 строки): разбор меняется у ОДНОЙ строки — 481 (`ADR-508`, grep-шаблон
`"Exception\\|RuntimeError"`), и меняется В СТОРОНУ «строка в форме». Ни одна строка формы
не теряется. То есть прежняя мера держала одно ЛОЖНОЕ срабатывание из 187 — и оно же было
единственной причиной, по которой экранирование чёрточки не могло починить строку: мера не
видела экранов.

**Исход приведения — ЗАМЕР, а не обещание.** Приведено 140 строк, отказано 46: у 45 статуса
не объявляет НИКТО (ни строка, ни файл решения), и подставлять его запрещено (`docs/37`);
одна строка (`ADR-424`) не обрамлена чёрточками, и её приведение потребовало бы ПЕРЕСТАВИТЬ
текст. Претензия на номер не изменилась НИ У ОДНОГО из 680 ключей (дифференциальный прогон
`parse_index` + `is_live_claim` до и после), ключей не потеряно и не добавлено, изменились
ровно 140 объявленных строк и ни одной другой.

Каждый тест ниже — положительный контроль измеренной формы, а не украшение
(`.claude/rules/deployment.md`, «проверка сторожа сторожей»): он зелен на целом контуре,
красен на каждом порванном звене, и ни один не проходит подстрокой.
"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod


adr = _load("adr_number_repair_under_test", "scripts/adr_number.py")

HEAD = ("# ADR INDEX\n\n"
        "Проза перед таблицей — её писатель не трогает.\n\n"
        "| ADR | Заголовок | Статус | Файл |\n"
        "|---|---|---|---|\n")


def _scene(tmp_path, rows: str, decisions: dict):
    """Одноразовый репозиторий: реестр + файлы решений. Живое дерево не трогается."""
    root = tmp_path / "repo"
    (root / "docs" / "decisions").mkdir(parents=True)
    (root / "docs/decisions/INDEX.md").write_text(HEAD + rows, encoding="utf-8")
    for name, text in decisions.items():
        (root / "docs/decisions" / name).write_text(text, encoding="utf-8")
    return root


def _labels(root):
    text = (root / "docs/decisions/INDEX.md").read_text(encoding="utf-8")
    return adr.declared_status_labels(text)


ACCEPTED = "# ADR\n\n- **Статус:** принято\n"
ACCEPTED_EN = "# ADR\n\n- **Статус:** Accepted\n"
SILENT = "# ADR\n\nрешение без строки статуса\n"


# ── МЕРА: ячейка markdown, а не чёрточка ─────────────────────────────────────

def test_an_escaped_pipe_does_not_split_a_cell():
    """АВАРИЯ ДОСЛОВНО: `\\|` внутри заголовка делал строку «пятиколоночной».

    Строка 481 живого реестра (`ADR-508`) несёт grep-шаблон `"Exception\\|RuntimeError"`
    и до #957 числилась ВНЕ формы при четырёх ячейках на экране.
    """
    line = (r"| ADR-508 | **Заголовок** с шаблоном `\"Exception\|RuntimeError\"` внутри "
            r"| Accepted | [ADR-508](ADR-508-x.md) |")
    cols = adr.row_columns(line)
    assert cols is not None and len(cols) == adr.DECLARED_COLUMNS, cols
    assert adr.parse_index(line) == {"508": [("Accepted", False)]}


def test_an_unescaped_pipe_still_splits_a_cell():
    """Обратная сторона: без экрана чёрточка по-прежнему делит ячейку.

    Без этой половины предыдущий тест был бы неотличим от меры, которая на чёрточки
    вообще не смотрит, — и тогда 136 трёхколоночных строк прошли бы как «в форме».
    """
    line = "| ADR-508 | заголовок с сырой | чёрточкой | Accepted | [ADR-508](ADR-508-x.md) |"
    assert len(adr.row_columns(line)) == 5


def test_an_escaped_backslash_is_not_an_escaped_pipe():
    r"""`\\|` — экранированная косая, а потом РАЗДЕЛИТЕЛЬ.

    Регулярка с оглядкой назад (`(?<!\\)\|`) ответила бы здесь неверно; поэтому строка
    проходится символ за символом, и обратная косая экранирует СЛЕДУЮЩИЙ символ, каким бы
    он ни был.
    """
    assert adr.cell_separators(r"|a\\|b|") == [0, 4, 6]
    assert adr.cell_separators(r"|a\|b|") == [0, 5]


def test_a_row_without_a_frame_is_not_a_table_row_at_all():
    """Обрамление — часть формы: судить колонки незакрытой строки значило бы их выдумать."""
    assert adr.row_columns("| ADR-424 | заголовок без закрывающей чёрточки") is None


# ── СЛОВАРЬ СТАТУСОВ объявляет сам реестр ────────────────────────────────────

def test_status_vocabulary_is_measured_from_the_registrys_own_rows(tmp_path):
    """Ярлыки берутся у строк В ФОРМЕ, а не из памяти модуля.

    Список в коде пришлось бы догонять руками, и расхождение было бы невидимым — ровно
    тот класс, против которого правило о провенансе.
    """
    root = _scene(tmp_path,
                  "| ADR-700 | т | Принято (владелец, Telegram 03.09) | [ADR-700](ADR-700-x.md) |\n"
                  "| ADR-701 | т | 2026-10-08 · принято | [ADR-701](ADR-701-x.md) |\n", {})
    labels = adr.declared_status_labels(
        (root / "docs/decisions/INDEX.md").read_text(encoding="utf-8"))
    assert labels == {"Принято (владелец, Telegram 03.09)", "принято"}, labels
    assert "2026-10-08" not in labels, "дата ярлыком статуса не является"


def test_status_vocabulary_also_comes_from_the_decisions_themselves(tmp_path):
    """ВТОРОЙ источник словаря — файлы решений, и без него он держался на СОВПАДЕНИИ.

    Реестр — проекция; статус объявляет решение. В реестре, где ВСЕ строки вне формы,
    строк в форме нет вовсе ⇒ словарь из одного реестра ПУСТ, и писатель принимал за
    обрывок заголовка даже ячейку `принято`. На живом реестре это не проявлялось: 496
    строк в форме кормили словарь. Контроль ставит сцену, в которой совпадения нет.
    """
    root = _scene(tmp_path,
                  "| ADR-700 | т | принято | 2026-10-14 (#868) | "
                  "[ADR-700](ADR-700-x.md) |\n",
                  {"ADR-700-x.md": ACCEPTED})
    index = (root / "docs/decisions/INDEX.md").read_text(encoding="utf-8")
    assert adr.declared_status_labels(index) == set(), "в форме нет ни одной строки"
    assert adr.declared_status_labels(index, root / "docs/decisions") == {"принято"}


def test_missing_header_makes_the_vocabulary_unmeasured_not_empty():
    """Шапки нет ⇒ None = НЕ ИЗМЕРЕНО. Пустое множество прошло бы за «ярлыков нет»."""
    assert adr.declared_status_labels("| ADR-700 | т | Accepted | [x](x.md) |\n") is None


# ── ТРИ РАЗРЕШЁННЫХ ДЕЙСТВИЯ, каждое со своим контролем ──────────────────────

def test_an_eaten_pipe_in_the_title_is_restored_by_escaping(tmp_path):
    """Действие 1. `^(FAILED|ERROR)` — ОДНА ячейка в замысле и ДВЕ в разборе.

    Текст не меняется ни на символ: добавляется обратная косая на стыке.
    """
    row = ("| ADR-700 | **Заголовок**: вердикт собирался по `^(FAILED|ERROR) ` "
           "| Accepted | [ADR-700](ADR-700-x.md) |\n")
    root = _scene(tmp_path, row, {"ADR-700-x.md": ACCEPTED_EN})
    rep = adr.repair_index(root)
    assert len(rep["repaired"]) == 1 and not rep["refused"], rep
    new = rep["repaired"][0]["new"]
    assert rep["repaired"][0]["action"] == "экранирована чёрточка в заголовке", (
        "статус у строки СВОЙ — брать его у файла здесь не требовалось")
    assert r"`^(FAILED\|ERROR) `" in new, new
    assert len(adr.row_columns(new)) == adr.DECLARED_COLUMNS
    assert adr.parse_index(new) == {"700": [("Accepted", False)]}


def test_an_extra_column_is_folded_into_the_status_and_the_date_survives(tmp_path):
    """Действие 2. Своя конвенция `… | Дата | Статус | Файл |` сворачивается через ` · `.

    Формат не выдуман: так устроены 131 строка реестра, УЖЕ стоящие в форме
    (`2026-10-08 · принято`). Дата СОХРАНЯЕТСЯ — удалять наблюдение нельзя (ADR-537).
    """
    row = ("| ADR-700 | заголовок | 2026-09-08 | Accepted | [ADR-700](ADR-700-x.md) |\n")
    root = _scene(tmp_path, row, {"ADR-700-x.md": ACCEPTED_EN})
    rep = adr.repair_index(root)
    assert len(rep["repaired"]) == 1, rep
    assert adr.parse_index(rep["repaired"][0]["new"]) == {
        "700": [("2026-09-08 · Accepted", False)]}


def test_a_dated_note_is_an_observation_not_a_piece_of_the_title(tmp_path):
    """Действие 2, вторая форма: `2026-10-14 (#868)` — наблюдение, а не обрывок прозы.

    ЗАМЕР, а не предположение: из 103 коротких ячеек строк вне формы такой формы ровно
    ВОСЕМЬ, и без неё писатель экранировал бы чёрточку там, где её не ел разбор
    (`ADR-724`, строка 621 живого реестра).
    """
    row = ("| ADR-700 | заголовок | принято | 2026-10-14 (#868) | "
           "[ADR-700](ADR-700-x.md) |\n")
    root = _scene(tmp_path, row, {"ADR-700-x.md": ACCEPTED})
    rep = adr.repair_index(root)
    assert len(rep["repaired"]) == 1, rep
    new = rep["repaired"][0]["new"]
    assert "\\|" not in new, "ни одной чёрточки экранировать здесь не требовалось"
    assert adr.parse_index(new) == {"700": [("принято · 2026-10-14 (#868)", False)]}


def test_a_date_only_row_gets_the_status_from_the_file_and_a_link(tmp_path):
    """Действие 3 — самый крупный класс (118 строк): ни статуса, ни ссылки в реестре нет.

    Статус берётся у САМОГО решения (источник правды о статусе — решение), ссылка — у
    единственного файла на диске; дата остаётся на месте, в колонке статуса.
    """
    root = _scene(tmp_path, "| ADR-700 | заголовок | 2026-09-09 |\n",
                  {"ADR-700-x.md": ACCEPTED})
    rep = adr.repair_index(root)
    assert len(rep["repaired"]) == 1, rep
    new = rep["repaired"][0]["new"]
    assert adr.parse_index(new) == {"700": [("2026-09-09 · принято", False)]}
    assert "[ADR-700](ADR-700-x.md)" in new


def test_a_link_only_row_gets_just_the_missing_status_column(tmp_path):
    """Класс из 18 строк: ссылка есть, колонки статуса нет. Ссылка не переписывается."""
    root = _scene(tmp_path, "| ADR-700 | заголовок | [ADR-700](ADR-700-x.md) |\n",
                  {"ADR-700-x.md": ACCEPTED})
    rep = adr.repair_index(root)
    assert len(rep["repaired"]) == 1, rep
    assert adr.row_columns(rep["repaired"][0]["new"]) == [
        "ADR-700", "заголовок", "принято", "[ADR-700](ADR-700-x.md)"]


# ── ЧЕТЫРЕ ОТКАЗА: «не измерено» никогда не сворачивается в «починено» ───────

def test_a_status_nobody_declares_is_refused_not_invented(tmp_path):
    """Файл решения молчит о статусе ⇒ отказ по строке, а не «Accepted» по умолчанию.

    Это 45 строк остатка. Строка при этом остаётся В ФАЙЛЕ как была — писатель её не
    трогает вовсе.
    """
    root = _scene(tmp_path, "| ADR-700 | заголовок | 2026-09-09 |\n",
                  {"ADR-700-x.md": SILENT})
    rep = adr.repair_index(root)
    assert not rep["repaired"] and len(rep["refused"]) == 1, rep
    assert "ЗАПРЕЩЕНО" in rep["refused"][0]["reason"]
    assert rep["new_text"] == (root / "docs/decisions/INDEX.md").read_text(encoding="utf-8")


def test_a_row_without_a_frame_is_refused_because_repair_would_reorder_text(tmp_path):
    """Единственная такая строка живого реестра (`ADR-424`): после колонки файла дописан хвост.

    Привести её значило бы ПЕРЕСТАВИТЬ текст между колонками, а писателю разрешено только
    экранировать, сворачивать и дописывать. Отказ называет именно это.
    """
    root = _scene(tmp_path,
                  "| ADR-700 | заголовок | Accepted | [ADR-700](ADR-700-x.md) | хвост\n",
                  {"ADR-700-x.md": ACCEPTED})
    rep = adr.repair_index(root)
    assert not rep["repaired"] and len(rep["refused"]) == 1, rep
    assert "ПЕРЕСТАВИТЬ" in rep["refused"][0]["reason"]


def test_a_missing_decision_file_is_refused_not_guessed(tmp_path):
    """Файла решения нет ⇒ ссылку выдумать нельзя; пустая ячейка прошла бы за «измерено».

    У строки СВОЙ статус (значит отказ не о статусе), а файла `ADR-700-*.md` на диске нет
    — ссылку пришлось бы назвать наугад. Словарь ярлыков даёт соседняя строка В ФОРМЕ:
    так устроен и живой реестр.
    """
    root = _scene(tmp_path,
                  "| ADR-701 | уже в форме | Accepted | [ADR-701](ADR-701-x.md) |\n"
                  "| ADR-700 | заголовок | 2026-09-09 · Accepted |\n",
                  {"ADR-701-x.md": ACCEPTED_EN})
    rep = adr.repair_index(root)
    assert not rep["repaired"], rep["repaired"]
    assert len(rep["refused"]) == 1 and "ссылка НЕ измерена" in rep["refused"][0]["reason"]


def test_an_unreadable_index_is_unmeasured_with_a_named_reason(tmp_path):
    """Реестра нет ⇒ `measured=False` с причиной и `new_text is None`, а не «починено 0»."""
    rep = adr.repair_index(tmp_path)
    assert rep["measured"] is False and rep["new_text"] is None
    assert rep["unmeasured_reason"] and "НЕ измерена" in rep["unmeasured_reason"]


# ── КОНТРОЛЬ КОНТРОЛЯ: сверка починки отказывает на каждой порче ─────────────

def test_the_check_refuses_a_repair_that_loses_a_field():
    """Потеря наблюдения — отказ, а не тихая правка (ADR-537).

    Это сторож писателя, и без него «привести в форму» означало бы «укоротить до формы».
    """
    old = "| ADR-700 | заголовок | 2026-09-09 |"
    lost = "| ADR-700 | заголовок | принято | [ADR-700](ADR-700-x.md) |"
    bad = adr.verify_repair(old, lost, adr.DECLARED_COLUMNS)
    assert "не выжило дословно" in bad and "2026-09-09" in bad, bad


def test_the_check_refuses_a_repair_that_changes_the_number():
    """Номер — тождество записи реестра (страж потери записей в пушере опознаёт её им же)."""
    bad = adr.verify_repair("| ADR-700 | т | 2026-09-09 |",
                            "| ADR-701 | т | 2026-09-09 · принято | [ADR-701](x.md) |",
                            adr.DECLARED_COLUMNS)
    assert "номер изменился" in bad, bad


def test_the_check_refuses_a_repair_that_is_still_out_of_form():
    """Починка, не давшая формы, починкой не является."""
    bad = adr.verify_repair("| ADR-700 | т | 2026-09-09 |",
                            "| ADR-700 | т | 2026-09-09 | принято | [x](x.md) |",
                            adr.DECLARED_COLUMNS)
    assert "не в форме" in bad, bad


def test_the_check_is_silent_on_a_sound_repair():
    """Обратная сторона: верная починка проходит молча.

    Без этой половины три отказа выше были бы неотличимы от сторожа, который краснеет
    всегда, — и его отключили бы первым.
    """
    assert adr.verify_repair(
        "| ADR-700 | заголовок | 2026-09-09 |",
        "| ADR-700 | заголовок | 2026-09-09 · принято | [ADR-700](ADR-700-x.md) |",
        adr.DECLARED_COLUMNS) == ""


# ── ДИФФЕРЕНЦИАЛЬНО: претензия на номер не меняется, прочее не трогается ────

MIXED = (
    "| ADR-700 | заголовок класса «только дата» | 2026-09-09 |\n"
    "| ADR-701 | заголовок с `^(FAILED|ERROR)` | Accepted | [ADR-701](ADR-701-x.md) |\n"
    "| ADR-702 | заголовок | 2026-09-08 | Accepted | [ADR-702](ADR-702-x.md) |\n"
    "| ADR-703 | заголовок класса «молчащий файл» | 2026-09-09 |\n"
    "| ADR-704 | строка УЖЕ в форме | Superseded by ADR-700 | [ADR-704](ADR-704-x.md) |\n"
)
MIXED_FILES = {"ADR-700-x.md": ACCEPTED, "ADR-701-x.md": ACCEPTED,
               "ADR-702-x.md": ACCEPTED, "ADR-703-x.md": SILENT,
               "ADR-704-x.md": "# ADR-704\n\n- **Статус:** Superseded by ADR-700\n"}


def test_repair_changes_no_number_claim_and_loses_no_key(tmp_path):
    """Главный дифференциальный контроль: ключи и претензии на номер ТОЖДЕСТВЕННЫ.

    На живом реестре этот замер и был решающим: 680 ключей до и после, изменившихся
    претензий — НОЛЬ. Снятая претензия (`Superseded`) обязана остаться снятой, живая —
    живой: иначе приведение формы молча освободило бы занятый номер, то есть вернуло бы
    аварию 08.08, ради которой написан весь модуль.
    """
    root = _scene(tmp_path, MIXED, MIXED_FILES)
    before = (root / "docs/decisions/INDEX.md").read_text(encoding="utf-8")
    rep = adr.repair_index(root)
    a, b = adr.parse_index(before), adr.parse_index(rep["new_text"])
    assert set(a) == set(b), (set(a) ^ set(b))

    def live(rows):
        return any(adr.is_live_claim(s, d) for s, d in rows)

    assert {k: live(v) for k, v in a.items()} == {k: live(v) for k, v in b.items()}
    assert live(b["704"]) is False, "снятая претензия обязана остаться снятой"
    assert live(b["700"]) is True


def test_repair_touches_only_the_rows_it_reports(tmp_path):
    """Прозу, шапку и строки В ФОРМЕ писатель не трогает ни байтом."""
    root = _scene(tmp_path, MIXED, MIXED_FILES)
    before = (root / "docs/decisions/INDEX.md").read_text(encoding="utf-8").splitlines()
    rep = adr.repair_index(root)
    after = rep["new_text"].splitlines()
    assert len(before) == len(after)
    changed = {i for i, (x, y) in enumerate(zip(before, after), 1) if x != y}
    assert changed == {r["line"] for r in rep["repaired"]}, changed
    assert len(changed) == 3, changed          # 700, 701, 702; 703 отказ, 704 уже в форме


def test_repair_is_idempotent(tmp_path):
    """Второй прогон не меняет ничего: приведённая строка уже в форме.

    Иначе писатель дописывал бы статус к статусу на каждом прогоне цикла.
    """
    root = _scene(tmp_path, MIXED, MIXED_FILES)
    first = adr.repair_index(root)["new_text"]
    (root / "docs/decisions/INDEX.md").write_text(first, encoding="utf-8")
    second = adr.repair_index(root)
    assert second["new_text"] == first
    assert not second["repaired"] and len(second["refused"]) == 1


def test_a_prose_fragment_is_never_promoted_into_the_status_column(tmp_path):
    """Ошибка писателя направлена в безопасную сторону.

    Не узнали ячейку ⇒ она ЧАСТЬ ЗАГОЛОВКА (её чёрточка экранируется, текст на месте).
    Обратная ошибка — обрывок прозы, уехавший в колонку статуса, — была бы потерей
    смысла, и именно её этот тест и запрещает: `|Δ| ≤ 0.134` из строки 277 живого реестра.
    """
    root = _scene(tmp_path, "| ADR-700 | заголовок: `max |Δ| ≤ 0.134 с` | 2026-09-10 |\n",
                  {"ADR-700-x.md": ACCEPTED})
    rep = adr.repair_index(root)
    assert len(rep["repaired"]) == 1, rep
    cols = adr.row_columns(rep["repaired"][0]["new"])
    assert cols[2] == "2026-09-10 · принято", cols
    assert r"`max \|Δ\| ≤ 0.134 с`" in cols[1], cols[1]


# ── ЖИВОЙ реестр: остаток назван, а не забыт ────────────────────────────────

def test_the_live_registry_has_nothing_left_for_the_writer_to_do():
    """У писателя на живом реестре НЕТ работы: ни приведённых строк, ни отказов.

    «Приведено N > 0» означало бы, что строку можно было привести и не привели (цикл
    обязан позвать `adr_number.py repair --write`, а не копить долг); «отказов N > 0» —
    что остаток есть, и тогда он обязан совпасть с базой храповика ПО ЧИСЛУ. Сегодня
    верно сильнейшее: оба числа — ноль.
    """
    rep = adr.repair_index(ROOT)
    assert rep["measured"], rep["unmeasured_reason"]
    assert not rep["repaired"], [r["key"] for r in rep["repaired"]]
    baseline = json.loads(
        (Path(__file__).parent / "adr_index_form_baseline.json").read_text(encoding="utf-8"))
    assert len(rep["refused"]) == baseline["out_of_form_rows"] == 0, (
        f"отказов {len(rep['refused'])} при {baseline['out_of_form_rows']} строках вне "
        f"формы в базе")


# ── СТАТУС объявляет решение, и форм объявления ТРИ ──────────────────────────
#
# ЗАЧЕМ ТРИ. «Статус не объявлен» у остатка оказался свойством ЧИТАТЕЛЯ, а не решений, и
# за один цикл класс всплыл ТРИЖДЕ: читатель спрашивал «объявлен ли статус В МОЕЙ ФОРМЕ
# СТРОКИ» (ADR-830 — у строки реестра), «…В МОЕЙ ФОРМЕ ОБЪЯВЛЕНИЯ» (отдельной строкой, а
# не полем шапки) и «…НА МОЁМ ЯЗЫКЕ» (по-русски, хотя репозиторий двуязычен, ADR-437).
# Замер 27.10 по всем 686 решениям: отдельной строкой по-русски — 552, полем шапки — ещё
# 98, только по-английски — 34, не объявляет НИ НА ОДНОМ языке — РОВНО ОДНО (`ADR-167`).

def _decision(tmp_path, text):
    path = tmp_path / "ADR-700-x.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_status_declared_by_a_separate_russian_line_is_read_whole(tmp_path):
    """Прежняя форма читается КАК И ПРЕЖДЕ — значением до конца строки.

    Так отвечают 552 решения из 686, и менять их ответы #957 не брался: ограничение
    по разделителю добавлено только НОВЫМ читателям.
    """
    path = _decision(tmp_path, "# ADR\n\n- **Статус:** принято · цикл #528 · 2026-09-08\n")
    assert adr.declared_status(path) == "принято · цикл #528 · 2026-09-08"


def test_status_declared_as_a_field_of_a_one_line_header_is_read(tmp_path):
    """Вторая форма: поле однострочной шапки. Значение ОГРАНИЧЕНО соседним полем.

    Без ограничения в колонку статуса уехало бы `**Область:** …` целиком.
    """
    path = _decision(
        tmp_path,
        "# ADR\n\n**Дата:** 2026-09-12 · **Статус:** принято · **Область:** шаг 3\n")
    assert adr.declared_status(path) == "принято"


def test_status_declared_in_english_is_read_too(tmp_path):
    """Третья форма: `- **Status:** ACCEPTED`. Ровно так объявляют ADR-816/817/818.

    Одноязычный читатель объявлял их «не объявляющими статус» — и строка реестра из-за
    этого оставалась вне формы, то есть ЯЗЫК ЧИТАТЕЛЯ решал вопрос о статусе решения.
    """
    path = _decision(tmp_path, "# ADR-816\n\n- **Status:** ACCEPTED\n- **Date:** 2026-10-26\n")
    assert adr.declared_status(path) == "ACCEPTED"


def test_the_word_status_in_prose_is_not_a_declaration(tmp_path):
    """Обратная сторона: слово «статус» в прозе объявлением НЕ является.

    Без обязательного двоеточия читатель принял бы за статус строку
    «статус скрипта = статус последней команды» (ADR-267) — и это был бы не статус,
    а обрывок рассказа в колонке статуса, то есть инв. #17 с другой стороны.
    """
    path = _decision(tmp_path,
                     "# ADR\n\nПОСЛЕДСТВИЕ: статус скрипта равен статусу последней команды.\n")
    assert adr.declared_status(path) is None


def test_a_declaration_too_long_for_a_status_cell_is_not_measured(tmp_path):
    """Объявлено ПРОЗОЙ на 250 символов ⇒ это не ярлык, и в ячейку статуса он не идёт.

    Третий исход отличим от «не объявлено»: `max_len=None` отдаёт объявленное значение,
    и отказ называет именно длину, а не отсутствие. Два разных события — две починки.
    """
    long_tail = "ACCEPTED (" + "очень подробное объяснение " * 10 + ")"
    path = _decision(tmp_path, f"# ADR\n\n- **Status:** {long_tail}\n")
    assert adr.declared_status(path) is None
    raw = adr.declared_status(path, max_len=None)
    assert raw and len(raw) > adr.META_CELL_MAXLEN


def test_the_refusal_names_which_of_the_two_outcomes_it_is(tmp_path):
    """Отказ по статусу различает «не объявлено» и «объявлено прозой» — разными словами."""
    silent = _scene(tmp_path / "a", "| ADR-700 | т | 2026-09-09 |\n",
                    {"ADR-700-x.md": SILENT})
    prose = _scene(tmp_path / "b", "| ADR-700 | т | 2026-09-09 |\n",
                   {"ADR-700-x.md": "# ADR\n\n- **Status:** ACCEPTED ("
                                    + "подробно " * 30 + ")\n"})
    r1 = adr.index_form(silent)["out_of_form"][0]["repair"]["status_reason"]
    r2 = adr.index_form(prose)["out_of_form"][0]["repair"]["status_reason"]
    assert "не объявляет статус" in r1 and "проза" not in r1, r1
    assert "проза" in r2 and "символов" in r2, r2


# ── ЖИВОЙ реестр: база храповика ПУСТА, и это проверяемое состояние ──────────

def test_the_live_registry_is_entirely_in_the_declared_form():
    """Сильнейшее состояние храповика: строк вне формы НОЛЬ, статус измерен у каждой.

    Красный здесь означает ровно одно: в реестр добавили строку не по форме (или
    решение перестало объявлять статус). Порога, под которым это «нормально», больше нет.
    """
    rep = adr.index_form(ROOT)
    assert rep["measured"], rep["unmeasured_reason"]
    assert rep["out_of_form"] == [], [
        (r["key"], r["line"], r["kind"]) for r in rep["out_of_form"]]
    assert rep["in_form"] == rep["rows_total"] > 0
