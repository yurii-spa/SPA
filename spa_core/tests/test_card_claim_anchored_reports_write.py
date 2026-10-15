"""Ответ о захвате обязан МЕРИТЬ запись, а не пересказывать вход (цикл #872, ADR-727).

Что измерено
------------------------------------------------------------------------------
ADR-725 довёл якорь ЗАПУСКАТЕЛЯ до frontmatter карточки, и в ответе `claim_card`
оказались рядом два сообщения об одной и той же записи:

    "worker_run_id": fields.get("claimed_run_id") or None     ← ЗАМЕР записи (ADR-721)
    "anchored":      bool(self_anchor)                        ← ПЕРЕСКАЗ входа

Первое отвечает на вопрос «что ушло в карточку», второе — на вопрос «что мне передали».
Читает же поле тот, кому важно ровно первое: `anchored` называют, чтобы знать, сможет ли
следующий цикл измерить этот захват осью запускателя. Пока обе стороны совпадали,
расхождения видно не было; разойтись они могли МОЛЧА.

И дверь к расхождению стояла открытой: писатель сужал вход выражением
`isinstance(self_anchor, (tuple, list))`, а всё, что под сужение не попало, превращал в
пустую пару БЕЗ единого слова — якорь не писался, захват состоялся, ответ объявлял
`anchored: True`. **Мутация этого сужения переживала весь набор** (замер #869, заказ
G725 п. 2 дословно: «вход, запрещённый контрактом `claim_card`, не проверяется ничем — у
контракта нет сторожа»).

Вход вне контракта правдоподобен, а не выдуман
------------------------------------------------------------------------------
В ТОМ ЖЕ файле якорь живёт ВТОРОЙ формой — СЛОВАРЁМ в вокабуляре шага 0a
(`card_claim_anchor` отдаёт `{"session_pid": …, "session_pid_start": …}`), и именно её
естественно передать в `self_anchor=`. Цена ошибки измерима: захват, который следующий
цикл не измерит НИ ОДНОЙ осью (ось работника молчит без `SPA_RUN_ID`, ось запускателя —
без пары), и который при этом отчитался «якорь есть». Карточка заперта всё окно
`DEFAULT_GRACE_HOURS` — ровно цена, которую #868 заплатил на приказе владельца.

Что проверяется, и почему в ОБЕ стороны
------------------------------------------------------------------------------
* вход вне контракта (словарь, строка, пара не той длины) ⇒ ОТКАЗ с названной причиной,
  а не тихий сброс якоря;
* пара измерена НЕ ЦЕЛИКОМ ⇒ в карточку не пишется НИ ОДНА её строка (половина личностью
  не является: pid переиспользуется ОС) И `anchored` честно False — третий исход
  (инв. #17), а не тихий успех;
* ПРАВИЛЬНАЯ пара ⇒ запись в карточку + `anchored: True`: правка дополняющая, а не
  запрещающая, и это отдельное звено;
* полноту пары решает РОВНО ОДИН судья (`_anchor_pair`) у ОБОИХ читателей — писателя
  frontmatter и поля ответа. Два экземпляра правила маскировали бы друг друга: снятие
  любого перестало бы ловиться (урок #869).

Время и живость — ВХОДЫ, а не окружение
------------------------------------------------------------------------------
Литеральных дат нет: все отметки выведены из якоря `NOW`, он же идёт измерителю
аргументом `now=`. Живость процесса ИНЪЕКТИРОВАНА (`ps=`) — сторож, спрашивающий живую
ОС, менял бы вердикт от того, кто сегодня занял номер
(`.claude/rules/deployment.md` § «ЛИЧНОСТЬ ПРОЦЕССА»). Номер якоря — `os.getpid()`: он
жив на любой машине ПО ПОСТРОЕНИЮ, поэтому сцена не зависит от везения с номером.
"""
import importlib.util
import os
import shutil
from datetime import timedelta
from pathlib import Path

import pytest

from spa_core.monitoring.card_acceptance import (NOT_SATISFIED, PROBES, SATISFIED,
                                                 UNMEASURED)
from spa_core.tests._freshness import now_utc

ROOT = Path(__file__).resolve().parents[2]

PROBE_NAME = "card_claim_anchored_reports_the_write"

#: Якорь времени — РЕАЛЬНЫЕ часы, инъектированные измерителю (`now=`). Литеральная дата
#: здесь начала бы падать от сдвига календаря, а не от кода.
NOW = now_utc().replace(microsecond=0)
#: Старт процесса ЗАВЕДОМО раньше захвата: иначе сцена мерила бы переиспользованный номер.
START = (NOW - timedelta(hours=2)).astimezone().strftime("%a %b %d %H:%M:%S %Y")
#: Номер ЖИВ на любой машине по построению (п. 2 порядка предпочтения из правила
#: доставки): проверке нужен такой, чей ответ ОС не зависит от везения.
PID = os.getpid()

DEAD = lambda _pid: (1, "")                                          # noqa: E731


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load("_c872_card_claim", ROOT / "scripts" / "check_card_claim.py")


@pytest.fixture(scope="module")
def sibling(guard):
    return guard.load_sibling()


@pytest.fixture()
def scene(tmp_path, guard, sibling):
    """Одноразовая карточка + ПУСТОЙ журнал. Возвращает (ответ, исключение, новые поля)."""
    counter = {"n": 0}

    def _run(anchor):
        counter["n"] += 1
        tracker = tmp_path / f"tracker{counter['n']}"
        tracker.mkdir()
        card = tracker / "inbox-scene.md"
        card.write_text("---\ntrackerStatus:\n  type: inbox\ntitle: сцена\n"
                        "status: new\n---\n\nтело\n", encoding="utf-8")
        before = set(guard.frontmatter(card.read_text(encoding="utf-8")) or {})
        log = tmp_path / f"log{counter['n']}.jsonl"
        log.write_text("", encoding="utf-8")
        res = err = None
        try:
            res = guard.claim_card("inbox-scene", log=str(log), session="cycle-872",
                                   tracker_dir=str(tracker), now=NOW, sibling=sibling,
                                   ps=DEAD, self_anchor=anchor)
        except Exception as exc:                     # noqa: BLE001
            err = exc
        meta = guard.frontmatter(card.read_text(encoding="utf-8")) or {}
        fresh = {k: str(meta.get(k) or "") for k in set(meta) - before}
        return res, err, fresh

    return _run


# ── ЕДИНСТВЕННЫЙ СУДЬЯ ПОЛНОТЫ ПАРЫ ──────────────────────────────────────────

def test_the_pair_judge_accepts_only_a_whole_pair(guard):
    """`_anchor_pair` — одно правило на обоих читателей, и оно судит ПОЛНОТУ."""
    keys = guard.CLAIM_ANCHOR_KEYS
    assert guard._anchor_pair({keys[0]: PID, keys[1]: START}) == (str(PID), START)
    assert guard._anchor_pair({keys[0]: PID, keys[1]: ""}) == ()
    assert guard._anchor_pair({keys[0]: "", keys[1]: START}) == ()
    assert guard._anchor_pair({}) == ()


# ── ВХОД ВНЕ КОНТРАКТА: ОТКАЗ, А НЕ ТИХИЙ СБРОС ──────────────────────────────

def test_the_dict_form_of_the_anchor_is_refused(scene, guard, sibling):
    """ВТОРАЯ форма якоря из того же файла (словарь шага 0a) обязана ОТКАЗАТЬ.

    До ADR-727 этот вход давал захват БЕЗ якоря и ответ `anchored: True` — то есть
    ровно утверждение о записи, которой нет.
    """
    keys = tuple(getattr(sibling, "DURABLE_KEYS", ()))
    res, err, fresh = scene({keys[0]: PID, keys[1]: START})
    assert isinstance(err, guard.ClaimError), f"принято молча: {res!r}"
    assert "вне контракта" in str(err)
    assert not any(k in fresh for k in guard.CLAIM_ANCHOR_KEYS)


@pytest.mark.parametrize("bad", [
    pytest.param("12345 Thu Oct 15 00:00:00 2026", id="строка"),
    pytest.param((PID,), id="пара-из-одного"),
    pytest.param((PID, START, "лишнее"), id="пара-из-трёх"),
])
def test_every_shape_outside_the_contract_is_refused(scene, guard, bad):
    """«Красный на чём-нибудь» ничего не доказывает: у каждой формы своё имя."""
    res, err, fresh = scene(bad)
    assert isinstance(err, guard.ClaimError), f"{bad!r} принято молча: {res!r}"
    assert not any(k in fresh for k in guard.CLAIM_ANCHOR_KEYS)


# ── ТРЕТИЙ ИСХОД: ПАРА ИЗМЕРЕНА НЕ ЦЕЛИКОМ ───────────────────────────────────

def test_half_a_pair_is_not_written_and_is_reported_as_unanchored(scene, guard):
    """Половина пары ⇒ ни одной строки в карточке И честное `anchored: False` (инв. #17)."""
    res, err, fresh = scene((PID, ""))
    assert err is None, f"захват отказал там, где отказывать не должен: {err!r}"
    assert not any(k in fresh for k in guard.CLAIM_ANCHOR_KEYS)
    assert res["anchored"] is False, (
        "ответ объявил якорь записанным, а в карточке его нет — пересказ входа")


# ── ГРАНИЦА: ПРАВИЛЬНАЯ ПАРА РАБОТАЕТ КАК ПРЕЖДЕ ─────────────────────────────

def test_a_whole_pair_is_written_and_reported(scene, guard):
    """Правка дополняющая: измеренная пара по-прежнему едет в карточку и в ответ."""
    res, err, fresh = scene((PID, START))
    assert err is None, f"{err!r}"
    assert fresh[guard.CLAIM_ANCHOR_KEYS[0]].strip() == str(PID)
    assert fresh[guard.CLAIM_ANCHOR_KEYS[1]].strip() == START
    assert res["anchored"] is True


def test_the_report_measures_the_card_not_the_input(scene, guard, monkeypatch):
    """Прямой замер УТВЕРЖДЕНИЯ: ответ следует за ЗАПИСЬЮ, а не за аргументом.

    Судья полноты подменяется так, что пара перестаёт считаться полной. Вход при этом
    не меняется НИ НА БАЙТ. Поле `anchored`, если оно меряет запись, обязано стать
    False вместе с ней; если оно пересказывает вход — останется True.

    **Это же и есть контроль «судья ОДИН».** Правило полноты не продублировано — и
    доказывается это ИСХОДОМ, а не подсчётом строк: порвав единственного судью, мы
    гасим ОБОИХ его читателей разом (строка якоря не уехала в карточку И ответ стал
    False). Будь у кого-то из них своя копия правила, одна из двух проверок ниже
    уцелела бы — ровно тот класс, что нашли мутации #869.
    """
    monkeypatch.setattr(guard, "_anchor_pair", lambda values: ())
    res, err, fresh = scene((PID, START))
    assert err is None, f"{err!r}"
    assert not any(k in fresh for k in guard.CLAIM_ANCHOR_KEYS)
    assert res["anchored"] is False


# ── КОНТРОЛЬ САМОЙ ПРОБЫ: зелена на контуре, красна на каждом порванном звене ─

#: Звенья контура. Каждое — (имя, что рвём, чем подменяем): замена ОБЯЗАНА найтись,
#: иначе «мутация» ничего не мутирует и контроль молча зеленеет на пустом месте.
_LINKS = {
    "контракт входа не проверяется": (
        "    if len(_anchor) != len(CLAIM_ANCHOR_KEYS):",
        "    if False:"),
    "`anchored` пересказывает вход": (
        '           "anchored": bool(_anchor_pair(fields)),',
        '           "anchored": bool(self_anchor),'),
    # Обратная сторона того же поля: оно обязано быть красным и когда занижает. Без
    # этого звена проба доказывала бы только «не завышай», то есть `anchored: False`
    # навсегда сошло бы ей за честность.
    "`anchored` занижает — всегда False": (
        '           "anchored": bool(_anchor_pair(fields)),',
        '           "anchored": False,'),
    "писатель печатает ПОЛОВИНУ пары": (
        "    return pair if all(pair) else ()",
        "    return (pair[0], '') if any(pair) else ()"),
    "писатель не кладёт якорь в поля захвата": (
        "        fields.update(dict(zip(CLAIM_ANCHOR_KEYS, (",
        "        _dropped = (dict(zip(CLAIM_ANCHOR_KEYS, ("),
    # Писатель frontmatter завёл СВОЙ экземпляр правила полноты и он мягче судьи: в
    # карточку уезжает половина пары, а поле `anchored` (оно спрашивает НАСТОЯЩЕГО
    # судью) честно говорит False. Ни одна другая проверка пробы этого не видит —
    # звено существует затем, чтобы та единственная не осталась без контроля.
    "писатель frontmatter судит пару САМ": (
        "    anchor = _anchor_pair(values)\n    if anchor:",
        "    anchor = tuple(str(values.get(key) or \"\").strip()\n                   for key in CLAIM_ANCHOR_KEYS)\n    if any(anchor):"),
}


@pytest.fixture()
def disposable_tree(tmp_path):
    """Одноразовая копия ТРЁХ файлов проводки: живое дерево не трогается."""
    def _make():
        tree = tmp_path / f"tree{len(list(tmp_path.glob('tree*')))}"
        (tree / "scripts").mkdir(parents=True)
        for name in ("check_card_claim.py", "check_undelivered_work.py",
                     "log_session_change.py"):
            shutil.copy2(ROOT / "scripts" / name, tree / "scripts" / name)
        return tree
    return _make


def test_the_probe_is_green_on_the_whole_contour(disposable_tree):
    verdict, why = PROBES[PROBE_NAME](None, repo_root=str(disposable_tree()))
    assert verdict == SATISFIED, why


@pytest.mark.parametrize("link", sorted(_LINKS))
def test_the_probe_is_red_on_every_broken_link(disposable_tree, link):
    """У каждого звена СВОЁ имя: «красная на чём-нибудь» проба ничего не доказывает."""
    old, new = _LINKS[link]
    tree = disposable_tree()
    path = tree / "scripts" / "check_card_claim.py"
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"звено {link!r} не найдено — мутация ничего не рвёт"
    path.write_text(text.replace(old, new), encoding="utf-8")
    verdict, why = PROBES[PROBE_NAME](None, repo_root=str(tree))
    assert verdict in (NOT_SATISFIED, UNMEASURED), f"{link}: проба осталась {verdict} — {why}"


def test_the_probe_does_not_pass_by_substring(disposable_tree):
    """ADR-333: проба меряет ИСХОД, а не наличие слов в файле.

    Рвутся СРАЗУ ОБА звена правки — это дословно состояние чистой вершины 953cd2b62.
    Весь текст про якорь, контракт и `_anchor_pair` при этом остаётся в файле.
    """
    tree = disposable_tree()
    path = tree / "scripts" / "check_card_claim.py"
    text = path.read_text(encoding="utf-8")
    for old, new in (_LINKS["контракт входа не проверяется"],
                     _LINKS["`anchored` пересказывает вход"]):
        assert text.count(old) == 1
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
    assert "_anchor_pair" in text and "anchored" in text and "контракт" in text
    verdict, why = PROBES[PROBE_NAME](None, repo_root=str(tree))
    assert verdict == NOT_SATISFIED, why


def test_the_probe_reports_a_missing_reader_as_unmeasured(disposable_tree):
    """Писателя НЕТ — это третий исход, а не «не выполнено» и не «чисто» (инв. #17)."""
    tree = disposable_tree()
    (tree / "scripts" / "check_card_claim.py").unlink()
    verdict, why = PROBES[PROBE_NAME](None, repo_root=str(tree))
    assert verdict == UNMEASURED, why


def test_the_probe_reports_a_diverged_vocabulary_as_unmeasured(disposable_tree):
    """Вокабуляры якоря разошлись ⇒ сцену задать нечем, и это НЕ «чисто»."""
    tree = disposable_tree()
    path = tree / "scripts" / "check_card_claim.py"
    text = path.read_text(encoding="utf-8")
    old = 'CLAIM_ANCHOR_KEYS = ("claimed_pid", "claimed_pid_start")'
    assert text.count(old) == 1
    path.write_text(text.replace(old, "CLAIM_ANCHOR_KEYS = ()"), encoding="utf-8")
    verdict, why = PROBES[PROBE_NAME](None, repo_root=str(tree))
    assert verdict == UNMEASURED, why
    # У третьего исхода обязана быть НАЗВАННАЯ причина, иначе «не измерено» снова
    # неотличимо от «что-то пошло не так». Без этой строки проверка зелена и тогда,
    # когда проба спотыкается о расхождение вокабуляров где-то ниже по течению
    # (замер мутациями #872: мутант «проба не отличает вокабуляры» ВЫЖИВАЛ).
    assert "вокабуляр" in why.lower(), why
