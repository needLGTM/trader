from .config import settings
from .models import Position
from .models import RiskReservation
from sqlmodel import select
from .db import get_session


class RiskGuard:
    def __init__(self):
        self.max_daily_loss = settings.max_daily_loss
        self.max_pos_per_ticker = settings.max_position_per_ticker

    def can_open(self, ticker: str, qty_delta: float) -> bool:
        # 簡易: ティッカー別の建玉上限のみチェック
        with get_session() as s:
            pos = s.exec(select(Position).where(Position.ticker == ticker)).first()
            current = 0.0 if not pos else pos.qty
            reserved = sum(
                row.qty
                for row in s.exec(
                    select(RiskReservation).where(
                        RiskReservation.ticker == ticker,
                        RiskReservation.status == "RESERVED",
                    )
                ).all()
            )
            return abs(current) + reserved + qty_delta <= self.max_pos_per_ticker

    def reserve(self, session, order_id: int, ticker: str, qty: float, broker_env: str, acc_type: str) -> bool:
        position = session.exec(
            select(Position).where(
                Position.ticker == ticker,
                Position.broker_env == broker_env,
                Position.acc_type == (acc_type or "MARGIN"),
            )
        ).first()
        current = abs(float(position.qty)) if position else 0.0
        reserved = sum(
            row.qty
            for row in session.exec(
                select(RiskReservation).where(
                    RiskReservation.ticker == ticker,
                    RiskReservation.broker_env == broker_env,
                    RiskReservation.acc_type == (acc_type or "MARGIN"),
                    RiskReservation.status == "RESERVED",
                )
            ).all()
        )
        if current + reserved + qty > self.max_pos_per_ticker:
            return False
        session.add(
            RiskReservation(
                order_id=order_id,
                ticker=ticker,
                broker_env=broker_env,
                acc_type=acc_type or "MARGIN",
                qty=qty,
            )
        )
        return True

    def finish_reservation(self, session, order_id: int, consumed: bool) -> None:
        reservations = session.exec(
            select(RiskReservation).where(RiskReservation.order_id == order_id)
        ).all()
        for reservation in reservations:
            reservation.status = "CONSUMED" if consumed else "RELEASED"


risk_guard = RiskGuard()