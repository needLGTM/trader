"""Autopilot configuration, audit journal, and safe strategy execution."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlmodel import select

from broker import get_broker
from .config import settings
from .db import get_session
from .models import AuditEvent, Order, Signal
from .risk import risk_guard
from .strategies import REGISTRY, StrategyProposal, definitions, generate

_STATE_FILE = Path(settings.database_url.replace("sqlite:///", "")).parent / "autopilot.json"
_DEFAULT_STATE: dict[str, Any] = {
    "enabled": False,
    "broker_env": "SIMULATE",
    "allocation_method": "inverse_volatility",
    "symbols": {key: list(value.default_symbols) for key, value in REGISTRY.items()},
    "strategies": {key: False for key in REGISTRY},
}


def _load() -> dict[str, Any]:
    try:
        stored = json.loads(_STATE_FILE.read_text()) if _STATE_FILE.exists() else {}
    except Exception:
        stored = {}
    result = {**_DEFAULT_STATE, **stored}
    result["strategies"] = {**_DEFAULT_STATE["strategies"], **stored.get("strategies", {})}
    result["symbols"] = {**_DEFAULT_STATE["symbols"], **stored.get("symbols", {})}
    # Autopilot can never default to real money from persisted state.
    result["broker_env"] = "SIMULATE" if result.get("broker_env") != "REAL" else "REAL"
    return result


def _save(state: dict[str, Any]) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


def state() -> dict[str, Any]:
    return _load()


def configure(patch: dict[str, Any]) -> dict[str, Any]:
    current = _load()
    for key in ("enabled", "allocation_method"):
        if key in patch:
            current[key] = patch[key]
    if "broker_env" in patch:
        # REAL requires an environment-level explicit acknowledgement, never a UI-only toggle.
        requested = str(patch["broker_env"]).upper()
        if requested == "REAL" and not settings.strategy_live_confirmed:
            raise ValueError("REAL autopilot requires STRATEGY_LIVE_CONFIRMED=true on the server")
        current["broker_env"] = requested
    for key in ("strategies", "symbols"):
        if isinstance(patch.get(key), dict):
            current[key].update(patch[key])
    _save(current)
    audit("autopilot.config", "Autopilot configuration updated", current)
    return current


def audit(event_type: str, message: str, data: dict[str, Any] | None = None) -> None:
    with get_session() as session:
        session.add(AuditEvent(event_type=event_type, message=message, data=json.dumps(data or {}, default=str)))
        session.commit()


def recent_audit(limit: int = 100) -> list[AuditEvent]:
    with get_session() as session:
        return session.exec(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)).all()


def _qty_for(proposal: StrategyProposal) -> float:
    # Allocation is intentionally capped by the central risk manager as well.
    return max(1.0, round(settings.strategy_order_usd / proposal.price, 4))


def _record_signal(proposal: StrategyProposal) -> Signal:
    signal = Signal(
        message_id=f"strategy:{proposal.strategy_id}:{proposal.symbol}:{datetime.utcnow().isoformat()}",
        author="autopilot",
        channel_id=0,
        content=proposal.reason,
        ticker=proposal.symbol,
        side=proposal.side,
        signal_type="ENTRY" if proposal.side == "BUY" else "EXIT",
        confidence=proposal.confidence,
        timeframe="1Day",
        entry=proposal.price,
        stop=proposal.stop,
    )
    with get_session() as session:
        session.add(signal)
        session.commit()
        session.refresh(signal)
    return signal


def execute(proposal: StrategyProposal, broker_env: str) -> dict[str, Any]:
    signal = _record_signal(proposal)
    qty = _qty_for(proposal)
    decision = risk_guard.evaluate(proposal.symbol, proposal.side, qty, proposal.price, broker_env)
    audit("risk.decision", decision.reason, {"signal_id": signal.id, **decision.as_dict()})
    if not decision.allowed:
        return {"signal_id": signal.id, "status": "SKIPPED", "reason": decision.reason}
    broker = get_broker(broker_env=broker_env)
    result = broker.place_order(proposal.symbol, proposal.side, qty, price=None, order_type="MARKET", tif="DAY")
    with get_session() as session:
        session.add(Order(broker=broker.name, broker_env=broker_env, order_id=result.get("order_id"), ticker=proposal.symbol, side=proposal.side, qty=qty, price=result.get("price"), status=result.get("status", "NEW"), reason=proposal.reason, signal_id=signal.id))
        session.commit()
    audit("order.placed", f"{proposal.strategy_id} {proposal.side} {proposal.symbol}", {"signal_id": signal.id, "result": result})
    return {"signal_id": signal.id, "status": result.get("status", "NEW"), "order": result}


def run(strategy_id: str | None = None) -> list[dict[str, Any]]:
    current = _load()
    if not current["enabled"]:
        return [{"status": "SKIPPED", "reason": "autopilot is disabled"}]
    ids = [strategy_id] if strategy_id else [key for key, enabled in current["strategies"].items() if enabled]
    results: list[dict[str, Any]] = []
    for item in ids:
        if item not in REGISTRY:
            results.append({"strategy_id": item, "status": "SKIPPED", "reason": "unknown strategy"})
            continue
        for symbol in current["symbols"].get(item, []):
            proposal = generate(item, symbol, REGISTRY[item].timeframe)
            if proposal is None:
                results.append({"strategy_id": item, "symbol": symbol, "status": "NO_SIGNAL"})
            else:
                results.append({"strategy_id": item, "symbol": symbol, **execute(proposal, current["broker_env"])})
    audit("autopilot.run", "Autopilot run completed", {"results": results})
    return results


def strategy_catalog() -> list[dict[str, Any]]:
    current = _load()
    return [{**definition, "enabled": bool(current["strategies"].get(definition["id"])), "symbols": current["symbols"].get(definition["id"], [])} for definition in definitions()]
