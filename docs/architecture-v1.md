FX IQ Architecture v1

Purpose

FX IQ is an AI-powered trading research and automation platform. The first objective is to build a reliable backtesting and paper-trading system before any live trading is considered.

Core Principles

1. No live trading until strategies are backtested and paper traded.
2. Every trade decision must be logged.
3. Risk management has priority over profit.
4. AI should initially score and filter trades, not make autonomous decisions.
5. The platform must be modular so strategies, brokers, and data providers can be swapped.

Main Components

1. Market Data Engine

Responsible for collecting, validating, storing, and serving price data.

Initial data type:

* FX candles
* Open, high, low, close
* Volume where available
* Timeframe
* Currency pair

2. Strategy Engine

Runs trading strategies against historical or live data.

Initial strategies:

* Moving average trend strategy
* Breakout strategy
* Mean reversion strategy

3. Backtesting Engine

Replays historical data and tests strategies.

Outputs:

* Profit and loss
* Win rate
* Maximum drawdown
* Sharpe ratio
* Trade list
* Equity curve

4. Risk Engine

Controls exposure and protects capital.

Initial rules:

* Maximum risk per trade
* Maximum daily loss
* Maximum open positions
* Stop-loss requirement
* No trading during restricted conditions

5. Broker Engine

Eventually connects to a broker API.

Initial broker target:

* OANDA demo account

6. AI Engine

Initially used to score trade quality.

AI will not place trades independently in Version 1.

7. Analytics Dashboard

Displays system performance, trades, and strategy results.

Initial dashboard can be API-based before we build a full frontend.

Version 1 Scope

Version 1 will include:

* FastAPI backend
* Market candle data model
* In-memory sample candle data
* Basic API endpoints
* Strategy-ready project structure
* GitHub version control

Future Scope

Later versions may include:

* PostgreSQL database
* TimescaleDB
* Historical FX import
* Paper trading
* AI confidence scoring
* Portfolio risk management
* Live broker execution
* Web dashboard