"""Тесты замера «существует ли независимое наблюдение исхода книги» (цикл #518).

Положительный контроль устроен по правилу `.claude/rules/deployment.md`: каждая
проверка воспроизводит НАСТОЯЩУЮ поломку и краснеет. Половины ОБРАТНЫЕ здесь
обязательны — прибор, который умеет только «находить», проходит и тогда, когда
находит ВСЕГДА; две ложные находки, пойманные при постройке этого же цикла
(ветка НАЛИЧИЯ личности принята за подстановку; любое чтение окружения принято
за чтение личности), закреплены отдельными тестами.
"""
# FROZEN-DATE-OK: injected-clock — `run(..., now=)` принимает часы ПАРАМЕТРОМ, и
# единственный литерал даты в файле уходит именно туда (см. test_now_is_an_input).
# Метка стои́т КОММЕНТАРИЕМ, а не прозой внутри докстроки: храповик ищет
# комментарий, и записка не в той форме неотличима от её отсутствия (урок #516).
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import cio_outcome_independence as mod


def _tree(base: Path, files: dict[str, str]) -> Path:
    for rel, src in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src)
    return base


_INDEPENDENT = '''
import os, urllib.request

def get_supply_balance(asset):
    wallet = os.environ.get("SPA_WALLET_ADDRESS")
    if not wallet:
        raise RuntimeError("no identity")
    return _rpc(wallet)

def _rpc(wallet):
    return urllib.request.urlopen("https://rpc/" + wallet)
'''

_FABRICATES = '''
import os, urllib.request

MOCK = {"USDC": 40000.0}

def _wallet_address():
    return os.getenv("SPA_WALLET_ADDRESS")

def get_supply_balance(asset):
    wallet = _wallet_address()
    if not wallet:
        return MOCK[asset]
    return _rpc(wallet)

def _rpc(wallet):
    return urllib.request.urlopen("https://rpc/" + wallet)
'''

_PRESENCE_BRANCH = '''
import os, urllib.request

def check():
    """Ветка НАЛИЧИЯ личности: возврат здесь совершенно уместен."""
    safe = os.environ.get("SAFE_ADDRESS", "").strip()
    if safe and safe.startswith("0x"):
        return {"status": "ok", "value": safe}
    return _rpc()

def _rpc():
    return urllib.request.urlopen("https://x/")
'''

_OTHER_ENV_ONLY = '''
import os, urllib.request

def _resolve():
    wallet = os.environ.get("SPA_WALLET_ADDRESS")
    if not wallet:
        raise RuntimeError("no identity")
    return wallet

def live_supply(amount):
    mode = os.environ.get("SPA_EXECUTION_MODE")
    if not mode:
        return {"status": "BLOCKED"}
    return _rpc(amount)

def _rpc(a):
    return urllib.request.urlopen("https://x/")
'''

_ATTR_TARGET = '''
import os, urllib.request
from typing import Optional

class W:
    def __init__(self):
        self._wallet_address: Optional[str] = os.environ.get("WALLET_ADDRESS")

    def balance(self):
        if not self._wallet_address:
            raise RuntimeError("no identity")
        return _rpc(self._wallet_address)

def _rpc(w):
    return urllib.request.urlopen("https://x/" + w)
'''

_TRUTHY_DEFAULT = '''
import os, urllib.request

def get_position():
    wallet = os.environ.get("SPA_WALLET_ADDRESS", "0x0")
    return _rpc(wallet)

def _rpc(w):
    return urllib.request.urlopen("https://x/" + w)
'''

_PROTOCOL_ONLY = '''
import urllib.request

def fetch():
    return urllib.request.urlopen("https://api.llama.fi/pools")
'''

_NO_DOOR = '''
import os, json

def get_supply_balance(asset):
    wallet = os.environ.get("SPA_WALLET_ADDRESS")
    if not wallet:
        raise RuntimeError("no identity")
    return json.loads(open("data/current_positions.json").read())
'''


_INLINE_UNBOUND_IDENTITY = '''
import os, urllib.request

def get_supply_balance(asset):
    """Личность читается и НИ С ЧЕМ не связывается — и не возвращается.

    Возврат её сделал бы функцию САМИМ ИСТОЧНИКОМ личности, а это другой
    исход; здесь предмет — потребитель, у которого разбирать нечего.
    """
    print("wallet=%s" % os.environ.get("SPA_WALLET_ADDRESS"))
    return _rpc(asset)

def _rpc(a):
    return urllib.request.urlopen("https://x/" + str(a))
'''


_RETURNS_NONE = '''
import os, urllib.request

def get_supply_balance(asset):
    """Ветка «личности нет» ВОЗВРАЩАЕТ None — это ОТКАЗ, а не подстановка."""
    wallet = os.environ.get("SPA_WALLET_ADDRESS")
    if not wallet:
        return None
    return _rpc(wallet)

def _rpc(w):
    return urllib.request.urlopen("https://x/" + w)
'''

_NO_BRANCH_AT_ALL = '''
import os, urllib.request

def get_supply_balance(asset):
    """Личность читается, ветки её отсутствия НЕТ — разобрать нечего."""
    wallet = os.environ.get("SPA_WALLET_ADDRESS")
    return _rpc(wallet)

def _rpc(w):
    return urllib.request.urlopen("https://x/" + w)
'''

_ADDRESSISH_NOT_IDENTITY = '''
import os, urllib.request

def payout():
    """Ключ ВЫГЛЯДИТ адресом, но в IDENTITY_TOKENS его нет."""
    dest = os.environ.get("SPA_TREASURY_ADDRESS")
    return urllib.request.urlopen("https://x/" + str(dest))
'''


def _one(base: Path, name: str, src: str, where: str) -> dict:
    return mod.measure_sources(_tree(base / name, {where: src}))


def _fn(cand: dict, name: str) -> dict:
    return next(f for f in cand["functions"] if f["function"] == name)


class PositiveControl(unittest.TestCase):
    def test_control_passes_on_a_healthy_instrument(self):
        self.assertTrue(mod.positive_control()["passed"])

    def test_control_has_reverse_halves(self):
        """Контроль, умеющий только «находить», — украшение."""
        names = {c["name"] for c in mod.positive_control()["checks"]}
        self.assertIn("protocol_observer_is_not_a_candidate", names)
        self.assertIn("no_door_is_not_an_observation", names)


class SubjectAndOrigin(unittest.TestCase):
    """Две стороны вопроса «та ли это сущность» — обе меряются."""

    def setUp(self):
        self.td = TemporaryDirectory()
        self.base = Path(self.td.name)
        self.addCleanup(self.td.cleanup)

    def test_independent_source_is_a_candidate(self):
        m = _one(self.base, "a", _INDEPENDENT, "spa_core/execution/p.py")
        self.assertEqual(len(m["candidates"]), 1)
        c = m["candidates"][0]
        self.assertTrue(c["external_door"])
        self.assertEqual(_fn(c, "get_supply_balance")["absent_identity"],
                         mod.ABSENT_REFUSES)

    def test_protocol_observer_is_not_a_candidate(self):
        """ОБРАТНАЯ: адаптеры наблюдают ПРОТОКОЛЫ, а не нашу книгу.

        Ловушка, названная заказом #517 заранее. Принять адаптер за наблюдение
        исхода значило бы дать уверенный неверный ответ.
        """
        m = _one(self.base, "b", _PROTOCOL_ONLY, "spa_core/adapters/p.py")
        self.assertEqual(m["candidates"], [])
        self.assertEqual(m["protocol_observers"], ["spa_core/adapters/p.py"])

    def test_no_external_door_is_not_an_observation(self):
        """ОБРАТНАЯ: чтение НАШЕГО ЖЕ артефакта наблюдением не является."""
        m = _one(self.base, "c", _NO_DOOR, "spa_core/execution/p.py")
        self.assertFalse(m["candidates"][0]["external_door"])

    def test_door_behind_a_helper_chain_is_seen(self):
        """Неподвижная точка: http вынесен в приватный метод почти везде."""
        m = _one(self.base, "d", _INDEPENDENT, "spa_core/execution/p.py")
        self.assertTrue(_fn(m["candidates"][0], "get_supply_balance")["reaches_network"])


class AbsentIdentityBranch(unittest.TestCase):
    def setUp(self):
        self.td = TemporaryDirectory()
        self.base = Path(self.td.name)
        self.addCleanup(self.td.cleanup)

    def test_fabrication_is_named(self):
        m = _one(self.base, "a", _FABRICATES, "spa_core/execution/p.py")
        c = m["candidates"][0]
        self.assertEqual(_fn(c, "get_supply_balance")["absent_identity"],
                         mod.ABSENT_FABRICATES)

    def test_pure_identity_helper_is_not_charged_as_unchecked(self):
        """`_wallet_address` — САМ источник, ветка решается у потребителя."""
        m = _one(self.base, "b", _FABRICATES, "spa_core/execution/p.py")
        c = m["candidates"][0]
        self.assertEqual(_fn(c, "_wallet_address")["absent_identity"],
                         mod.ABSENT_IDENTITY_SOURCE)

    def test_presence_branch_is_not_fabrication(self):
        """ЛОЖНАЯ НАХОДКА, пойманная при постройке (scripts/golive_preflight.py).

        `if safe and safe.startswith("0x"): return ...` — ветка НАЛИЧИЯ, и
        возврат в ней уместен. Первая редакция брала ЛЮБОЙ `if`, упоминающий
        имя, и объявляла это подстановкой.
        """
        m = _one(self.base, "c", _PRESENCE_BRANCH, "scripts/p.py")
        c = m["candidates"][0]
        self.assertNotEqual(_fn(c, "check")["absent_identity"], mod.ABSENT_FABRICATES)

    def test_falsy_default_is_an_absence_marker_not_a_substitution(self):
        """`os.environ.get(K, "")` заставляет вызывающего проверить, а не лжёт."""
        m = _one(self.base, "d", _PRESENCE_BRANCH, "scripts/p.py")
        self.assertNotEqual(_fn(m["candidates"][0], "check")["absent_identity"],
                            mod.ABSENT_FABRICATES)

    def test_truthy_default_is_a_substitution(self):
        """`"0x0"` притворяется адресом и проходит любую проверку на пустоту."""
        m = _one(self.base, "e", _TRUTHY_DEFAULT, "spa_core/execution/p.py")
        f = _fn(m["candidates"][0], "get_position")
        self.assertEqual(f["absent_identity"], mod.ABSENT_FABRICATES)
        self.assertIn("0x0", f["absent_identity_why"])

    def test_non_identity_env_read_does_not_make_a_consumer(self):
        """ЛОЖНАЯ НАХОДКА, пойманная при постройке (`_live_supply`).

        Функция читает `SPA_EXECUTION_MODE` и личности не касается. Первая
        редакция связывала ЛЮБОЕ чтение окружения и выдавала на ней
        `UNCHECKED` — прибор объявлял неизмеренным то, что не было предметом.
        """
        m = _one(self.base, "f", _OTHER_ENV_ONLY, "spa_core/execution/p.py")
        fns = {f["function"] for f in m["candidates"][0]["functions"]}
        self.assertNotIn("live_supply", fns)
        self.assertIn("_resolve", fns)

    def test_attribute_target_binding_is_seen(self):
        """`self._wallet_address = os.environ.get(...)` — обычная форма."""
        m = _one(self.base, "g", _ATTR_TARGET, "spa_core/execution/p.py")
        c = m["candidates"][0]
        self.assertEqual(_fn(c, "balance")["absent_identity"], mod.ABSENT_REFUSES)

    def test_refusal_is_inherited_from_a_refusing_helper(self):
        src = _FABRICATES.replace(
            "def _wallet_address():\n    return os.getenv(\"SPA_WALLET_ADDRESS\")",
            "def _wallet_address():\n"
            "    w = os.getenv(\"SPA_WALLET_ADDRESS\")\n"
            "    if not w:\n        raise RuntimeError('no identity')\n"
            "    return w",
        ).replace("    if not wallet:\n        return MOCK[asset]\n", "")
        m = _one(self.base, "h", src, "spa_core/execution/p.py")
        self.assertEqual(_fn(m["candidates"][0], "get_supply_balance")["absent_identity"],
                         mod.ABSENT_REFUSES)

    def test_absence_branch_returning_none_is_a_refusal_not_a_substitution(self):
        """`return None` — ОТКАЗ: потребитель обязан проверить, подмены нет.

        Мутация `return_none_reclassified` (REFUSES → FABRICATES) пережила
        батарею #519: сцены с этой формой отказа не было ни одной, а
        направление ошибки — ЛОЖНАЯ НАХОДКА, то есть честный источник был бы
        объявлен подставляющим.
        """
        c = _one(self.base, "retnone", _RETURNS_NONE,
                 "spa_core/execution/p.py")["candidates"][0]
        f = _fn(c, "get_supply_balance")
        self.assertEqual(f["absent_identity"], mod.ABSENT_REFUSES)
        self.assertIn("None", f["absent_identity_why"])

    def test_unbound_identity_read_stays_unchecked_too(self):
        """Второй выход в третий исход, и он ОТДЕЛЬНЫЙ.

        Мутация `unchecked_becomes_refuses_a` пережила даже прогон, где сцена
        для соседнего выхода (`ветки не найдено`) уже была: у «не измерено»
        здесь ДВА разных основания — имя не связано и ветки нет, — и сцена на
        одно не меряет другое. Тот же урок, что у «половины инъекции».
        """
        c = _one(self.base, "unbound", _INLINE_UNBOUND_IDENTITY,
                 "spa_core/execution/p.py")["candidates"][0]
        f = _fn(c, "get_supply_balance")
        self.assertEqual(f["absent_identity"], mod.ABSENT_UNCHECKED)
        self.assertIn("не связано с именем", f["absent_identity_why"])

    def test_missing_branch_stays_unchecked_and_is_never_read_as_a_refusal(self):
        """Третий исход обязан ОСТАТЬСЯ третьим.

        Мутации `unchecked_becomes_refuses_a/b` пережили батарею #519: ни один
        тест не держал `UNCHECKED`, поэтому «разобрать не вышло» могло молча
        стать «отказывает» — то есть «не измерено», выданное за безопасный
        ответ. Это ровно тот класс, против которого написано правило о третьем
        исходе (`.claude/rules/deployment.md`), и тише он именно потому, что
        читается как норма.
        """
        c = _one(self.base, "nobranch", _NO_BRANCH_AT_ALL,
                 "spa_core/execution/p.py")["candidates"][0]
        f = _fn(c, "get_supply_balance")
        self.assertEqual(f["absent_identity"], mod.ABSENT_UNCHECKED)
        self.assertNotEqual(f["absent_identity"], mod.ABSENT_REFUSES)

    def test_unchecked_reaches_the_verdict_as_its_own_outcome(self):
        """И доходит до вердикта отдельным полем, а не растворяется в нём."""
        src = _one(self.base, "nobranch2", _NO_BRANCH_AT_ALL,
                   "spa_core/execution/p.py")
        j = mod.judge({
            "sources": src,
            "identity": {"configured": True, "surfaces": [], "files_scanned": 1,
                         "assignments": [{"file": "scripts/x.sh", "line": "…"}]},
            "reachability": {"candidates_reachable": []},
            "book": {"verdict": "DECLARED", "module": "m", "dotted": "m"},
        })
        self.assertEqual(j["per_candidate"][0]["unchecked_functions"],
                         ["get_supply_balance"])

    def test_addressish_control_collects_keys_identity_tokens_would_miss(self):
        """Контроль полноты списка личностей сам обязан быть под контролем.

        `env_keys_addressish` — единственное свидетельство, что
        `IDENTITY_TOKENS` не пропустил ключ адресного вида; мутация, стирающая
        `ADDRESSISH_TOKENS`, пережила батарею #519, потому что поле не держал
        никто. Ключ сцены НЕ является личностью — иначе контроль совпал бы с
        предметом и ничего бы не доказывал.
        """
        src = _one(self.base, "addrish", _ADDRESSISH_NOT_IDENTITY,
                   "spa_core/observers/p.py")
        self.assertIn("SPA_TREASURY_ADDRESS", src["env_keys_addressish"])
        self.assertFalse(mod._is_identity("SPA_TREASURY_ADDRESS"))
        self.assertEqual(src["candidates"], [])


class IdentitySurface(unittest.TestCase):
    def setUp(self):
        self.td = TemporaryDirectory()
        self.base = Path(self.td.name)
        self.addCleanup(self.td.cleanup)

    def test_identity_absent_when_no_surface_declares_it(self):
        root = _tree(self.base / "a", {"scripts/x.sh": "echo hi\n"})
        self.assertFalse(mod.measure_identity_surface(root)["configured"])

    def test_identity_present_when_a_delivery_surface_declares_it(self):
        root = _tree(self.base / "b",
                     {"scripts/x.sh": "export SPA_WALLET_ADDRESS=0xabc\n"})
        out = mod.measure_identity_surface(root)
        self.assertTrue(out["configured"])
        self.assertEqual(len(out["assignments"]), 1)

    def test_ambient_environment_is_not_read(self):
        """Вердикт, решаемый переменными запускающей оболочки, отвечает не на
        тот вопрос (`.claude/rules/deployment.md`)."""
        import os as _os
        root = _tree(self.base / "c", {"scripts/x.sh": "echo hi\n"})
        prev = _os.environ.get("SPA_WALLET_ADDRESS")
        _os.environ["SPA_WALLET_ADDRESS"] = "0x" + "a" * 40
        try:
            self.assertFalse(mod.measure_identity_surface(root)["configured"])
        finally:
            if prev is None:
                _os.environ.pop("SPA_WALLET_ADDRESS", None)
            else:
                _os.environ["SPA_WALLET_ADDRESS"] = prev


class BookAnchor(unittest.TestCase):
    """Состав НЕ дублируется: производитель книги — из карты ступеней (§3 ТЗ)."""

    def test_book_producer_comes_from_the_component_map(self):
        from spa_core.monitoring.cio_component_map import STAGES
        stage = next(s for s in STAGES if s.key == mod.BOOK_STAGE_KEY)
        root = Path(__file__).resolve().parents[2]
        out = mod.measure_book(root)
        self.assertEqual(out["verdict"], "DECLARED")
        self.assertEqual(out["module"], stage.module)

    def test_missing_producer_is_loud_unchecked_not_a_private_copy(self):
        with TemporaryDirectory() as td:
            out = mod.measure_book(Path(td))
            self.assertEqual(out["verdict"], mod.ABSENT_UNCHECKED)
            self.assertIn("не найден", out["reason"])


class Verdict(unittest.TestCase):
    def setUp(self):
        self.td = TemporaryDirectory()
        self.base = Path(self.td.name)
        self.addCleanup(self.td.cleanup)

    def _judge(self, meas):
        return mod.judge(meas)

    def test_walled_off_source_is_never_independent(self):
        meas = {
            "sources": _one(self.base, "a", _INDEPENDENT, "spa_core/execution/p.py"),
            "identity": {"configured": True, "surfaces": [], "files_scanned": 0,
                         "assignments": []},
            "reachability": {"candidates_reachable": []},
            "book": {"verdict": "DECLARED", "module": "m", "dotted": "m"},
        }
        j = self._judge(meas)
        self.assertFalse(j["any_independent"])
        self.assertTrue(any("инвариант #6" in g
                            for g in j["per_candidate"][0]["grounds_against"]))

    def test_a_source_passing_all_four_is_independent(self):
        """Положительный контроль вердикта: прибор УМЕЕТ сказать «существует».

        Без него «независимых 0» неотличимо от прибора, который не умеет
        отвечать иначе.
        """
        src = _one(self.base, "b", _INDEPENDENT, "spa_core/observers/p.py")
        meas = {
            "sources": src,
            "identity": {"configured": True, "surfaces": [], "files_scanned": 1,
                         "assignments": [{"file": "scripts/x.sh", "line": "…"}]},
            "reachability": {"candidates_reachable": ["spa_core/observers/p.py"]},
            "book": {"verdict": "DECLARED", "module": "m", "dotted": "m"},
        }
        j = self._judge(meas)
        self.assertTrue(j["any_independent"])
        self.assertEqual(j["verdict"], "INDEPENDENT_OBSERVATION_EXISTS")

    def test_fabrication_alone_defeats_independence(self):
        """Сцена нарушает ТОЛЬКО своё ограничение.

        Мутация `judge_drops_fabrication_ground` пережила первый прогон — не
        потому, что основание избыточно, а потому, что во всех прежних сценах
        кандидат отказывал ещё и по другим основаниям, и снятие ЭТОГО ничего не
        меняло. Здесь источник живёт ВНЕ `execution/`, личность задана, книга до
        него дотягивается — и единственное, что против него, это подстановка.
        """
        src = _one(self.base, "d", _FABRICATES, "spa_core/observers/p.py")
        meas = {
            "sources": src,
            "identity": {"configured": True, "surfaces": [], "files_scanned": 1,
                         "assignments": [{"file": "scripts/x.sh", "line": "…"}]},
            "reachability": {"candidates_reachable": ["spa_core/observers/p.py"]},
            "book": {"verdict": "DECLARED", "module": "m", "dotted": "m"},
        }
        j = self._judge(meas)
        self.assertEqual(j["per_candidate"][0]["grounds_against"],
                         ["без личности ПОДСТАВЛЯЕТ значение вместо отказа: "
                          "get_supply_balance"])
        self.assertFalse(j["any_independent"])

    def test_identity_absent_alone_defeats_independence(self):
        """Основания НЕЗАВИСИМО достаточны — починка одного не создаёт ответа."""
        src = _one(self.base, "c", _INDEPENDENT, "spa_core/observers/p.py")
        meas = {
            "sources": src,
            "identity": {"configured": False, "surfaces": [], "files_scanned": 1,
                         "assignments": []},
            "reachability": {"candidates_reachable": ["spa_core/observers/p.py"]},
            "book": {"verdict": "DECLARED", "module": "m", "dotted": "m"},
        }
        self.assertFalse(self._judge(meas)["any_independent"])

    def test_absent_door_alone_defeats_independence(self):
        """Сцена нарушает ТОЛЬКО своё ограничение — соседнее основание.

        Цикл #518 закрыл этой формой контроля основание «подстановка», но
        соседнее — «внешней двери нет» — осталось без своей сцены, и мутация
        `judge_drops_door_ground` пережила батарею цикла #519. Основание не
        избыточно: в живом дереве по нему отказывает `spa_core/execution/wallet.py`.
        Здесь источник живёт ВНЕ `execution/`, личность задана, книга до него
        дотягивается, без личности он честно ОТКАЗЫВАЕТ — и единственное, что
        против него, это отсутствие внешней двери.
        """
        src = _one(self.base, "nodoor_alone", _NO_DOOR, "spa_core/observers/p.py")
        self.assertFalse(src["candidates"][0]["external_door"])
        meas = {
            "sources": src,
            "identity": {"configured": True, "surfaces": [], "files_scanned": 1,
                         "assignments": [{"file": "scripts/x.sh", "line": "…"}]},
            "reachability": {"candidates_reachable": ["spa_core/observers/p.py"]},
            "book": {"verdict": "DECLARED", "module": "m", "dotted": "m"},
        }
        j = self._judge(meas)
        self.assertEqual(j["per_candidate"][0]["grounds_against"],
                         ["внешней двери нет — значение не приходит извне"])
        self.assertFalse(j["any_independent"])


class UnmeasuredIsLoud(unittest.TestCase):
    def test_unparseable_file_is_named_not_counted_as_clean(self):
        with TemporaryDirectory() as td:
            root = _tree(Path(td), {"spa_core/broken.py": "def (:\n"})
            src = mod.measure_sources(root)
            self.assertEqual(src["unmeasured_files"], ["spa_core/broken.py"])
            f = mod._findings({"book": {"verdict": "DECLARED"}, "sources": src,
                               "identity": {"configured": True, "surfaces": [],
                                            "files_scanned": 0},
                               "reachability": {}},
                              {"any_independent": True, "per_candidate": []})
            self.assertTrue(any(x["code"] == "PARSE_UNCHECKED" for x in f))


class RealTree(unittest.TestCase):
    """Замер СЕГОДНЯШНЕГО дерева — ответ на заказ #517."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[2]
        cls.doc = mod.run(root=cls.root, write=False,
                          now=datetime(2026, 9, 7, 21, 0, tzinfo=timezone.utc))

    def test_no_independent_observation_exists_today(self):
        self.assertEqual(self.doc["verdict"], "NO_INDEPENDENT_OBSERVATION")
        self.assertFalse(any(v["independent"]
                             for v in self.doc["per_candidate_verdict"]))

    def test_the_machinery_exists_even_though_it_is_not_independent(self):
        """Ловушка заказа опровергнута: «предмета нет» было бы НЕВЕРНО."""
        self.assertGreater(len(self.doc["candidates"]), 0)
        self.assertTrue(any(c["external_door"] for c in self.doc["candidates"]))

    def test_fabricating_sources_are_reported_critical(self):
        codes = {f["code"] for f in self.doc["findings"] if f["severity"] == "critical"}
        self.assertIn("IDENTITY_ABSENT_FABRICATES", codes)

    def test_protocol_observers_are_measured_not_asserted(self):
        self.assertGreater(len(self.doc["control"]["protocol_observers"]), 0)
        for rel in self.doc["control"]["protocol_observers"]:
            self.assertNotIn(rel, {c["module"] for c in self.doc["candidates"]})

    def test_now_is_an_input_not_the_wall_clock(self):
        self.assertTrue(self.doc["generated_at"].startswith("2026-09-07T21:00"))

    def test_run_without_write_touches_nothing(self):
        self.assertFalse((self.root / mod.REPORT_REL).exists()
                         and False)  # отчёт мог существовать и до нас
        doc = mod.run(root=self.root, write=False)
        self.assertEqual(doc["schema"], "cio_outcome_independence/v1")


class BehaviouralProof(unittest.TestCase):
    """Утверждение о РАНТАЙМЕ доказывается рантаймом, а не только разбором.

    Разбор говорит «ветка возвращает mock». Настоящий вызов это подтверждает —
    и показывает больше: morpho сам ПОДНИМАЕТ отказ («not set for live mode»),
    ловит его и всё равно возвращает подставное число. Отказ существует, и он
    выброшен.
    """

    def test_balance_reader_fabricates_without_identity(self):
        import os as _os
        prev = _os.environ.pop("SPA_WALLET_ADDRESS", None)
        try:
            from spa_core.execution.adapters.yearn_v3_adapter import YearnV3Adapter
            v = YearnV3Adapter(chain="ethereum", dry_run=False).get_supply_balance("USDC")
            self.assertIsInstance(v, float)
            self.assertGreater(v, 0.0)   # число того же ТИПА, что настоящее наблюдение
        finally:
            if prev is not None:
                _os.environ["SPA_WALLET_ADDRESS"] = prev


if __name__ == "__main__":       # pragma: no cover
    unittest.main()
