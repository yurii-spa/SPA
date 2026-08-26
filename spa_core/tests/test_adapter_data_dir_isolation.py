"""Заслон герметичности доходит до адаптеров — положительный контроль на реальной аварии.

Что здесь проверяется
------------------------------------------------------------------------------
``tests/conftest.py::_isolate_data_dir`` обещает, что код, разрешающий каталог
состояния штатным механизмом (``SPA_DATA_DIR``), никогда не прочитает живой
``data/``. До цикла #386 из 16 адаптерных модулей под это обещание не попадал НИ
ОДИН: каждый брал ``_DEFAULT_DATA_DIR = _REPO_ROOT / "data"`` константой,
вычисляемой при импорте, — то есть до того, как фикстура успевала выставить
переменную.

Авария, которую воспроизводит этот файл (замер цикла #361, карточка
``inbox-zaslon-izolyatsii-data-v-testah-pokryvae``):

| состояние хоста                        | ``_adapter_class_gate("spark_susds")`` |
|---|---|
| канон ``origin/main`` (наблюдения GSM нет) | ``(False, 'gsm_not_confirmed')``  |
| боевое дерево (GSM 48 ч наблюдён, ADR-065) | ``(True, None)``                  |

Один и тот же код, два вердикта — решал файл данных хоста. Каждый тест ниже
краснеет на НЕпочиненном модуле (умолчание, разрешённое при импорте, переменную
не видит) и зелен при ЛЮБОМ состоянии живого ``data/``.

Почему проверка идёт через переменную, а не через подмену константы
------------------------------------------------------------------------------
``monkeypatch.setattr(mod, "_DEFAULT_DATA_DIR", tmp)`` работал и раньше — и
именно поэтому ничего не доказывает: он чинит ОДИН тест, оставляя механизм,
которым пользуется весь набор, неподключённым. Здесь инъекция идёт ровно тем
способом, каким её делает autouse-фикстура.

Обратный контроль обязателен и он тут есть
------------------------------------------------------------------------------
``test_default_is_unchanged_when_the_env_is_absent``: без переменной умолчание
остаётся ``<дерево модуля>/data`` — прод-поведение бит-в-бит прежнее. Без этой
половины «починка» была бы неотличима от тихого переезда состояния.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from spa_core.utils.data_dir import DATA_DIR_ENV, own_data_dir

# (модуль, класс) — все адаптерные модули, починенные циклом #386.
# Список поимённый, а не собранный сканом: скан, потерявший модуль, оставил бы
# тест зелёным ровно в том случае, ради которого он написан.
_FIXED = [
    ("sdai_adapter", "SdaiAdapter"),
    ("wusdm_adapter", "WusdmAdapter"),
    ("spark_susds_adapter", "SparkSusdsAdapter"),
    ("fluid_fusdc_adapter", "FluidFUSDCAdapter"),
    ("sfrax_adapter", "SfraxAdapter"),
    ("aave_v3_optimism_adapter", "AaveV3OptimismAdapter"),
    ("aave_v3_polygon_adapter", "AaveV3PolygonAdapter"),
    ("susde_adapter", "SusdeAdapter"),
    ("scrvusd_adapter", "ScrvusdAdapter"),
    ("sky_susds_feed", "SkySUSDSFeed"),
    ("stusd_adapter", "StusdAdapter"),
    ("morpho_steakhouse_adapter", "MorphoSteakhouseAdapter"),
    ("compound_v3_adapter", "CompoundV3Adapter"),
    ("frax_adapter", "FraxAdapter"),
]


def _resolved_data_dir(obj) -> Path:
    """Каталог, который адаптер выбрал себе сам (имя поля у двух модулей разное)."""
    for attr in ("_data_dir", "data_dir"):
        value = getattr(obj, attr, None)
        if value is not None:
            return Path(value)
    raise AssertionError(f"{type(obj).__name__} не выставил каталог состояния вовсе")


# ── сам хелпер ──────────────────────────────────────────────────────────────


def test_own_data_dir_prefers_the_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DATA_DIR_ENV, "/tmp/spa-sandbox")
    assert own_data_dir(Path("/repo/data")) == Path("/tmp/spa-sandbox")


def test_own_data_dir_falls_back_to_the_module_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DATA_DIR_ENV, raising=False)
    assert own_data_dir(Path("/repo/data")) == Path("/repo/data")


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_env_is_absent_not_cwd(
    monkeypatch: pytest.MonkeyPatch, blank: str,
) -> None:
    """Пустая строка — «не выставлено», а не ``Path(".")``.

    ``Path("")`` это текущий каталог: молчаливый переезд состояния в cwd был бы
    ровно тем классом отказа, ради которого написан ``utils/live_paths.py``.
    """
    monkeypatch.setenv(DATA_DIR_ENV, blank)
    assert own_data_dir(Path("/repo/data")) == Path("/repo/data")


# ── адаптеры ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("mod_name", "cls_name"), _FIXED)
def test_adapter_default_follows_the_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mod_name: str, cls_name: str,
) -> None:
    """Каждый починенный адаптер разрешает умолчание В МОМЕНТ ВЫЗОВА.

    Красный на непочиненном модуле при любом состоянии хоста: константа,
    вычисленная при импорте, отдаст ``<дерево>/data``.
    """
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path))
    mod = importlib.import_module(f"spa_core.adapters.{mod_name}")
    adapter = getattr(mod, cls_name)()
    assert _resolved_data_dir(adapter) == tmp_path, mod_name


@pytest.mark.parametrize(("mod_name", "cls_name"), _FIXED)
def test_default_is_unchanged_when_the_env_is_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mod_name: str, cls_name: str,
) -> None:
    """Обратный контроль: без переменной конструктор берёт РОВНО умолчание модуля.

    Это и есть обещание «в проде бит-в-бит прежнее поведение», проверенное, а не
    заявленное: там ``SPA_DATA_DIR`` не выставлена.

    Умолчание при этом подменено на tmp НАМЕРЕННО. Дать конструктору разрешиться
    в настоящий ``<дерево>/data`` было бы не «честнее», а вредно: часть адаптеров
    пишет туда журнал прямо при создании, и сторож записи в живое состояние
    краснеет на такой прогон по делу (карточка
    ``agent-test-run-dirties-tracked-fixtures``). Что сама константа осталась
    каталогом своего дерева, проверяет
    ``test_module_default_still_points_at_the_own_tree`` ниже — вместе эти две
    половины и составляют утверждение о проде.
    """
    monkeypatch.delenv(DATA_DIR_ENV, raising=False)
    mod = importlib.import_module(f"spa_core.adapters.{mod_name}")
    monkeypatch.setattr(mod, "_DEFAULT_DATA_DIR", tmp_path, raising=True)
    adapter = getattr(mod, cls_name)()
    assert _resolved_data_dir(adapter) == tmp_path, mod_name


@pytest.mark.parametrize(("mod_name", "cls_name"), _FIXED)
def test_module_default_still_points_at_the_own_tree(
    mod_name: str, cls_name: str,
) -> None:
    """Вторая половина прод-паритета: сама константа не переехала.

    Проверяется без создания адаптера — утверждение о ЗНАЧЕНИИ, и побочных
    записей в живое состояние тут быть не должно.
    """
    mod = importlib.import_module(f"spa_core.adapters.{mod_name}")
    assert mod._DEFAULT_DATA_DIR == mod._REPO_ROOT / "data", mod_name


def test_explicit_data_dir_still_wins_over_the_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Вызывающий сказал — вызывающий прав: хелпер трогает только УМОЛЧАНИЕ."""
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path / "sandbox"))
    explicit = tmp_path / "explicit"
    from spa_core.adapters.spark_susds_adapter import SparkSusdsAdapter
    assert _resolved_data_dir(SparkSusdsAdapter(data_dir=explicit)) == explicit


# ── общий читатель схемы ────────────────────────────────────────────────────


def test_status_reader_reads_from_the_env_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """``status_reader`` — общий читатель для 14 адаптеров, его цена самая высокая."""
    from spa_core.adapters import status_reader
    (tmp_path / status_reader.STATUS_FILENAME).write_text(
        json.dumps({"adapters": {"probe": {"live_apy": 4.2}}}), encoding="utf-8")
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path))
    assert status_reader.read_status_doc()["adapters"]["probe"]["live_apy"] == 4.2


def test_status_reader_sees_an_empty_sandbox_as_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Пустая песочница ⇒ пусто, ЧТО БЫ ни лежало в живом ``data/`` хоста.

    Половина, доказывающая независимость от дерева: без починки этот вызов
    возвращал бы содержимое живого файла.
    """
    from spa_core.adapters import status_reader
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path))
    assert status_reader.read_status_doc() == {}


# ── воспроизведение самой аварии: денежный гейт ─────────────────────────────


_GSM_CASES = [
    # наблюдение есть и свежее → капитал может войти (ADR-065)
    ("confirmed_at_threshold", {"gsm_hours": 48.0}, 1, (True, None)),
    ("confirmed_above_threshold", {"gsm_hours": 72.0}, 1, (True, None)),
    # …и каждый способ наблюдению не состояться держит дверь закрытой (инв. 10)
    ("below_threshold", {"gsm_hours": 47.9}, 1, (False, "gsm_not_confirmed")),
    ("never_observed", {}, None, (False, "gsm_not_confirmed")),
    ("reading_expired", {"gsm_hours": 72.0}, 200, (False, "gsm_not_confirmed")),
]


@pytest.mark.parametrize(("case", "block", "age_h", "expected"), _GSM_CASES)
def test_gsm_gate_follows_the_injected_observation_via_the_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    case: str, block: dict, age_h, expected: tuple,
) -> None:
    """Та самая авария, воспроизведённая ЧЕРЕЗ штатный механизм заслона.

    Инъекция — только ``SPA_DATA_DIR``; константа модуля не подменяется. Значит,
    зелёный здесь означает, что механизм, которым пользуется весь набор, наконец
    доходит до настоящей цепочки: реестр → настоящий класс адаптера →
    ``is_gsm_compliant`` → ``status_reader.gsm_confirmed``.

    Инвариант 10 не ослаблен: 0 % до подтверждения задержки; изменилось лишь то,
    что «подтверждено» теперь подаёт ТЕСТ, а не дерево, из которого его запустили.
    """
    from spa_core.allocator.allocator import _adapter_class_gate
    from spa_core.tests._freshness import ts

    payload = dict(block)
    if age_h is not None:
        payload["gsm_hours_as_of"] = ts(hours_ago=age_h)
    (tmp_path / "adapter_status.json").write_text(
        json.dumps({"adapters": {"spark_susds": payload}}), encoding="utf-8")
    monkeypatch.setenv(DATA_DIR_ENV, str(tmp_path))

    assert _adapter_class_gate("spark_susds") == expected, case
