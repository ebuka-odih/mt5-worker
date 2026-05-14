from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import math

import pandas as pd

from brain.data.trade_logger import TradeLogger


@dataclass
class GridSimulationConfig:
    """MT5-style dry-run settings using external BTC market data.

    This simulator does not assume Bybit execution. Bybit candles are only a BTC
    movement feed; fills are modeled as if an MT5 BTCUSD CFD worker were placing
    and managing orders with these guardrails.
    """

    starting_balance: float = 10_000.0
    max_total_drawdown_pct: float = 20.0
    daily_loss_budget: float = 200.0
    total_grid_levels: int = 1000
    max_active_orders: int = 30
    grid_spacing: float = 120.0
    take_profit_spacing: float = 120.0
    stop_loss_spacing: float = 60.0
    risk_per_order: float = 10.0
    trend_guard_bars: int = 6
    trend_guard_pct: float = 2.0
    active_window_refresh: bool = True
    allowed_sides: tuple[str, ...] = ("buy", "sell")
    round_trip_cost_per_order: float = 0.0
    max_new_orders_per_bar: int = 5
    max_entry_risk_pct: float = 2.0
    pip_size: float = 1.0
    spread_pips: float = 0.0
    contract_size_per_lot: float = 1.0
    leverage: float = 10.0
    max_margin_usage_pct: float = 100.0
    min_lot_size: float = 0.0
    lot_step: float = 0.0
    fixed_lot_size: float | None = None


@dataclass
class SimPosition:
    side: str
    entry: float
    tp: float
    sl: float
    risk: float
    opened_at: object
    symbol: str = ""
    lot_size: float = 0.0
    pip_value_per_lot: float = 0.0
    pip_size: float = 1.0
    margin_required: float = 0.0


@dataclass
class GridSimulationResult:
    starting_balance: float
    balance: float
    equity: float
    realized_pnl: float
    max_drawdown: float
    stopped: bool
    stop_reason: str | None
    total_grid_levels: int
    max_active_orders: int
    orders_opened: int
    orders_closed_tp: int
    orders_closed_sl: int
    open_positions: int
    pause_events: int
    new_orders_blocked: int
    trend_guard_events: int
    max_margin_used: float = 0.0
    margin_block_events: int = 0
    equity_curve: list[dict] = field(default_factory=list)


@dataclass
class PortfolioGridSimulationResult:
    starting_balance: float
    balance: float
    equity: float
    realized_pnl: float
    max_drawdown: float
    stopped: bool
    stop_reason: str | None
    symbols: tuple[str, ...]
    symbol_results: dict[str, GridSimulationResult]
    max_entry_risk: float
    max_active_orders: int
    orders_opened: int
    orders_closed_tp: int
    orders_closed_sl: int
    open_positions: int
    pause_events: int
    new_orders_blocked: int
    trend_guard_events: int
    max_margin_used: float = 0.0
    margin_block_events: int = 0
    equity_curve: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class _GridOrder:
    side: str
    price: float


def _pip_value_per_lot(cfg: GridSimulationConfig) -> float:
    """Approximate USD profit/loss value of one pip for one MT5 CFD lot.

    For USD-quoted crypto CFDs like BTCUSD, if 1 lot = 1 BTC and pip_size = 1.0,
    then one pip is roughly $1 per lot. Broker contract specs can override this.
    """

    return max(cfg.contract_size_per_lot * cfg.pip_size, 1e-9)


def _lot_size_for_risk(entry: float, sl: float, risk: float, cfg: GridSimulationConfig) -> float:
    stop_pips = abs(entry - sl) / max(cfg.pip_size, 1e-9)
    return risk / max(stop_pips * _pip_value_per_lot(cfg), 1e-9)


def _risk_for_lot(entry: float, sl: float, lot_size: float, cfg: GridSimulationConfig) -> float:
    stop_pips = abs(entry - sl) / max(cfg.pip_size, 1e-9)
    return stop_pips * _pip_value_per_lot(cfg) * max(lot_size, 0.0)


def _quantize_lot_size(raw_lot_size: float, cfg: GridSimulationConfig) -> float:
    lot_size = max(raw_lot_size, 0.0)
    min_lot_size = max(cfg.min_lot_size, 0.0)
    lot_step = max(cfg.lot_step, 0.0)

    if cfg.fixed_lot_size is not None:
        lot_size = max(cfg.fixed_lot_size, 0.0)

    if lot_step > 0:
        lot_size = math.floor((lot_size / lot_step) + 1e-9) * lot_step

    if lot_size > 0 and lot_size < min_lot_size:
        lot_size = min_lot_size

    return round(lot_size, 8)


def _spread_cost(position: SimPosition, cfg: GridSimulationConfig) -> float:
    return cfg.spread_pips * position.pip_value_per_lot * position.lot_size


def _position_pnl(position: SimPosition, exit_price: float, cfg: GridSimulationConfig) -> float:
    direction = 1 if position.side == "buy" else -1
    price_move_pips = direction * (exit_price - position.entry) / max(position.pip_size, 1e-9)
    raw = price_move_pips * position.pip_value_per_lot * position.lot_size
    return raw - _spread_cost(position, cfg) - cfg.round_trip_cost_per_order


def _mark_to_market(position: SimPosition, price: float) -> float:
    if position.lot_size and position.pip_value_per_lot:
        direction = 1 if position.side == "buy" else -1
        price_move_pips = direction * (price - position.entry) / max(position.pip_size, 1e-9)
        return price_move_pips * position.pip_value_per_lot * position.lot_size
    if position.side == "buy":
        denom = max(position.entry - position.sl, 1e-9)
        return ((price - position.entry) / denom) * position.risk
    denom = max(position.sl - position.entry, 1e-9)
    return ((position.entry - price) / denom) * position.risk


def _margin_required(entry: float, lot_size: float, cfg: GridSimulationConfig) -> float:
    leverage = max(cfg.leverage, 1e-9)
    notional = abs(entry * cfg.contract_size_per_lot * lot_size)
    return notional / leverage


def _active_orders(price: float, cfg: GridSimulationConfig) -> list[_GridOrder]:
    per_side = max(1, cfg.max_active_orders // max(len(cfg.allowed_sides), 1))
    orders: list[_GridOrder] = []
    if "buy" in cfg.allowed_sides:
        orders.extend(_GridOrder("buy", price - (cfg.grid_spacing * i)) for i in range(1, per_side + 1))
    if "sell" in cfg.allowed_sides:
        orders.extend(_GridOrder("sell", price + (cfg.grid_spacing * i)) for i in range(1, per_side + 1))
    return orders


def _daily_key(index_value: object) -> date | int:
    try:
        return pd.Timestamp(index_value).date()
    except Exception:
        return 0


def run_grid_simulation(candles: pd.DataFrame, cfg: GridSimulationConfig | None = None, symbol: str = "BTCUSD") -> GridSimulationResult:
    cfg = cfg or GridSimulationConfig()
    logger = TradeLogger(symbol)
    if candles.empty:
        return GridSimulationResult(
            starting_balance=cfg.starting_balance,
            balance=cfg.starting_balance,
            equity=cfg.starting_balance,
            realized_pnl=0.0,
            max_drawdown=0.0,
            stopped=False,
            stop_reason=None,
            total_grid_levels=cfg.total_grid_levels,
            max_active_orders=0,
            orders_opened=0,
            orders_closed_tp=0,
            orders_closed_sl=0,
            open_positions=0,
            pause_events=0,
            new_orders_blocked=0,
            trend_guard_events=0,
        )

    balance = cfg.starting_balance
    min_balance = cfg.starting_balance * (1 - cfg.max_total_drawdown_pct / 100)
    max_entry_risk = cfg.starting_balance * cfg.max_entry_risk_pct / 100
    positions: list[SimPosition] = []
    max_drawdown = 0.0
    orders_opened = 0
    orders_closed_tp = 0
    orders_closed_sl = 0
    pause_events = 0
    new_orders_blocked = 0
    trend_guard_events = 0
    max_active_seen = 0
    max_margin_used = 0.0
    margin_block_events = 0
    stopped = False
    stop_reason: str | None = None
    current_day = None
    day_start_balance = balance
    daily_paused = False
    equity_curve: list[dict] = []

    close_series = candles["Close"].astype(float)
    # Grid orders are assumed to be resting before each candle moves. Use the
    # previous close as the active-window anchor for fills inside the current
    # candle; anchoring to the current close misses one-way adverse moves.
    previous_close = float(candles["Open"].iloc[0]) if "Open" in candles else float(close_series.iloc[0])

    for bar_no, (idx, row) in enumerate(candles.iterrows()):
        day = _daily_key(idx)
        if day != current_day:
            current_day = day
            day_start_balance = balance
            daily_paused = False

        high = float(row["High"])
        low = float(row["Low"])
        close = float(row["Close"])

        # Close positions on TP/SL. Conservative ordering: SL first if both could
        # be touched inside the same candle.
        survivors: list[SimPosition] = []
        for pos in positions:
            hit_sl = low <= pos.sl if pos.side == "buy" else high >= pos.sl
            hit_tp = high >= pos.tp if pos.side == "buy" else low <= pos.tp
            if hit_sl:
                pnl = _position_pnl(pos, pos.sl, cfg)
                balance += pnl
                orders_closed_sl += 1
                logger.log_close(pos.side, pos.entry, pos.sl, pnl, "sl", timestamp=str(idx))
            elif hit_tp:
                pnl = _position_pnl(pos, pos.tp, cfg)
                balance += pnl
                orders_closed_tp += 1
                logger.log_close(pos.side, pos.entry, pos.tp, pnl, "tp", timestamp=str(idx))
            else:
                survivors.append(pos)
        positions = survivors

        # Hard funded-challenge kill switch. Model emergency flattening before
        # the account crosses the configured maximum loss.
        if balance <= min_balance:
            balance = min_balance
            stopped = True
            stop_reason = "max_drawdown"
            positions.clear()

        pre_entry_unrealized = sum(_mark_to_market(pos, close) for pos in positions)
        pre_entry_equity = balance + pre_entry_unrealized
        day_loss = max(0.0, day_start_balance - pre_entry_equity)
        if day_loss >= cfg.daily_loss_budget and not daily_paused:
            pause_events += 1
            daily_paused = True

        trend_guard = False
        if bar_no >= cfg.trend_guard_bars:
            ref = float(close_series.iloc[bar_no - cfg.trend_guard_bars])
            move_pct = abs((close - ref) / ref) * 100 if ref else 0.0
            trend_guard = move_pct >= cfg.trend_guard_pct
            if trend_guard:
                trend_guard_events += 1

        if not stopped:
            if daily_paused or trend_guard:
                new_orders_blocked += 1
            else:
                active_orders = _active_orders(previous_close, cfg)
                new_orders_this_bar = 0
                order_risk = min(cfg.risk_per_order, max_entry_risk)
                for order in active_orders:
                    if len(positions) >= cfg.max_active_orders or new_orders_this_bar >= cfg.max_new_orders_per_bar:
                        break
                    already_open = any(abs(p.entry - order.price) < 1e-9 and p.side == order.side for p in positions)
                    if already_open:
                        continue
                    filled = low <= order.price if order.side == "buy" else high >= order.price
                    if filled:
                        candidate = _position_from_order("", order, cfg, order_risk, idx)
                        current_margin = sum(p.margin_required for p in positions)
                        margin_limit = max(0.0, pre_entry_equity * cfg.max_margin_usage_pct / 100)
                        if current_margin + candidate.margin_required > margin_limit:
                            margin_block_events += 1
                            new_orders_blocked += 1
                            continue
                        positions.append(candidate)
                        orders_opened += 1
                        new_orders_this_bar += 1
                        logger.log_fill(
                            candidate.side, candidate.entry, candidate.tp, candidate.sl,
                            candidate.lot_size, candidate.risk, timestamp=str(idx),
                            bar_no=bar_no, price_at_fill=close,
                        )

        max_active_seen = max(max_active_seen, len(positions))
        max_margin_used = max(max_margin_used, sum(p.margin_required for p in positions))
        unrealized = sum(_mark_to_market(pos, close) for pos in positions)
        equity = balance + unrealized
        drawdown = max(0.0, cfg.starting_balance - equity)
        if drawdown > cfg.starting_balance - min_balance:
            equity = min_balance
            balance = min(balance, min_balance)
            positions.clear()
            stopped = True
            stop_reason = "max_drawdown"
            drawdown = cfg.starting_balance - min_balance
        max_drawdown = max(max_drawdown, drawdown)
        logger.log_equity(balance, equity, len(positions), close, timestamp=str(idx))
        equity_curve.append(
            {
                "time": str(idx),
                "close": close,
                "balance": round(balance, 2),
                "equity": round(equity, 2),
                "open_positions": len(positions),
                "daily_paused": daily_paused,
                "trend_guard": trend_guard,
            }
        )
        previous_close = close
        if stopped:
            break

    final_close = float(candles["Close"].iloc[min(len(equity_curve), len(candles)) - 1]) if equity_curve else float(candles["Close"].iloc[-1])
    final_equity = balance + sum(_mark_to_market(pos, final_close) for pos in positions)
    logger.flush()
    return GridSimulationResult(
        starting_balance=cfg.starting_balance,
        balance=round(balance, 2),
        equity=round(final_equity, 2),
        realized_pnl=round(balance - cfg.starting_balance, 2),
        max_drawdown=round(max_drawdown, 2),
        stopped=stopped,
        stop_reason=stop_reason,
        total_grid_levels=cfg.total_grid_levels,
        max_active_orders=max_active_seen,
        orders_opened=orders_opened,
        orders_closed_tp=orders_closed_tp,
        orders_closed_sl=orders_closed_sl,
        open_positions=len(positions),
        pause_events=pause_events,
        new_orders_blocked=new_orders_blocked,
        trend_guard_events=trend_guard_events,
        max_margin_used=round(max_margin_used, 2),
        margin_block_events=margin_block_events,
        equity_curve=equity_curve,
    )


def _config_for_symbol(
    cfg: GridSimulationConfig | dict[str, GridSimulationConfig], symbol: str
) -> GridSimulationConfig:
    if isinstance(cfg, dict):
        return cfg.get(symbol) or next(iter(cfg.values()))
    return cfg


def _position_from_order(symbol: str, order: _GridOrder, cfg: GridSimulationConfig, risk: float, opened_at: object) -> SimPosition:
    if order.side == "buy":
        tp = order.price + cfg.take_profit_spacing
        sl = order.price - cfg.stop_loss_spacing
    else:
        tp = order.price - cfg.take_profit_spacing
        sl = order.price + cfg.stop_loss_spacing
    requested_lot_size = _lot_size_for_risk(order.price, sl, risk, cfg)
    lot_size = _quantize_lot_size(requested_lot_size, cfg)
    actual_risk = _risk_for_lot(order.price, sl, lot_size, cfg)
    pip_value_per_lot = _pip_value_per_lot(cfg)
    return SimPosition(
        symbol=symbol,
        side=order.side,
        entry=order.price,
        tp=tp,
        sl=sl,
        risk=actual_risk,
        opened_at=opened_at,
        lot_size=lot_size,
        pip_value_per_lot=pip_value_per_lot,
        pip_size=cfg.pip_size,
        margin_required=_margin_required(order.price, lot_size, cfg),
    )


def run_portfolio_grid_simulation(
    candles_by_symbol: dict[str, pd.DataFrame],
    cfg: GridSimulationConfig | dict[str, GridSimulationConfig] | None = None,
) -> PortfolioGridSimulationResult:
    """Run multiple MT5-style crypto grids on one funded-account balance.

    BTC and ETH can each use the same grid rules, but this portfolio simulator
    enforces the funded challenge at the shared account level: one balance, one
    drawdown limit, one daily pause, and the 2% per-entry cap across symbols.
    """

    base_cfg = cfg or GridSimulationConfig()
    default_cfg = next(iter(base_cfg.values())) if isinstance(base_cfg, dict) else base_cfg
    symbols = tuple(candles_by_symbol.keys())
    if not symbols:
        empty = run_grid_simulation(pd.DataFrame(), default_cfg)
        return PortfolioGridSimulationResult(
            starting_balance=default_cfg.starting_balance,
            balance=default_cfg.starting_balance,
            equity=default_cfg.starting_balance,
            realized_pnl=0.0,
            max_drawdown=0.0,
            stopped=False,
            stop_reason=None,
            symbols=(),
            symbol_results={},
            max_entry_risk=round(default_cfg.starting_balance * default_cfg.max_entry_risk_pct / 100, 2),
            max_active_orders=0,
            orders_opened=0,
            orders_closed_tp=0,
            orders_closed_sl=0,
            open_positions=0,
            pause_events=0,
            new_orders_blocked=0,
            trend_guard_events=0,
            equity_curve=empty.equity_curve,
        )

    balance = default_cfg.starting_balance
    min_balance = default_cfg.starting_balance * (1 - default_cfg.max_total_drawdown_pct / 100)
    max_entry_risk = default_cfg.starting_balance * default_cfg.max_entry_risk_pct / 100
    positions: list[SimPosition] = []
    symbol_stats = {
        symbol: {"opened": 0, "tp": 0, "sl": 0, "realized": 0.0, "blocked": 0, "trend": 0}
        for symbol in symbols
    }

    max_drawdown = 0.0
    orders_opened = 0
    orders_closed_tp = 0
    orders_closed_sl = 0
    pause_events = 0
    new_orders_blocked = 0
    trend_guard_events = 0
    max_active_seen = 0
    max_margin_used = 0.0
    margin_block_events = 0
    stopped = False
    stop_reason: str | None = None
    current_day = None
    day_start_balance = balance
    daily_paused = False
    equity_curve: list[dict] = []

    common_index = candles_by_symbol[symbols[0]].index
    for frame in candles_by_symbol.values():
        common_index = common_index.intersection(frame.index)
    close_series_by_symbol = {symbol: candles_by_symbol[symbol]["Close"].astype(float) for symbol in symbols}
    # Resting active windows are anchored to the previous close, so a fast move
    # through pre-existing grid orders is counted instead of missed.
    previous_close_by_symbol = {
        symbol: float(candles_by_symbol[symbol]["Open"].iloc[0]) if "Open" in candles_by_symbol[symbol] else float(close_series_by_symbol[symbol].iloc[0])
        for symbol in symbols
    }

    for bar_no, idx in enumerate(common_index):
        day = _daily_key(idx)
        if day != current_day:
            current_day = day
            day_start_balance = balance
            daily_paused = False

        rows = {symbol: candles_by_symbol[symbol].loc[idx] for symbol in symbols}

        survivors: list[SimPosition] = []
        for pos in positions:
            row = rows[pos.symbol]
            high = float(row["High"])
            low = float(row["Low"])
            cfg_for_pos = _config_for_symbol(base_cfg, pos.symbol)
            hit_sl = low <= pos.sl if pos.side == "buy" else high >= pos.sl
            hit_tp = high >= pos.tp if pos.side == "buy" else low <= pos.tp
            if hit_sl:
                pnl = _position_pnl(pos, pos.sl, cfg_for_pos)
                balance += pnl
                symbol_stats[pos.symbol]["sl"] += 1
                symbol_stats[pos.symbol]["realized"] += pnl
                orders_closed_sl += 1
            elif hit_tp:
                pnl = _position_pnl(pos, pos.tp, cfg_for_pos)
                balance += pnl
                symbol_stats[pos.symbol]["tp"] += 1
                symbol_stats[pos.symbol]["realized"] += pnl
                orders_closed_tp += 1
            else:
                survivors.append(pos)
        positions = survivors

        if balance <= min_balance:
            balance = min_balance
            stopped = True
            stop_reason = "max_drawdown"
            positions.clear()

        pre_entry_unrealized = 0.0
        for pos in positions:
            close_for_pos = float(rows[pos.symbol]["Close"])
            pre_entry_unrealized += _mark_to_market(pos, close_for_pos)
        pre_entry_equity = balance + pre_entry_unrealized
        day_loss = max(0.0, day_start_balance - pre_entry_equity)
        if day_loss >= default_cfg.daily_loss_budget and not daily_paused:
            pause_events += 1
            daily_paused = True

        if not stopped:
            for symbol in symbols:
                symbol_cfg = _config_for_symbol(base_cfg, symbol)
                row = rows[symbol]
                close = float(row["Close"])
                high = float(row["High"])
                low = float(row["Low"])
                trend_guard = False
                if bar_no >= symbol_cfg.trend_guard_bars:
                    ref = float(close_series_by_symbol[symbol].loc[common_index[bar_no - symbol_cfg.trend_guard_bars]])
                    move_pct = abs((close - ref) / ref) * 100 if ref else 0.0
                    trend_guard = move_pct >= symbol_cfg.trend_guard_pct
                    if trend_guard:
                        trend_guard_events += 1
                        symbol_stats[symbol]["trend"] += 1

                if daily_paused or trend_guard:
                    new_orders_blocked += 1
                    symbol_stats[symbol]["blocked"] += 1
                    continue

                if len(positions) >= default_cfg.max_active_orders:
                    new_orders_blocked += 1
                    symbol_stats[symbol]["blocked"] += 1
                    continue

                active_orders = _active_orders(previous_close_by_symbol[symbol], symbol_cfg)
                new_orders_this_bar = 0
                active_for_symbol = sum(1 for p in positions if p.symbol == symbol)
                order_risk = min(symbol_cfg.risk_per_order, max_entry_risk)
                for order in active_orders:
                    if (
                        len(positions) >= default_cfg.max_active_orders
                        or active_for_symbol >= symbol_cfg.max_active_orders
                        or new_orders_this_bar >= symbol_cfg.max_new_orders_per_bar
                    ):
                        break
                    already_open = any(
                        p.symbol == symbol and abs(p.entry - order.price) < 1e-9 and p.side == order.side for p in positions
                    )
                    if already_open:
                        continue
                    filled = low <= order.price if order.side == "buy" else high >= order.price
                    if filled:
                        candidate = _position_from_order(symbol, order, symbol_cfg, order_risk, idx)
                        current_margin = sum(p.margin_required for p in positions)
                        margin_limit = max(0.0, pre_entry_equity * default_cfg.max_margin_usage_pct / 100)
                        if current_margin + candidate.margin_required > margin_limit:
                            margin_block_events += 1
                            new_orders_blocked += 1
                            symbol_stats[symbol]["blocked"] += 1
                            continue
                        positions.append(candidate)
                        active_for_symbol += 1
                        orders_opened += 1
                        symbol_stats[symbol]["opened"] += 1
                        new_orders_this_bar += 1

        max_active_seen = max(max_active_seen, len(positions))
        max_margin_used = max(max_margin_used, sum(p.margin_required for p in positions))
        unrealized = 0.0
        for pos in positions:
            close = float(rows[pos.symbol]["Close"])
            unrealized += _mark_to_market(pos, close)
        equity = balance + unrealized
        drawdown = max(0.0, default_cfg.starting_balance - equity)
        if drawdown > default_cfg.starting_balance - min_balance:
            equity = min_balance
            balance = min(balance, min_balance)
            positions.clear()
            stopped = True
            stop_reason = "max_drawdown"
            drawdown = default_cfg.starting_balance - min_balance
        max_drawdown = max(max_drawdown, drawdown)
        equity_curve.append(
            {
                "time": str(idx),
                "balance": round(balance, 2),
                "equity": round(equity, 2),
                "open_positions": len(positions),
                "daily_paused": daily_paused,
            }
        )
        for symbol in symbols:
            previous_close_by_symbol[symbol] = float(rows[symbol]["Close"])
        if stopped:
            break

    if common_index.empty:
        final_equity = balance
    else:
        final_idx = common_index[min(len(equity_curve), len(common_index)) - 1]
        final_equity = balance + sum(
            _mark_to_market(pos, float(candles_by_symbol[pos.symbol].loc[final_idx]["Close"])) for pos in positions
        )

    symbol_results: dict[str, GridSimulationResult] = {}
    for symbol in symbols:
        stats = symbol_stats[symbol]
        symbol_cfg = _config_for_symbol(base_cfg, symbol)
        open_count = sum(1 for p in positions if p.symbol == symbol)
        symbol_results[symbol] = GridSimulationResult(
            starting_balance=default_cfg.starting_balance,
            balance=round(default_cfg.starting_balance + stats["realized"], 2),
            equity=round(default_cfg.starting_balance + stats["realized"], 2),
            realized_pnl=round(stats["realized"], 2),
            max_drawdown=0.0,
            stopped=stopped,
            stop_reason=stop_reason,
            total_grid_levels=symbol_cfg.total_grid_levels,
            max_active_orders=open_count,
            orders_opened=int(stats["opened"]),
            orders_closed_tp=int(stats["tp"]),
            orders_closed_sl=int(stats["sl"]),
            open_positions=open_count,
            pause_events=pause_events,
            new_orders_blocked=int(stats["blocked"]),
            trend_guard_events=int(stats["trend"]),
        )

    return PortfolioGridSimulationResult(
        starting_balance=default_cfg.starting_balance,
        balance=round(balance, 2),
        equity=round(final_equity, 2),
        realized_pnl=round(balance - default_cfg.starting_balance, 2),
        max_drawdown=round(max_drawdown, 2),
        stopped=stopped,
        stop_reason=stop_reason,
        symbols=symbols,
        symbol_results=symbol_results,
        max_entry_risk=round(max_entry_risk, 2),
        max_active_orders=max_active_seen,
        orders_opened=orders_opened,
        orders_closed_tp=orders_closed_tp,
        orders_closed_sl=orders_closed_sl,
        open_positions=len(positions),
        pause_events=pause_events,
        new_orders_blocked=new_orders_blocked,
        trend_guard_events=trend_guard_events,
        max_margin_used=round(max_margin_used, 2),
        margin_block_events=margin_block_events,
        equity_curve=equity_curve,
    )
