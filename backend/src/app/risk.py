from .config import settings
from .models import PnL, Position
from sqlmodel import select
from .db import get_session
from dataclasses import asdict, dataclass
from datetime import date


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str
    def as_dict(self):
        return asdict(self)


class RiskGuard:
    def __init__(self):
        self.max_daily_loss = settings.max_daily_loss
        self.max_pos_per_ticker = settings.max_position_per_ticker

    def can_open(self, ticker: str, qty_delta: float) -> bool:
        # 簡易: ティッカー別の建玉上限のみチェック
        with get_session() as s:
            pos = s.exec(select(Position).where(Position.ticker == ticker)).first()
            current = 0.0 if not pos else pos.qty
            return abs(current + qty_delta) <= self.max_pos_per_ticker

    def status(self, broker_env: str = "SIMULATE") -> dict:
        with get_session() as s:
            positions = s.exec(select(Position).where(Position.broker_env == broker_env)).all()
            pnls = s.exec(select(PnL).where(PnL.broker_env == broker_env, PnL.date == date.today().isoformat())).all()
            history = s.exec(select(PnL).where(PnL.broker_env == broker_env).order_by(PnL.date.asc())).all()
        realized = sum(row.realized for row in pnls)
        unrealized = sum(row.unrealized for row in pnls)
        equity = settings.strategy_initial_equity
        peak = equity
        max_drawdown = 0.0
        # PnL rows are daily deltas. Grouping supports brokers that emit more
        # than one update for the same day.
        daily: dict[str, float] = {}
        for row in history:
            daily[row.date] = daily.get(row.date, 0.0) + row.realized + row.unrealized
        for pnl in daily.values():
            equity += pnl
            peak = max(peak, equity)
            if peak:
                max_drawdown = min(max_drawdown, (equity - peak) / peak * 100)
        return {"halted": self._halted(), "daily_pnl": realized + unrealized, "open_positions": len(positions), "max_open_positions": settings.max_open_positions, "max_daily_loss": self.max_daily_loss, "drawdown_pct": max_drawdown, "max_drawdown_pct": settings.max_drawdown_pct}

    def _halted(self) -> bool:
        from .automation import state
        return bool(state().get("halted", False))

    def evaluate(self, ticker: str, side: str, qty: float, price: float, broker_env: str) -> RiskDecision:
        status = self.status(broker_env)
        if status["halted"]:
            return RiskDecision(False, "kill switch is active")
        if side == "BUY" and status["daily_pnl"] <= -self.max_daily_loss:
            return RiskDecision(False, "daily loss limit reached")
        if side == "BUY" and status["drawdown_pct"] <= -settings.max_drawdown_pct:
            return RiskDecision(False, "maximum drawdown limit reached")
        if side == "BUY" and status["open_positions"] >= settings.max_open_positions:
            return RiskDecision(False, "maximum open positions reached")
        if side == "BUY" and not self.can_open(ticker, qty):
            return RiskDecision(False, "ticker position limit reached")
        return RiskDecision(True, "approved")

    def set_halted(self, halted: bool, reason: str = "manual") -> dict:
        from .automation import _load, _save, audit
        current = _load()
        current["halted"] = halted
        _save(current)
        audit("risk.kill_switch", "Trading halted" if halted else "Trading resumed", {"reason": reason})
        return self.status()


risk_guard = RiskGuard()
