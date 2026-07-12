from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from app.market_data.models import Candle
from app.portfolio.models import (
    PortfolioBacktestResult,
    PortfolioEquityPoint,
    PortfolioStrategyConfig,
    PortfolioStrategySummary,
    PortfolioTrade,
)
from app.strategies.manager import (
    list_available_strategy_names,
    run_strategy,
)
from app.trading.simulator import (
    calculate_profit_percent,
    calculate_trading_cost_percent,
)


@dataclass
class _PendingEntry:
    direction: str
    signal_timestamp: datetime


@dataclass
class _OpenPosition:
    config_index: int
    strategy_name: str
    symbol: str
    direction: str

    signal_timestamp: datetime
    entry_timestamp: datetime

    entry_price: float
    stop_loss: float
    take_profit: float

    position_size_units: float
    notional_value: float
    risk_amount: float
    leverage_at_entry: float

    trading_cost_percent: float


def _validate_inputs(
    candles_by_symbol: dict[str, list[Candle]],
    strategy_configs: list[PortfolioStrategyConfig],
    initial_balance: float,
    max_portfolio_leverage: float,
    max_total_risk_percent: float,
) -> None:
    if not candles_by_symbol:
        raise ValueError("At least one candle series is required.")

    if not strategy_configs:
        raise ValueError("At least one strategy config is required.")

    if initial_balance <= 0:
        raise ValueError(
            "Initial balance must be greater than zero."
        )

    if max_portfolio_leverage <= 0:
        raise ValueError(
            "Maximum portfolio leverage must be greater than zero."
        )

    if max_total_risk_percent <= 0:
        raise ValueError(
            "Maximum total risk percent must be greater than zero."
        )

    if max_total_risk_percent > 100:
        raise ValueError(
            "Maximum total risk percent cannot exceed 100."
        )

    available_strategies = set(
        list_available_strategy_names()
    )

    for config in strategy_configs:
        if config.strategy_name not in available_strategies:
            raise ValueError(
                f"Unknown strategy: {config.strategy_name}"
            )

        if config.symbol not in candles_by_symbol:
            raise ValueError(
                f"No candles supplied for symbol: {config.symbol}"
            )

        if not candles_by_symbol[config.symbol]:
            raise ValueError(
                f"At least one candle is required for "
                f"{config.symbol}."
            )

        if config.stop_loss_percent <= 0:
            raise ValueError(
                "Stop-loss percent must be greater than zero."
            )

        if config.take_profit_percent <= 0:
            raise ValueError(
                "Take-profit percent must be greater than zero."
            )

        if config.risk_per_trade_percent <= 0:
            raise ValueError(
                "Risk per trade percent must be greater than zero."
            )

        if config.spread_pips < 0:
            raise ValueError("Spread pips cannot be negative.")

        if config.commission_percent < 0:
            raise ValueError(
                "Commission percent cannot be negative."
            )

        if config.slippage_pips < 0:
            raise ValueError("Slippage pips cannot be negative.")

        if config.pip_size <= 0:
            raise ValueError(
                "Pip size must be greater than zero."
            )

        if config.allowed_directions is not None:
            invalid = (
                config.allowed_directions
                - {"BUY", "SELL"}
            )

            if invalid:
                raise ValueError(
                    "Allowed directions must contain only "
                    "BUY or SELL."
                )


def _calculate_exit(
    position: _OpenPosition,
    candle: Candle,
) -> tuple[float, str] | None:
    if position.direction == "BUY":
        stop_hit = candle.low <= position.stop_loss
        target_hit = candle.high >= position.take_profit

        if stop_hit:
            reason = (
                "Stop-loss used: both stop-loss and "
                "take-profit were touched in the same candle."
                if target_hit
                else "Stop-loss hit."
            )
            return position.stop_loss, reason

        if target_hit:
            return position.take_profit, "Take-profit hit."

    elif position.direction == "SELL":
        stop_hit = candle.high >= position.stop_loss
        target_hit = candle.low <= position.take_profit

        if stop_hit:
            reason = (
                "Stop-loss used: both stop-loss and "
                "take-profit were touched in the same candle."
                if target_hit
                else "Stop-loss hit."
            )
            return position.stop_loss, reason

        if target_hit:
            return position.take_profit, "Take-profit hit."

    return None


def _unrealized_pnl(
    position: _OpenPosition,
    current_price: float,
) -> float:
    if position.direction == "BUY":
        return (
            current_price - position.entry_price
        ) * position.position_size_units

    return (
        position.entry_price - current_price
    ) * position.position_size_units


def _close_position(
    position: _OpenPosition,
    exit_timestamp: datetime,
    exit_price: float,
    exit_reason: str,
    balance_before: float,
) -> PortfolioTrade:
    gross_profit_percent = calculate_profit_percent(
        direction=position.direction,
        entry_price=position.entry_price,
        exit_price=exit_price,
    )

    gross_pnl = (
        gross_profit_percent
        / 100
        * position.notional_value
    )

    trading_cost = (
        position.trading_cost_percent
        / 100
        * position.notional_value
    )

    net_pnl = gross_pnl - trading_cost

    account_return_percent = (
        net_pnl / balance_before * 100
        if balance_before > 0
        else 0.0
    )

    return PortfolioTrade(
        strategy_name=position.strategy_name,
        symbol=position.symbol,
        direction=position.direction,
        signal_timestamp=position.signal_timestamp,
        entry_timestamp=position.entry_timestamp,
        exit_timestamp=exit_timestamp,
        entry_price=round(position.entry_price, 6),
        exit_price=round(exit_price, 6),
        stop_loss=round(position.stop_loss, 6),
        take_profit=round(position.take_profit, 6),
        position_size_units=round(
            position.position_size_units,
            2,
        ),
        notional_value=round(position.notional_value, 2),
        risk_amount=round(position.risk_amount, 2),
        leverage_at_entry=round(
            position.leverage_at_entry,
            4,
        ),
        gross_pnl=round(gross_pnl, 2),
        trading_cost=round(trading_cost, 2),
        net_pnl=round(net_pnl, 2),
        account_return_percent=round(
            account_return_percent,
            6,
        ),
        exit_reason=exit_reason,
    )


def _maximum_drawdown(
    equity_curve: list[PortfolioEquityPoint],
) -> float:
    if not equity_curve:
        return 0.0

    peak = equity_curve[0].equity
    maximum_drawdown = 0.0

    for point in equity_curve:
        peak = max(peak, point.equity)

        if peak <= 0:
            continue

        drawdown = (
            (peak - point.equity)
            / peak
            * 100
        )

        maximum_drawdown = max(
            maximum_drawdown,
            drawdown,
        )

    return round(maximum_drawdown, 2)


def run_portfolio_backtest(
    candles_by_symbol: dict[str, list[Candle]],
    strategy_configs: list[PortfolioStrategyConfig],
    initial_balance: float = 10000.0,
    max_portfolio_leverage: float = 20.0,
    max_total_risk_percent: float = 1.0,
) -> PortfolioBacktestResult:
    _validate_inputs(
        candles_by_symbol=candles_by_symbol,
        strategy_configs=strategy_configs,
        initial_balance=initial_balance,
        max_portfolio_leverage=max_portfolio_leverage,
        max_total_risk_percent=max_total_risk_percent,
    )

    sorted_candles = {
        symbol: sorted(
            candles,
            key=lambda candle: candle.timestamp,
        )
        for symbol, candles in candles_by_symbol.items()
    }

    candles_at_timestamp: dict[
        datetime,
        dict[str, Candle],
    ] = defaultdict(dict)

    for symbol, candles in sorted_candles.items():
        for candle in candles:
            candles_at_timestamp[candle.timestamp][
                symbol
            ] = candle

    timeline = sorted(candles_at_timestamp)

    histories: dict[str, list[Candle]] = {
        symbol: []
        for symbol in sorted_candles
    }

    latest_prices: dict[str, float] = {}

    pending_entries: dict[int, _PendingEntry] = {}
    open_positions: dict[int, _OpenPosition] = {}

    trades: list[PortfolioTrade] = []
    equity_curve: list[PortfolioEquityPoint] = []

    balance = initial_balance
    rejected_entries = 0
    maximum_open_positions = 0
    maximum_gross_leverage = 0.0

    for timestamp in timeline:
        current_candles = candles_at_timestamp[timestamp]

        for symbol, candle in current_candles.items():
            histories[symbol].append(candle)
            latest_prices[symbol] = candle.close

        # Signals created at the previous close enter at this open.
        for config_index, config in enumerate(
            strategy_configs
        ):
            if config_index not in pending_entries:
                continue

            if config_index in open_positions:
                continue

            candle = current_candles.get(config.symbol)

            if candle is None:
                continue

            pending = pending_entries.pop(config_index)

            entry_price = candle.open

            if pending.direction == "BUY":
                stop_loss = entry_price * (
                    1 - config.stop_loss_percent / 100
                )
                take_profit = entry_price * (
                    1 + config.take_profit_percent / 100
                )
            else:
                stop_loss = entry_price * (
                    1 + config.stop_loss_percent / 100
                )
                take_profit = entry_price * (
                    1 - config.take_profit_percent / 100
                )

            stop_distance = abs(
                entry_price - stop_loss
            )

            desired_risk = (
                balance
                * config.risk_per_trade_percent
                / 100
            )

            open_risk = sum(
                position.risk_amount
                for position in open_positions.values()
            )

            total_risk_limit = (
                balance
                * max_total_risk_percent
                / 100
            )

            remaining_risk = max(
                total_risk_limit - open_risk,
                0.0,
            )

            risk_amount = min(
                desired_risk,
                remaining_risk,
            )

            open_notional = sum(
                position.notional_value
                for position in open_positions.values()
            )

            maximum_notional = (
                balance * max_portfolio_leverage
            )

            remaining_notional = max(
                maximum_notional - open_notional,
                0.0,
            )

            risk_based_units = (
                risk_amount / stop_distance
                if stop_distance > 0
                else 0.0
            )

            leverage_based_units = (
                remaining_notional / entry_price
                if entry_price > 0
                else 0.0
            )

            units = min(
                risk_based_units,
                leverage_based_units,
            )

            if units <= 0 or risk_amount <= 0:
                rejected_entries += 1
                continue

            notional_value = units * entry_price

            gross_leverage_after_entry = (
                open_notional + notional_value
            ) / balance

            trading_cost_percent = (
                calculate_trading_cost_percent(
                    entry_price=entry_price,
                    spread_pips=config.spread_pips,
                    commission_percent=(
                        config.commission_percent
                    ),
                    slippage_pips=config.slippage_pips,
                    pip_size=config.pip_size,
                )
            )

            open_positions[config_index] = _OpenPosition(
                config_index=config_index,
                strategy_name=config.strategy_name,
                symbol=config.symbol,
                direction=pending.direction,
                signal_timestamp=(
                    pending.signal_timestamp
                ),
                entry_timestamp=timestamp,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                position_size_units=units,
                notional_value=notional_value,
                risk_amount=risk_amount,
                leverage_at_entry=(
                    gross_leverage_after_entry
                ),
                trading_cost_percent=(
                    trading_cost_percent
                ),
            )

        # New entries can stop or hit target during their entry candle.
        positions_to_close: list[
            tuple[int, float, str]
        ] = []

        for config_index, position in list(
            open_positions.items()
        ):
            candle = current_candles.get(position.symbol)

            if candle is None:
                continue

            exit_result = _calculate_exit(
                position=position,
                candle=candle,
            )

            if exit_result is None:
                continue

            exit_price, exit_reason = exit_result
            positions_to_close.append(
                (
                    config_index,
                    exit_price,
                    exit_reason,
                )
            )

        for config_index, exit_price, exit_reason in (
            positions_to_close
        ):
            position = open_positions.pop(config_index)

            trade = _close_position(
                position=position,
                exit_timestamp=timestamp,
                exit_price=exit_price,
                exit_reason=exit_reason,
                balance_before=balance,
            )

            balance += trade.net_pnl
            trades.append(trade)

        # Generate signals only after this candle has closed.
        for config_index, config in enumerate(
            strategy_configs
        ):
            if config_index in open_positions:
                continue

            if config_index in pending_entries:
                continue

            if config.symbol not in current_candles:
                continue

            try:
                signal = run_strategy(
                    config.strategy_name,
                    histories[config.symbol],
                )
            except ValueError:
                continue

            if signal.direction == "HOLD":
                continue

            if (
                config.allowed_directions is not None
                and signal.direction
                not in config.allowed_directions
            ):
                continue

            pending_entries[config_index] = _PendingEntry(
                direction=signal.direction,
                signal_timestamp=timestamp,
            )

        unrealized_pnl = 0.0

        for position in open_positions.values():
            current_price = latest_prices.get(
                position.symbol,
                position.entry_price,
            )

            unrealized_pnl += _unrealized_pnl(
                position=position,
                current_price=current_price,
            )

        equity = balance + unrealized_pnl

        gross_notional = sum(
            position.notional_value
            for position in open_positions.values()
        )

        gross_leverage = (
            gross_notional / equity
            if equity > 0
            else 0.0
        )

        maximum_open_positions = max(
            maximum_open_positions,
            len(open_positions),
        )

        maximum_gross_leverage = max(
            maximum_gross_leverage,
            gross_leverage,
        )

        equity_curve.append(
            PortfolioEquityPoint(
                timestamp=timestamp,
                balance=round(balance, 2),
                equity=round(equity, 2),
                unrealized_pnl=round(
                    unrealized_pnl,
                    2,
                ),
                open_positions=len(open_positions),
                gross_leverage=round(
                    gross_leverage,
                    4,
                ),
            )
        )

    # Close surviving positions at their final known market close.
    if timeline:
        final_timestamp = timeline[-1]

        for config_index, position in list(
            open_positions.items()
        ):
            final_price = latest_prices[position.symbol]

            trade = _close_position(
                position=position,
                exit_timestamp=final_timestamp,
                exit_price=final_price,
                exit_reason="Closed at final candle.",
                balance_before=balance,
            )

            balance += trade.net_pnl
            trades.append(trade)
            open_positions.pop(config_index)

        if equity_curve:
            equity_curve[-1] = PortfolioEquityPoint(
                timestamp=final_timestamp,
                balance=round(balance, 2),
                equity=round(balance, 2),
                unrealized_pnl=0.0,
                open_positions=0,
                gross_leverage=0.0,
            )

    winning_trades = sum(
        trade.net_pnl > 0
        for trade in trades
    )

    losing_trades = sum(
        trade.net_pnl < 0
        for trade in trades
    )

    total_trades = len(trades)

    win_rate_percent = (
        winning_trades / total_trades * 100
        if total_trades
        else 0.0
    )

    summaries: list[PortfolioStrategySummary] = []

    for config in strategy_configs:
        matching = [
            trade
            for trade in trades
            if (
                trade.strategy_name
                == config.strategy_name
                and trade.symbol == config.symbol
            )
        ]

        summaries.append(
            PortfolioStrategySummary(
                strategy_name=config.strategy_name,
                symbol=config.symbol,
                total_trades=len(matching),
                winning_trades=sum(
                    trade.net_pnl > 0
                    for trade in matching
                ),
                losing_trades=sum(
                    trade.net_pnl < 0
                    for trade in matching
                ),
                net_pnl=round(
                    sum(
                        trade.net_pnl
                        for trade in matching
                    ),
                    2,
                ),
            )
        )

    final_equity = (
        equity_curve[-1].equity
        if equity_curve
        else balance
    )

    return PortfolioBacktestResult(
        initial_balance=round(initial_balance, 2),
        final_balance=round(balance, 2),
        final_equity=round(final_equity, 2),
        return_percent=round(
            (
                balance / initial_balance - 1
            ) * 100,
            2,
        ),
        max_drawdown_percent=_maximum_drawdown(
            equity_curve
        ),
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate_percent=round(
            win_rate_percent,
            2,
        ),
        rejected_entries=rejected_entries,
        maximum_open_positions=(
            maximum_open_positions
        ),
        maximum_gross_leverage=round(
            maximum_gross_leverage,
            4,
        ),
        trades=trades,
        equity_curve=equity_curve,
        strategy_summaries=summaries,
    )
