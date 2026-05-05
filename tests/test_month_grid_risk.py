from __future__ import annotations

from brain.risk.funded_challenge import daily_loss_budget, max_drawdown_budget, per_grid_level_risk_budget
from shared.settings import Settings, load_settings


def test_month_grid_config_targets_30_day_bybit_btc_eth_and_1000_levels() -> None:
    settings = load_settings()

    assert settings.market_data.provider == "bybit"
    assert settings.market_data.candles_period == "30d"
    assert settings.market_data.candles_interval == "1h"
    assert settings.market_data.symbols == ["BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD"]
    assert settings.grid_strike.levels_each_side == 500
    assert settings.grid_strike.levels_each_side * 2 == 1000


def test_funded_challenge_total_drawdown_budget_caps_10000_balance_at_2000() -> None:
    settings = Settings()
    settings.risk.starting_balance = 10_000
    settings.risk.max_total_drawdown_pct = 20.0
    settings.risk.challenge_min_days = 30
    settings.risk.challenge_max_days = 60

    assert max_drawdown_budget(settings.risk.starting_balance, settings.risk) == 2_000
    assert daily_loss_budget(settings.risk.starting_balance, settings.risk, days=30) == 66.67
    assert daily_loss_budget(settings.risk.starting_balance, settings.risk, days=60) == 33.33


def test_1000_level_grid_risk_budget_does_not_allow_2pct_on_every_level() -> None:
    settings = Settings()
    settings.risk.starting_balance = 10_000
    settings.risk.max_total_drawdown_pct = 20.0

    assert per_grid_level_risk_budget(10_000, settings.risk, total_levels=1000) == 2.0
