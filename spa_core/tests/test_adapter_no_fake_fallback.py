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
    _kill_network(monkeypatch)
    violators = {}
    for name, _tier, cls in ADAPTER_REGISTRY:
        try:
            value = _build_blind(cls, tmp_path).get_apy()
        except Exception:  # noqa: BLE001 — падение ≠ подстановка; это не наш класс дефекта
            continue
        if value is not None:
            violators[name] = value
    return violators


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


def test_baseline_names_are_real_registry_entries():
    """База не должна тухнуть: имя из неё обязано существовать в реестре."""
    baseline = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))["known_violators"]
    known = {name for name, _tier, _cls in ADAPTER_REGISTRY}
    assert not (set(baseline) - known), (
        f"В базе нарушителей есть несуществующие адаптеры: {sorted(set(baseline) - known)}"
    )
