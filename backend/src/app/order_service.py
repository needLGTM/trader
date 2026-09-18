from __future__ import annotations

import datetime
import logging

from app.db import get_session
from app.models import Order
from app.risk import risk_guard
from broker import get_broker, reset_broker_cache
from sqlmodel import select

log = logging.getLogger(__name__)


def enqueue_order(
    *,
    broker_name: str,
    broker_env: str,
    ticker: str,
    side: str,
    qty: float,
    price: float | None,
    order_type: str,
    tif: str,
    acc_type: str | None,
    signal_id: int,
) -> dict | None:
    """Persist an order intent; the executor worker performs the external call."""
    with get_session() as session:
        order = Order(
            broker=broker_name,
            broker_env=broker_env,
            ticker=ticker,
            side=side,
            qty=qty,
            price=price,
            status="PENDING",
            signal_id=signal_id,
            order_type=order_type,
            tif=tif,
            acc_type=acc_type,
        )
        session.add(order)
        session.flush()
        if side.upper() == "BUY" and not risk_guard.reserve(
            session, order.id, ticker, qty, broker_env, acc_type or "MARGIN"
        ):
            session.rollback()
            return None
        session.commit()
        session.refresh(order)
        return {
            "id": order.id,
            "status": order.status,
            "order_id": order.order_id,
            "ticker": order.ticker,
            "side": order.side,
            "qty": order.qty,
        }


def execute_pending_orders() -> int:
    """Claim and execute pending orders once; UNKNOWN is never retried blindly."""
    executed = 0
    with get_session() as session:
        pending = session.exec(
            select(Order).where(Order.status == "PENDING").order_by(Order.created_at).limit(20)
        ).all()
        for candidate in pending:
            candidate.status = "EXECUTING"
            candidate.attempts += 1
            session.commit()
            try:
                broker = get_broker(broker_name=candidate.broker, broker_env=candidate.broker_env)
                result = broker.place_order(
                    ticker=candidate.ticker,
                    side=candidate.side,
                    qty=candidate.qty,
                    price=candidate.price,
                    order_type=candidate.order_type,
                    tif=candidate.tif,
                    acc_type=candidate.acc_type,
                )
                candidate.order_id = result.get("order_id")
                candidate.price = result.get("price", candidate.price)
                candidate.status = result.get("status", "SUBMITTED")
                candidate.reason = result.get("reason")
                candidate.submitted_at = datetime.datetime.utcnow()
                risk_guard.finish_reservation(session, candidate.id, consumed=True)
                session.commit()
                executed += 1
            except Exception as exc:
                reset_broker_cache()
                candidate.status = "UNKNOWN"
                candidate.reason = str(exc)
                risk_guard.finish_reservation(session, candidate.id, consumed=False)
                session.commit()
                log.exception("order execution unknown order_id=%s", candidate.id)
    return executed