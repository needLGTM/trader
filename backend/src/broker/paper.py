from .base import Broker
from typing import Optional
from sqlmodel import select
from app.db import get_session
from app.models import Position


class PaperBroker(Broker):
    name = "paper"


    def place_order(
        self,
        ticker: str,
        side: str,
        qty: float,
        price: Optional[float] = None,
        order_type: str = "LIMIT",
        tif: str = "DAY",
        acc_type: Optional[str] = None,
    ) -> dict:
        # 約定=即時、価格は直近値の代わりに指定/ダミー（1.0）
        px = price or 1.0
        with get_session() as s:
            # ポジション更新
            pos = s.exec(select(Position).where(Position.ticker == ticker)).first()
            signed_qty = qty if side == "BUY" else -qty
            if pos:
                new_qty = pos.qty + signed_qty
                if new_qty == 0:
                    s.delete(pos)
                else:
                    # 単純平均
                    pos.avg_price = (abs(pos.qty) * pos.avg_price + qty * px) / max(abs(new_qty), 1)
                    pos.qty = new_qty
            else:
                s.add(Position(ticker=ticker, qty=signed_qty, avg_price=px))

            # API レイヤで Order レコードを保存し、その後 sync_executions で Execution を起こす。
            s.commit()
            return {
                "broker": self.name,
                "ticker": ticker,
                "side": side,
                "qty": qty,
                "price": px,
                "status": "FILLED",
                "reason": None,
                "order_id": None,
            }


    def positions(self) -> dict[str, dict]:
        with get_session() as s:
            rows = s.exec(select(Position)).all()
            return {r.ticker: {"qty": r.qty, "avg_price": r.avg_price} for r in rows}


    def cancel_all(self) -> None:
        return None

    def sync_order(self, order_id: str) -> dict | None:
        return None
