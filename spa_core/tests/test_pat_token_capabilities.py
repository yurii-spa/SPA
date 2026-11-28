"""«Ключ ЖИВ» ≠ «ключ МОЖЕТ»: способность ключа доставки спрашивается у GitHub (ADR-1128).

Каждый тест здесь — положительный контроль замера 2026-11-28. Владелец выпустил новый
`GITHUB_PAT_SPA` 26.11, оба прежних сторожа о ключе стали зелёными (`/user` → 200,
календарь ротации в норме) — и `POST /repos/yurii-spa/SPA/actions/workflows/
ci-control.yml/dispatches` ответил **403 «Resource not accessible by personal access
token»**: контрольного прогона CI заказать нельзя, и «вердикт CI о моём коммите» у
КАЖДОГО цикла выходит НЕ ИЗМЕРЕН. Причина наша: карточка ротации и
`docs/GITHUB_CREDENTIALS.md` просили `Contents RW` + `Workflows RW`, а
`workflow_dispatch` гейтит разрешение `Actions` — его не просил никто.

Это тот же класс, что ADR-1094 («ключ ЕСТЬ» выдавалось за «ключ ЖИВ»), на шаг дальше:
зелёный ответ на вопрос о СОСТОЯНИИ не есть ответ о СПОСОБНОСТИ.

# FROZEN-DATE-OK: no-dates — предмет файла КОД ОТВЕТА HTTP, а не срок: ни одно
# сравнение здесь не берёт дату ни одной стороной, и календарь на вердикт не влияет
# никак. Даты в тексте выше — ДАТЫ ЗАМЕРА в прозе, а не операнды. Пометку
# `injected-clock` этот файл носить НЕ ВПРАВЕ, и сторож претензии
# (`test_injected_clock_claim.py`) это поймал на первой же редакции: инъекции часов
# здесь нет, потому что часов здесь нет вовсе. Двери наружу — входы по другой причине:
# `secret_reader=` и `door_probe=` нужны, чтобы не держать на руках живой ключ без права.
"""

import ast
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import pat_rotation_helper as prh  # noqa: E402

from spa_core.monitoring.system_health_monitor import (  # noqa: E402
    CRITICAL,
    OK,
    WARNING,
    SystemHealthMonitor,
)

#: Токен сцены. Секретом никогда не был: живёт только в этом файле и служит ровно
#: одному вопросу — «не утёк ли он в вывод».
_SCENE_TOKEN = "scene_token_capability_not_a_real_secret"

#: Ответ GET о ветке-зонде, при котором проба безвредна. 404 = ветки НЕТ.
_ABSENT = 404


def _reader(secret=_SCENE_TOKEN, reason=None):
    """Дверь к связке ключей как ВХОД."""
    def _read(_service, runner=None):
        return secret, reason
    return _read


def _door(answers, calls=None):
    """Дверь к GitHub как ВХОД.

    `answers` — отображение «(метод, хвост пути) → (код|None, причина|None)»; хвост
    ищется вхождением, чтобы сцена не переписывала полный URL. Каждый зов
    записывается в `calls`, и это несущая часть проверки безвредности: «проба не
    писала» мерится СПИСКОМ ЗАПРОСОВ, а не доверием к ветвлению.
    """
    def _probe(_token, method, url, body=None, _timeout=None):
        if calls is not None:
            calls.append((method, url, body))
        for (want_method, tail), answer in answers.items():
            if method == want_method and tail in url:
                return answer
        raise AssertionError(f"сцена не объявила ответа на {method} {url}")
    return _probe


def _ref_ok(extra):
    """Сцена, в которой ветка-зонд ОТСУТСТВУЕТ (проба безвредна), плюс `extra`."""
    answers = {("GET", "/git/ref/heads/"): (_ABSENT, None)}
    answers.update(extra)
    return answers


def _by_key(result):
    return {row["key"]: row for row in result["doors"]}


# ── ось: 403 против 422 на запросе ОДНОЙ формы ────────────────────────────────

def test_four_oh_three_on_an_absent_target_means_the_right_is_absent():
    """Предмет аварии: живой ключ, а права на заказ прогона CI нет."""
    result = prh.probe_token_capabilities(
        secret_reader=_reader(),
        door_probe=_door(_ref_ok({
            ("PATCH", "/git/refs/heads/"): (422, None),
            ("POST", "/dispatches"): (403, None),
        })))
    rows = _by_key(result)
    assert rows["actions_write"]["state"] == prh.CAP_CANNOT
    assert rows["actions_write"]["http_status"] == 403
    assert rows["contents_write"]["state"] == prh.CAP_CAN
    assert result["verdict"] == prh.CAP_CANNOT
    # Находка обязана НАЗЫВАТЬ право и то, что из-за него не работает.
    assert "Actions" in rows["actions_write"]["reason"]
    assert "ci_control_verdict" in rows["actions_write"]["reason"]


def test_the_same_shape_answered_422_means_the_right_is_present():
    """Обратная половина той же оси — без неё «403 ⇒ нет права» непроверяемо."""
    result = prh.probe_token_capabilities(
        secret_reader=_reader(),
        door_probe=_door(_ref_ok({
            ("PATCH", "/git/refs/heads/"): (422, None),
            ("POST", "/dispatches"): (422, None),
        })))
    rows = _by_key(result)
    assert rows["actions_write"]["state"] == prh.CAP_CAN
    assert rows["contents_write"]["state"] == prh.CAP_CAN
    assert result["verdict"] == prh.CAP_CAN
    assert result["cannot"] == 0


def test_a_missing_target_also_means_the_right_is_present():
    """404 «цели не существует» — тот же ответ о праве, что и 422."""
    result = prh.probe_token_capabilities(
        secret_reader=_reader(),
        door_probe=_door(_ref_ok({
            ("PATCH", "/git/refs/heads/"): (404, None),
            ("POST", "/dispatches"): (404, None),
        })))
    assert result["verdict"] == prh.CAP_CAN


# ── третий исход: НЕ ИЗМЕРЕНО, и он никогда не «умеет» ────────────────────────

@pytest.mark.parametrize("scene,expect_calls", [
    ("no_key", 0),
    ("dead_network", 3),
    ("odd_answer", 3),
])
def test_three_kinds_of_unmeasured_never_read_as_can(scene, expect_calls):
    """Ключа нет · сеть молчит · ответ ни тот ни другой — три РАЗНЫЕ причины, один
    исход «НЕ ИЗМЕРЕНО», и ни одна не выдаётся за «умеет» (инвариант #17)."""
    calls = []
    if scene == "no_key":
        result = prh.probe_token_capabilities(
            secret_reader=_reader(secret=None, reason="в связке ключей нет записи"),
            door_probe=_door({}, calls))
    elif scene == "dead_network":
        result = prh.probe_token_capabilities(
            secret_reader=_reader(),
            door_probe=_door(_ref_ok({
                ("PATCH", "/git/refs/heads/"): (None, "сеть не ответила (сцена)"),
                ("POST", "/dispatches"): (None, "сеть не ответила (сцена)"),
            }), calls))
    else:
        result = prh.probe_token_capabilities(
            secret_reader=_reader(),
            door_probe=_door(_ref_ok({
                ("PATCH", "/git/refs/heads/"): (500, None),
                ("POST", "/dispatches"): (500, None),
            }), calls))
    assert result["verdict"] == prh.CAP_UNMEASURED
    assert result["can"] == 0 and result["cannot"] == 0
    assert result["unmeasured"] == result["measured_doors"]
    for row in result["doors"]:
        if row["state"] == prh.CAP_UNMEASURED:
            assert row["reason"], "у «не измерено» обязана быть НАЗВАННАЯ причина"
    assert len(calls) == expect_calls, calls


def test_a_rejected_key_is_unmeasured_capability_not_a_missing_right():
    """401 — вопрос СОСТОЯНИЯ, и у него свой сторож. Назвать его «права нет»
    значило бы послать владельца выдавать право мёртвому ключу."""
    result = prh.probe_token_capabilities(
        secret_reader=_reader(),
        door_probe=_door(_ref_ok({
            ("PATCH", "/git/refs/heads/"): (401, None),
            ("POST", "/dispatches"): (401, None),
        })))
    assert result["verdict"] == prh.CAP_UNMEASURED
    assert result["cannot"] == 0


def test_a_named_absence_wins_over_unmeasured_and_says_its_lower_bound():
    """Запрет рядом с неизмеренным — находка НАЗВАНА, а счёт объявлен НИЖНЕЙ границей."""
    result = prh.probe_token_capabilities(
        secret_reader=_reader(),
        door_probe=_door(_ref_ok({
            ("PATCH", "/git/refs/heads/"): (None, "сеть не ответила (сцена)"),
            ("POST", "/dispatches"): (403, None),
        })))
    assert result["verdict"] == prh.CAP_CANNOT
    assert result["cannot"] == 1 and result["unmeasured"] == 1


# ── безвредность: проба права на ЗАПИСЬ не имеет права писать ─────────────────

def test_an_existing_probe_branch_stops_the_probe_before_any_write():
    """Вся безвредность стои́т на том, что цель ОТСУТСТВУЕТ. Появись ветка-зонд —
    запрос пошёл бы по НАСТОЯЩЕЙ цели, поэтому её отсутствие НАБЛЮДАЕТСЯ, а
    не предполагается, и не-404 останавливает замер ДО первого write."""
    calls = []
    result = prh.probe_token_capabilities(
        secret_reader=_reader(),
        door_probe=_door({("GET", "/git/ref/heads/"): (200, None)}, calls))
    assert result["verdict"] == prh.CAP_UNMEASURED
    assert [c[0] for c in calls] == ["GET"], calls
    assert all(c[0] not in ("PATCH", "POST", "PUT", "DELETE") for c in calls)
    assert prh.CAPABILITY_ABSENT_REF in result["doors"][0]["reason"]


def test_every_probing_door_aims_at_the_declared_absent_target():
    """Сторож против будущей правки, которая нацелит пробу на НАСТОЯЩУЮ ветку.

    Мерится не подстрокой в исходнике, а самим объявлением двери: у каждой пробы и
    путь, и тело обязаны упоминать ровно ветку-зонд.
    """
    probing = [d for d in prh.CAPABILITY_DOORS if d.get("state") is None]
    assert probing, "ни одной двери с безвредной пробой — знаменатель пуст"
    for door in probing:
        blob = door["path"] + repr(door.get("body"))
        assert prh.CAPABILITY_ABSENT_REF in blob, door["key"]
        assert door["method"] in ("PATCH", "POST"), door["key"]
        assert 403 in tuple(door["cannot_codes"]), door["key"]
        assert set(door["can_codes"]) <= {404, 422}, door["key"]


def test_the_probe_target_is_a_name_that_cannot_be_one_of_our_branches():
    """Та же проба, нацеленная на НАСТОЯЩУЮ ветку, умирает МОЛЧА, а не громко.

    Безвредность держит наблюдение 404 (тест выше), но имя цели — вторая линия:
    назови зонд `main`, и существующая ветка навсегда переведёт замер в «не
    измерено», ничего не сломав и ничего не сказав. Проверять «имя константы
    упоминается в дверях» для этого НЕДОСТАТОЧНО — такая проверка истинна при любом
    значении константы, то есть она тавтологична (мутация «зонд = main» её
    переживала).
    """
    ref = prh.CAPABILITY_ABSENT_REF
    assert ref.startswith("__") and ref.endswith("__"), ref
    assert "probe" in ref, ref
    assert "/" not in ref, "ветка-зонд не имеет права выглядеть как пространство имён"
    assert ref not in {"main", "master", "HEAD", "gh-pages", "dev"}, ref
    assert not ref.startswith(("rescue/", "wip/", "feature/", "refs/")), ref


def test_the_token_itself_never_leaves_the_probe(capsys):
    """Инвариант #7: наружу уходят код ответа и имя права, но не секрет."""
    result = prh.probe_token_capabilities(
        secret_reader=_reader(),
        door_probe=_door(_ref_ok({
            ("PATCH", "/git/refs/heads/"): (422, None),
            ("POST", "/dispatches"): (403, None),
        })))
    prh.cmd_probe_capabilities(result)
    printed = capsys.readouterr().out
    assert _SCENE_TOKEN not in printed
    assert _SCENE_TOKEN not in repr(result)


# ── знаменатель объявлен, а не подразумевается ────────────────────────────────

def test_doors_answered_by_repo_visibility_are_out_of_the_denominator():
    """Репозиторий ПУБЛИЧНЫЙ: читающие двери отвечают 200 вовсе без ключа (замер
    2026-11-28), поэтому 200 на них есть свойство видимости, а не грант. Зачесть их
    в «умеет» значило бы повторить «ключ ЕСТЬ ⇒ ключ ЖИВ» на новом месте."""
    result = prh.probe_token_capabilities(
        secret_reader=_reader(),
        door_probe=_door(_ref_ok({
            ("PATCH", "/git/refs/heads/"): (422, None),
            ("POST", "/dispatches"): (422, None),
        })))
    rows = _by_key(result)
    assert rows["contents_read"]["state"] == prh.CAP_ANSWERED_BY_VISIBILITY
    assert rows["actions_read"]["state"] == prh.CAP_ANSWERED_BY_VISIBILITY
    assert result["answered_by_visibility"] == 2
    assert result["measured_doors"] < result["declared_doors"]
    assert result["measured_doors"] == result["can"] + result["cannot"] + result["unmeasured"]


def test_a_door_without_a_harmless_probe_is_declared_with_a_reason():
    """`no_safe_probe` — ОБЪЯВЛЕННАЯ граница меры, и она не имеет права стать
    тихим укрытием: причина обязательна у каждой такой двери."""
    declared = [d for d in prh.CAPABILITY_DOORS if d.get("state") is not None]
    assert declared
    for door in declared:
        assert door["state"] in (prh.CAP_NO_SAFE_PROBE,
                                 prh.CAP_ANSWERED_BY_VISIBILITY), door["key"]
        assert door.get("reason"), door["key"]
        assert door.get("permission"), door["key"]
        assert door.get("need"), door["key"]


def test_the_declared_door_registry_cannot_shrink_silently():
    """Перечень дверей — ЗНАМЕНАТЕЛЬ. Укоротить его молча значило бы ответить
    «умеет всё» про меньший вопрос; перечень снят с кода пушеров, а не из головы."""
    keys = [d["key"] for d in prh.CAPABILITY_DOORS]
    assert keys == ["contents_write", "actions_write", "workflows_write",
                    "contents_read", "actions_read"], keys
    assert len(set(keys)) == len(keys)
    assert prh.CAPABILITY_CI_WORKFLOW == "ci-control.yml", (
        "спрашивать право надо у ТОГО воркфлоу, которым заказывает прогон "
        "scripts/ci_control_verdict.py")


def test_an_empty_denominator_is_unmeasured_not_can():
    """Ни одной двери с безвредной пробой — это НЕ «всё умеет»."""
    result = prh.probe_token_capabilities(
        secret_reader=_reader(),
        door_probe=_door({}),
        doors=({"key": "only_declared", "need": "n", "permission": "p",
                "state": prh.CAP_NO_SAFE_PROBE, "reason": "r"},))
    assert result["verdict"] == prh.CAP_UNMEASURED
    assert result["measured_doors"] == 0


def test_cli_has_three_exit_codes():
    """0=умеет · 1=права НЕТ · 2=НЕ ИЗМЕРЕНО. Код 2 отдельно от 1 потому, что
    «сеть молчит» и «владелец не выдал право» чинят разные люди."""
    assert prh.cmd_probe_capabilities({"verdict": prh.CAP_CAN, "doors": []}) == 0
    assert prh.cmd_probe_capabilities(
        {"verdict": prh.CAP_CANNOT, "doors": [], "unmeasured": 0}) == 1
    assert prh.cmd_probe_capabilities({"verdict": prh.CAP_UNMEASURED, "doors": []}) == 2


# ── у меры есть ЧИТАТЕЛЬ, иначе это украшение ────────────────────────────────

_SCENE_OVERRIDE = '''

import os as _probe_os


def _read_keychain_secret(service, runner=None):  # noqa: F811
    if _probe_os.environ.get("SPA_TEST_CAP_SCENE") == "no_key":
        return None, "в связке ключей нет записи с именем сервиса"
    return "scene_token_not_a_real_secret", None


def _github_identity_probe(token, timeout=None):  # noqa: F811
    return 200, {}, None


def _github_door_probe(token, method, url, body=None, timeout=None):  # noqa: F811
    scene = _probe_os.environ.get("SPA_TEST_CAP_SCENE")
    if "/git/ref/heads/" in url and method == "GET":
        return 404, None
    if scene == "can":
        return 422, None
    if scene == "cannot":
        return (403, None) if "/dispatches" in url else (422, None)
    return None, "сеть не ответила (сцена теста)"
'''


def _scene_tree(tmp_path, *, with_capabilities=True):
    """Дерево-сцена: НАСТОЯЩИЙ страж, у которого подменены только двери наружу."""
    root = tmp_path / "scene"
    (root / "scripts").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    src = (_PROJECT_ROOT / "scripts" / "pat_rotation_helper.py").read_text(encoding="utf-8")
    if not with_capabilities:
        # Сцена «страж СТАРШЕ ADR-1128»: наблюдения о способности нет вовсе.
        src = src.replace("def probe_token_capabilities(",
                          "def _removed_probe_token_capabilities(")
    (root / "scripts" / "pat_rotation_helper.py").write_text(
        src + _SCENE_OVERRIDE, encoding="utf-8")
    return root


@pytest.mark.parametrize("scene,expected", [
    ("cannot", CRITICAL), ("can", OK), ("no_key", WARNING), ("dead", WARNING),
])
def test_health_check_maps_the_outcomes(tmp_path, monkeypatch, scene, expected):
    """Отсутствующее право — АВАРИЯ: рычаг у владельца, и молчать о нём нельзя.
    Не измерено — WARNING с причиной и НИКОГДА OK."""
    monkeypatch.setenv("SPA_TEST_CAP_SCENE", scene)
    root = _scene_tree(tmp_path)
    monitor = SystemHealthMonitor(project_root=root, data_dir=str(root / "data"))
    got = monitor._check_pat_token_capable("d5_code_integrity")
    assert got.status == expected, got.to_dict()
    if expected != OK:
        assert got.error, "непринятая способность обязана нести названную причину"
    if expected == CRITICAL:
        assert "Actions" in got.title
        assert "owner" in got.title


def test_health_check_refuses_to_say_ok_about_a_guard_that_cannot_ask(tmp_path, monkeypatch):
    """Дерево старше ADR-1128: сторож не умеет спросить ⇒ WARNING с причиной."""
    monkeypatch.setenv("SPA_TEST_CAP_SCENE", "can")
    root = _scene_tree(tmp_path, with_capabilities=False)
    monitor = SystemHealthMonitor(project_root=root, data_dir=str(root / "data"))
    got = monitor._check_pat_token_capable("d5_code_integrity")
    assert got.status == WARNING
    assert "probe_token_capabilities" in (got.error or "")


def test_health_check_is_wired_into_the_domain(tmp_path, monkeypatch):
    """Проверка без вызывающего — то самое украшение. Мерится ИСХОДОМ домена.

    И рядом обязаны остаться оба прежних вопроса о ключе: способность их не
    заменяет, она третья.
    """
    monkeypatch.setenv("SPA_TEST_CAP_SCENE", "cannot")
    root = _scene_tree(tmp_path)
    monitor = SystemHealthMonitor(project_root=root, data_dir=str(root / "data"))
    by_id = {r.id: r for r in monitor.check_d5_code_integrity()}
    assert "d5.security.pat_token_capable" in by_id, sorted(by_id)
    assert "d5.security.pat_token_alive" in by_id, "вопрос о состоянии не заменён"
    assert "d5.security.pat_rotation" in by_id, "календарный вопрос не заменён"
    assert by_id["d5.security.pat_token_capable"].status == CRITICAL


def test_the_three_questions_are_appended_in_one_place():
    """Проводка мерится AST, а не подстрокой: все три вердикта о ключе обязаны
    добавляться в ОДНОМ списке — иначе один из них легко потерять правкой, и
    потеря будет невидимой."""
    src = (_PROJECT_ROOT / "spa_core" / "monitoring"
           / "system_health_monitor.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    wanted = {"_check_pat_rotation", "_check_pat_token_alive", "_check_pat_token_capable"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        called = set()
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr in wanted):
                called.add(inner.func.attr)
        if called == wanted:
            return
    raise AssertionError(
        "ни одна функция не добавляет все три вердикта о ключе: "
        f"{sorted(wanted)} — проводка разошлась")
