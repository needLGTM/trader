import os
from typing import Optional

from pydantic import BaseModel

_moomoo_acc_raw = os.getenv("MOOMOO_ACC_ID")


class Settings(BaseModel):
    discord_bot_token: str = os.getenv("DISCORD_BOT_TOKEN", "")
    discord_target_channel_ids: list[int] = [
        int(x) for x in os.getenv("DISCORD_TARGET_CHANNEL_IDS", "").split(",") if x
    ]

    llm_provider: str = os.getenv("LLM_PROVIDER", "openai")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_api_base: str = os.getenv("OPENAI_API_BASE", "")  # Groq: https://api.groq.com/openai/v1
    openai_model: str = os.getenv("OPENAI_MODEL", "llama-3.3-70b-versatile")  # Groq無料モデル

    max_daily_loss: float = float(os.getenv("MAX_DAILY_LOSS", "500"))
    max_position_per_ticker: int = int(os.getenv("MAX_POSITION_PER_TICKER", "2"))
    default_order_usd: float = float(os.getenv("DEFAULT_ORDER_USD", "200"))
    max_price_deviation_pct: float = float(os.getenv("MAX_PRICE_DEVIATION_PCT", "2.0"))
    strategy_order_usd: float = float(os.getenv("STRATEGY_ORDER_USD", "200"))
    strategy_live_confirmed: bool = os.getenv("STRATEGY_LIVE_CONFIRMED", "false").lower() == "true"
    max_daily_loss_pct: float = float(os.getenv("MAX_DAILY_LOSS_PCT", "3.0"))
    max_drawdown_pct: float = float(os.getenv("MAX_DRAWDOWN_PCT", "10.0"))
    max_open_positions: int = int(os.getenv("MAX_OPEN_POSITIONS", "5"))
    strategy_initial_equity: float = float(os.getenv("STRATEGY_INITIAL_EQUITY", "10000"))
    market: str = os.getenv("MARKET", "US")

    # 自動取引設定
    auto_trade_enabled: bool = os.getenv("AUTO_TRADE_ENABLED", "false").lower() == "true"
    min_confidence: float = float(os.getenv("MIN_CONFIDENCE", "0.7"))

    broker: str = os.getenv("BROKER", "paper")  # paper or moomoo
    broker_env: str = os.getenv("BROKER_ENV", "SIMULATE")  # SIMULATE or REAL
    twitter_broker_env: str = os.getenv("TWITTER_BROKER_ENV", "REAL")
    dexter_broker_env: str = os.getenv("DEXTER_BROKER_ENV", "SIMULATE")
    twitter_acc_type: str = os.getenv("TWITTER_ACC_TYPE", "margin")
    dexter_acc_type: str = os.getenv("DEXTER_ACC_TYPE", "margin")
    twitter_polling_enabled: bool = os.getenv("TWITTER_POLLING_ENABLED", "true").lower() == "true"
    twitter_auto_trade_enabled: bool = os.getenv("TWITTER_AUTO_TRADE_ENABLED", "true").lower() == "true"
    dexter_auto_trade_enabled: bool = os.getenv("DEXTER_AUTO_TRADE_ENABLED", "false").lower() == "true"
    moomoo_opend_host: str = os.getenv("MOOMOO_OPEND_HOST", "127.0.0.1")
    moomoo_opend_port: int = int(os.getenv("MOOMOO_OPEND_PORT", "11111"))
    moomoo_login_region: str = os.getenv("MOOMOO_LOGIN_REGION", "")
    moomoo_security_firm: str = os.getenv("MOOMOO_SECURITY_FIRM", "auto")
    moomoo_preferred_acc_type: str = os.getenv("MOOMOO_PREFERRED_ACC_TYPE", "auto")
    moomoo_rsa_private_key_path: str = os.getenv("MOOMOO_RSA_PRIVATE_KEY_PATH", "")
    moomoo_trade_password: str = os.getenv("MOOMOO_TRADE_PASSWORD", "")
    moomoo_trade_password_md5: str = os.getenv("MOOMOO_TRADE_PASSWORD_MD5", "")
    moomoo_acc_id: Optional[int] = int(_moomoo_acc_raw) if _moomoo_acc_raw else None

    line_channel_access_token: str = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    line_user_id: str = os.getenv("LINE_USER_ID", "")

    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./trader.db")


settings = Settings()
