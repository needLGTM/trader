from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Iterable

from sqlmodel import Session, select
from sqlalchemy.exc import IntegrityError

from app.models import Signal
from app.schemas import ExtractedSignal, SignalIn

log = logging.getLogger(__name__)
_EXIT_RE = re.compile(r"利確")
_PARTIAL_EXIT_RE = re.compile(r"[0-9０-９]+割利確|一部利確|半分利確|部分利確")


@dataclass
class SignalPersistResult:
    signal: Signal | None = None
    status: str | None = None


def _has_duplicate(session: Session, keys: Iterable[str], url: str | None) -> bool:
    for key in keys:
        if key and session.exec(select(Signal.id).where(Signal.message_id == key)).first():
            return True
    if url and session.exec(select(Signal.id).where(Signal.content.contains(url))).first():
        return True
    return False


def _alert_type(content: str) -> str | None:
    if "#オプションアラート" in content or "オプションアラート" in content:
        return "オプション"
    if "#スイングアラート" in content or "スイングアラート" in content:
        return "スイング"
    if "#デイトレアラート" in content or "デイトレアラート" in content:
        return "デイトレ"
    return None


def _signal_type(side: str, content: str, has_levels: bool) -> str | None:
    if side.upper() == "SELL" and _EXIT_RE.search(content):
        return "EXIT"
    if side.upper() == "BUY" and has_levels:
        return "ENTRY"
    return None


def persist_signal(
    session: Session,
    payload: SignalIn,
    parsed: ExtractedSignal,
    message_id: str,
    message_id_candidates: list[str],
    url: str | None,
    author: str,
    channel_id: int,
    parent_ticker: str | None,
) -> SignalPersistResult:
    if _has_duplicate(session, [message_id, *message_id_candidates[1:]], url):
        log.info("duplicate signal skipped message_id=%s", message_id)
        return SignalPersistResult(status="duplicate")

    if parsed.side.upper() == "INFO":
        return SignalPersistResult(status="ignored")

    content = payload.text
    if url and url not in content:
        content = f"{content}\n\nSource: {url}"
    has_levels = parsed.stop is not None or parsed.take is not None or bool(parsed.targets)
    if not parent_ticker and not has_levels:
        log.info("signal ignored without stop/target ticker=%s", parsed.ticker)
        return SignalPersistResult(status="ignored")

    signal = Signal(
        message_id=message_id,
        author=author,
        channel_id=channel_id,
        content=content,
        ticker=parsed.ticker,
        side=parsed.side,
        signal_type=_signal_type(parsed.side, content, has_levels),
        confidence=parsed.confidence,
        timeframe=parsed.timeframe,
        alert_type=_alert_type(content),
        entry=parsed.entry,
        stop=parsed.stop,
        take=parsed.take,
        targets=json.dumps(parsed.targets) if parsed.targets else None,
    )
    session.add(signal)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        log.info("duplicate signal skipped after concurrent insert message_id=%s", message_id)
        return SignalPersistResult(status="duplicate")
    session.refresh(signal)
    return SignalPersistResult(signal=signal)
