from __future__ import annotations

from brain.data.forex_data import YFinanceForexProvider
from brain.risk.funded_challenge import entry_risk_budget
from brain.signals.grid_strike import GridStrikeSettings, build_grid_plan, pip_size, score_grid_candidate
from shared.settings import load_settings

from tests.test_grid_strike import candles_from


def test_yfinance_provider_maps_broker_bitcoin_symbols_to_public_btc_usd() -> None:
    provider = YFinanceForexProvider()

    assert provider.to_yf_symbol("BTCUSD") == "BTC-USD"
    assert provider.to_yf_symbol("BTC/USD") == "BTC-USD"
    assert provider.to_yf_symbol("XBTUSD") == "BTC-USD"


def test_btc_grid_uses_dollar_price_steps_not_forex_fractional_pips() -> None:
    values = [100_000 + (600 if i % 2 else -600) for i in range(96)]
    candidate = score_grid_candidate(
        "BTCUSD",
        candles_from(values),
        GridStrikeSettings(min_range_pct=0.2, max_range_pct=3.0, min_spacing_pips=50, max_spacing_pips=300),
    )

    assert pip_size("BTCUSD") == 1.0
    assert candidate.tradeable is True
    assert 50 <= candidate.grid_spacing_pips <= 300

    plan = build_grid_plan(candidate, mid_price=100_000)

    assert plan.buy_levels[0].price <= 99_999
    assert plan.sell_levels[0].price >= 100_001
    assert plan.lower_bound < 100_000 < plan.upper_bound


def test_eth_grid_uses_cent_price_steps_not_forex_fractional_pips() -> None:
    values = [2_400 + (20 if i % 2 else -20) for i in range(96)]
    candidate = score_grid_candidate(
        "ETHUSD",
        candles_from(values),
        GridStrikeSettings(min_range_pct=0.2, max_range_pct=3.0, min_spacing_pips=20, max_spacing_pips=500),
    )

    assert pip_size("ETHUSD") == 0.01
    assert candidate.tradeable is True
    assert 20 <= candidate.grid_spacing_pips <= 500

    plan = build_grid_plan(candidate, mid_price=2_400)

    assert plan.buy_levels[0].price <= 2399.99
    assert plan.sell_levels[0].price >= 2400.01
    assert round(plan.buy_levels[0].price, 2) == plan.buy_levels[0].price
    assert round(plan.sell_levels[0].price, 2) == plan.sell_levels[0].price


def test_config_is_focused_on_bitcoin_funded_challenge_rules() -> None:
    settings = load_settings()

    assert "BTCUSD" in settings.market_data.symbols
    assert settings.risk.max_risk_per_trade_pct == 0.44
    assert settings.risk.funded_challenge_mode is True
    assert entry_risk_budget(100_000, settings.risk) == 440
