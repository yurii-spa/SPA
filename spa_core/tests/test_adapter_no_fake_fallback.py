"""Сторож: адаптер БЕЗ НАБЛЮДЕНИЯ обязан отвечать ``None``, а не литералом.

Решение владельца 2026-08-08, вариант 1 карточки
``owner-decision-morfo-40-knigi-pri-propazhe-dannyh-podst``:

    «Убрать подстановку 6.5 % у Морфо — нет данных означает "не знаю", как у
     остальных одиннадцати адаптеров. Плюс добавить проверку, которая краснеет,
     если подстановка вернётся в ЛЮБОЙ адаптер (чтобы третьего раза не было).»

Почему «третьего раза». Первый раз — ADR-063 (2026-08-02), двенадцать адаптеров.
Второй — тот же ADR прошёл мимо Морфо, потому что у Морфо подстановка сидела не в
``get_apy()``, а в соседнем ``get_apy_pct()``, и правку делали по имени метода.
Отсюда конструкция сторожа: он смотрит на ПОВЕДЕНИЕ канонического
``get_apy()`` при отсутствии наблюдения, и ему безразлично, в каком методе,
константе или ветке спрятана подстановка.

Каждый тест ниже — положительный контроль: он воспроизводит замеренный дефект и
краснеет на неисправленном коде (замер на 785d8104d записан в карточке).

Правило `.claude/rules/adapters.md`: «Никаких fake-fallback'ов. Если фид
недоступен / данные не пришли — адаптер возвращает None (by design), система
fail-close'ится, а не подставляет выдуманное значение».
"""
from __future__ import annotations

import importlib
import inspect
import json
import socket
import urllib.request
from pathlib import Path

import pytest

from spa_core.adapters import ADAPTER_REGISTRY
from spa_core.adapters.morpho_steakhouse_adapter import MorphoSteakhouseAdapter

_BASELINE_PATH = Path(__file__).with_name("adapter_fake_fallback_baseline.json")


# ── общий стенд «наблюдения нет» ─────────────────────────────────────────────

def _kill_network(monkeypatch) -> None:
    """Наблюдение невозможно физически: ни сети, ни сокетов.

    Без этого тест бесполезен: адаптер сходит в DeFiLlama, вернёт ЖИВОЕ число,
    и сторож зазеленеет на неисправленном коде. Именно так провалился первый
    (негодный) замер 2026-08-08 — он показал 17 нарушителей, из которых 15
    оказались живыми данными.
    """
    def _boom(*args, **kwargs):
        raise OSError("network disabled by test")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(socket, "create_connection", _boom)


def _build_blind(cls, empty_dir: Path):
    """Строит адаптер, которому НЕОТКУДА взять наблюдение."""
    params = inspect.signature(cls.__init__).parameters
    kwargs = {}
    if "data_dir" in params:
        kwargs["data_dir"] = str(empty_dir)
    if "http_get" in params:
        def _boom(*a, **k):
            raise OSError("network disabled by test")
        kwargs["http_get"] = _boom
    adapter = cls(**kwargs)
    feed = getattr(adapter, "feed", None)
    if feed is not None:
        try:
            feed.enabled = False
        except Exception:  # noqa: BLE001 — не у всех фидов есть флаг
            pass
    return adapter


@pytest.fixture()
def blind_morpho(tmp_path, monkeypatch):
    """Морфо без единого источника наблюдения (пустой data_dir + нет сети)."""
    _kill_network(monkeypatch)
    return _build_blind(MorphoSteakhouseAdapter, tmp_path)


# ── морфо: положительные контроли реального дефекта 2026-08-02 ───────────────

def test_morpho_get_apy_pct_is_none_without_observation(blind_morpho):
    """Было 6.5 — литерал. Стало None."""
    assert blind_morpho.get_apy_pct() is None


def test_morpho_get_apy_is_none_without_observation(blind_morpho):
    """Было 0.065. Именно это утверждение ADR-063 п.3 объявлял выполненным."""
    assert blind_morpho.get_apy() is None


def test_morpho_switch_recommended_is_false_without_observation(blind_morpho):
    """САМЫЙ ЗЛОЙ из дефектов: метод отвечал True РОВНО КОГДА данных не было.

    6.5 % (выдуманные) против бенчмарка Aave 3.2 % + 50 bps ⇒ «переложись в
    Морфо». То есть пропажа фида не гасила рекомендацию, а ВКЛЮЧАЛА её.
    """
    assert blind_morpho.switch_recommended() is False


def test_morpho_switch_gain_pct_is_none_without_observation(blind_morpho):
    """Было 3.3 п.п. «выигрыша», посчитанного из воздуха."""
    assert blind_morpho.switch_gain_pct() is None


def test_morpho_allocate_reports_no_apy_without_observation(blind_morpho):
    """Отчёт об аллокации не имеет права штамповать выдуманный APY."""
    assert blind_morpho.allocate(1_000.0)["apy_pct"] is None


def test_morpho_health_check_is_degraded_and_says_not_observed(blind_morpho):
    health = blind_morpho.health_check()
    assert health["status"] == "degraded"
    assert health["apy_pct"] is None
    assert health["apy_observed"] is False


def test_morpho_class_has_no_fallback_attribute():
    """Атрибута нет СОВСЕМ — пока он есть, его легко «вернуть на минутку»."""
    assert not hasattr(MorphoSteakhouseAdapter, "FALLBACK_APY_PCT")


# ── контроль в обратную сторону: наблюдение по-прежнему проходит ─────────────

def test_morpho_status_file_observation_still_works(tmp_path, monkeypatch):
    """Сторож не должен превращать адаптер в вечное «не знаю».

    Без этого теста «починка» вида ``return None`` всегда была бы зелёной.
    """
    _kill_network(monkeypatch)
    (tmp_path / "adapter_status.json").write_text(
        json.dumps({"morpho_steakhouse": {"apy": 3.4657}}), encoding="utf-8"
    )
    adapter = _build_blind(MorphoSteakhouseAdapter, tmp_path)
    assert adapter.get_apy_pct() == pytest.approx(3.4657)
    assert adapter.get_apy() == pytest.approx(0.034657)
    assert adapter.health_check()["apy_observed"] is True


def test_morpho_live_feed_observation_still_works(tmp_path, monkeypatch):
    """Живой фид — первый приоритет и он не сломан."""
    _kill_network(monkeypatch)
    adapter = _build_blind(MorphoSteakhouseAdapter, tmp_path)
    monkeypatch.setattr(
        adapter, "fetch_live",
        lambda *a, **k: {"apy": 0.0347, "tvl": 105_000_000.0, "live_data": True},
    )
    assert adapter.get_apy_pct() == pytest.approx(3.47)
    assert adapter.get_yield_info().apy == pytest.approx(0.0347)


def test_morpho_switch_recommended_still_fires_on_real_observation(tmp_path, monkeypatch):
    """False без данных — не «всегда False»: на наблюдённом превосходстве True."""
    _kill_network(monkeypatch)
    (tmp_path / "adapter_status.json").write_text(
        json.dumps({"morpho_steakhouse": {"apy": 9.0}}), encoding="utf-8"
    )
    adapter = _build_blind(MorphoSteakhouseAdapter, tmp_path)
    assert adapter.switch_recommended() is True
    assert adapter.switch_gain_pct() == pytest.approx(5.8)


# ── храповик по ВСЕМ адаптерам реестра ───────────────────────────────────────

def _sweep_registry(tmp_path, monkeypatch) -> dict:
    """{имя адаптера: значение get_apy()} для тех, кто вернул НЕ None."""
    return _sweep_registry_full(tmp_path, monkeypatch)[0]


def _sweep_registry_full(tmp_path, monkeypatch):
    """Как ``_sweep_registry``, но ещё и СКОЛЬКО адаптеров реально опрошено.

    2026-08-17, инв. №16 — изменение намеренное и РАСШИРЯЮЩЕЕ. Прежний свип
    глотал любое исключение через ``continue`` и возвращал только словарь
    нарушителей. Из-за этого он мог пройти ВХОЛОСТУЮ: если конструирование
    ломается у всех разом (замерено — достаточно одного затенённого модуля
    stdlib в ``sys.path``, и все 36 падают на ``inspect.signature``), словарь
    выходит пустым, и оба храповика зеленеют, ничего не проверив. Пустой
    результат «нарушителей нет» и пустой результат «замер не состоялся» были
    неотличимы — ровно тот класс, что и `#242`.

    Поэтому счётчик опрошенных возвращается наружу и проверяется отдельным
    тестом. Ни одна прежняя проверка не ослаблена: старая сигнатура сохранена
    обёрткой выше, глотание исключений оставлено (падение действительно НЕ
    подстановка), но теперь оно ВИДНО.
    """
    _kill_network(monkeypatch)
    violators = {}
    probed = 0
    for name, _tier, cls in ADAPTER_REGISTRY:
        try:
            value = _build_blind(cls, tmp_path).get_apy()
        except Exception:  # noqa: BLE001 — падение ≠ подстановка; это не наш класс дефекта
            continue
        probed += 1
        if value is not None:
            violators[name] = value
    return violators, probed


def _module_level_apy_functions():
    """МОДУЛЬНЫЕ (не методы класса) функции ``get_apy*`` в модулях адаптеров.

    Слепое пятно, стоившее двух выживших подстановок: сторож ищет литерал
    только в ``cls.get_apy()``, а рядом с классом живёт одноимённая функция
    уровня модуля «для обратной совместимости», и у неё СВОЯ точка возврата.
    """
    seen_modules = set()
    for name, _tier, cls in ADAPTER_REGISTRY:
        module = importlib.import_module(cls.__module__)
        if module.__name__ in seen_modules:
            continue
        seen_modules.add(module.__name__)
        for attr in dir(module):
            if not attr.startswith("get_apy"):
                continue
            fn = getattr(module, attr)
            if inspect.isfunction(fn):
                yield name, module, attr, fn


def _apy_values_of(result):
    """Все непустые APY-поля результата — и у объекта, и у dict.

    Второе слепое пятно: ``get_yield_info()`` у части адаптеров возвращает
    ОБЪЕКТ с атрибутом ``.apy``, а у части — ``dict`` с ключом ``apy_pct``.
    Проверка через ``getattr(result, "apy", None)`` на dict молча даёт ``None``,
    то есть докладывает «чисто» именно там, где смотреть и надо было.
    """
    keys = ("apy", "apy_pct", "apy_percent", "current_apy", "net_apy")
    if isinstance(result, dict):
        return {k: result[k] for k in keys if result.get(k) is not None}
    return {k: getattr(result, k) for k in keys if getattr(result, k, None) is not None}


def test_morpho_is_not_in_the_baseline():
    """Морфо обязан быть ВЫЧЕРКНУТ из базы — это и есть решение владельца."""
    baseline = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
    assert "morpho_steakhouse" not in baseline["known_violators"]


def test_no_new_adapter_starts_substituting_a_literal(tmp_path, monkeypatch):
    """Новых нарушителей быть не может. База — только для уже замеренных.

    Это ХРАПОВИК: если тест покраснел, чинить адаптер, а НЕ дописывать его
    в ``adapter_fake_fallback_baseline.json``.
    """
    baseline = set(json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))["known_violators"])
    found = _sweep_registry(tmp_path, monkeypatch)
    new = sorted(set(found) - baseline)
    assert not new, (
        "Адаптер(ы) начали подставлять литерал вместо None: "
        + ", ".join(f"{n}={found[n]!r}" for n in new)
        + ". Чинить адаптер (нет наблюдения ⇒ None), а не дописывать в baseline — "
          "запрет ровно тот же, что у test_frozen_date_ratchet."
    )


def test_baseline_only_shrinks(tmp_path, monkeypatch):
    """Починил адаптер — вычеркни его из базы. Иначе храповик не храповик."""
    baseline = set(json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))["known_violators"])
    found = set(_sweep_registry(tmp_path, monkeypatch))
    fixed = sorted(baseline - found)
    assert not fixed, (
        "Эти адаптеры УЖЕ честны, но всё ещё числятся нарушителями: "
        + ", ".join(fixed)
        + ". Вычеркни их из adapter_fake_fallback_baseline.json."
    )


def test_sweep_actually_probed_every_adapter(tmp_path, monkeypatch):
    """Храповик не имеет права пройти ВХОЛОСТУЮ.

    Положительный контроль: свип глотает исключения, поэтому «нарушителей 0»
    и «не удалось опросить ни одного» выглядят одинаково. Здесь проверяется,
    что замер вообще состоялся — иначе оба теста-храповика выше зелены по
    построению и не значат ничего.
    """
    _violators, probed = _sweep_registry_full(tmp_path, monkeypatch)
    total = len(ADAPTER_REGISTRY)
    assert probed == total, (
        f"Свип опросил {probed} адаптеров из {total} — остальные упали при "
        "конструировании или в get_apy(). Пока они падают, храповик подстановок "
        "по ним НЕ РАБОТАЕТ и зелен вхолостую. Чинить адаптер (или стенд), а не "
        "ослаблять эту проверку."
    )


def test_module_level_get_apy_twin_does_not_substitute(tmp_path, monkeypatch):
    """Модульный двойник ``get_apy()`` тоже обязан отвечать ``None``.

    Положительный контроль замера 2026-08-17: метод класса починили 08.08, а
    одноимённые функции уровня модуля пережили починку и продолжали отдавать
    свой литерал — ``extra_finance_base`` 8.0, ``moonwell_base`` 5.5. Сторож их
    не видел, потому что смотрел только на ``cls.get_apy()``.
    """
    _kill_network(monkeypatch)
    monkeypatch.chdir(tmp_path)
    offenders = {}
    for name, module, attr, fn in _module_level_apy_functions():
        # кэш модуля мог сохранить наблюдение от соседнего теста
        cache = getattr(module, "_cache", None)
        if isinstance(cache, dict):
            cache.clear()
        try:
            value = fn()
        except Exception:  # noqa: BLE001 — падение ≠ подстановка
            continue
        if value is not None:
            offenders[f"{module.__name__.split('.')[-1]}.{attr}"] = value
    assert not offenders, (
        "Модульные функции подставляют литерал вместо None: "
        + ", ".join(f"{k}={v!r}" for k, v in sorted(offenders.items()))
        + ". Чинить функцию (нет наблюдения ⇒ None), а не эту проверку."
    )


def test_get_yield_info_carries_no_literal_in_any_shape(tmp_path, monkeypatch):
    """``get_yield_info()`` не несёт APY, когда наблюдения нет — в ЛЮБОЙ форме.

    Положительный контроль замера 2026-08-17: у ``extra_finance_base`` этот
    метод возвращает ``dict`` с ключом ``apy_pct`` и подставлял туда 8.0 из
    ``self.APY_FALLBACK`` — независимо от уже починенного ``get_apy()``.
    Проверка «через атрибут ``.apy``» на dict молча возвращает ``None``, то
    есть докладывала «чисто» ровно там, где сидел литерал.
    """
    _kill_network(monkeypatch)
    offenders = {}
    for name, _tier, cls in ADAPTER_REGISTRY:
        try:
            info = _build_blind(cls, tmp_path).get_yield_info()
        except Exception:  # noqa: BLE001 — падение ≠ подстановка
            continue
        leaked = _apy_values_of(info)
        if leaked:
            offenders[name] = leaked
    assert not offenders, (
        "APY доехал до поверхности оркестратора без наблюдения: "
        + ", ".join(f"{k}={v!r}" for k, v in sorted(offenders.items()))
        + ". Чинить адаптер, а не проверку."
    )


def test_baseline_names_are_real_registry_entries():
    """База не должна тухнуть: имя из неё обязано существовать в реестре."""
    baseline = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))["known_violators"]
    known = {name for name, _tier, _cls in ADAPTER_REGISTRY}
    assert not (set(baseline) - known), (
        f"В базе нарушителей есть несуществующие адаптеры: {sorted(set(baseline) - known)}"
    )
