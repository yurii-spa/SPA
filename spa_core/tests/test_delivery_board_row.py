"""Десятая ось доставки: НАЗОВЁТ ли доска очереди уезжающую карточку? (ADR-1060)

**Класс, который воспроизводит каждый тест этого файла.**
`nimbalyst-local/tracker/_BOARD.md` — тот файл, который `CLAUDE.md` велит КАЖДОЙ
сессии читать ПЕРВЫМ («ЕДИНЫЙ ОБЗОР всех карточек одним взглядом … Читать ЕГО
первым, не открывая 56 файлов»). Карточка без строки на доске для читателя
индекса НЕ СУЩЕСТВУЕТ: он видит 1659 карточек и не узнаёт о 1660-й. Сторож у
класса ЕСТЬ — `spa_core/tests/test_tracker_board_matches_cards.py`. Чего не было
— ВОПРОСА В МОМЕНТ ДОСТАВКИ.

**Цена измерена на живой истории** (замер 2026-11-19, цикл #1202, полный клон
`SPA_mirror` — прод-клон УСЕЧЁН и на этот вопрос отвечать не способен, ADR-918;
400 вершин `origin/main`, трогавших карточки; разбор ЕДИНСТВЕННОЙ дверью
`build_tracker_board.board_status_map`):

* **47 вершин** несли карточку, у которой на доске НЕТ строки — и вершина
  `4d656a541` на момент замера была одной из них;
* **0** вершин несли строку доски без карточки;
* ось «строка есть, статус другой» — **НЕ ИЗМЕРЕНО** (разрешается против origin
  того дня, а временный каталог не репозиторий), затронуто 23 вершины.

Цена последней: `test_live_board_matches_live_cards` покраснел на `main` и пришёл
в красный набор CI прогона **44434382029** ОДНИМ именем — единственным
пришедшим, о котором прогон вообще вынес вердикт.

Положительный контроль идёт **ДОСЛОВНО по байтам** аварии из коммита
`8d6e97e20` (цикл #1201): доска `737e748d2` и карточка `100fd92a5`, — а не по
выдуманному «похожему» файлу (`.claude/rules/deployment.md`, § «проверка сторожа
сторожей»).

Четыре существующих сторожа доставки отвечают на этой аварии ВЕРНО и мимо:

* слепок байтов (ADR-774) — «сверено»: он пинует байты ТОЙ ЖЕ карточки и
  отвечает «байты не подменились», а не «индекс её называет»;
* гейт разбора (ADR-886) — молчит ВЕРНО: карточка не объявляла себя Python;
* гейт колонки реестра (ADR-889) — спрашивает `docs/decisions/INDEX.md` и про
  трекер не знает ничего;
* `guard_card_section_loss` — судит ПОТЕРЮ разделов карточки, а не её
  присутствие в индексе.

Литеральных дат и литеральных pid в файле нет: предмет — содержимое байтов, и ни
календарь, ни номера процессов к нему отношения не имеют. Имя ветки одноразовой
сцены ОБЪЯВЛЕНО (`git init -b main`) — `init.defaultBranch` есть свойство ХОСТА
(`.claude/rules/deployment.md`, § «GIT-ОКРУЖЕНИЕ в тестах»). Сеть не трогается ни
одним тестом: все отказы этой семьи стоят ДО сети.

Запуск: python3 -m pytest spa_core/tests/test_delivery_board_row.py -v
"""
from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: Дословные байты аварии из коммита `8d6e97e20` (цикл #1201).
INCIDENT_BOARD_BLOB = "737e748d2cb14ccb1c7af9265baaa5dfbd8ae0f3"
INCIDENT_CARD_BLOB = "100fd92a586ce30ea803abae221eb6b60473c126"

#: Карточка, уехавшая на `main` без строки на доске.
INCIDENT_CARD = "inbox-shest-dorogih-failov-ne-obyavili-svoih-d.md"

#: Путь доски ОТНОСИТЕЛЬНО корня дерева — часть предмета: гейт задаёт вопрос
#: только карточкам трекера, и сцена, положившая те же байты в другое место,
#: мерила бы другой вопрос.
TRACKER_REL = "nimbalyst-local/tracker"


class Unmeasured(AssertionError):
    """НЕ ИЗМЕРЕНО с названной причиной — третий исход, а не «чисто»."""


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def ptg():
    mod = _load("_board_row_gate_ptg", "push_to_github.py")
    yield mod
    mod.reset_delivery_pin()


def _blob(sha: str) -> bytes:
    """Байты блоба из ИСТОРИИ репозитория.

    Предпосылка — НАСТОЯЩАЯ история доставки, и выдумать её тест не может.
    Блоба нет ⇒ ГРОМКИЙ отказ с названной причиной, а НЕ `pytest.skip`: скип
    сделал бы «не измерено» неотличимым от «прошло» — урок цикла #465.
    """
    try:
        out = subprocess.run(["git", "cat-file", "blob", sha],
                             cwd=ROOT, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Unmeasured(
            f"НЕ ИЗМЕРЕНО: git не ответил ({type(exc).__name__}: {exc}) — "
            f"положительный контроль мерить не на чем") from exc
    if out.returncode != 0:
        raise Unmeasured(
            f"НЕ ИЗМЕРЕНО: блоба {sha[:12]} нет в объектной базе {ROOT} "
            f"(код {out.returncode}: "
            f"{out.stderr.decode('utf-8', 'replace').strip()}). Это предпосылка "
            f"ХАРНЕССА, а не предмет теста: джоба обязана объявить "
            f"`fetch-depth: 0`")
    return out.stdout


@pytest.fixture(scope="module")
def incident_board() -> bytes:
    return _blob(INCIDENT_BOARD_BLOB)


@pytest.fixture(scope="module")
def incident_card() -> bytes:
    return _blob(INCIDENT_CARD_BLOB)


def _tracker(tmp_path: Path, *, card: bytes | None = None,
             card_name: str = INCIDENT_CARD,
             board: bytes | None = None) -> Path:
    """Одноразовый трекер по КАНОНИЧЕСКОМУ пути внутри дерева."""
    tr = tmp_path / TRACKER_REL
    tr.mkdir(parents=True, exist_ok=True)
    if card is not None:
        (tr / card_name).write_bytes(card)
    if board is not None:
        (tr / "_BOARD.md").write_bytes(board)
    return tr


def _board_naming(names) -> bytes:
    """Доска в ОБЪЯВЛЕННОЙ форме, называющая ровно переданные карточки.

    Форма берётся из той же единственной двери, которой гейт её читает, —
    сцена, собранная по догадке о форме, мерила бы догадку.
    """
    rows = "\n".join(f"- заголовок  ·  `{n}` · 2026-11-19" for n in names)
    return (f"# Board\n\n## 📥 Inbox  ({len(names)})\n\n"
            f"### · new\n{rows}\n").encode("utf-8")


def _source(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _functions(source: str) -> dict:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise Unmeasured(f"НЕ ИЗМЕРЕНО: модуль не разобран ({exc})") from exc
    return {n.name: n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _calls_in(source: str, func_name: str) -> list:
    funcs = _functions(source)
    if func_name not in funcs:
        raise Unmeasured(f"НЕ ИЗМЕРЕНО: функции `{func_name}` нет")
    out = []
    for c in ast.walk(funcs[func_name]):
        if isinstance(c, ast.Call):
            if isinstance(c.func, ast.Name):
                out.append(c.func.id)
            elif isinstance(c.func, ast.Attribute):
                out.append(c.func.attr)
    return out


# ═════════════════════════════════════════════════════════════════════════════
# A. ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ — ДОСЛОВНЫЕ БАЙТЫ АВАРИИ, И ОБЕ СТОРОНЫ
#
# Проверка, никогда не видевшая настоящей поломки, — украшение. Здесь поломка не
# изображена, а ВЗЯТА из коммита `8d6e97e20`. Обе стороны на ОДНОЙ карточке:
# иначе «отказ» нельзя отличить от «гейт отказывает всегда».
# ═════════════════════════════════════════════════════════════════════════════
def test_the_incident_card_is_refused_and_named(ptg, tmp_path,
                                                incident_board, incident_card):
    """Дословная авария #1201: отказ называет карточку, доску и починку."""
    assert ptg.git_blob_sha(incident_card) == INCIDENT_CARD_BLOB, (
        "взяты НЕ байты аварии — положительный контроль мерил бы не тот предмет")
    tr = _tracker(tmp_path, card=incident_card, board=incident_board)
    files = [str(tr / INCIDENT_CARD), str(tr / "_BOARD.md")]
    ptg.pin_delivery_bytes(files)
    with pytest.raises(ptg.DeliveredCardHasNoBoardRow) as e:
        ptg.enforce_delivery_board_row(files)
    msg = str(e.value)
    assert INCIDENT_CARD in msg, "отказ не называет карточку"
    assert "build_tracker_board.py" in msg, "отказ не называет починку"
    assert "--allow-cardless-board" in msg, "отказ не называет осознанный обход"


def test_the_same_card_passes_once_the_board_names_it(ptg, tmp_path,
                                                      incident_card):
    """ОБРАТНАЯ сторона той же сцены: строка появилась ⇒ гейт зелен.

    Без этого теста отказ выше был бы неотличим от гейта, который отказывает
    всегда, — то есть от сторожа, не умеющего сказать «чисто».
    """
    tr = _tracker(tmp_path, card=incident_card,
                  board=_board_naming([INCIDENT_CARD]))
    files = [str(tr / INCIDENT_CARD), str(tr / "_BOARD.md")]
    ptg.pin_delivery_bytes(files)
    verdicts = ptg.enforce_delivery_board_row(files)
    assert [v["state"] for v in verdicts] == ["named"], verdicts
    assert "названы все" in ptg.delivery_board_row_summary()


# ═════════════════════════════════════════════════════════════════════════════
# B. ВОПРОС — ПРО ORIGIN ПОСЛЕ ДОСТАВКИ, А НЕ ПРО ДОСКУ В ДЕРЕВЕ
#
# Эта сцена убивает наивную редакцию гейта. Доска, пересобранная в рабочем
# дереве и НЕ включённая в набор, на origin не попадает — спроси дерево, и гейт
# зеленел бы РОВНО в том случае, ради которого написан.
# ═════════════════════════════════════════════════════════════════════════════
def test_a_board_rebuilt_in_the_tree_but_undelivered_is_still_refused(
        ptg, tmp_path, incident_card):
    """Доска в дереве строку несёт, в наборе её НЕТ ⇒ на origin строки не будет.

    Сцена ОБЯЗАНА различать `HEAD` и `origin/main`, иначе она не мерит ничего:
    первая редакция этого теста положила одинаковую доску в оба, и мутация
    «спрашивать HEAD вместо origin» ВЫЖИЛА — мутация без различающей сцены
    выживает, и выжившую записывают, а не замазывают. Поэтому здесь ДВА
    коммита: `origin/main` держит доску БЕЗ строки, `HEAD` — доску СО строкой.
    """
    tr = _tracker(tmp_path, card=incident_card)
    # Одноразовый репозиторий с ОБЪЯВЛЕННЫМ именем ветки: `init.defaultBranch`
    # есть свойство ХОСТА, и `git init` без `-b` дал бы `master` на раннере.
    def _g(*a):
        subprocess.run(["git", *a], cwd=tmp_path, capture_output=True, check=True)
    _g("init", "-b", "main")
    _g("config", "user.email", "t@t")
    _g("config", "user.name", "t")

    # Коммит 1 — то, что лежит на origin: доска называет ДРУГУЮ карточку.
    # Пустая доска (ноль строк) была бы честным `unmeasured`, и сцена мерила бы
    # не тот исход.
    (tr / "_BOARD.md").write_bytes(_board_naming(["inbox-sosedka.md"]))
    _g("add", "-A")
    _g("commit", "-m", "board as it lies on origin")
    origin_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path,
                                 capture_output=True, text=True,
                                 check=True).stdout.strip()
    _g("update-ref", "refs/remotes/origin/main", origin_head)

    # Коммит 2 — HEAD дерева: доска ПЕРЕСОБРАНА и строку несёт. Доставлять её
    # никто не собирается, поэтому на origin она не попадёт.
    (tr / "_BOARD.md").write_bytes(_board_naming(["inbox-sosedka.md",
                                                  INCIDENT_CARD]))
    _g("add", "-A")
    _g("commit", "-m", "board rebuilt in the tree")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path,
                          capture_output=True, text=True,
                          check=True).stdout.strip()
    assert head != origin_head, (
        "сцена НЕ РАЗЛИЧАЕТ HEAD и origin/main — мутация «спросить HEAD» "
        "выжила бы, ничего не измерив")

    files = [str(tr / INCIDENT_CARD)]            # доски в наборе НЕТ
    ptg.pin_delivery_bytes(files)
    with pytest.raises(ptg.DeliveredCardHasNoBoardRow):
        ptg.enforce_delivery_board_row(files)


def test_the_origin_ref_is_the_one_asked_not_the_working_head(
        ptg, tmp_path, incident_card):
    """Обратная сторона: строка появилась НА ORIGIN ⇒ гейт зелен, HEAD тут не судья.

    Пара к тесту выше. Вместе они закрепляют, что спрашивается РОВНО
    `origin/<branch>`: один краснеет, когда строка только в HEAD, другой зеленеет,
    когда строка только на origin.
    """
    tr = _tracker(tmp_path, card=incident_card)
    def _g(*a):
        subprocess.run(["git", *a], cwd=tmp_path, capture_output=True, check=True)
    _g("init", "-b", "main")
    _g("config", "user.email", "t@t")
    _g("config", "user.name", "t")
    (tr / "_BOARD.md").write_bytes(_board_naming(["inbox-sosedka.md",
                                                  INCIDENT_CARD]))
    _g("add", "-A")
    _g("commit", "-m", "board on origin names the card")
    origin_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path,
                                 capture_output=True, text=True,
                                 check=True).stdout.strip()
    _g("update-ref", "refs/remotes/origin/main", origin_head)
    # HEAD уезжает вперёд и строку ТЕРЯЕТ — но судить обязан не он.
    (tr / "_BOARD.md").write_bytes(_board_naming(["inbox-sosedka.md"]))
    _g("add", "-A")
    _g("commit", "-m", "head loses the row")

    files = [str(tr / INCIDENT_CARD)]
    ptg.pin_delivery_bytes(files)
    verdicts = ptg.enforce_delivery_board_row(files)
    assert [v["state"] for v in verdicts] == ["named"], verdicts
    assert "origin/main" in verdicts[0]["whence"], verdicts


def test_the_board_source_is_printed_not_assumed(ptg, tmp_path, capsys,
                                                 incident_card):
    """Выбор доски ПЕЧАТАЕТСЯ (ADR-918): читатель узна́ет, о чьей доске речь."""
    tr = _tracker(tmp_path, card=incident_card,
                  board=_board_naming([INCIDENT_CARD]))
    files = [str(tr / INCIDENT_CARD), str(tr / "_BOARD.md")]
    ptg.pin_delivery_bytes(files)
    verdicts = ptg.enforce_delivery_board_row(files)
    assert verdicts[0]["whence"] == "уезжает этим пушем", verdicts


# ═════════════════════════════════════════════════════════════════════════════
# C. ТРИ ИСХОДА РАЗЛИЧИМЫ (инв. #17)
# ═════════════════════════════════════════════════════════════════════════════
def test_an_unreadable_origin_board_is_unmeasured_not_a_refusal(
        ptg, tmp_path, incident_card):
    """Доски нет ни в наборе, ни в ссылке ⇒ НЕ ИЗМЕРЕНО с причиной.

    Отказ здесь был бы неверен: он остановил бы доставку КОДА от сбоя git,
    ничего не измерив. Молчанием это тоже не является — причина печатается.
    """
    tr = _tracker(tmp_path, card=incident_card)      # доски нет вовсе
    files = [str(tr / INCIDENT_CARD)]
    ptg.pin_delivery_bytes(files)
    verdicts = ptg.enforce_delivery_board_row(files)
    assert [v["state"] for v in verdicts] == ["unmeasured"], verdicts
    assert verdicts[0]["reason"], "исход НЕ ИЗМЕРЕНО без названной причины"
    assert "НЕ ИЗМЕРЕНО" in ptg.delivery_board_row_summary()


def test_a_board_without_a_single_declared_row_is_unmeasured(ptg, tmp_path,
                                                             incident_card):
    """Ноль строк в объявленной форме ⇒ НЕ ИЗМЕРЕНО, а не отказ по КАЖДОЙ карточке.

    «Строки нет» здесь было бы утверждением о замере, которого не было: от
    одного непонятого файла гейт отказал бы всему набору.
    """
    tr = _tracker(tmp_path, card=incident_card,
                  board="# Board\n\nни одной строки в объявленной форме\n"
                        .encode("utf-8"))
    files = [str(tr / INCIDENT_CARD), str(tr / "_BOARD.md")]
    ptg.pin_delivery_bytes(files)
    verdicts = ptg.enforce_delivery_board_row(files)
    assert [v["state"] for v in verdicts] == ["unmeasured"], verdicts
    assert "НИ ОДНОЙ строки" in verdicts[0]["reason"]


def test_undecodable_board_bytes_are_unmeasured(ptg, tmp_path, incident_card):
    """Байты доски не UTF-8 ⇒ НЕ ИЗМЕРЕНО с названной причиной."""
    tr = _tracker(tmp_path, card=incident_card, board=b"\xff\xfe\x00board")
    files = [str(tr / INCIDENT_CARD), str(tr / "_BOARD.md")]
    ptg.pin_delivery_bytes(files)
    verdicts = ptg.enforce_delivery_board_row(files)
    assert [v["state"] for v in verdicts] == ["unmeasured"], verdicts
    assert "UTF-8" in verdicts[0]["reason"]


def test_never_called_is_not_the_same_as_nothing_to_judge(ptg, tmp_path):
    """Пустой перечень — ДВА разных состояния, и они различимы.

    Склеить «гейта не звали» (библиотечный вызов минуя CLI) со «звали, карточек
    не было» — тот же дефект, что склеить «не измерено» со «сверено».
    """
    assert "не зван НИ РАЗУ" in ptg.delivery_board_row_summary()
    other = tmp_path / "code.py"
    other.write_text("x = 1\n", encoding="utf-8")
    ptg.pin_delivery_bytes([str(other)])
    ptg.enforce_delivery_board_row([str(other)])
    assert "судить нечего" in ptg.delivery_board_row_summary()


def test_the_board_itself_is_not_its_own_subject(ptg, tmp_path):
    """Доска строки о себе не несёт — спрашивать её о себе значило бы отказать всегда."""
    tr = _tracker(tmp_path, board=_board_naming(["inbox-sosedka.md"]))
    files = [str(tr / "_BOARD.md")]
    ptg.pin_delivery_bytes(files)
    verdicts = ptg.enforce_delivery_board_row(files)
    assert verdicts == [], verdicts
    assert "судить нечего" in ptg.delivery_board_row_summary()


# ═════════════════════════════════════════════════════════════════════════════
# D. ОСОЗНАННЫЙ ОБХОД — НАЗВАН И ПЕЧАТАЕТСЯ
# ═════════════════════════════════════════════════════════════════════════════
def test_the_override_names_itself_and_does_not_silence(ptg, tmp_path, capsys,
                                                       incident_board,
                                                       incident_card):
    """`--allow-cardless-board` снимает отказ, но НЕ молчание: находка печатается."""
    tr = _tracker(tmp_path, card=incident_card, board=incident_board)
    files = [str(tr / INCIDENT_CARD), str(tr / "_BOARD.md")]
    ptg.pin_delivery_bytes(files)
    verdicts = ptg.enforce_delivery_board_row(files, allow=True)
    out = capsys.readouterr().out
    assert [v["state"] for v in verdicts] == ["absent"], verdicts
    assert "--allow-cardless-board" in out, "обход не НАЗВАН в выводе"
    assert "НЕТ СТРОКИ НА ДОСКЕ" in out, "находка не напечатана"


# ═════════════════════════════════════════════════════════════════════════════
# E. ДВЕРЬ ОДНА — НИ РАЗБОРА, НИ ЧТЕНИЯ БАЙТОВ СВОЕЙ КОПИИ
#
# Меряется AST, а не подстрокой: разойдись копия с генератором — гейт пускал бы
# через себя ровно те строки, из-за которых он и понадобился (ADR-774/889).
# ═════════════════════════════════════════════════════════════════════════════
def test_the_gate_has_no_own_copy_of_board_parsing():
    """Разбор доски приходит из `build_tracker_board`, своего в пушере нет."""
    src = _source("push_to_github.py")
    assert "board_status_map" not in {n for n in _functions(src)}, (
        "в пушере завелась СВОЯ копия разбора доски — разойдись она с "
        "генератором, гейт пускал бы через себя предмет класса")
    assert "build_tracker_board.py" in _source("push_to_github.py"), (
        "гейт не называет прибор, у которого берёт единственную дверь разбора")
    calls = _calls_in(src, "_board_parser")
    assert "spec_from_file_location" in calls, (
        "дверь разбора ввозится не из файла прибора — значит это не она")


def test_a_prober_without_the_door_is_unmeasured_not_a_pass(ptg, tmp_path):
    """Прибор НА МЕСТЕ, но двери разбора в нём НЕТ ⇒ НЕ ИЗМЕРЕНО с причиной.

    Дыра покрытия, НАЙДЕННАЯ мутацией M14: проверка `hasattr(mod,
    "board_status_map")` снималась, и батарея этого не замечала — ни одна сцена
    не подавала прибор БЕЗ двери. «Прибора нет» и «строка есть» это разные
    ответы (дословный урок `pyflakes`: отсутствие инструмента — самостоятельный
    третий исход, а не число и не скип).
    """
    fake = tmp_path / "scripts"
    fake.mkdir(parents=True)
    (fake / "build_tracker_board.py").write_text(
        "# прибор на месте, двери разбора в нём нет\nX = 1\n", encoding="utf-8")
    mod, why = ptg._board_parser(runner_file=str(tmp_path / "push_to_github.py"))
    assert mod is None, "прибор без двери разбора принят за годный"
    assert "board_status_map" in why, why
    assert "ЗАПРЕЩЕНО" in why, "причина не называет, почему своей копии быть не может"


def test_a_missing_prober_is_unmeasured_too(ptg, tmp_path):
    """Прибора НЕТ вовсе ⇒ тот же третий исход, и причина называет путь."""
    mod, why = ptg._board_parser(runner_file=str(tmp_path / "push_to_github.py"))
    assert mod is None, "отсутствующий прибор принят за годный"
    assert "НЕ ИЗМЕРЕНА" in why, why


def test_the_unmeasured_prober_reaches_the_verdict_not_a_refusal(ptg, tmp_path,
                                                                 incident_card,
                                                                 monkeypatch):
    """Непривезённый прибор доходит до ВЕРДИКТА `unmeasured`, а не до отказа.

    Вторая половина той же дыры: мало вернуть причину из `_board_parser` — она
    обязана стать исходом карточки, а не потеряться по дороге.
    """
    tr = _tracker(tmp_path, card=incident_card,
                  board=_board_naming([INCIDENT_CARD]))
    monkeypatch.setattr(ptg, "_board_parser",
                        lambda runner_file=None: (None, "прибор НЕ ввезён (сцена)"))
    files = [str(tr / INCIDENT_CARD), str(tr / "_BOARD.md")]
    ptg.pin_delivery_bytes(files)
    verdicts = ptg.enforce_delivery_board_row(files)
    assert [v["state"] for v in verdicts] == ["unmeasured"], verdicts
    assert verdicts[0]["reason"] == "прибор НЕ ввезён (сцена)"


def test_the_gate_reads_bytes_through_the_single_pinned_door():
    """Байты доски берутся `read_delivery_bytes`, своего чтения нет (ADR-774)."""
    src = _source("push_to_github.py")
    calls = _calls_in(src, "board_after_delivery")
    assert "read_delivery_bytes" in calls, (
        "гейт читает уезжающую доску мимо единственной двери — судил бы ОДНО "
        "чтение, а уехало бы ДРУГОЕ")
    assert "open" not in calls, "у гейта завелось своё чтение диска"


def test_both_delivery_doors_call_the_gate():
    """Реализация ОДНА, дверей ДВЕ — иначе batch-CLI везёт класс целиком."""
    for rel, fn in (("push_to_github.py", "main"),
                    ("push_to_github_batch.py", "main")):
        calls = _calls_in(_source(rel), fn)
        assert "enforce_delivery_board_row" in calls, (
            f"{rel}::{fn}() гейта не зовёт — вторая дверь доставки пропускала "
            f"бы карточку без строки молча")


def test_the_batch_door_imports_the_gate_and_keeps_no_second_copy():
    """Batch-CLI ИМПОРТИРУЕТ дверь, а не повторяет её (ADR-796 п. 5)."""
    src = _source("push_to_github_batch.py")
    assert "_root_push.enforce_delivery_board_row" in src, (
        "batch-дверь не берёт реализацию у канона")
    assert "enforce_delivery_board_row" not in {n for n in _functions(src)}, (
        "в batch-двери завелась ВТОРАЯ копия гейта")


def test_the_exit_code_is_its_own_and_not_shared():
    """У отказа СВОЙ код возврата: иначе вызывающий не отличит его от соседей."""
    ptg = _load("_board_row_gate_codes", "push_to_github.py")
    codes = {ptg.BYTES_DRIFT_EXIT, ptg.DELIVERY_TREE_EXIT, ptg.NOT_PYTHON_EXIT,
             ptg.FAT_ADR_TITLE_EXIT, ptg.ADR_INTERLOCK_EXIT,
             ptg.MUTATION_WINDOW_EXIT, ptg.CHANGE_EVIDENCE_EXIT}
    assert ptg.CARDLESS_BOARD_EXIT not in codes, (
        f"код {ptg.CARDLESS_BOARD_EXIT} уже занят соседним отказом")
