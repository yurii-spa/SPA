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


# ═════════════════════════════════════════════════════════════════════════════
# G. ОСЬ 2 (ADR-1062) — СТРОКА ЕСТЬ, А СТАТУС НА НЕЙ ДРУГОЙ
#
# ADR-1060 закрыл ось 1 («строки нет вовсе») и ось 2 оставил НЕ ИЗМЕРЕННОЙ с
# названной причиной. Цикл #1204 её ИЗМЕРИЛ прибором
# `scripts/board_status_axis_census.py` на ПОЛНОМ зеркале (прод-клон усечён и на
# вопрос об истории пути отвечать не способен — поправка #1031):
#
#   вершин, тронувших очередь : 1925        пар «вершина × карточка» : 3797
#   согласие                  : 2764        ОСЬ 2 · СТАТУС ДРУГОЙ    :  287 в 141 вершине
#   ось 1 · строки нет        :  654        возврат к прежним байтам :    0
#
# Направление ОДНОРОДНО: доска говорила `new`/`needs-owner`/`backlog` о карточке,
# которая сама объявляла `done`/`ingested`. У 110 пар из 287 индекс числил за
# ВЛАДЕЛЬЦЕМ работу, на которую он уже ответил, — тот же дефект, что замер #436.
#
# `revert_shaped: 0` на всех 3797 парах и есть ответ на вопрос заказа «можно ли
# судить ось статуса, не угадывая»: единственное состояние, в котором доска несла
# бы статус origin ЗАКОННО (байты карточки дословно равны прежней версии того же
# пути ⇒ сверка назвала бы её `stale`), в истории не встретилось НИ РАЗУ.
#
# Положительный контроль — ДОСЛОВНЫЕ байты вершины `36de624ca`, а не выдуманный
# «похожий» файл: доска того коммита объявляла карточку `needs-owner`, сама
# карточка — `ingested`.
# ═════════════════════════════════════════════════════════════════════════════

#: Вершина замера, у которой доска и карточка расходились СТАТУСОМ.
STATUS_INCIDENT_VERTEX = "36de624ca4cb78d4c5c08bde9db2c708983dd2b0"
STATUS_INCIDENT_BOARD_BLOB = "cce42589094e1fdc9d77f4202d89b8df21727743"
STATUS_INCIDENT_CARD_BLOB = "852dd87500b08d06b00ab5e9c260e415cdcc5ef2"
STATUS_INCIDENT_CARD = "owner-decision-utochnenie-po-zametke-kupit-zont-v-pyatn-6.md"
#: Что говорили обе стороны в тот момент. Не «похоже», а ПРОЧИТАНО у блобов.
STATUS_INCIDENT_CARD_SAYS = "ingested"
STATUS_INCIDENT_BOARD_SAYS = "needs-owner"


@pytest.fixture(scope="module")
def status_incident_board() -> bytes:
    return _blob(STATUS_INCIDENT_BOARD_BLOB)


@pytest.fixture(scope="module")
def status_incident_card() -> bytes:
    return _blob(STATUS_INCIDENT_CARD_BLOB)


def _board_naming_with_status(names, status: str) -> bytes:
    """Доска, называющая карточки под ОБЪЯВЛЕННЫМ заголовком статуса.

    Статус здесь ВХОД сцены, а не умолчание: у `_board_naming` он был зашит
    (`### · new`) и совпадал со статусом карточки аварии СЛУЧАЙНО. Сцена, чьё
    согласие случайно, не различает «ось 2 зелена» и «ось 2 не задаёт вопроса», —
    а мутация без различающей сцены выживает (урок #1202).
    """
    rows = "\n".join(f"- заголовок  ·  `{n}` · 2026-11-19" for n in names)
    return (f"# Board\n\n## 📥 Inbox  ({len(names)})\n\n"
            f"### · {status}\n{rows}\n").encode("utf-8")


def _card_with_status(status: str, title: str = "сцена") -> bytes:
    """Карточка, объявляющая ровно переданный статус."""
    return (f"---\ntrackerStatus:\n  type: inbox\ntitle: \"{title}\"\n"
            f"status: {status}\ncreated: 2026-11-19\n---\n\n# {title}\n"
            ).encode("utf-8")


def test_the_status_incident_bytes_are_the_ones_measured(status_incident_board,
                                                         status_incident_card,
                                                         ptg):
    """Предпосылка контроля: взяты ИМЕННО байты замера, и обе стороны прочитаны.

    Без этой пробы остальные тесты раздела могли бы стоять на «похожем» файле —
    ровно то, что § «проверка сторожа сторожей» запрещает.
    """
    assert ptg.git_blob_sha(status_incident_board) == STATUS_INCIDENT_BOARD_BLOB
    assert ptg.git_blob_sha(status_incident_card) == STATUS_INCIDENT_CARD_BLOB
    btb = _load("_btb_for_status_axis", "scripts/build_tracker_board.py")
    assert btb.card_status(status_incident_card.decode()) == \
        STATUS_INCIDENT_CARD_SAYS, "карточка аварии говорит не то, что записано"
    rows = btb.board_status_map(status_incident_board.decode())
    assert rows.get(STATUS_INCIDENT_CARD) == STATUS_INCIDENT_BOARD_SAYS, (
        "доска аварии говорит не то, что записано")


def test_the_status_incident_is_refused_and_both_sides_named(
        ptg, tmp_path, status_incident_board, status_incident_card):
    """Дословная авария оси 2: отказ называет ОБА статуса, починку и обход."""
    tr = _tracker(tmp_path, card=status_incident_card,
                  card_name=STATUS_INCIDENT_CARD, board=status_incident_board)
    files = [str(tr / STATUS_INCIDENT_CARD), str(tr / "_BOARD.md")]
    ptg.pin_delivery_bytes(files)
    with pytest.raises(ptg.DeliveredCardBoardStatusDiffers) as e:
        ptg.enforce_delivery_board_row(files)
    msg = str(e.value)
    assert STATUS_INCIDENT_CARD in msg, "отказ не называет карточку"
    assert STATUS_INCIDENT_CARD_SAYS in msg, "отказ не называет статус КАРТОЧКИ"
    assert STATUS_INCIDENT_BOARD_SAYS in msg, "отказ не называет статус ДОСКИ"
    assert "build_tracker_board.py" in msg, "отказ не называет починку"
    assert "--allow-stale-board-status" in msg, "отказ не называет обход"
    assert "инв. #14" in msg, (
        "отказ не запрещает править СТАТУС КАРТОЧКИ под доску — а это первое, "
        "что придёт в голову тому, кто читает отказ впервые")


def test_the_same_card_passes_once_the_board_says_the_same_status(
        ptg, tmp_path, status_incident_card):
    """ОБРАТНАЯ сторона: доска называет ТОТ ЖЕ статус ⇒ гейт зелен.

    Без неё отказ выше неотличим от гейта, который отказывает всегда.
    """
    tr = _tracker(tmp_path, card=status_incident_card,
                  card_name=STATUS_INCIDENT_CARD,
                  board=_board_naming_with_status([STATUS_INCIDENT_CARD],
                                                  STATUS_INCIDENT_CARD_SAYS))
    files = [str(tr / STATUS_INCIDENT_CARD), str(tr / "_BOARD.md")]
    ptg.pin_delivery_bytes(files)
    verdicts = ptg.enforce_delivery_board_row(files)
    assert [v["state"] for v in verdicts] == ["named"], verdicts
    assert verdicts[0]["card_says"] == STATUS_INCIDENT_CARD_SAYS
    assert "названы все" in ptg.delivery_board_row_summary()


def test_axis_one_wins_over_axis_two_and_stays_distinguishable(
        ptg, tmp_path, status_incident_card):
    """Строки нет ВОВСЕ ⇒ отказ ОСИ 1, а не оси 2 — вердикты не склеены.

    «Строки нет» — утверждение сильнее, чем «статус другой». Сложи их в один
    отказ, и ответ ADR-1060 перестал бы быть различимым у кода возврата.
    """
    tr = _tracker(tmp_path, card=status_incident_card,
                  card_name=STATUS_INCIDENT_CARD,
                  board=_board_naming_with_status(["someone-else.md"], "new"))
    files = [str(tr / STATUS_INCIDENT_CARD), str(tr / "_BOARD.md")]
    ptg.pin_delivery_bytes(files)
    with pytest.raises(ptg.DeliveredCardHasNoBoardRow):
        ptg.enforce_delivery_board_row(files)
    assert [v["state"] for v in ptg._BOARD_ROW_VERDICTS] == ["absent"]


def test_the_named_bypass_turns_the_refusal_into_a_printed_warning(
        ptg, tmp_path, status_incident_board, status_incident_card, capsys):
    """Обход НАЗВАН и ПЕЧАТАЕТСЯ, а вердикт остаётся `status_differs`.

    Обход, который стирал бы вердикт, превращал бы осознанное решение в
    молчание — то есть ровно в то, против чего ось написана.
    """
    tr = _tracker(tmp_path, card=status_incident_card,
                  card_name=STATUS_INCIDENT_CARD, board=status_incident_board)
    files = [str(tr / STATUS_INCIDENT_CARD), str(tr / "_BOARD.md")]
    ptg.pin_delivery_bytes(files)
    verdicts = ptg.enforce_delivery_board_row(files, allow_stale_status=True)
    assert [v["state"] for v in verdicts] == ["status_differs"], verdicts
    out = capsys.readouterr().out
    assert "--allow-stale-board-status" in out, "обход не НАПЕЧАТАН"
    # ПОИМЁННАЯ строка, а не итоговая: первая редакция проверяла подстроку
    # «СТАТУС ДРУГОЙ», которая есть И в итоговой строке, поэтому снятие
    # поимённой печати мутацию НЕ убивало — проба не различала два разных
    # утверждения.
    assert "СТАТУС НА ДОСКЕ ДРУГОЙ" in out, (
        "поимённый вердикт оси 2 не напечатан — читатель узнал бы ЧИСЛО "
        "расхождений, но не узнал бы, У КАКОЙ карточки и какие два статуса")
    assert STATUS_INCIDENT_CARD_SAYS in out and STATUS_INCIDENT_BOARD_SAYS in out, (
        "оба статуса в поимённой строке не напечатаны")


def test_the_bypass_of_axis_one_does_not_silence_axis_two(
        ptg, tmp_path, status_incident_board, status_incident_card):
    """`--allow-cardless-board` ось 2 НЕ гасит: у каждой оси свой обход.

    Иначе один флаг снимал бы ДВА вопроса, и «я разрешил отсутствие строки»
    молча означало бы «и соврать о статусе тоже можно».
    """
    tr = _tracker(tmp_path, card=status_incident_card,
                  card_name=STATUS_INCIDENT_CARD, board=status_incident_board)
    files = [str(tr / STATUS_INCIDENT_CARD), str(tr / "_BOARD.md")]
    ptg.pin_delivery_bytes(files)
    with pytest.raises(ptg.DeliveredCardBoardStatusDiffers):
        ptg.enforce_delivery_board_row(files, allow=True)


def test_a_card_without_a_status_field_is_unmeasured_not_agreed(
        ptg, tmp_path):
    """Поля `status:` нет вовсе ⇒ НЕ ИЗМЕРЕНО с причиной, а не «совпало».

    Третий исход (инв. #17): доске нечего подтверждать, и «совпало» здесь было
    бы утверждением о замере, которого не было.
    """
    name = "inbox-bez-statusa.md"
    card = b"---\ntrackerStatus:\n  type: inbox\ntitle: \"no status\"\n---\n\n# x\n"
    tr = _tracker(tmp_path, card=card, card_name=name,
                  board=_board_naming_with_status([name], "new"))
    files = [str(tr / name), str(tr / "_BOARD.md")]
    ptg.pin_delivery_bytes(files)
    verdicts = ptg.enforce_delivery_board_row(files)
    assert [v["state"] for v in verdicts] == ["unmeasured"], verdicts
    assert "status:" in verdicts[0]["reason"], verdicts[0]["reason"]
    assert "НЕ ИЗМЕРЕНО" in ptg.delivery_board_row_summary()


def test_a_missing_status_door_is_unmeasured_and_does_not_stop_delivery(
        ptg, tmp_path, monkeypatch):
    """Мерки нет ⇒ НЕ ИЗМЕРЕНО с названной причиной, доставка КОДА не встаёт.

    Прибор без двери `card_status` — это «мерить нечем», а не «статус совпал»;
    и останавливать доставку кода от того, что мерка не ввезена, значило бы
    запереть пуш, ничего не измерив (тот же названный выбор, что у оси 1).
    """
    name = "inbox-dver-propala.md"
    card = _card_with_status("done")
    tr = _tracker(tmp_path, card=card, card_name=name,
                  board=_board_naming_with_status([name], "new"))
    files = [str(tr / name), str(tr / "_BOARD.md")]

    real = _load("_btb_no_status_door", "scripts/build_tracker_board.py")

    class _NoStatusDoor:
        board_status_map = staticmethod(real.board_status_map)

    monkeypatch.setattr(ptg, "_board_parser",
                        lambda runner_file=None: (_NoStatusDoor(), None))
    ptg.pin_delivery_bytes(files)
    verdicts = ptg.enforce_delivery_board_row(files)
    assert [v["state"] for v in verdicts] == ["unmeasured"], verdicts
    assert "card_status" in verdicts[0]["reason"], verdicts[0]["reason"]


def test_the_status_is_read_through_the_generators_own_door(ptg):
    """Статус читает ДВЕРЬ ГЕНЕРАТОРА, своей копии разбора у гейта нет.

    Разойдись они — гейт считал бы согласием то, что сборка доски считает
    расхождением, то есть пропускал ровно тот класс, ради которого написан.
    """
    btb = _load("_btb_single_door", "scripts/build_tracker_board.py")
    assert hasattr(btb, "card_status"), (
        "у генератора нет двери `card_status` — гейту пришлось бы завести свою")
    # Сборка доски обязана спрашивать ТУ ЖЕ дверь, иначе копий снова две.
    assert "card_status" in _calls_in(_source("scripts/build_tracker_board.py"),
                                      "card_dict"), (
        "`card_dict` читает статус МИМО собственной двери — у правила снова две "
        "копии, и расходиться им ничто не мешает")
    src = _source("push_to_github.py")
    calls = _calls_in(src, "_card_status_of")
    assert "card_status" in calls, "гейт не зовёт дверь генератора"
    assert "parse_frontmatter" not in calls, (
        "у гейта завелась СВОЯ копия разбора frontmatter")


def test_the_status_axis_does_not_pass_by_substring(ptg, tmp_path):
    """Не проходит ПОДСТРОКОЙ (ADR-333): `done` ВХОДИТ в `owner-done`.

    **Пара здесь ИЗМЕРЕНА, а не выдумана, и первая редакция этого теста на том
    и споткнулась.** Там стояло «`new` внутри `needs-owner`», и мутация
    сравнения подстрокой ВЫЖИЛА: `new` в `needs-owner` не входит вовсе
    (n-e-e-d-s-o-w-n-e-r), то есть тест называл подстрокой то, что ею не
    является, и мерил согласие двух НЕ пересекающихся строк. Настоящая
    подстрочная пара словаря статусов — `done` ⊂ `owner-done`, и обе стороны в
    замере встречаются.
    """
    name = "inbox-podstroka.md"
    assert "done" in "owner-done", (
        "предпосылка теста: пара обязана быть ПОДСТРОЧНОЙ, иначе мутация "
        "сравнения подстрокой выживет, а тест будет выглядеть зелёным")
    tr = _tracker(tmp_path, card=_card_with_status("done"), card_name=name,
                  board=_board_naming_with_status([name], "owner-done"))
    files = [str(tr / name), str(tr / "_BOARD.md")]
    ptg.pin_delivery_bytes(files)
    with pytest.raises(ptg.DeliveredCardBoardStatusDiffers):
        ptg.enforce_delivery_board_row(files)


def test_the_status_axis_exit_code_is_its_own():
    """У оси 2 СВОЙ код возврата: 17 и 18 — разные утверждения об индексе."""
    ptg = _load("_board_status_codes", "push_to_github.py")
    taken = {ptg.BYTES_DRIFT_EXIT, ptg.DELIVERY_TREE_EXIT, ptg.NOT_PYTHON_EXIT,
             ptg.FAT_ADR_TITLE_EXIT, ptg.ADR_INTERLOCK_EXIT,
             ptg.MUTATION_WINDOW_EXIT, ptg.CHANGE_EVIDENCE_EXIT,
             ptg.CARDLESS_BOARD_EXIT}
    assert ptg.STALE_BOARD_STATUS_EXIT not in taken, (
        f"код {ptg.STALE_BOARD_STATUS_EXIT} уже занят соседним отказом — "
        f"читатель не отличит «строки нет» от «статус другой»")


def test_both_delivery_doors_declare_and_wire_the_status_bypass():
    """Обе двери доставки ловят ось 2 и объявляют её обход СВОИМ флагом."""
    for rel in ("push_to_github.py", "push_to_github_batch.py"):
        src = _source(rel)
        assert "--allow-stale-board-status" in src, (
            f"{rel} не объявляет обход оси 2 — осознанный обход, которого нет в "
            f"argparse, есть обход, которым нельзя воспользоваться")
        assert "DeliveredCardBoardStatusDiffers" in src, (
            f"{rel} ось 2 не ловит — отказ ушёл бы наружу как «пушер сломался»")
        assert "STALE_BOARD_STATUS_EXIT" in src, (
            f"{rel} не выходит СВОИМ кодом оси 2")
    batch = _source("push_to_github_batch.py")
    assert "allow_stale_status=allow_stale_board_status" in batch, (
        "batch-дверь флаг объявила, но до гейта его НЕ ДОВЕЛА — половина "
        "проводки есть та же бомба, что отсутствие флага, только с argparse")


def test_the_census_declares_its_outcomes_and_the_revert_case(ptg):
    """Перепись объявляет ЗАКРЫТЫЙ перечень исходов, и `revert_shaped` в нём.

    Исход «возврат к прежним байтам» — единственное состояние, в котором доска
    несёт статус origin ЗАКОННО. Не объяви его перепись отдельно — она сложила
    бы его в находки и завысила класс, то есть выдумала бы дефект.
    """
    census = _load("_board_status_census", "scripts/board_status_axis_census.py")
    assert "revert_shaped" in census.OUTCOMES, (
        "перепись не различает возврат к прежним байтам — судила бы законное "
        "поведение доски как находку")
    for door in ("agree", "disagree", "no_row", "unmeasured"):
        assert door in census.OUTCOMES, f"исход `{door}` не объявлен"
    assert census.history_completeness(Path("/")).get("state") in {
        "unmeasured", "shallow", "complete"}, (
        "у вопроса о полноте клона нет трёх исходов")


def test_the_census_refuses_a_truncated_clone(tmp_path):
    """Усечённый клон — ТРЕТИЙ ИСХОД, а не ответ (поправка #1031).

    На усечённом графе `git log -- <путь>` возвращает ПУСТО кодом 0, то есть
    «истории нет» неотличимо от «её здесь нет», и ошибка идёт в ОПАСНУЮ сторону:
    усечение РОЖДАЕТ находку, которой нет.
    """
    census = _load("_board_status_census_shallow",
                   "scripts/board_status_axis_census.py")
    repo = tmp_path / "shallow"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", "."], cwd=repo,
                   capture_output=True, check=True)
    (repo / ".git" / "shallow").write_text("0" * 40 + "\n")
    verdict = census.history_completeness(repo)
    assert verdict["state"] == "shallow", verdict
    assert "УСЕЧ" in verdict["reason"], verdict
    rc = census.main(["--repo-root", str(repo), "--limit", "5"])
    assert rc == 2, f"усечённый клон дал код {rc}, а НЕ ИЗМЕРЕНО — это код 2"


def test_the_census_takes_its_parsers_from_the_running_tree_not_the_graph():
    """Мерка — из дерева ПРИБОРА, граф — из полного клона: входы РАЗНЫЕ.

    Первая редакция переписи ввозила двери из клона, у которого спрашивает
    историю, и честно отказала кодом 2: зеркало отстаёт от рабочего дерева, и
    двери `card_status` там ещё нет. Отказ был ВЕРЕН, вопрос — не тот.
    """
    src = _source("scripts/board_status_axis_census.py")
    fn = _functions(src)["_parsers"]
    assert not fn.args.args, (
        "`_parsers` снова принимает клон истории — мерка пришла бы из графа, то "
        "есть перепись судила бы доставляемый код ЧУЖОЙ, отстающей копией правила")
    # Подпись — не ответ: мутация, подставившая путь зеркала ЛИТЕРАЛОМ, подпись
    # не трогает и прежнюю редакцию этой пробы ПЕРЕЖИВАЛА. Спрашиваем, откуда
    # мерка пришла НА САМОМ ДЕЛЕ.
    census = _load("_board_status_census_door",
                   "scripts/board_status_axis_census.py")
    btb = census._parsers()
    got = Path(btb.__file__).resolve()
    assert got == (ROOT / "scripts" / "build_tracker_board.py").resolve(), (
        f"мерка ввезена НЕ из дерева прибора, а из {got} — перепись судила бы "
        f"доставляемый код чужой, отстающей копией правила")


def test_the_card_bytes_also_come_through_the_single_pinned_door():
    """Байты КАРТОЧКИ тоже берутся `read_delivery_bytes` (ADR-774).

    Соседний тест стережёт байты ДОСКИ. У оси 2 читаемых файлов ДВА, и своё
    чтение карточки вернуло бы предмет ADR-774 на новом месте: гейт судил бы
    ОДНИ байты, а уехали бы ДРУГИЕ.
    """
    src = _source("push_to_github.py")
    calls = _calls_in(src, "enforce_delivery_board_row")
    assert "read_delivery_bytes" in calls, (
        "гейт читает уезжающую карточку мимо единственной двери")
    assert "open" not in calls, "у оси 2 завелось своё чтение диска"


def test_the_census_asks_the_revert_question_before_calling_it_a_finding():
    """Перепись СПРАШИВАЕТ про возврат, а не только объявляет исход.

    Объявленный в `OUTCOMES` и никогда не задаваемый вопрос есть ЛОЖНОЕ
    усиление: перечень выглядит полным, а законное поведение доски всё равно
    попадает в находки и завышает класс.
    """
    src = _source("scripts/board_status_axis_census.py")
    assert "_looks_like_revert" in _calls_in(src, "measure"), (
        "`measure` про возврат к прежним байтам не спрашивает — исход "
        "`revert_shaped` объявлен и НЕДОСТИЖИМ")
    body = src.split("def _looks_like_revert")[1].split("\ndef ")[0]
    assert "hash-object" in body, (
        "возврат судится не по БАЙТАМ — «похоже старее» признаком не является")
    assert '"-w"' not in body and "'-w'" not in body, (
        "перепись пишет в объектную базу ЧУЖОГО клона (`hash-object -w`) — "
        "прибор обязан только ЧИТАТЬ того, у кого лишь спрашивает")


def _census_scene(root: Path, steps) -> Path:
    """Одноразовый репозиторий очереди: по коммиту на шаг `(статус карточки, статус доски)`.

    Имя ветки ОБЪЯВЛЕНО (`git init -b main`): `init.defaultBranch` есть свойство
    ХОСТА, и фикстура, назвавшая потом `origin/main`, была бы зелена здесь и
    красна на раннере (`.claude/rules/deployment.md`, § «GIT-ОКРУЖЕНИЕ»).
    `origin/main` создаётся ссылкой — перепись спрашивает именно её.
    """
    repo = root / "scene"
    tr = repo / TRACKER_REL
    tr.mkdir(parents=True)
    run = lambda *a: subprocess.run(["git", *a], cwd=repo, capture_output=True,
                                    check=True)
    run("init", "-b", "main", ".")
    run("config", "user.email", "scene@example.invalid")
    run("config", "user.name", "scene")
    name = "inbox-stsena.md"
    for i, (card_status, board_status, title) in enumerate(steps):
        (tr / name).write_bytes(_card_with_status(card_status, title))
        (tr / "_BOARD.md").write_bytes(
            _board_naming_with_status([name], board_status))
        run("add", "-A")
        run("commit", "-m", f"шаг {i}")
    run("update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


def test_the_census_calls_a_reverted_card_a_revert_and_not_a_finding(tmp_path):
    """СЦЕНА, а не AST: байты карточки вернулись к прежним ⇒ `revert_shaped`.

    **Эта проба написана потому, что прежняя ВЫЖИЛА мутацию.** Там стоял разбор
    AST («`measure` зовёт `_looks_like_revert`»), а мутация `if False and
    _looks_like_revert(...)` зов ОСТАВЛЯЕТ на месте — присутствие вызова в
    дереве разбора не есть его ДОСТИЖИМОСТЬ. Отличить объявленный исход от
    достижимого может только сцена, в которой он НАСТУПАЕТ.
    """
    census = _load("_census_revert_scene", "scripts/board_status_axis_census.py")
    # шаг 0: согласие · шаг 1: карточка ушла в `new` · шаг 2: байты ВЕРНУЛИСЬ к
    # шагу 0, доска осталась на `new` ⇒ расхождение ЕСТЬ, но это ВОЗВРАТ.
    repo = _census_scene(tmp_path, [("done", "done", "одно"),
                                    ("new", "new", "другое"),
                                    ("done", "new", "одно")])
    report = census.measure(repo)
    assert report["tally"]["revert_shaped"] == 1, report["tally"]
    assert report["tally"]["disagree"] == 0, (
        f"возврат к прежним байтам зачтён НАХОДКОЙ — перепись завысила бы "
        f"класс, объявив дефектом законное поведение доски: {report['tally']}")


def test_the_census_still_calls_a_fresh_divergence_a_finding(tmp_path):
    """ОБРАТНАЯ половина той же сцены: байты НОВЫЕ ⇒ это находка, а не возврат.

    Без неё проба выше неотличима от переписи, которая объявляет возвратом
    ВСЁ и потому не находит ничего.
    """
    census = _load("_census_fresh_scene", "scripts/board_status_axis_census.py")
    repo = _census_scene(tmp_path, [("done", "done", "одно"),
                                    ("new", "new", "другое"),
                                    ("done", "new", "ТРЕТЬЕ, новых байт")])
    report = census.measure(repo)
    assert report["tally"]["disagree"] == 1, report["tally"]
    assert report["tally"]["revert_shaped"] == 0, report["tally"]
    assert report["findings"][0]["card_says"] == "done"
    assert report["findings"][0]["board_says"] == "new"


def test_the_summary_line_distinguishes_all_three_states(ptg, tmp_path,
                                                         status_incident_board,
                                                         status_incident_card):
    """Итоговая строка — СВОЁ утверждение, и три состояния в ней РАЗЛИЧИМЫ.

    **Эта проба написана потому, что две соседние делили одну подстроку.**
    Контроль обхода проверял вхождение «СТАТУС ДРУГОЙ», которое есть И в
    поимённой строке, И в итоговой; поэтому снятие одной из двух печатей
    вердикт пробы не меняло, и мутация выживала — сперва одна, после починки
    другая. Утверждение об ИТОГЕ обязано иметь свою пробу, а не быть побочным
    следствием чужой.
    """
    name = "inbox-itog.md"

    def _summary(board: bytes, card: bytes, **kw) -> str:
        tr = _tracker(tmp_path / board[:8].hex(), card=card, card_name=name,
                      board=board)
        files = [str(tr / name), str(tr / "_BOARD.md")]
        ptg.pin_delivery_bytes(files)
        try:
            ptg.enforce_delivery_board_row(files, **kw)
        except (ptg.DeliveredCardHasNoBoardRow,
                ptg.DeliveredCardBoardStatusDiffers):
            pass
        out = ptg.delivery_board_row_summary()
        ptg.reset_delivery_pin()
        return out

    agreed = _summary(_board_naming_with_status([name], "done"),
                      _card_with_status("done"))
    differs = _summary(_board_naming_with_status([name], "new"),
                       _card_with_status("done"))
    absent = _summary(_board_naming_with_status(["other.md"], "new"),
                      _card_with_status("done"))

    assert "названы все" in agreed, agreed
    assert "СТАТУС ДРУГОЙ" in differs, differs
    assert "НЕ НАЗВАНО" in absent, absent
    assert len({agreed, differs, absent}) == 3, (
        f"итоговая строка не различает три состояния — читатель одной строки "
        f"не узнает, что именно нашлось: {agreed!r} / {differs!r} / {absent!r}")


# ═════════════════════════════════════════════════════════════════════════════
# H. ЧИСЛО В ОТКАЗЕ — ЗАМЕР, И ЖИВЁТ ОНО У ПРИБОРА
#
# Отказ объясняет себя числом (287 пар в 141 вершине). Своя копия этого числа у
# гейта превратила бы замер в константу — тот самый дефект, за который проект уже
# платил: строка «~3,3 % фактических» стояла руками в ШЕСТНАДЦАТИ местах, между
# собой не расходилась ни на йоту (проверка на расхождение была зелёной), а трек в
# тот день давал 5,3 % (`.claude/rules/site-numbers.md`).
#
# Побочно это и есть ПРОВОДКА прибора: скрипт, которого никто не зовёт, храповик
# `test_unwired_scripts_ratchet` объявляет «доставленным и мёртвым», и дописывать
# его в базу ЗАПРЕЩЕНО (инв. #16). Здесь он зван по делу, а не для сторожа.
# ═════════════════════════════════════════════════════════════════════════════
def test_the_refusal_number_comes_from_the_prober_not_a_local_copy(ptg):
    """Гейт читает замер у прибора, своей копии числа у него НЕТ."""
    pop, why = ptg.board_status_population()
    assert why is None, why
    assert pop["disagree"] == 287 and pop["disagree_vertices"] == 141, pop
    src = _source("push_to_github.py")
    # Число не должно стоять ЛИТЕРАЛОМ в двери доставки: это и есть «вторая копия».
    gate = src.split("def _board_status_measurement_line")[1].split("\ndef ")[0]
    assert "287" not in gate and "141" not in gate, (
        "население оси 2 вписано в гейт ЛИТЕРАЛОМ — замер стал константой, и "
        "перемер прибором её уже не поправит")


def test_the_prober_declares_the_measurement_with_its_date_and_window():
    """Замер несёт ДАТУ и ОКНО: число без них — намерение, а не наблюдение."""
    census = _load("_census_population", "scripts/board_status_axis_census.py")
    pop = census.POPULATION
    for key in ("measured_at", "window", "vertices_scanned", "pairs_measured",
                "agree", "disagree", "disagree_vertices", "revert_shaped",
                "unmeasured", "claimed_for_owner"):
        assert key in pop, f"в замере не объявлено поле `{key}`"
    assert pop["agree"] + pop["disagree"] + pop["no_row"] + \
        pop["revert_shaped"] + pop["unmeasured"] == pop["pairs_measured"], (
        f"исходы не складываются в измеренное население — часть пар потерялась "
        f"молча: {pop}")


def test_an_unreadable_prober_is_named_and_does_not_invent_a_number(ptg,
                                                                    tmp_path):
    """Прибора нет ⇒ отказ ГОВОРИТ это, а не печатает число по умолчанию.

    Третий исход (инв. #17): «замер недоступен» и «население ноль» — разные
    ответы. Отказ при этом остаётся в силе: он про ЭТУ доставку, а не про историю.
    """
    fake_runner = tmp_path / "push_to_github.py"
    fake_runner.write_text("# дерево без прибора переписи\n")
    pop, why = ptg.board_status_population(str(fake_runner))
    assert pop is None and why, (pop, why)
    assert "НЕ ИЗМЕРЕН" in why, why
    line = ptg._board_status_measurement_line(str(fake_runner))
    assert "НЕ ПРОЧИТАН" in line, line
    assert "287" not in line, "гейт выдумал число, не прочитав прибора"
    assert "Отказ это не отменяет" in line, (
        "отказ про ЭТУ доставку обязан остаться в силе: недоступность замера "
        "истории к уезжающим байтам отношения не имеет")


def test_a_prober_without_a_measurement_is_also_named_not_zero(ptg, tmp_path):
    """Прибор ЕСТЬ, а замера в нём НЕТ ⇒ тоже НЕ ИЗМЕРЕНО, а не ноль.

    **У третьего исхода ДВЕ причины, и соседняя проба закрывала только одну.**
    Там дерево было без файла переписи вовсе, поэтому отказывал ввоз, и ветка
    «ввезли, но замера не несёт» не исполнялась ни одной сценой — мутация,
    подставлявшая `{"disagree": 0}` умолчанием `getattr`, ВЫЖИЛА. Ноль,
    подставленный вместо замера, — это инв. #17 наизнанку: «мерить нечем»
    печаталось бы как «класс пуст».
    """
    fake = tmp_path / "tree"
    (fake / "scripts").mkdir(parents=True)
    (fake / "push_to_github.py").write_text("# судья\n")
    (fake / "scripts" / "board_status_axis_census.py").write_text(
        "# перепись есть, замера в ней нет\nOUTCOMES = ()\n")
    pop, why = ptg.board_status_population(str(fake / "push_to_github.py"))
    assert pop is None, f"гейт принял прибор без замера: {pop}"
    assert "POPULATION" in why, why
    line = ptg._board_status_measurement_line(str(fake / "push_to_github.py"))
    assert "НЕ ПРОЧИТАН" in line, line
    assert " 0 пар" not in line, "ноль подставлен вместо замера"


def test_the_census_total_counts_the_unmeasured_pairs_too(tmp_path):
    """`pairs_measured` включает НЕ ИЗМЕРЕННЫЕ пары — иначе они теряются молча.

    **Сцена с НЕНУЛЕВЫМ `unmeasured` обязательна, и без неё мутация выживает.**
    Соседняя проба сверяет сумму в ОБЪЯВЛЕННОМ замере, а не в живом счёте
    прибора; у всех прежних сцен `unmeasured` был 0, поэтому слагаемое можно было
    выкинуть из суммы, ничего не покраснив. Пара, выпавшая из итога, — это
    «не измерено», выданное за отсутствие предмета.
    """
    census = _load("_census_total_scene", "scripts/board_status_axis_census.py")
    repo = tmp_path / "scene"
    tr = repo / TRACKER_REL
    tr.mkdir(parents=True)
    run = lambda *a: subprocess.run(["git", *a], cwd=repo, capture_output=True,
                                    check=True)
    run("init", "-b", "main", ".")
    run("config", "user.email", "scene@example.invalid")
    run("config", "user.name", "scene")
    name = "inbox-udalyaemaya.md"
    (tr / name).write_bytes(_card_with_status("done"))
    (tr / "_BOARD.md").write_bytes(_board_naming_with_status([name], "done"))
    run("add", "-A")
    run("commit", "-m", "карточка есть")
    (tr / name).unlink()                      # вершина УДАЛЯЕТ карточку
    run("add", "-A")
    run("commit", "-m", "карточка удалена")
    run("update-ref", "refs/remotes/origin/main", "HEAD")

    report = census.measure(repo)
    t = report["tally"]
    assert t["unmeasured"] >= 1, (
        f"сцена не обеспечила НЕ ИЗМЕРЕННУЮ пару — без неё проба ничего не "
        f"различает: {t}")
    assert report["pairs_measured"] == sum(t.values()), (
        f"итог не сходится с исходами: {report['pairs_measured']} против "
        f"{sum(t.values())} — пары выпали из счёта МОЛЧА: {t}")
