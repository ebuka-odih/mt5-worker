from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class ApiSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8780
    worker_token: str = "CHANGE_ME_LONG_RANDOM_TOKEN"


class MarketDataSettings(BaseModel):
    provider: str = "yfinance"
    refresh_seconds: int = 60
    candles_interval: str = "15m"
    candles_period: str = "5d"
    symbols: list[str] = Field(default_factory=lambda: ["EURUSD", "GBPUSD", "USDJPY"])


class RiskSettings(BaseModel):
    account_currency: str = "USD"
    starting_balance: float = 10_000
    max_risk_per_trade_pct: float = 0.5
    max_daily_loss_pct: float = 2.0
    max_total_drawdown_pct: float = 20.0
    funded_challenge_mode: bool = False
    challenge_min_days: int = 30
    challenge_max_days: int = 60
    max_open_positions: int = 3
    max_positions_per_symbol: int = 1
    max_same_side_positions: int = 0
    max_directional_skew: int = 0
    default_stop_loss_pips: float = 20
    default_take_profit_pips: float = 30
    min_rr: float = 1.2
    risk_per_order: float = 10.0
    daily_loss_budget: float = 1000.0
    leverage: float = 1.0
    max_margin_usage_pct: float = 80.0


class StrategySettings(BaseModel):
    enabled: bool = True
    min_signal_confidence: float = 0.65
    trend_fast_ema: int = 20
    trend_slow_ema: int = 50
    rsi_period: int = 14
    rsi_buy_below: float = 35
    rsi_sell_above: float = 65
    trend_guard_bars: int = 6
    trend_guard_pct: float = 2.0
    max_new_orders_per_bar: int = 4


class GridStrikeSettings(BaseModel):
    enabled: bool = True
    min_score: float = 0.55
    min_range_pct: float = 0.05
    max_range_pct: float = 1.20
    max_trend_ratio: float = 0.65
    lookback_candles: int = 96
    levels_each_side: int = 5
    min_spacing_pips: float = 3.0
    max_spacing_pips: float = 25.0
    order_lots: float = 0.01
    grid_spacing: float = 120.0
    take_profit_spacing: float = 120.0
    stop_loss_spacing: float = 60.0
    atr_period: int = 14
    atr_spacing_multiplier: float = 1.25
    session_start_hour_utc: int = 6
    session_end_hour_utc: int = 22
    max_spread_pips: float = 0.0
    symbol_lots: dict[str, float] = Field(default_factory=dict)

    def get_lots(self, symbol: str) -> float:
        """Return per-symbol lot size, falling back to order_lots."""
        return self.symbol_lots.get(symbol.upper(), self.order_lots)


class BasketProfitLockSettings(BaseModel):
    enabled: bool = False
    trail_pct: float = 30.0
    activation_threshold: float = 500.0
    cooldown_hours: float = 4.0


class Mt5WorkerSettings(BaseModel):
    poll_seconds: int = 1
    heartbeat_seconds: int = 10
    allowed_order_types: list[str] = Field(default_factory=lambda: ["market", "limit"])
    magic_number: int = 552501
    comment_prefix: str = "vps_forex_brain"
    auto_close_enabled: bool = True
    auto_close_profit_pct: float = 2.0
    auto_close_loss_pct: float = 1.5
    basket_take_profit_usd: float = 0.0
    stale_position_minutes: int = 0
    volatility_spike_close_pct: float = 0.0
    reentry_cooldown_seconds: int = 0
    auto_reopen_after_close: bool = True


class AppSection(BaseModel):
    name: str = "forex-mt5-bot"
    mode: str = "paper"
    timezone: str = "UTC"


class Settings(BaseModel):
    app: AppSection = Field(default_factory=AppSection)
    api: ApiSettings = Field(default_factory=ApiSettings)
    market_data: MarketDataSettings = Field(default_factory=MarketDataSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    strategy: StrategySettings = Field(default_factory=StrategySettings)
    grid_strike: GridStrikeSettings = Field(default_factory=GridStrikeSettings)
    basket_profit_lock: BasketProfitLockSettings = Field(default_factory=BasketProfitLockSettings)
    mt5_worker: Mt5WorkerSettings = Field(default_factory=Mt5WorkerSettings)


def load_settings(path: str | Path = "config/settings.yaml") -> Settings:
    path = Path(path)
    raw: dict[str, Any] = yaml.safe_load(path.read_text()) if path.exists() else {}
    return Settings.model_validate(raw)
