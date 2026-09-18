from typing import Optional
from sqlmodel import SQLModel, Field
from datetime import datetime


class Signal(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    message_id: str
    author: str
    channel_id: int
    content: str
    ticker: str
    side: str # BUY/SELL
    signal_type: str | None = None  # ENTRY/EXIT
    confidence: float | None = None
    timeframe: str | None = None
    alert_type: str | None = None   # デイトレ / スイング / オプション
    entry: float | None = None
    stop: float | None = None
    take: float | None = None       # 第一ターゲット（後方互換）
    targets: str | None = None     # JSON配列 "[3.93, 4.15, 4.63]"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Order(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    broker: str
    broker_env: str = "SIMULATE"
    order_id: str | None = None
    ticker: str
    side: str # BUY/SELL
    qty: float
    price: float | None = None
    status: str = "NEW" # NEW/FILLED/CANCELED/REJECTED
    reason: str | None = None
    signal_id: int | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Position(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ticker: str
    qty: float # + long / - short（紙取引用の簡易モデル）
    avg_price: float
    broker_env: str = Field(default="SIMULATE")
    acc_type: str = Field(default="MARGIN")


class Execution(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: Optional[int] = Field(default=None)   # local Order.id (system-placed)
    deal_id: Optional[str] = Field(default=None)    # moomoo deal_id (imported)
    ticker: str
    side: str
    qty: float
    price: float
    broker_env: str = Field(default="SIMULATE")
    executed_at: datetime = Field(default_factory=datetime.utcnow)


class PnL(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    date: str # YYYY-MM-DD
    realized: float = 0.0
    unrealized: float = 0.0
    broker_env: str = Field(default="SIMULATE")


class MarketBar(SQLModel, table=True):
    """シンプルなOHLCVバー（銘柄×時間足×時刻）。"""

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str
    timeframe: str  # e.g. 1Min, 5Min, 1Hour, 1Day
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class AuditEvent(SQLModel, table=True):
    """Append-only journal for configuration, risk decisions, and orders."""
    id: Optional[int] = Field(default=None, primary_key=True)
    event_type: str
    message: str
    data: str = "{}"
    created_at: datetime = Field(default_factory=datetime.utcnow)
