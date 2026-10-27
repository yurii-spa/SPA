"""Форма строки реестра решений: статус читается по ФОРМЕ, а не по числу чёрточек (ADR-830).

**Что измерено 2026-10-27 (цикл #956).** `docs/decisions/INDEX.md` объявляет шапкой ровно
одну форму — `| ADR | Заголовок | Статус | Файл |`. В форме **494** строки из **681**;
остальные **187** в неё не попадают, и у **136** из них колонок всего три: у 118 третья
колонка — ДАТА, то есть ни статуса, ни ссылки на файл решения в реестре нет вовсе.

Старая мера отвечала на вопрос «сколько в строке чёрточек» (`len(line.split("|")) >= 5`,
статус — `parts[-3]`) и платила этим в ОБЕ стороны:

* верно написанная строка из двух колонок получала `None`, то есть ИСЧЕЗАЛА из реестра, и
  интерлок пушера отказывал «нет ни одной строки ADR-NNN» — направление отказа верное,
  причина ЛОЖНАЯ. Цикл #955 заплатил этим: его собственная строка прошла сторожа только
  благодаря чёрточке внутри `^(FAILED|ERROR)` своего же заголовка;
* строка вне формы отдавала СТАТУСОМ не ту колонку — у тех 118 это заголовок на 900
  символов. «Не измерено», выданное за измеренное, — ровно инв. #17 у производителя.

**Цена названа замером, а не на глаз.** Дифференциальный прогон старого и нового разбора
на живом реестре: ключей 678 ↔ 678, строк с ИЗМЕНИВШЕЙСЯ претензией на номер — **ноль**.
То есть сегодня неверно прочитанный статус не переворачивает ни одного ответа: заголовок
не начинается со слова «Superseded», и `is_live_claim` случайно отвечает в безопасную
сторону. Это делает дефект ЛАТЕНТНЫМ fail-OPEN, а не действующим, — и так и сказано
вслух. Активная цена, уже уплаченная, — ложный отказ доставке (#955).

Каждый тест ниже — положительный контроль измеренной формы аварии, а не украшение
(`.claude/rules/deployment.md`, «проверка сторожа сторожей»): на целом контуре он зелен,
на каждом порванном звене — красен, и ни один не проходит подстрокой.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASELINE = Path(__file__).parent / "adr_index_form_baseline.json"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod


adr = _load("adr_number_form_under_test", "scripts/adr_number.py")

INDEX_HEAD = (
    "# ADR INDEX\n\n"
    "| ADR | Заголовок | Статус | Файл |\n"
    "|---|---|---|---|\n"
)


def _run(cwd, *args):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    """Одноразовый репозиторий, где ветка `origin/main` играет роль origin.

    Имя ветки объявлено входом сцены (`git init -b main`): умолчание `init.defaultBranch`
    есть свойство ХОСТА — на Маке `main`, на `ubuntu-latest` `master`, — и фикстура,
    молча положившаяся на него, красна там и зелена здесь
    (`.claude/rules/deployment.md`, § «GIT-ОКРУЖЕНИЕ в тестах»).
    """
    r = tmp_path / "repo"
    (r / "docs" / "decisions").mkdir(parents=True)
    _run(r, "git", "init", "-q", "-b", "main")
    _run(r, "git", "config", "user.email", "t@t")
    _run(r, "git", "config", "user.name", "t")
    return r


def _commit_origin(repo, files: dict):
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    _run(repo, "git", "add", "-A")
    _run(repo, "git", "commit", "-qm", "origin state")
    head = _run(repo, "git", "rev-parse", "HEAD").stdout.strip()
    _run(repo, "git", "update-ref", "refs/remotes/origin/main", head)


# ── форму объявляет ДОКУМЕНТ, а не память модуля ─────────────────────────────

def test_declared_form_comes_from_the_live_table_header():
    """Константы модуля обязаны совпасть с шапкой живого реестра.

    Если шапку однажды сменят, судить строки по старой памяти модуля было бы ровно тем
    дефектом, против которого правило о провенансе. Поэтому форма читается из документа,
    а этот тест — её положительный контроль.
    """
    text = (ROOT / "docs/decisions/INDEX.md").read_text(encoding="utf-8")
    assert adr.declared_form(text) == (adr.DECLARED_COLUMNS, adr.STATUS_COLUMN)


def test_missing_header_is_the_third_outcome_not_an_empty_finding():
    """Шапки нет ⇒ НЕ ИЗМЕРЕНО с причиной, а не «строк вне формы ноль»."""
    assert adr.declared_form("| ADR-830 | т | Accepted | [x](x.md) |\n") is None
    form, total, in_form, rows = adr.form_scan("| ADR-830 | т | Accepted | [x](x.md) |\n")
    assert (form, total, in_form, rows) == (None, 0, 0, [])


def test_unreadable_index_is_unmeasured_with_a_named_reason(tmp_path):
    """Реестра нет ⇒ `measured=False` и причина, а не чистый ноль находок."""
    rep = adr.index_form(tmp_path)
    assert rep["measured"] is False
    assert rep["unmeasured_reason"] and "НЕ измерена" in rep["unmeasured_reason"]
    assert rep["out_of_form"] == []


# ── статус: измерен / НЕ ИЗМЕРЕН ─────────────────────────────────────────────

def test_status_of_a_row_in_declared_form_is_measured():
    """Заголовок с запятыми, скобками и ссылкой внутри формы не ломает чтение статуса."""
    line = ("| ADR-054 | Kill-switch authority — latches (manual_pause vs risk), "
            "D-08 accepted | Accepted | [ADR-054](ADR-054-kill-switch-authority.md) |")
    assert adr.parse_index(line) == {"054": [("Accepted", False)]}


def test_row_out_of_form_reports_status_as_unmeasured_not_as_its_title():
    """АВАРИЯ ДОСЛОВНО: 118 строк отдавали СТАТУСОМ свой заголовок.

    Форма замера — `| ADR | заголовок | дата |`: ни статуса, ни файла. Прежний разбор
    брал `parts[-3]` и возвращал заголовок как измеренный статус.
    """
    line = "| ADR-293 | **Фактическая ставка берётся из снимка, а не руками.** Проза | 2026-09-09 |"
    rows = adr.parse_index(line)
    assert rows == {"293": [(None, False)]}, "статус вне формы обязан быть НЕ ИЗМЕРЕН"
    status, dup = rows["293"][0]
    assert dup is False, "пометки «(дубль)» в строке нет — претензия обычная"
    assert adr.status_label(status) == adr.UNMEASURED_STATUS
    assert "2026-09-09" not in adr.status_label(status)


def test_five_column_row_does_not_pass_as_measured_either():
    """Пятая колонка (своя конвенция `… | Дата | Статус | Файл |`) — тоже вне формы.

    Старая мера «предпоследняя колонка» на этой форме отвечала ВЕРНО и ровно поэтому
    выглядела исправной: 45 строк живого реестра устроены так. Но верный ответ на одной
    из трёх бытующих форм не есть измерение формы — это совпадение.
    """
    line = ("| ADR-269 | заголовок | 2026-09-08 | Accepted | "
            "[ADR-269](ADR-269-x.md) |")
    assert adr.parse_index(line) == {"269": [(None, False)]}


def test_two_column_row_still_claims_its_number():
    """ПЕРВАЯ половина цены #955: такая строка ИСЧЕЗАЛА из реестра целиком.

    Строка без чёрточки в прозе даёт 4 куска, старый порог `>= 5` её отбрасывал, и
    интерлок отказывал «нет ни одной строки ADR-NNN» — причина ложная, строка на месте.
    Теперь строка узнаётся по ЯКОРЮ: номер занят, статус не измерен.
    """
    assert adr.parse_index("| ADR-829 | заголовок без чёрточек |") == {
        "829": [(None, False)]}


def test_row_without_a_closing_pipe_is_out_of_form_too():
    """Обрамление — часть формы, и одна такая строка в живом реестре есть.

    Строка, не закрытая чёрточкой, не является строкой markdown-таблицы: судить её
    колонки значило бы выдумать их число. Номер при этом занят — якорь на месте.
    """
    line = "| ADR-424 | заголовок без закрывающей чёрточки"
    assert adr.row_columns(line) is None
    assert adr.parse_index(line) == {"424": [(None, False)]}


def test_unmeasured_status_claims_the_number_fail_closed():
    """Неизмеренный статус НЕ освобождает номер — иначе сломанная форма отдала бы его второму.

    Обратная сторона здесь же: пометка «(дубль)» претензию снимает по-прежнему, то есть
    fail-CLOSED не съел принятый способ расходиться (ADR-073).
    """
    assert adr.is_live_claim(None, False) is True
    assert adr.is_live_claim(None, True) is False
    assert adr.is_live_claim("Superseded by ADR-048", False) is False
    assert adr.is_live_claim("Accepted", False) is True


# ── починка ИЗМЕРЯЕТСЯ, а не выдумывается ────────────────────────────────────

def test_repair_takes_the_status_from_the_decision_file(repo):
    """Статус строки — проекция решения; источник правды о статусе есть сам файл решения."""
    _commit_origin(repo, {
        "docs/decisions/INDEX.md": INDEX_HEAD + "| ADR-830 | заголовок | 2026-10-27 |\n",
        "docs/decisions/ADR-830-x.md": "# ADR-830\n\n- **Статус:** принято\n",
    })
    rep = adr.index_form(repo)
    assert rep["measured"] and len(rep["out_of_form"]) == 1
    repair = rep["out_of_form"][0]["repair"]
    assert repair["file"] == "ADR-830-x.md"
    assert repair["status"] == "принято"


def test_repair_refuses_to_invent_a_status_the_file_does_not_declare(repo):
    """Файл решения молчит о статусе ⇒ третий исход с причиной, а не «Accepted» по умолчанию."""
    _commit_origin(repo, {
        "docs/decisions/INDEX.md": INDEX_HEAD + "| ADR-830 | заголовок | 2026-10-27 |\n",
        "docs/decisions/ADR-830-x.md": "# ADR-830\n\nтекст без строки статуса\n",
    })
    repair = adr.index_form(repo)["out_of_form"][0]["repair"]
    assert repair["status"] is None
    assert repair["status_reason"] and "НЕ ИЗМЕРЕН" in repair["status_reason"]


def test_repair_names_the_missing_decision_file_instead_of_guessing(repo):
    """Файла решения нет ⇒ ссылка НЕ измерена; пустая строка совпала бы с «измерено»."""
    _commit_origin(repo, {
        "docs/decisions/INDEX.md": INDEX_HEAD + "| ADR-777 | заголовок | 2026-10-27 |\n"})
    repair = adr.index_form(repo)["out_of_form"][0]["repair"]
    assert repair["file"] is None
    assert repair["file_reason"] and "НЕ измерена" in repair["file_reason"]


# ── интерлок доставки: контроль в ОБЕ стороны ────────────────────────────────

def _origin_with(repo, index_rows, extra=None):
    files = {"docs/decisions/INDEX.md": INDEX_HEAD + index_rows,
             "docs/decisions/ADR-830-x.md": "# ADR-830\n\n- **Статус:** принято\n"}
    files.update(extra or {})
    _commit_origin(repo, files)


def test_interlock_refuses_a_delivered_decision_whose_row_is_out_of_form(repo):
    """Строка моего решения вне формы ⇒ отказ с ВЕРНОЙ причиной и номером строки."""
    _origin_with(repo, "| ADR-830 | заголовок | 2026-10-27 |\n")
    findings, unchecked = adr.check_push(
        repo, [repo / "docs/decisions/ADR-830-x.md", repo / "docs/decisions/INDEX.md"])
    assert not unchecked
    broken = [f for f in findings if "НЕ в объявленной форме" in f]
    assert len(broken) == 1, findings
    assert "строка 5" in broken[0] and "колонок 3" in broken[0]
    assert "нет ни одной строки" not in " ".join(findings), (
        "прежняя ЛОЖНАЯ причина не должна возвращаться")


def test_interlock_is_quiet_when_the_same_row_is_written_by_form(repo):
    """Обратная сторона: та же доставка с строкой В ФОРМЕ проходит молча.

    Без этой половины отказ выше был бы неотличим от сторожа, который краснеет всегда.
    """
    _origin_with(repo, "| ADR-830 | заголовок | принято | [ADR-830](ADR-830-x.md) |\n")
    findings, unchecked = adr.check_push(
        repo, [repo / "docs/decisions/ADR-830-x.md", repo / "docs/decisions/INDEX.md"])
    assert not unchecked and not findings, findings


def test_interlock_does_not_refuse_because_of_SOMEONE_ELSES_broken_row(repo):
    """Предсуществующие 187 строк вне формы не запирают чужую доставку.

    Сторож, краснеющий не на твоей работе, отключают первым — поэтому их убыль стережёт
    храповик ниже, а не этот отказ.
    """
    _origin_with(repo,
                 "| ADR-293 | чужая строка вне формы | 2026-09-09 |\n"
                 "| ADR-830 | заголовок | принято | [ADR-830](ADR-830-x.md) |\n")
    findings, unchecked = adr.check_push(
        repo, [repo / "docs/decisions/ADR-830-x.md", repo / "docs/decisions/INDEX.md"])
    assert not unchecked and not findings, findings


def test_interlock_is_unmeasured_when_the_header_is_gone(repo):
    """Шапки в реестре нет ⇒ fail-CLOSED «не измерено», а не зелёный пропуск."""
    _commit_origin(repo, {
        "docs/decisions/INDEX.md": "# ADR INDEX\n\n| ADR-830 | т | принято | [x](x.md) |\n",
        "docs/decisions/ADR-830-x.md": "# ADR-830\n\n- **Статус:** принято\n"})
    findings, unchecked = adr.check_push(
        repo, [repo / "docs/decisions/ADR-830-x.md", repo / "docs/decisions/INDEX.md"])
    assert not findings
    assert any("форма строк НЕ измерена" in u for u in unchecked), unchecked


# ── храповик по ЖИВОМУ реестру: база может только УМЕНЬШАТЬСЯ ────────────────

def test_rows_out_of_declared_form_only_shrink():
    """База формы — как `frozen_date_baseline.json`: дописывать в неё ЗАПРЕЩЕНО.

    Сверка идёт по КЛЮЧАМ, а не по их числу: иначе «одну починили, другую сломали»
    прошло бы незамеченным при неизменном счёте.
    """
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    known = set(baseline["known_out_of_form_keys"])
    rep = adr.index_form(ROOT)
    assert rep["measured"], rep["unmeasured_reason"]
    actual = {r["key"] for r in rep["out_of_form"]}

    new = sorted(actual - known)
    assert not new, (
        f"новые строки реестра ВНЕ объявленной формы: {new}. Напиши строку формой "
        f"`| ADR-NNN | Заголовок | Статус | Файл |` — измеренные значения печатает "
        f"`python3 scripts/adr_number.py form`. Дописывать ключ в "
        f"{BASELINE.name}, чтобы погасить падение, ЗАПРЕЩЕНО")

    healed = sorted(known - actual)
    assert not healed, (
        f"строки {healed} приведены в форму — удали их из {BASELINE.name} и обнови "
        f"счётчики: база храповика обязана уменьшаться, иначе она ничего не стережёт")


def test_baseline_counters_agree_with_the_live_measurement():
    """Числа базы — ЗАМЕР, а не память: разойдутся — красный, а не тихий дрейф.

    Урок правила о числах сайта: «32 из 140» однажды перепечатали из текста вместо прибора
    и ошиблись в тридцать два раза. Поэтому счётчики сверяются с прибором.

    **Какое число чем сверяется — разные вопросы, и мерить их одинаково нельзя.**
    `out_of_form_rows` — предмет храповика, он сверяется ТОЧНО. `rows_total` / `in_form`
    растут от каждого нового решения, то есть от нормальной работы: требовать от них
    точного равенства значило бы краснеть на УСПЕХЕ и учить править базу — ровно то,
    против чего храповик. Поэтому они сверяются МОНОТОННО: вверх свободно, вниз — находка
    (строка исчезла из реестра).

    **НАМЕРЕННОЕ изменение проверки, цикл #957 (инв. #16): `repair_fully_measured` стал
    сверяться ТОЧНО, а не «монотонно вверх».** Причина — замер, а не удобство. Это число
    считает строки ВНЕ формы, у которых починка измерима целиком, то есть оно УБЫВАЕТ от
    каждой приведённой строки: 140 → 1, когда #957 привёл 140 строк
    (`adr_number.py repair --write`, ADR-831). Требование «только вверх» на нём краснело
    бы ровно на успехе храповика и учило бы править базу — тот самый дефект, против
    которого храповик написан. Направление «вверх» было верно лишь пока не приведена ни
    одна строка. Обоснование — в `docs/journal/2026-W44.md` и в ADR-831.
    """
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    rep = adr.index_form(ROOT)
    assert rep["measured"], rep["unmeasured_reason"]
    whole = [r for r in rep["out_of_form"]
             if r["repair"]["file"] and r["repair"]["status"]]
    not_declared = len(rep["out_of_form"]) - len(whole)

    assert baseline["out_of_form_rows"] == len(rep["out_of_form"]), (
        f"строк вне формы {len(rep['out_of_form'])}, в базе "
        f"{baseline['out_of_form_rows']} — обнови базу ЗАМЕРОМ "
        f"(`python3 scripts/adr_number.py form`), а не на глаз")

    assert rep["rows_total"] >= baseline["rows_total"], (
        f"строк реестра стало МЕНЬШЕ замера ({rep['rows_total']} против "
        f"{baseline['rows_total']}): решение пропало из реестра")
    assert rep["in_form"] >= baseline["in_form"], (
        f"строк В ФОРМЕ стало меньше ({rep['in_form']} против {baseline['in_form']})")
    assert len(whole) == baseline["repair_fully_measured"], (
        f"починка измерима у {len(whole)} строк против {baseline['repair_fully_measured']} "
        f"в замере. Больше — решение объявило статус, которого не объявляло (обнови базу "
        f"ЗАМЕРОМ); меньше — строку либо ПРИВЕЛИ в форму (тогда она ушла и из "
        f"known_out_of_form_keys, обнови базу), либо решение перестало объявлять свой "
        f"статус. Это РАЗНЫЕ события, и число сверяется точно именно поэтому")
    assert not_declared <= baseline["status_not_declared_anywhere"], (
        f"строк, чей статус не объявляет никто, стало больше: {not_declared} против "
        f"{baseline['status_not_declared_anywhere']}")
