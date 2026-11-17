"""Реестр решений СОСТАВНОЙ — и вопросы к нему задаются ОБЪЕДИНЕНИЮ (ADR-1046).

ЧТО БЫЛО. `docs/decisions/INDEX.md` назван обязательным чтением шага 0 в той же строке
`CLAUDE.md`, что и `STATE.md`, и у его цены чтения есть потолок — 180 000 символов
(ADR-838/840, сторож `test_mandatory_reading_read_price.py`). Замер 2026-11-17: реестр
стоял **186 664** символа при **903** строках таблицы (895 строк решений), то есть
потолок был превышен на 6 664, и два имени набора краснели на этом одном факте.

ПОЧЕМУ ПОТОЛОК НАД ОДНИМ НАКАПЛИВАЮЩИМСЯ ФАЙЛОМ ЕСТЬ ОБРАТНЫЙ ОТСЧЁТ, А НЕ ХРАПОВИК.
С 28.10 (136 610 символов, 691 строка) по 17.11 реестр вырос на **50 054** символа —
≈2 500 символов в сутки при ≈10 новых строках. Потолок, назначенный 28.10 с запасом
43 390, был обречён быть пробитым через ≈17 суток и был пробит через 20. Это тот же
класс, что «счётный потолок устаревает НА ДЕНЬ ДОСТАВКИ»: число отвечает на вопрос
«когда», а звучит как «сколько».

ПОЧЕМУ НЕЛЬЗЯ БЫЛО СОКРАТИТЬ. Поднимать потолок запрещено (инв. #16). Сокращать
колонку «Заголовок» было НЕЧЕМ: сумма H1 всех 900 файлов решений — 91 160 символов
против 95 249 в колонке, то есть колонка УЖЕ есть заголовок, а не пересказ, и прибор
`adr_number.py titles` выиграл бы 4 089 символов — сутки с половиной роста.

ЧТО ДЕЛАЕМ. Реестр объявлен составным: живая часть (`INDEX.md`) и архивная
(`INDEX-ARCHIVE.md`) в ТОМ ЖЕ каталоге — ссылки строк относительны каталогу решений, и
перенос файла в `docs/journal/` оборвал бы все 745 ссылок разом.

ЧЕГО ЭТОТ ФАЙЛ СТЕРЕЖЁТ. Перенос обязан быть НЕОТЛИЧИМ от «ничего не потеряно» для
всех, кто спрашивал реестр, И отличим от настоящей пропажи. Каждый тест ниже — либо
целый контур, либо ПОРВАННОЕ звено с названным именем; ни один не проходит подстрокой.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

HEAD = ("# ADR INDEX\n\n"
        "| ADR | Заголовок | Статус | Файл |\n"
        "|---|---|---|---|\n")


class Unmeasured(AssertionError):
    """НЕ ИЗМЕРЕНО с названной причиной — третий исход, а не «чисто»."""


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    if spec is None or spec.loader is None:
        raise Unmeasured(f"НЕ ИЗМЕРЕНО: {rel} не загружается — мерить нечем")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


adr = _load("adr_number_parts_under_test", "scripts/adr_number.py")
mem = _load("check_memory_in_git_parts_under_test", "scripts/check_memory_in_git.py")


def _tree(root: Path, live: str, archive: str | None = None,
          decisions: dict | None = None) -> Path:
    """Одноразовое дерево с реестром по КАНОНИЧЕСКИМ путям.

    Путь — часть предмета: читатели спрашивают именно `docs/decisions/INDEX.md` и
    `docs/decisions/INDEX-ARCHIVE.md`, и сцена, положившая байты в другое место,
    мерила бы другой вопрос.
    """
    d = root / "docs" / "decisions"
    d.mkdir(parents=True, exist_ok=True)
    (d / "INDEX.md").write_text(live, encoding="utf-8")
    if archive is not None:
        (d / "INDEX-ARCHIVE.md").write_text(archive, encoding="utf-8")
    for name, text in (decisions or {}).items():
        (d / name).write_text(text, encoding="utf-8")
    return root


# ── A. ОБЪЕДИНЕНИЕ: перенесённая строка остаётся записью реестра ─────────────

def test_a_row_moved_to_the_archive_is_still_in_the_register(tmp_path):
    """Целый контур: решение упомянуто ТОЛЬКО в архиве — и оно в реестре.

    Это главный вопрос всей правки. Ответь на него «нет» — и 745 решений стали бы
    недостижимыми в тот же миг, когда их сделали достижимыми по номеру.
    """
    _tree(tmp_path,
          HEAD + "| ADR-1046 | Новое | Accepted | [ADR-1046](ADR-1046-x.md) |\n"
                 "\n> архив: [`INDEX-ARCHIVE.md`](INDEX-ARCHIVE.md)\n",
          HEAD + "| ADR-055 | Старое | Accepted | [ADR-055](ADR-055-y.md) |\n",
          {"ADR-1046-x.md": "# ADR-1046\n", "ADR-055-y.md": "# ADR-055\n"})
    findings, unchecked = mem.check_index_links(tmp_path)
    assert unchecked == [], unchecked
    assert findings == [], findings


def test_a_decision_in_neither_part_is_a_finding(tmp_path):
    """Порванное звено: решение не упомянуто НИ В ОДНОЙ части — находка.

    Без этого контроля объединение могло бы «подтверждать» что угодно: спросить
    два файла и промолчать о третьем состоянии значило бы снять проверку, а не
    расширить её.
    """
    _tree(tmp_path,
          HEAD + "> архив: [`INDEX-ARCHIVE.md`](INDEX-ARCHIVE.md)\n",
          HEAD,
          {"ADR-777-orphan.md": "# ADR-777\n"})
    findings, unchecked = mem.check_index_links(tmp_path)
    assert unchecked == [], unchecked
    assert any("ADR-777-orphan.md" in f and "не упомянут" in f for f in findings), findings


def test_a_declared_archive_that_is_absent_is_unmeasured_not_clean(tmp_path):
    """Порванное звено: живая часть ССЫЛАЕТСЯ на архив, а файла нет.

    Третий исход (инв. #17): это НЕ «архива не было» и НЕ «всё цело» — это
    «решения, перенесённые в архив, НЕДОСТИЖИМЫ», и так и сказано вслух.
    """
    _tree(tmp_path,
          HEAD + "> архив: [`INDEX-ARCHIVE.md`](INDEX-ARCHIVE.md)\n")
    texts, unreadable = adr.register_parts(tmp_path)
    assert list(texts) == ["docs/decisions/INDEX.md"]
    assert len(unreadable) == 1 and "НЕДОСТИЖИМЫ" in unreadable[0], unreadable
    rep = adr.register_form(tmp_path)
    assert not rep["measured"] and "НЕДОСТИЖИМЫ" in rep["unmeasured_reason"]


def test_an_undeclared_absent_archive_is_measured_zero_not_unmeasured(tmp_path):
    """Обратная сторона того же: реестр ещё НЕ ДЕЛИЛИ — терять нечего.

    Эти два состояния обязаны быть различимы, иначе каждое дерево без архива
    (а такими были все деревья до 17.11) кричало бы «не измерено», и крик
    перестал бы что-либо значить.
    """
    _tree(tmp_path, HEAD + "| ADR-055 | x | Accepted | [ADR-055](ADR-055-y.md) |\n",
          decisions={"ADR-055-y.md": "# ADR-055\n"})
    texts, unreadable = adr.register_parts(tmp_path)
    assert unreadable == [], unreadable
    assert list(texts) == ["docs/decisions/INDEX.md"]
    rep = adr.register_form(tmp_path)
    assert rep["measured"] and rep["rows_total"] == 1


def test_a_missing_live_part_is_unmeasured_always(tmp_path):
    """Живой части нет ⇒ «не измерено» независимо от архива."""
    (tmp_path / "docs" / "decisions").mkdir(parents=True)
    texts, unreadable = adr.register_parts(tmp_path)
    assert texts == {} and len(unreadable) == 1 and "НЕ ИЗМЕРЕНО" in unreadable[0]


# ── B. СЧЁТ ЗАПИСЕЙ: сумма по частям, и пропажа всё ещё краснеет ─────────────

def test_the_form_census_sums_the_parts(tmp_path):
    """`register_form` складывает части — иначе перенос читался бы как пропажа."""
    _tree(tmp_path,
          HEAD + "| ADR-1046 | a | Accepted | [x](ADR-1046-x.md) |\n"
                 "> архив: [`INDEX-ARCHIVE.md`](INDEX-ARCHIVE.md)\n",
          HEAD + "| ADR-055 | b | Accepted | [y](ADR-055-y.md) |\n"
                 "| ADR-056 | c | Accepted | [z](ADR-056-z.md) |\n")
    rep = adr.register_form(tmp_path)
    assert rep["measured"]
    assert rep["rows_total"] == 3, rep
    assert set(rep["parts"]) == {"docs/decisions/INDEX.md",
                                 "docs/decisions/INDEX-ARCHIVE.md"}


def test_a_row_deleted_from_the_archive_lowers_the_union_count(tmp_path):
    """Порванное звено: строку УДАЛИЛИ из архива — счёт объединения упал.

    Ровно та авария, против которой написан страж общей тетради (цикл #459: строки
    реестра исчезали в семи коммитах при параллельных писателях). После разделения
    реестра большая часть этой памяти живёт в архиве, и если бы счёт его не видел,
    пропажа 745 строк не покраснела бы нигде.
    """
    live = (HEAD + "| ADR-1046 | a | Accepted | [x](ADR-1046-x.md) |\n"
                   "> архив: [`INDEX-ARCHIVE.md`](INDEX-ARCHIVE.md)\n")
    _tree(tmp_path, live,
          HEAD + "| ADR-055 | b | Accepted | [y](ADR-055-y.md) |\n")
    before = adr.register_form(tmp_path)["rows_total"]
    (tmp_path / "docs" / "decisions" / "INDEX-ARCHIVE.md").write_text(
        HEAD, encoding="utf-8")
    after = adr.register_form(tmp_path)["rows_total"]
    assert (before, after) == (2, 1), (before, after)


# ── C. ПЕРЕНОС: дословный, без потерь, идемпотентный ────────────────────────

def test_archive_rows_moves_verbatim_and_loses_nothing(tmp_path):
    """Целый контур переноса: ключи до == ключи после, текст строки — побайтово."""
    rows = "".join(f"| ADR-{n:03d} | заголовок {n} | Accepted | "
                   f"[ADR-{n:03d}](ADR-{n:03d}-x.md) |\n" for n in (55, 56, 901, 902))
    named = "| ADR-OWN-2026-07 | п | Accepted | [o](ADR-OWN-2026-07-x.md) |\n"
    _tree(tmp_path, HEAD + rows + named)
    rep = adr.archive_rows(tmp_path, 900)
    assert rep["measured"], rep["unmeasured_reason"]
    assert rep["moved"] == ["ADR-055", "ADR-056"], rep["moved"]
    assert rep["kept"] == 3, rep  # 901, 902 и ИМЕНОВАННОЕ семейство — номера у него нет
    assert adr._row_keys(rep["live_text"]) + adr._row_keys(rep["archive_text"]) != []
    before = sorted(adr._row_keys(HEAD + rows + named))
    after = sorted(adr._row_keys(rep["live_text"]) + adr._row_keys(rep["archive_text"]))
    assert before == after, (before, after)
    for n in (55, 56):
        line = (f"| ADR-{n:03d} | заголовок {n} | Accepted | "
                f"[ADR-{n:03d}](ADR-{n:03d}-x.md) |")
        assert line in rep["archive_text"], line
        assert line not in rep["live_text"], line
    assert "INDEX-ARCHIVE.md" in rep["live_text"], (
        "живая часть обязана СКАЗАТЬ о второй — иначе читатель решит, что решения нет")


def test_archive_rows_refuses_when_the_transfer_would_lose_a_row(tmp_path, monkeypatch):
    """Порванное звено ВНУТРИ самого прибора: контроль переноса обязан отказать.

    Контроль, никогда не видевший потери, был бы украшением. Здесь потеря
    устроена в точке, где её мог бы устроить дефект: сборка живой части.
    """
    rows = "".join(f"| ADR-{n:03d} | t | Accepted | [x](ADR-{n:03d}-x.md) |\n"
                   for n in (55, 901, 902))
    _tree(tmp_path, HEAD + rows)
    monkeypatch.setattr(adr, "_insert_pointer",
                        lambda text, pointer: text.replace(
                            "| ADR-902 | t | Accepted | [x](ADR-902-x.md) |\n", ""))
    rep = adr.archive_rows(tmp_path, 900)
    assert not rep["measured"]
    assert "контроль переноса ОТКАЗАЛ" in rep["unmeasured_reason"]
    assert "ADR-902" in rep["unmeasured_reason"]
    assert rep["live_text"] is None and rep["archive_text"] is None, (
        "отказавший контроль не имеет права отдать текст на запись")


def test_a_second_archive_run_moves_nothing(tmp_path):
    """Идемпотентность: «переносить нечего» есть измеренный ноль, а не отказ."""
    rows = "".join(f"| ADR-{n:03d} | t | Accepted | [x](ADR-{n:03d}-x.md) |\n"
                   for n in (55, 901))
    root = _tree(tmp_path, HEAD + rows)
    first = adr.archive_rows(root, 900)
    assert first["measured"] and first["moved"] == ["ADR-055"]
    (root / "docs" / "decisions" / "INDEX.md").write_text(first["live_text"],
                                                          encoding="utf-8")
    (root / "docs" / "decisions" / "INDEX-ARCHIVE.md").write_text(
        first["archive_text"], encoding="utf-8")
    second = adr.archive_rows(root, 900)
    assert second["measured"] and second["moved"] == []
    assert second["chars_live_after"] == second["chars_before"]


def test_an_unreadable_existing_archive_refuses_the_transfer(tmp_path):
    """Архив ЕСТЬ и не разбирается ⇒ дописывать строки некуда (fail-CLOSED)."""
    _tree(tmp_path, HEAD + "| ADR-055 | t | Accepted | [x](ADR-055-x.md) |\n",
          "проза без шапки таблицы\n")
    rep = adr.archive_rows(tmp_path, 900)
    assert not rep["measured"] and "шапка таблицы не найдена" in rep["unmeasured_reason"]


# ── D. ЖИВОЕ ДЕРЕВО: обе части на месте и обе под проверкой ─────────────────

def test_the_live_tree_register_is_whole_and_within_the_read_price():
    """Замер на ЖИВОМ дереве: части читаются, строки целы, цена чтения в потолке.

    Единственный тест файла, который спрашивает живое дерево: остальные мерят
    поведение на одноразовых сценах. Здесь предмет — само состояние реестра.
    """
    texts, unreadable = adr.register_parts(ROOT)
    assert unreadable == [], unreadable
    rep = adr.register_form(ROOT)
    assert rep["measured"], rep["unmeasured_reason"]
    live = (ROOT / "docs" / "decisions" / "INDEX.md").read_text(encoding="utf-8")
    assert len(live) <= 180_000, (
        f"живая часть реестра стои́т {len(live)} символов при потолке 180 000 — "
        f"перенеси старые строки: `python3 scripts/adr_number.py archive "
        f"--below <N> --write`")
    if "docs/decisions/INDEX-ARCHIVE.md" in texts:
        assert "INDEX-ARCHIVE.md" in live, (
            "архивная часть есть, а живая о ней не говорит — читатель решит, что "
            "решения в реестре нет")


def test_the_parts_are_declared_once_and_the_pusher_shares_the_declaration():
    """Перечень частей — ОДНА копия. Разойдись они — гейт судил бы не тот реестр.

    Пушер держит свой литерал (импортировать `adr_number` из `push_to_github` нельзя:
    пушер обязан работать в дереве, где `scripts/` может быть не на пути), поэтому
    единственная защита от расхождения — этот тест.
    """
    ptg = _load("_parts_ptg", "push_to_github.py")
    assert tuple(ptg.ADR_REGISTER_PARTS) == tuple(adr.REGISTER_PARTS), (
        f"пушер судит {ptg.ADR_REGISTER_PARTS}, а реестр объявлен "
        f"{adr.REGISTER_PARTS} — предел колонки обошла бы та часть, о которой "
        f"гейт не знает")
    for name in ("APPEND_ONLY_DOCS", "REGISTRY_DOCS", "SHARED_MEMORY_DOCS"):
        assert adr.ARCHIVE_REL in getattr(ptg, name), (
            f"{name} не знает об архивной части: в ней лежит БОЛЬШАЯ часть памяти "
            f"реестра, и её пропажа не покраснела бы нигде")


def test_the_delivery_title_gate_judges_the_archive_part(tmp_path):
    """Гейт ADR-889 задаёт вопрос о пределе колонки и АРХИВНОЙ части.

    Иначе перенос строки в архив выносил бы её из-под гейта молча — ровно тот
    класс, против которого гейт написан.
    """
    ptg = _load("_parts_ptg_gate", "push_to_github.py")
    try:
        d = tmp_path / "docs" / "decisions"
        d.mkdir(parents=True)
        fat = d / "INDEX-ARCHIVE.md"
        fat.write_text(HEAD + f"| ADR-055 | {'я' * 201} | Accepted | [x](x.md) |\n",
                       encoding="utf-8")
        ptg.pin_delivery_bytes([str(fat)])
        with pytest.raises(ptg.DeliveredAdrTitleIsFat):
            ptg.enforce_delivery_adr_titles([str(fat)])
        ptg.reset_delivery_pin()

        thin = d / "INDEX-ARCHIVE.md"
        thin.write_text(HEAD + "| ADR-055 | короткий | Accepted | [x](x.md) |\n",
                        encoding="utf-8")
        ptg.pin_delivery_bytes([str(thin)])
        verdicts = ptg.enforce_delivery_adr_titles([str(thin)])
        assert [v["state"] for v in verdicts] == ["within_limit"], verdicts
    finally:
        ptg.reset_delivery_pin()


# ── E. КОНТРОЛЬНАЯ БАТАРЕЯ ПРОБЫ ПРИЁМКИ (`.claude/rules/acceptance.md` п. 3) ──
#
# Проба, никогда не видевшая настоящей поломки, остаётся украшением. Ниже: целый
# контур зелен, КАЖДОЕ порванное звено красно с НАЗВАННЫМ именем, и ни один вердикт
# не проходит подстрокой — числа в строке согласия ИЗМЕРЕНЫ и на разных сценах разные.

def _probe():
    from spa_core.monitoring import card_acceptance as ca  # noqa: PLC0415
    return ca, ca.PROBES["register_read_price_within_ceiling"]


def _probe_scene(root: Path, live_rows: str = "", archive_rows: str | None = None,
                 decisions: dict | None = None, pointer: bool = True) -> Path:
    live = HEAD + live_rows
    if pointer and archive_rows is not None:
        live += "\n> архив: [`INDEX-ARCHIVE.md`](INDEX-ARCHIVE.md)\n"
    return _tree(root, live,
                 None if archive_rows is None else HEAD + archive_rows,
                 decisions)


def test_probe_is_satisfied_on_a_whole_circuit(tmp_path):
    ca, probe = _probe()
    _probe_scene(tmp_path,
                 "| ADR-1046 | новое | Accepted | [ADR-1046](ADR-1046-x.md) |\n",
                 "| ADR-055 | старое | Accepted | [ADR-055](ADR-055-y.md) |\n",
                 {"ADR-1046-x.md": "# ADR-1046\n", "ADR-055-y.md": "# ADR-055\n"})
    state, line = probe(root=str(tmp_path))
    assert state == ca.SATISFIED, (state, line)
    assert "частей реестра 2" in line and "строк решений 2" in line, line


def test_probe_is_not_satisfied_when_the_live_part_is_over_the_ceiling(tmp_path):
    """Порванное звено: цена чтения выше потолка — ровно состояние 17.11."""
    ca, probe = _probe()
    fat = "".join(f"| ADR-{n} | {'я' * 150} | Accepted | [x](ADR-{n}-x.md) |\n"
                  for n in range(1000, 2400))
    _probe_scene(tmp_path, fat, None,
                 {f"ADR-{n}-x.md": "# x\n" for n in range(1000, 2400)},
                 pointer=False)
    state, line = probe(root=str(tmp_path))
    assert state == ca.NOT_SATISFIED, (state, line)
    assert "при потолке 180000" in line and "archive --below" in line, line


def test_probe_is_not_satisfied_when_a_decision_left_the_register(tmp_path):
    """Порванное звено: решение есть на диске и ни в одной части реестра.

    Это второй из двух исходов пробы, и он нужен ровно затем, чтобы «дешёвый»
    путь к зелёному (вынести реестр целиком) её НЕ проходил.
    """
    ca, probe = _probe()
    _probe_scene(tmp_path, "", "",
                 {"ADR-777-orphan.md": "# ADR-777\n"})
    state, line = probe(root=str(tmp_path))
    assert state == ca.NOT_SATISFIED, (state, line)
    assert "ВНЕ реестра" in line, line


def test_probe_is_not_satisfied_on_a_dangling_register_link(tmp_path):
    """Порванное звено: строка есть, файла решения нет."""
    ca, probe = _probe()
    _probe_scene(tmp_path,
                 "| ADR-1046 | x | Accepted | [ADR-1046](ADR-1046-gone.md) |\n")
    state, line = probe(root=str(tmp_path))
    assert state == ca.NOT_SATISFIED, (state, line)
    assert "битых ссылок" in line, line


def test_probe_is_unmeasured_when_a_declared_part_is_absent(tmp_path):
    """Третий исход: живая часть ссылается на архив, а файла нет."""
    ca, probe = _probe()
    _tree(tmp_path, HEAD + "\n> архив: [`INDEX-ARCHIVE.md`](INDEX-ARCHIVE.md)\n")
    state, line = probe(root=str(tmp_path))
    assert state == ca.UNMEASURED, (state, line)
    assert "НЕДОСТИЖИМЫ" in line, line


def test_probe_is_unmeasured_when_the_instrument_is_absent(tmp_path):
    """Третий исход: приборов нет — это НЕ «чисто» и НЕ ноль."""
    ca, probe = _probe()
    _probe_scene(tmp_path)
    state, line = probe(root=str(tmp_path), code_root=str(tmp_path))
    assert state == ca.UNMEASURED, (state, line)
    assert "не импортируется" in line, line


def test_probe_is_unmeasured_when_the_live_part_is_missing(tmp_path):
    """Третий исход: реестра нет вовсе."""
    ca, probe = _probe()
    (tmp_path / "docs" / "decisions").mkdir(parents=True)
    state, line = probe(root=str(tmp_path))
    assert state == ca.UNMEASURED, (state, line)


def test_probe_does_not_pass_by_substring(tmp_path):
    """Строка согласия несёт ИЗМЕРЕННЫЕ числа: две разные сцены — две разные строки.

    Постоянная строка согласия прошла бы любую сцену, и проба отвечала бы на вопрос
    «позвали ли меня», а не на свой.
    """
    ca, probe = _probe()
    one = tmp_path / "one"
    two = tmp_path / "two"
    _probe_scene(one, "| ADR-1046 | a | Accepted | [x](ADR-1046-x.md) |\n",
                 None, {"ADR-1046-x.md": "# a\n"}, pointer=False)
    _probe_scene(two,
                 "| ADR-1046 | a | Accepted | [x](ADR-1046-x.md) |\n"
                 "| ADR-1047 | b | Accepted | [y](ADR-1047-y.md) |\n",
                 "| ADR-055 | c | Accepted | [z](ADR-055-z.md) |\n",
                 {"ADR-1046-x.md": "# a\n", "ADR-1047-y.md": "# b\n",
                  "ADR-055-z.md": "# c\n"})
    s1, l1 = probe(root=str(one))
    s2, l2 = probe(root=str(two))
    assert (s1, s2) == (ca.SATISFIED, ca.SATISFIED), (s1, l1, s2, l2)
    assert l1 != l2, l1
    assert "строк решений 1" in l1 and "строк решений 3" in l2, (l1, l2)


def test_the_probe_is_registered_under_its_declared_name():
    """Карточка объявляет имя пробы — реестр обязан его знать, иначе очередь откажет."""
    ca, _ = _probe()
    assert "register_read_price_within_ceiling" in ca.PROBES
