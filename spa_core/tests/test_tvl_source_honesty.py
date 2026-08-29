"""Живой TVL обязан называться живым, а подстановка — литералом (ADR-053).

Замер 29.08: `ethena_susde` и `fluid_usdc` берут TVL у DeFiLlama — число совпадает с пулом
ДО ДОЛЛАРА ($1 328 991 640 против $1 328 948 554) — но в `YieldInfo` не передавали
`tvl_source` вовсе, и умолчание `"static"` делало пул НЕ проходящим порог TVL. Живое число
носило метку литерала, и два крупных кандидата ($1.33 млрд под 4.75 % и $149 млн под 4.66 %)
оказывались нефинансируемы по причине, не имеющей отношения к их качеству.

Обратная сторона здесь важнее прямой: подстановка `FALLBACK_TVL_USD` НЕ смеет уехать под
ярлыком «живое» — это дефект ADR-126 («метка живое на КОНСТАНТЕ»), только наоборот. Поэтому
флаг снимается ДО подстановки, и проверяется в обе стороны.

Шов инъекции — тот же `http_get`, что у соседних тестов адаптеров: помощник переиспользуется,
а не копируется (своя копия фикстуры — второй дом для одного факта).
"""
from __future__ import annotations

import pytest

from spa_core.adapters.ethena_susde_adapter import EthenaSusdeAdapter
from spa_core.tests.test_ethena_susde_adapter import _make_http


class TestLiveTvlIsCalledLive:
    def test_live_pool_tvl_is_labelled_live(self):
        a = EthenaSusdeAdapter(http_get=_make_http(primary_value=12.0, dl_tvl=1_000_000_000.0))
        info = a.get_yield_info()
        assert info.tvl_source == "live", "TVL пришёл из пула — метка обязана быть live"
        assert info.tvl_usd == pytest.approx(1_000_000_000.0)

    def test_tvl_is_live_even_when_apy_feed_is_dead(self):
        """Живость TVL — ОТДЕЛЬНЫЙ сигнал: APY может отсутствовать, а пул быть живым."""
        a = EthenaSusdeAdapter(http_get=_make_http(primary_fail=True, dl_apy=None,
                                                   dl_tvl=500_000_000.0))
        info = a.get_yield_info()
        assert info.tvl_source == "live"
        assert info.tvl_usd == pytest.approx(500_000_000.0)


class TestFallbackIsNeverCalledLive:
    """Обратный контроль — здесь он главный."""

    def test_fallback_tvl_is_labelled_static(self):
        a = EthenaSusdeAdapter(http_get=_make_http(primary_fail=True, dl_fail=True))
        info = a.get_yield_info()
        assert info.tvl_source == "static", \
            "фид молчал ⇒ подстановка НЕ смеет зваться живой (ADR-126 наоборот)"
        assert info.tvl_usd == pytest.approx(EthenaSusdeAdapter.FALLBACK_TVL_USD)

    def test_none_tvl_from_pool_is_static(self):
        a = EthenaSusdeAdapter(http_get=_make_http(primary_value=12.0, dl_tvl=None))
        info = a.get_yield_info()
        assert info.tvl_source == "static"
