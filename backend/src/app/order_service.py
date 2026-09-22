from __future__ import annotations

import datetime
import json
import logging

from app.db import get_session
from app.models import Order, Signal
from app.risk import risk_guard
from broker import get_broker, reset_broker_cache
from sqlmodel import select

log = logging.getLogger(__name__)


def enqueue_target_orders_for_entry(
    session,
    entry_order: Order,
    filled_qty: float,
    entry_execution_id: int | None = None,
) -> None:
    signal = session.get(Signal, entry_order.signal_id) if entry_order.signal_id else None
    if signal is None or not signal.targets:
        return
    try:
        targets = [float(value) for value in json.loads(signal.targets)]
    except (TypeError, ValueError, json.JSONDecodeError):
        return
    targets = [target for target in targets if target > 0]
    if not targets:
        return
    marker_key = f"entry_order_id={entry_order.id}"
    if session.exec(select(Order).where(Order.reason.contains(marker_key))).first():
        return
    marker = f"TARGET_ORDER {marker_key}"
    base_qty = filled_qty / len(targets)
    for index, target in enumerate(targets):
        qty = filled_qty - base_qty * (len(targets) - 1) if index == 0 else base_qty
        session.add(Order(
            broker=entry_order.broker,
            broker_env=entry_order.broker_env,
            ticker=entry_order.ticker,
            side="SELL",
            qty=qty,
            price=target,
            status="PENDING",
            reason=f"{marker} target_index={index + 1}",
            signal_id=entry_order.signal_id,
            order_type="LIMIT",
            tif=entry_order.tif,
            fill_outside_rth=entry_order.fill_outside_rth,
            acc_type=entry_order.acc_type,
        ))
    log.info("target limit orders queued entry_order_id=%s targets=%s qty=%s", entry_order.id, targets, filled_qty)


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
    fill_outside_rth: bool = False,
    acc_type: str | None = None,
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
            fill_outside_rth=fill_outside_rth,
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
                    fill_outside_rth=candidate.fill_outside_rth,
                    acc_type=candidate.acc_type,
                )
                candidate.order_id = result.get("order_id")
                candidate.price = result.get("price", candidate.price)
                candidate.status = result.get("status", "SUBMITTED")
                candidate.reason = result.get("reason")
                candidate.submitted_at = datetime.datetime.utcnow()
                risk_guard.finish_reservation(session, candidate.id, consumed=True)
                if candidate.side.upper() == "BUY" and candidate.status == "FILLED":
                    enqueue_target_orders_for_entry(session, candidate, float(result.get("qty") or candidate.qty))
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