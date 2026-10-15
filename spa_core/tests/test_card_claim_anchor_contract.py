"""КОНТРАКТ `self_anchor` обязан спрашиваться КАЖДЫМ читателем, а не одним (цикл #873, ADR-728).

Что измерено, и почему это не «ещё одна проверка типа»
------------------------------------------------------------------------------
ADR-727 (#872) поставил сторожа контракта `self_anchor` у ОДНОЙ двери — пишущей
(`claim_card`) — и сам назвал остаток вслух (заказ G727 п. 1). Дверей три, и все три
ведут к одному вопросу «это объявление МОЁ?» (`self_identities`):

    claim_card    — взятие карточки
    gather        — отчёт шага 0b (через `build_report`)
    release_card  — снятие захвата (тот же `self_identities` напрямую)

Замер #873 на чистой вершине `3b417db92`. Сцена: карточка захвачена ярлыком `pidNNN`,
а запись журнала написана ТЕМ ЖЕ долгоживущим процессом под тем же ярлыком — дословно
состояние сессии, у которой `claim` и `release` суть две разные CLI-команды:

    дверь          вход      исход
    gather         пара      free     · self_sessions = мой ярлык + ярлык захвата
    gather         СЛОВАРЬ   stale    · self_sessions = ТОЛЬКО мой ярлык
    gather         None      stale    · то же самое, байт в байт
    release_card   пара      ОТПУЩЕНА
    release_card   СЛОВАРЬ   «снять чужой захват можно только с --force»

Причина у обеих дверей одна: `anchor_of(entry) == anchor` со словарём не совпадает
НИКОГДА, поэтому опознание своих объявлений МОЛЧА выключается. Это дословно дефект
цикла #70, ради которого `self_identities` и написан, — и докстринг `release_card`
называет его УЖЕ ЗАКРЫТЫМ.

Вход вне контракта не выдуман: якорь живёт ВТОРОЙ формой — СЛОВАРЁМ в вокабуляре шага 0a
(`{"session_pid": …, "session_pid_start": …}`), и ровно её отдаёт
`log_session_change.durable_process`, прежде чем `anchor_of` сведёт пару.

Направление ошибки — ложная ЗАНЯТОСТЬ, а не ложная свобода: сторож не обходится, чужая
работа не забирается. Но цена ложной занятости измерена 08.10 — ЧЕТЫРЕ карточки
неберущимися, среди них критический приказ владельца, 634 цикла мимо. И молчит она так
же: ни один ключ отчёта про якорь не говорит, поэтому «вход негоден» неотличимо от
«опознание выключено намеренно» (инв. #17).

Что проверяется, и почему в ОБЕ стороны
------------------------------------------------------------------------------
* ОДИН судья (`require_anchor_contract`) — и у него ТРИ читателя: каждая дверь отказывает
  на входе вне контракта И НАЗЫВАЕТ СЕБЯ (три двери ⇒ отказ без имени отправит искать
  не туда);
* `None` — ОБЪЯВЛЕННОЕ отключение опознания (им зовут герметичные тесты): проходит без
  слова, и поведение каждой двери остаётся прежним. Правка дополняющая, а не запрещающая;
* контрактная пара продолжает опознавать свой захват (`gather` ⇒ ярлык захвата в
  `self_sessions`; `release_card` ⇒ карточка отпущена) — без этого звена замер двери
  ничего не значил бы;
* РАЗДЕЛЕНИЕ ТРУДА двух судей: контракт судит ФОРМУ, а полноту пары — `_anchor_pair`.
  Половина пары (`(pid, "")`) контракт ПРОХОДИТ: иначе два условия об одном маскировали
  бы друг друга, и снятие любого перестало бы ловиться (урок #869);
* положительный контроль СЦЕНЫ: пара и `None` обязаны давать РАЗНЫЙ исход, иначе
  разница, которой судят остальные звенья, не наблюдаема.

Время и живость — ВХОДЫ, а не окружение
------------------------------------------------------------------------------
Литеральных дат нет ни одной: все отметки выведены из якоря `NOW`, он же идёт
измерителю аргументом `now=`. Живость запускателя ИНЪЕКТИРОВАНА (`ps=`). Единственный
номер процесса — `os.getpid()`: он ЖИВ на любой машине по построению
(`.claude/rules/deployment.md` § «ЛИЧНОСТЬ ПРОЦЕССА», приём №2), а ответ ОС за него всё
равно даёт инъекция.
"""
import importlib.util
import json
import os
from datetime import timedelta
from pathlib import Path

import pytest

from spa_core.tests._freshness import now_utc

ROOT = Path(__file__).resolve().parents[2]

#: Якорь времени — РЕАЛЬНЫЕ часы: предмет файла — свежесть захвата, и литеральная дата
#: начала бы падать от сдвига календаря, а не от кода. Часы инъектированы (`now=`), обе
#: стороны сравнения выведены отсюда.
NOW = now_utc().replace(microsecond=0)

#: Номер ЖИВ по построению; за ответ ОС всё равно отвечает инъекция `ps=`.
PID = os.getpid()
HOLDER = f"pid{PID}"
MINE = f"cycle-873-{PID}"
START = (NOW - timedelta(hours=2)).astimezone().strftime("%a %b %d %H:%M:%S %Y")
AT = (NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
PAIR = (PID, START)

#: Имя пробы приёмки карточки — одна копия на файл.
PROBE_NAME = "card_claim_anchor_contract_guards_every_reader"

DEAD = lambda _pid: (1, "")                                          # noqa: E731


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load("_c873_card_claim", ROOT / "scripts" / "check_card_claim.py")


@pytest.fixture(scope="module")
def sibling(guard):
    return guard.load_sibling()


@pytest.fixture(scope="module")
def dict_form(sibling):
    """Якорь ВТОРОЙ формой — вокабуляр шага 0a, а не пара имён из головы.

    Имена спрашиваются у СОСЕДА (`DURABLE_KEYS`): сцена «вход вне контракта» обязана
    быть той самой формой, что живёт рядом в коде, иначе тест мерил бы выдуманный вход.
    """
    keys = tuple(getattr(sibling, "DURABLE_KEYS", ()) or ())
    assert len(keys) == 2, f"вокабуляр якоря шага 0a изменился: {keys!r}"
    return dict(zip(keys, PAIR))


class _MuteAnnouncer:
    """Объявлять некуда: сцена одноразовая, общий журнал координации не трогаем."""

    def record(self, *a, **k):
        return None

    def append(self, *a, **k):
        return None


def _scene(tmp_path, name):
    """Карточка, захваченная `HOLDER`, + журнал, написанный ТЕМ ЖЕ процессом."""
    tracker = tmp_path / name
    tracker.mkdir()
    (tracker / "inbox-scene.md").write_text(
        "---\ntrackerStatus:\n  type: inbox\ntitle: сцена\nstatus: in-progress\n"
        f"claimed_by: {HOLDER}\nclaimed_at: {AT}\n---\n\nтело\n", encoding="utf-8")
    log = tmp_path / f"{name}.jsonl"
    log.write_text(
        json.dumps({
            "ts": AT, "session": HOLDER, "card": "inbox-scene",
            "summary": "[check_card_claim] claim inbox-scene",
            "session_pid": PID, "session_pid_start": START}) + "\n"
        # ВТОРАЯ запись — БЕЗ якоря и о ДРУГОЙ карточке: без неё граница «`None`
        # выключает опознание РАНО» заявлена, но не наблюдаема (мутант выживал).
        # Карточка другая намеренно — лишнего захвата в сцене не появляется.
        + json.dumps({
            "ts": AT, "session": f"{HOLDER}-anchorless", "card": "inbox-another",
            "summary": "[check_card_claim] claim inbox-another"}) + "\n",
        encoding="utf-8")
    return tracker, log


def _read(guard, sibling, tmp_path, name, anchor):
    tracker, log = _scene(tmp_path, name)
    return guard.gather("inbox-scene", log=log, tracker_dir=tracker, sibling=sibling,
                        self_session=MINE, now=NOW, ps=DEAD, self_anchor=anchor,
                        shared_trees=())


def _free(guard, tmp_path, name, anchor):
    tracker, log = _scene(tmp_path, name)
    return guard.release_card("inbox-scene", log=log, session=MINE, tracker_dir=tracker,
                              self_anchor=anchor, announcer=_MuteAnnouncer())


def _take(guard, sibling, tmp_path, name, anchor):
    """Чистая карточка (без захвата) + пустой журнал — сцена ВЗЯТИЯ."""
    tracker = tmp_path / name
    tracker.mkdir()
    (tracker / "inbox-scene.md").write_text(
        "---\ntrackerStatus:\n  type: inbox\ntitle: сцена\nstatus: new\n---\n\nтело\n",
        encoding="utf-8")
    log = tmp_path / f"{name}.jsonl"
    log.write_text("", encoding="utf-8")
    res = guard.claim_card("inbox-scene", log=log, session=MINE, tracker_dir=tracker,
                           now=NOW, sibling=sibling, ps=DEAD, self_anchor=anchor,
                           announcer=_MuteAnnouncer())
    meta = guard.frontmatter((tracker / "inbox-scene.md").read_text(encoding="utf-8"))
    return res, meta or {}


# ── судья: один на весь файл ─────────────────────────────────────────────────

class TestTheJudge:
    def test_the_contract_form_passes_unchanged(self, guard):
        """Пара `anchor_of` — контракт; судья отдаёт её КАК ЕСТЬ, ничего не пересобирая."""
        # Сравнение по ЗНАЧЕНИЮ и ТИПУ: `tuple(x)` на тупле возвращает тот же
        # объект лишь по реализации CPython, и опирать утверждение на это
        # значило бы проверять интерпретатор, а не контракт.
        out = guard.require_anchor_contract(PAIR, reader="тест")
        assert out == PAIR and isinstance(out, tuple)

    def test_None_is_a_DECLARED_disabling_and_passes(self, guard):
        """`None` — объявленное отключение опознания (герметичные тесты), не ошибка."""
        assert guard.require_anchor_contract(None, reader="тест") is None

    def test_the_step_0a_dict_form_is_REFUSED(self, guard, dict_form):
        """Вход вне контракта ОТКАЗЫВАЕТ, а не сбрасывается в пустую пару молча."""
        with pytest.raises(guard.ClaimError) as exc:
            guard.require_anchor_contract(dict_form, reader="тест")
        assert "вне контракта" in str(exc.value)

    def test_the_refusal_NAMES_the_reader(self, guard, dict_form):
        """Дверей ТРИ: отказ без имени читателя отправит искать не туда."""
        for reader in ("gather", "claim_card", "release_card"):
            with pytest.raises(guard.ClaimError) as exc:
                guard.require_anchor_contract(dict_form, reader=reader)
            assert reader in str(exc.value)

    def test_a_LIST_is_NORMALISED_to_a_pair(self, guard):
        """Список контракт ПРОХОДИТ — и обязан выйти пáрой, иначе ломается тише.

        `anchor_of(entry)` отдаёт ТУПЛ, а `tuple != list` в Python никогда не равны:
        список, пропущенный без приведения, выключал бы опознание так же, как словарь,
        но БЕЗ отказа — то есть сторож закрывал бы одну половину класса и оставлял
        вторую незаметнее прежней (замер #873).
        """
        out = guard.require_anchor_contract([PID, START], reader="тест")
        assert out == PAIR and isinstance(out, tuple), out

    def test_a_HALF_pair_passes_the_contract_judge(self, guard):
        """РАЗДЕЛЕНИЕ ТРУДА: контракт судит ФОРМУ, полноту пары — `_anchor_pair`.

        Два условия об одном маскировали бы друг друга, и снятие любого перестало бы
        ловиться тестами (замер мутациями #869 — обе проверки выживали поодиночке).
        Поэтому половина пары форму ПРОХОДИТ, а не пишется уже у `_anchor_pair`.
        """
        half = (PID, "")
        assert guard.require_anchor_contract(half, reader="тест") == half
        assert guard._anchor_pair(dict(zip(guard.CLAIM_ANCHOR_KEYS, half))) == ()


# ── дверь 1: `gather` (читающая, отчёт шага 0b) ──────────────────────────────

class TestTheGatherDoor:
    def test_the_contract_pair_RECOGNISES_my_own_claim(self, guard, sibling, tmp_path):
        """Положительный контроль сцены: без него замер двери ничего не значит."""
        r = _read(guard, sibling, tmp_path, "pair", PAIR)
        assert HOLDER in (r.get("self_sessions") or []), r.get("self_sessions")

    def test_the_scene_SEPARATES_the_input_forms(self, guard, sibling, tmp_path):
        """Пара и `None` обязаны давать РАЗНЫЙ вердикт — иначе разница не наблюдаема."""
        pair = _read(guard, sibling, tmp_path, "sep_pair", PAIR)
        none = _read(guard, sibling, tmp_path, "sep_none", None)
        assert pair["verdict"] != none["verdict"], (pair["verdict"], none["verdict"])

    def test_the_dict_form_is_REFUSED_before_it_reaches_the_verdict(
            self, guard, sibling, tmp_path, dict_form):
        """Отчёт шага 0b не вправе называть СВОЙ захват чужим из-за формы входа."""
        with pytest.raises(guard.ClaimError) as exc:
            _read(guard, sibling, tmp_path, "dict", dict_form)
        assert "gather" in str(exc.value)

    def test_a_LIST_behaves_EXACTLY_like_the_pair(self, guard, sibling, tmp_path):
        """Исход, не форма: у двери список и туплл обязаны давать одно и то же."""
        as_pair = _read(guard, sibling, tmp_path, "lpair", PAIR)
        as_list = _read(guard, sibling, tmp_path, "llist", [PID, START])
        assert as_list["verdict"] == as_pair["verdict"]
        assert sorted(as_list.get("self_sessions") or []) == sorted(
            as_pair.get("self_sessions") or [])

    def test_None_keeps_the_PREVIOUS_behaviour(self, guard, sibling, tmp_path):
        """Объявленное отключение: опознан ровно один ярлык — мой, как до 01.08."""
        r = _read(guard, sibling, tmp_path, "none", None)
        assert sorted(r.get("self_sessions") or []) == [MINE]


# ── дверь 2: `release_card` (пишущая, снятие захвата) ────────────────────────

class TestTheReleaseDoor:
    def test_the_contract_pair_RELEASES_my_own_claim(self, guard, tmp_path):
        """Положительный контроль: пара опознаёт свой захват и снятие проходит."""
        assert _free(guard, tmp_path, "pair", PAIR).get("released") is True

    def test_None_still_REFUSES_as_foreign(self, guard, tmp_path):
        """Граница: без якоря опознавать нечем ⇒ отказ прежний, а не новый."""
        with pytest.raises(guard.ClaimError) as exc:
            _free(guard, tmp_path, "none", None)
        assert "--force" in str(exc.value)

    def test_the_dict_form_is_REFUSED_by_its_OWN_name(self, guard, tmp_path, dict_form):
        """Со словарём здесь стоял отказ «снять чужой захват» о СВОЕЙ карточке (#70)."""
        with pytest.raises(guard.ClaimError) as exc:
            _free(guard, tmp_path, "dict", dict_form)
        assert "release_card" in str(exc.value)
        assert "--force" not in str(exc.value), (
            "отказ по контракту не вправе выглядеть как отказ «захват чужой»: это "
            "разные факты, и совет `--force` на негодный вход снял бы НАСТОЯЩИЙ чужой")

    def test_the_card_is_NOT_touched_when_the_contract_refuses(
            self, guard, tmp_path, dict_form):
        """Отказ ДО замка и ДО записи: захват в карточке остаётся на месте."""
        tracker = tmp_path / "intact"
        tracker.mkdir()
        card = tracker / "inbox-scene.md"
        card.write_text(
            "---\ntrackerStatus:\n  type: inbox\ntitle: сцена\nstatus: in-progress\n"
            f"claimed_by: {HOLDER}\nclaimed_at: {AT}\n---\n\nтело\n", encoding="utf-8")
        before = card.read_text(encoding="utf-8")
        log = tmp_path / "intact.jsonl"
        log.write_text("", encoding="utf-8")
        with pytest.raises(guard.ClaimError):
            guard.release_card("inbox-scene", log=log, session=MINE, tracker_dir=tracker,
                               self_anchor=dict_form, announcer=_MuteAnnouncer())
        assert card.read_text(encoding="utf-8") == before


# ── дверь 3: `claim_card` (ADR-727 — не сломана правкой) ─────────────────────

class TestTheClaimDoorStillHolds:
    def test_the_contract_pair_still_TAKES_the_card_with_the_anchor(
            self, guard, sibling, tmp_path):
        res, meta = _take(guard, sibling, tmp_path, "pair", PAIR)
        assert res.get("anchored") is True
        assert all(str(meta.get(k) or "").strip() for k in guard.CLAIM_ANCHOR_KEYS)

    def test_the_dict_form_is_REFUSED_and_the_card_is_NOT_taken(
            self, guard, sibling, tmp_path, dict_form):
        with pytest.raises(guard.ClaimError) as exc:
            _take(guard, sibling, tmp_path, "dict", dict_form)
        assert "claim_card" in str(exc.value)
        meta = guard.frontmatter(
            (tmp_path / "dict" / "inbox-scene.md").read_text(encoding="utf-8")) or {}
        assert not str(meta.get("claimed_by") or "").strip()


# ── контроли САМОЙ ПРОБЫ: зелена на целом контуре, красна на каждом звене ────
#
# Без этого раздела мутационный замер #873 нашёл ЧЕТЫРЕ выживших мутанта, и все четыре
# — ветки обнаружения самой пробы: порвать их значило ослепить приёмку, и ни один тест
# этого не замечал (`.claude/rules/acceptance.md` §3 требует контроль в обе стороны).

#: Звенья проводки. Разрывается ПРАВКОЙ ФАЙЛА в одноразовом дереве: проба меряет исход
#: у настоящего читателя, поэтому подменить ей объект нельзя — только код, который она
#: ввозит. Имя у каждого звена СВОЁ: «красная на чём-нибудь» проба не доказывает ничего.
_LINKS = {
    "сторожа нет у читающей двери `gather`": (
        '    self_anchor = require_anchor_contract(self_anchor, reader="gather")',
        "    pass"),
    "сторожа нет у пишущей двери `release_card`": (
        '    self_anchor = require_anchor_contract(self_anchor, reader="release_card")',
        "    pass"),
    "судья контракта не судит вовсе": (
        "    if len(pair) != len(CLAIM_ANCHOR_KEYS):",
        "    if False:"),
    # Вход КОНТРАКТНОЙ формы, но не той, что отдаёт `anchor_of`: список. Сторож его
    # ПРОПУСКАЕТ (так же, как прежнее сужение `isinstance(..., (tuple, list))`), и без
    # приведения к пáре `anchor_of(entry) == anchor` не совпадал бы НИКОГДА — тот же
    # дефект #70, только тише, потому что отказа нет и не будет.
    "судья пропускает вход вместо приведения": (
        "            f\"этом не было бы сказано ни слова.\")\n    return pair",
        "            f\"этом не было бы сказано ни слова.\")\n    return self_anchor"),
    "судья пускает словарь — вторую форму якоря": (
        "    pair = tuple(self_anchor) if isinstance(self_anchor, (tuple, list)) else ()",
        "    pair = tuple(self_anchor) if isinstance(self_anchor, (tuple, list, dict)) else ()"),
    "опознание своих объявлений сломано у ПАРЫ — контроль сцены": (
        "        if anchor_of(entry, sibling) == anchor:",
        "        if False:"),
    # Это звено ПОЯВИЛОСЬ в сцене не сразу, и путь к нему стои́т записи. Пока в
    # журнале сцены была ОДНА запись — с якорем, — мутант оставлял пробу ЗЕЛЁНОЙ:
    # `anchor_of(entry)` отдаёт пару, с `None` она не совпадает, и ранний выход ничего
    # не менял. Разница мутанта возникает на записи БЕЗ якоря (`None == None` ⇒ её ярлык
    # становится «моим»), поэтому сцена получила ВТОРУЮ запись — без якоря и о другой
    # карточке. Так граница стала НАБЛЮДАЕМОЙ, а не заявленной.
    "объявленное отключение `None` перестало отключать рано": (
        "    if not anchor:\n        return selves",
        "    if False:\n        return selves"),
}


@pytest.fixture()
def disposable_tree(tmp_path):
    """Одноразовая копия трёх файлов проводки: живое дерево не трогается.

    Трёх достаточно: `ROOT` у шага 0b выводится из пути самого файла, а сосед и
    объявитель адресуются от него же — все трое stdlib-only.
    """
    import shutil

    def _make():
        tree = tmp_path / f"tree{len(list(tmp_path.glob('tree*')))}"
        (tree / "scripts").mkdir(parents=True)
        for name in ("check_card_claim.py", "check_undelivered_work.py",
                     "log_session_change.py"):
            shutil.copy2(ROOT / "scripts" / name, tree / "scripts" / name)
        return tree
    return _make


def test_the_probe_is_green_on_the_whole_contour(disposable_tree):
    from spa_core.monitoring.card_acceptance import PROBES, SATISFIED
    verdict, why = PROBES[PROBE_NAME](None, repo_root=str(disposable_tree()))
    assert verdict == SATISFIED, why


@pytest.mark.parametrize("link", sorted(_LINKS))
def test_the_probe_is_red_on_every_broken_link(disposable_tree, link):
    """У каждого звена СВОЁ имя, и разрыв обязан быть НАЙДЕН в файле.

    `assert count == 1` здесь — не украшение: мутация, не нашедшая якоря, не рвёт
    ничего, и «проба красна» означало бы лишь, что тест сам себя не обеспечил.
    """
    from spa_core.monitoring.card_acceptance import NOT_SATISFIED, PROBES, UNMEASURED
    old, new = _LINKS[link]
    tree = disposable_tree()
    path = tree / "scripts" / "check_card_claim.py"
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"звено {link!r} не найдено — мутация ничего не рвёт"
    path.write_text(text.replace(old, new), encoding="utf-8")
    verdict, why = PROBES[PROBE_NAME](None, repo_root=str(tree))
    assert verdict in (NOT_SATISFIED, UNMEASURED), f"{link}: проба осталась {verdict} — {why}"


def test_the_probe_reports_a_missing_reader_as_unmeasured(disposable_tree):
    """Читателя НЕТ — третий исход, а не «не выполнено» и не «чисто» (инв. #17)."""
    from spa_core.monitoring.card_acceptance import PROBES, UNMEASURED
    tree = disposable_tree()
    (tree / "scripts" / "check_card_claim.py").unlink()
    verdict, why = PROBES[PROBE_NAME](None, repo_root=str(tree))
    assert verdict == UNMEASURED, why


def test_the_probe_does_not_pass_by_substring(disposable_tree):
    """ADR-333: проба меряет ИСХОД у читателя, а не наличие слов в файле.

    Контроль: ОБА зова судьи остаются в файле дословно — вместе с именем функции, именем
    читателя и всей прозой про контракт, — а судья при этом не судит. Текст на месте,
    вердикт обязан быть красным.
    """
    from spa_core.monitoring.card_acceptance import NOT_SATISFIED, PROBES
    tree = disposable_tree()
    path = tree / "scripts" / "check_card_claim.py"
    text = path.read_text(encoding="utf-8")
    old, new = _LINKS["судья контракта не судит вовсе"]
    assert text.count(old) == 1
    path.write_text(text.replace(old, new), encoding="utf-8")
    after = path.read_text(encoding="utf-8")
    assert 'require_anchor_contract(self_anchor, reader="gather")' in after
    assert 'require_anchor_contract(self_anchor, reader="release_card")' in after
    assert "вне контракта" in after
    verdict, _why = PROBES[PROBE_NAME](None, repo_root=str(tree))
    assert verdict == NOT_SATISFIED
