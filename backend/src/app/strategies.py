"""Deterministic, database-backed strategies used by the autopilot.

Strategies never submit orders.  They emit a proposal which is evaluated by
``RiskGuard`` and executed by the automation service.  This separation keeps
the dashboard and a scheduled run from bypassing portfolio controls.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable

from sqlmodel import select

from .db import get_session
from .models import MarketBar


@dataclass(frozen=True)
class StrategyDefinition:
    id: str
    name: str
    description: str
    default_symbols: tuple[str, ...]
    timeframe: str = "1Day"


@dataclass(frozen=True)
class StrategyProposal:
    strategy_id: str
    symbol: str
    side: str
    price: float
    confidence: float
    reason: str
    stop: float | None = None


REGISTRY = {
    "sma_momentum": StrategyDefinition("sma_momentum", "SMA Momentum", "短期・長期移動平均のクロス", ("SPY", "QQQ")),
    "rsi_reversion": StrategyDefinition("rsi_reversion", "RSI Mean Reversion", "RSI 売られ過ぎからの反発", ("SPY", "QQQ")),
    "breakout": StrategyDefinition("breakout", "20-day Breakout", "20日高値ブレイクアウト", ("SPY", "QQQ", "IWM")),
}


def definitions() -> list[dict]:
    return [asdict(item) for item in REGISTRY.values()]


def _bars(symbol: str, timeframe: str, limit: int = 210) -> list[MarketBar]:
    with get_session() as session:
        rows = session.exec(
            select(MarketBar)
            .where(MarketBar.symbol == symbol, MarketBar.timeframe == timeframe)
            .order_by(MarketBar.ts.desc())
            .limit(limit)
        ).all()
    return list(reversed(rows))


def _sma(values: list[float], window: int) -> float | None:
    return sum(values[-window:]) / window if len(values) >= window else None


def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    changes = [values[i] - values[i - 1] for i in range(-period, 0)]
    gains = sum(max(change, 0) for change in changes) / period
    losses = sum(max(-change, 0) for change in changes) / period
    if losses == 0:
        return 100.0
    return 100 - 100 / (1 + gains / losses)


def _sma_momentum(symbol: str, bars: list[MarketBar]) -> StrategyProposal | None:
    closes = [bar.close for bar in bars]
    if len(closes) < 21:
        return None
    previous_fast, previous_slow = _sma(closes[:-1], 5), _sma(closes[:-1], 20)
    fast, slow = _sma(closes, 5), _sma(closes, 20)
    if None in (previous_fast, previous_slow, fast, slow):
        return None
    if previous_fast <= previous_slow and fast > slow:
        return StrategyProposal("sma_momentum", symbol, "BUY", closes[-1], .75, "SMA(5) crossed above SMA(20)", closes[-1] * .92)
    if previous_fast >= previous_slow and fast < slow:
        return StrategyProposal("sma_momentum", symbol, "SELL", closes[-1], .75, "SMA(5) crossed below SMA(20)")
    return None


def _rsi_reversion(symbol: str, bars: list[MarketBar]) -> StrategyProposal | None:
    closes = [bar.close for bar in bars]
    rsi = _rsi(closes)
    if rsi is None:
        return None
    if rsi < 28:
        return StrategyProposal("rsi_reversion", symbol, "BUY", closes[-1], .70, f"RSI(14) oversold: {rsi:.1f}", closes[-1] * .94)
    if rsi > 72:
        return StrategyProposal("rsi_reversion", symbol, "SELL", closes[-1], .70, f"RSI(14) overbought: {rsi:.1f}")
    return None


def _breakout(symbol: str, bars: list[MarketBar]) -> StrategyProposal | None:
    if len(bars) < 21:
        return None
    price = bars[-1].close
    prior_high = max(bar.high for bar in bars[-21:-1])
    if price > prior_high:
        return StrategyProposal("breakout", symbol, "BUY", price, .72, f"20-day breakout above {prior_high:.2f}", price * .93)
    return None


_RUNNERS: dict[str, Callable[[str, list[MarketBar]], StrategyProposal | None]] = {
    "sma_momentum": _sma_momentum,
    "rsi_reversion": _rsi_reversion,
    "breakout": _breakout,
}


def generate(strategy_id: str, symbol: str, timeframe: str = "1Day") -> StrategyProposal | None:
    if strategy_id not in _RUNNERS:
        raise ValueError(f"Unknown strategy: {strategy_id}")
    return _RUNNERS[strategy_id](symbol.upper(), _bars(symbol.upper(), timeframe))
