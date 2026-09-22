import base64
import datetime
import hashlib
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Iterable, List

_EXIT_RE = re.compile(r"利確")
_PARTIAL_EXIT_RE = re.compile(r"[0-9０-９]+割利確|一部利確|半分利確|部分利確")
_SL_RAISE_RE = re.compile(r"逆指値(?:を)?[ \t]*(\d+(?:\.\d+)?)")

# 全角数字 → 半角
_ZEN_DIGIT = str.maketrans("０１２３４５６７８９", "0123456789")


def _parse_exit_fraction(text: str) -> float | None:
    """
    利確の割合を 0-1 の float で返す。
    - "8割利確" → 0.8
    - "半分利確" / "5割利確" → 0.5
    - "全部利確" / "全量利確" → 1.0
    - "50%利確" → 0.5
    - "一部利確"（数字なし）→ None（割合不明）
    """
    t = text.translate(_ZEN_DIGIT)
    # N割 (e.g. 8割, 7割5分)
    m = re.search(r"(\d+(?:\.\d+)?)割(?:(\d+)分)?利確", t)
    if m:
        val = float(m.group(1)) + (float(m.group(2)) / 10 if m.group(2) else 0)
        return min(val / 10, 1.0)
    # N% (e.g. 80%利確)
    m = re.search(r"(\d+(?:\.\d+)?)%利確", t)
    if m:
        return min(float(m.group(1)) / 100, 1.0)
    # 半分
    if re.search(r"半分利確", t):
        return 0.5
    # 全部・全量
    if re.search(r"(?:全部|全量|全て|すべて)利確", t):
        return 1.0
    # 「利確」のみ（一部・部分 などの修飾語なし）→ 全量
    if _EXIT_RE.search(t) and not _PARTIAL_EXIT_RE.search(t):
        return 1.0
    # 一部利確など割合不明
    return None

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from app.db import init_db, get_session
from app.models import Execution, Order, PnL, Position, Signal
from app.config import settings
from app.schemas import SignalIn, ExtractedSignal
from app.utils import naive_extract
from app.order_service import enqueue_order
from app.signal_service import persist_signal
from app.state_sync import _dedupe_daily_pnl, sync_executions, sync_orders, sync_positions, sync_pnl, sync_trading_state
from app.cookie_store import save_cookies, load_cookies, get_version
from llm.base import LLM
from broker import get_broker, reset_broker_cache
from sqlmodel import delete, select
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger("api")

# Runtime overrides — take precedence over env-var defaults from settings
_rt: dict[str, object] = {}

_RT_FILE = Path(settings.database_url.replace("sqlite:///", "")).parent / "settings_rt.json"
_RT_KEYS = frozenset({
    "broker_env", "twitter_broker_env", "dexter_broker_env",
    "twitter_acc_type", "dexter_acc_type",
    "auto_trade_enabled", "twitter_polling_enabled",
    "twitter_auto_trade_enabled", "dexter_auto_trade_enabled",
    "default_order_usd_real", "default_order_usd_simulate",
})


def _load_rt() -> None:
    try:
        if _RT_FILE.exists():
            data = json.loads(_RT_FILE.read_text())
            _rt.update({k: v for k, v in data.items() if k in _RT_KEYS})
    except Exception:
        pass


def _save_rt() -> None:
    try:
        _RT_FILE.write_text(json.dumps({k: _rt[k] for k in _RT_KEYS if k in _rt}))
    except Exception:
        pass


# Worker heartbeat timestamps (UTC)
_worker_last_seen: dict[str, datetime.datetime] = {}


def _get(key: str) -> object:
    return _rt.get(key, getattr(settings, key))


def _resolve_default_order_usd_for_env(broker_env: str | None) -> float:
    env = (broker_env or str(_get("broker_env") or "SIMULATE")).upper()
    key = "default_order_usd_real" if env == "REAL" else "default_order_usd_simulate"
    value = _get(key)
    if value is None:
        value = getattr(settings, "default_order_usd_real" if env == "REAL" else "default_order_usd_simulate")
    return float(value)


app = FastAPI(title="Discord-LLM-Trader")


@app.on_event("startup")
def on_startup():
    init_db()
    _load_rt()
    logger.setLevel(logging.INFO)
    if settings.broker == "moomoo":
        try:
            from workers.price_reminder_worker import init_worker
            from broker.moomoo_sdk import configure_sdk_encryption
            is_encrypt = configure_sdk_encryption(settings.moomoo_rsa_private_key_path)
            init_worker(settings.moomoo_opend_host, settings.moomoo_opend_port, is_encrypt).start()
        except Exception as e:
            logger.warning("PriceReminderWorker start failed: %s", e)


llm_client: LLM | None = None
if settings.llm_provider == "ollama":
    try:
        from llm.ollama_client import OllamaLLM  # type: ignore

        base_url = settings.openai_api_base or "http://127.0.0.1:11434/v1"
        model = settings.openai_model or "qwen3:14b"

        llm_client = OllamaLLM(model, base_url)
        logger.info("LLM initialised: provider=%s model=%s base_url=%s", settings.llm_provider, model, base_url)
    except Exception as e:  # pragma: no cover - logging/optional dependency
        logger.warning("Ollama LLM initialisation failed: %s", e)
elif settings.llm_provider in {"openai", "local_openai"}:
    try:
        from llm.openai_client import OpenAILLM  # type: ignore

        base_url = settings.openai_api_base or None
        api_key = settings.openai_api_key
        model = settings.openai_model

        if settings.llm_provider == "local_openai":
            base_url = base_url or "http://127.0.0.1:11434/v1"
            api_key = api_key or "ollama"
            model = model or "qwen3:14b"

        llm_client = OpenAILLM(
            model,
            api_key,
            base_url,
        )
        logger.info("LLM initialised: provider=%s model=%s base_url=%s", settings.llm_provider, model, base_url or "default")
    except Exception as e:  # pragma: no cover - logging/optional dependency
        logger.warning("OpenAI LLM initialisation failed: %s", e)


def extract_signal(text: str, parent_ticker: str | None = None) -> ExtractedSignal | None:
    llm_text = f"[{parent_ticker} のアラートへの返信] {text}" if parent_ticker else text
    if llm_client:
        try:
            result = llm_client.extract(llm_text)
            if result:
                return result
        except Exception as e:  # pragma: no cover - defensive logging
            logger.warning("LLM extraction failed: %s", e)
    return naive_extract(llm_text)


def ensure_int(value, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def ensure_float(value, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def has_duplicate(session, keys: Iterable[str], url: str | None) -> bool:
    for key in keys:
        if not key:
            continue
        existing = session.exec(select(Signal.id).where(Signal.message_id == key)).first()
        if existing:
            logger.info("duplicate signal detected via key=%s", key)
            return True
    if url:
        existing = session.exec(select(Signal.id).where(Signal.content.contains(url))).first()
        if existing:
            logger.info("duplicate signal detected via url=%s", url)
            return True
    return False


def resolve_signal_policy(source: str, meta: dict) -> tuple[str, bool, str]:
    requested_env = str(meta.get("broker_env") or meta.get("target_env") or "").strip().upper()
    if requested_env in {"SIMULATE", "REAL"}:
        broker_env = requested_env
    elif source == "twitter":
        broker_env = str(_get("twitter_broker_env")).upper()
    elif source == "dexter":
        broker_env = str(_get("dexter_broker_env")).upper()
    else:
        broker_env = str(_get("broker_env")).upper()

    if source == "twitter":
        auto_trade_enabled = bool(_get("twitter_auto_trade_enabled"))
        acc_type = str(_get("twitter_acc_type") or "auto").lower()
    elif source == "dexter":
        auto_trade_enabled = bool(_get("dexter_auto_trade_enabled"))
        acc_type = str(_get("dexter_acc_type") or "auto").lower()
    else:
        auto_trade_enabled = bool(_get("auto_trade_enabled"))
        acc_type = "auto"

    return broker_env, auto_trade_enabled, acc_type


@app.get("/health")
def health():
    return {"ok": True}


# ── Trading Settings ────────────────────────────────

class TradingSettingsOut(BaseModel):
    broker: str
    broker_env: str
    twitter_broker_env: str
    dexter_broker_env: str
    twitter_acc_type: str
    dexter_acc_type: str
    auto_trade_enabled: bool
    twitter_polling_enabled: bool
    twitter_auto_trade_enabled: bool
    dexter_auto_trade_enabled: bool
    default_order_usd_real: float
    default_order_usd_simulate: float


class TradingSettingsPatch(BaseModel):
    broker_env: str | None = None
    twitter_broker_env: str | None = None
    dexter_broker_env: str | None = None
    twitter_acc_type: str | None = None
    dexter_acc_type: str | None = None
    auto_trade_enabled: bool | None = None
    twitter_polling_enabled: bool | None = None
    twitter_auto_trade_enabled: bool | None = None
    dexter_auto_trade_enabled: bool | None = None
    default_order_usd_real: float | None = None
    default_order_usd_simulate: float | None = None


class OrderModifyIn(BaseModel):
    price: float | None = None
    qty: float | None = None


def _build_trading_settings() -> TradingSettingsOut:
    return TradingSettingsOut(
        broker=str(_get("broker")),
        broker_env=str(_get("broker_env")).upper(),
        twitter_broker_env=str(_get("twitter_broker_env")).upper(),
        dexter_broker_env=str(_get("dexter_broker_env")).upper(),
        twitter_acc_type=str(_get("twitter_acc_type") or "auto").lower(),
        dexter_acc_type=str(_get("dexter_acc_type") or "auto").lower(),
        auto_trade_enabled=bool(_get("auto_trade_enabled")),
        twitter_polling_enabled=bool(_get("twitter_polling_enabled")),
        twitter_auto_trade_enabled=bool(_get("twitter_auto_trade_enabled")),
        dexter_auto_trade_enabled=bool(_get("dexter_auto_trade_enabled")),
        default_order_usd_real=float(_get("default_order_usd_real")),
        default_order_usd_simulate=float(_get("default_order_usd_simulate")),
    )


@app.get("/settings/trading", response_model=TradingSettingsOut)
def get_trading_settings():
    return _build_trading_settings()


@app.patch("/settings/trading", response_model=TradingSettingsOut)
def patch_trading_settings(payload: TradingSettingsPatch):
    for env_key in ("broker_env", "twitter_broker_env", "dexter_broker_env"):
        val = getattr(payload, env_key)
        if val is not None:
            v = val.upper()
            if v not in {"SIMULATE", "REAL"}:
                raise HTTPException(status_code=422, detail=f"{env_key} must be SIMULATE or REAL")
            _rt[env_key] = v
            reset_broker_cache()
    for acc_key in ("twitter_acc_type", "dexter_acc_type"):
        val = getattr(payload, acc_key)
        if val is not None:
            v = val.lower()
            if v not in {"auto", "margin", "cash"}:
                raise HTTPException(status_code=422, detail=f"{acc_key} must be auto, margin, or cash")
            _rt[acc_key] = v
    for bool_key in ("auto_trade_enabled", "twitter_polling_enabled", "twitter_auto_trade_enabled", "dexter_auto_trade_enabled"):
        val = getattr(payload, bool_key)
        if val is not None:
            _rt[bool_key] = val
    if payload.default_order_usd_real is not None:
        value = float(payload.default_order_usd_real)
        if value <= 0:
            raise HTTPException(status_code=422, detail="default_order_usd_real must be > 0")
        _rt["default_order_usd_real"] = value
    if payload.default_order_usd_simulate is not None:
        value = float(payload.default_order_usd_simulate)
        if value <= 0:
            raise HTTPException(status_code=422, detail="default_order_usd_simulate must be > 0")
        _rt["default_order_usd_simulate"] = value
    _save_rt()
    return _build_trading_settings()


# ── OpenD Management ───────────────────────────────

_OPEND_HOME = Path("/mnt/opend_home")
_OPEND_TELNET_HOST = settings.moomoo_opend_host


def _opend_api_port() -> int:
    return settings.moomoo_opend_port


_OPEND_LOG_DIR = Path(os.getenv("OPEND_LOG_PATH", "/mnt/opend_logs"))

# Verification state detected from container logs (set by _update_opend_verify_state)
_opend_verify_state: dict = {"type": None, "updated_at": None}  # type: "captcha"|"sms"|None


def _find_captcha_image() -> Path | None:
    if not _OPEND_HOME.exists():
        return None
    for png in _OPEND_HOME.glob("*/PicVerifyCode.png"):
        return png
    return None


def _opend_verify_type(connected: bool) -> str | None:
    """Detect what verification OpenD is waiting for from shared files."""
    if connected:
        return None
    log_text = ""
    try:
        log_files = sorted(
            (path for path in _OPEND_LOG_DIR.glob("*") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:5]
        log_text = "\n".join(path.read_text(errors="replace")[-65536:] for path in log_files)
    except OSError:
        return "captcha" if _find_captcha_image() is not None else None

    lines = log_text.splitlines()
    login_idx = max((i for i, line in enumerate(lines) if "Login successful" in line), default=-1)
    sms_idx = max((i for i, line in enumerate(lines) if "req_phone_verify_code" in line), default=-1)
    if sms_idx > login_idx:
        return "sms"
    cap_idx = max((i for i, line in enumerate(lines) if "PicVerifyCode" in line), default=-1)
    if cap_idx > login_idx and _find_captcha_image() is not None:
        return "captcha"
    return None


@app.get("/opend/status")
def opend_status():
    from broker import _is_host_reachable
    connected = _is_host_reachable(_OPEND_TELNET_HOST, _opend_api_port(), timeout=1.0)
    verify = _opend_verify_type(connected)
    captcha = _find_captcha_image() if verify == "captcha" else None
    return {
        "connected": connected,
        "verify_type": verify,          # "captcha" | "sms" | null
        "captcha_pending": verify == "captcha",
        "sms_pending": verify == "sms",
        "captcha_path": str(captcha) if captcha else None,
    }


@app.get("/opend/captcha-image")
def opend_captcha_image():
    captcha = _find_captcha_image()
    if captcha is None:
        raise HTTPException(status_code=404, detail="キャプチャ画像が見つかりません")
    data = base64.b64encode(captcha.read_bytes()).decode()
    return {"image": f"data:image/png;base64,{data}"}


class CaptchaSubmit(BaseModel):
    code: str
    verify_type: str = "captcha"  # "captcha" | "sms"


def _opend_exec(cmd: str) -> str:
    if not re.fullmatch(r"input_(?:phone|pic)_verify_code -code=[A-Za-z0-9]+", cmd):
        raise HTTPException(status_code=422, detail="unsupported OpenD command")

    control_path = Path(os.getenv("OPEND_CONTROL_PATH", "/mnt/opend_home/opend_input"))
    try:
        control_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", dir=control_path.parent, prefix=".opend_input.", delete=False
        ) as tmp:
            tmp.write(cmd + "\n")
            temporary_path = Path(tmp.name)
        temporary_path.replace(control_path)
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"OpenD制御ファイルを書き込めません: {exc}") from exc
    return "queued"


@app.post("/opend/submit-captcha")
def opend_submit_captcha(payload: CaptchaSubmit):
    code = payload.code.strip()
    if not code:
        raise HTTPException(status_code=422, detail="code is required")
    try:
        if payload.verify_type == "sms":
            _opend_exec(f"input_phone_verify_code -code={code}")
        else:
            _opend_exec(f"input_pic_verify_code -code={code}")
        return {"ok": True, "response": "送信しました。OpenD のログで結果を確認してください。"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"OpenD command queue failed: {e}")


# ── Worker Status ──────────────────────────────────

@app.post("/workers/twitter/heartbeat")
def twitter_heartbeat():
    _worker_last_seen["twitter"] = datetime.datetime.utcnow()
    return {"enabled": bool(_get("twitter_polling_enabled"))}


@app.get("/workers/status")
def workers_status():
    now = datetime.datetime.utcnow()

    def _entry(name: str, enabled_key: str) -> dict:
        ts = _worker_last_seen.get(name)
        seconds_ago = int((now - ts).total_seconds()) if ts else None
        return {
            "last_seen": ts.isoformat() if ts else None,
            "seconds_ago": seconds_ago,
            "alive": seconds_ago is not None and seconds_ago < 90,
            "enabled": bool(_get(enabled_key)),
        }

    return {
        "twitter": _entry("twitter", "twitter_polling_enabled"),
    }


# ── Dexter ─────────────────────────────────────────

class DexterQueryIn(BaseModel):
    query: str


@app.post("/dexter/query")
def dexter_query(payload: DexterQueryIn):
    if not payload.query.strip():
        raise HTTPException(status_code=422, detail="query is empty")
    try:
        from app.dexter_bridge import get_dexter_dir_from_env, run_dexter_once
        dexter_dir = get_dexter_dir_from_env()
        answer = run_dexter_once(dexter_dir, payload.query.strip())
        return {"answer": answer}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Twitter Cookie 管理 ─────────────────────────────

class CookieIn(BaseModel):
    auth_token: str
    ct0: str


@app.post("/settings/twitter-cookies")
def set_twitter_cookies(payload: CookieIn):
    """Cookie を受け取り保存。簡易テストも行う"""
    if len(payload.auth_token) < 20 or len(payload.ct0) < 20:
        raise HTTPException(status_code=422, detail="Cookie の値が短すぎます")

    save_cookies(payload.auth_token, payload.ct0)
    return {"status": "saved", "valid": True, "error": None, "version": get_version()}


@app.get("/settings/twitter-cookies")
def get_twitter_cookie_status():
    auth_token, ct0 = load_cookies()
    has_cookies = bool(auth_token and ct0)
    return {
        "has_cookies": has_cookies,
        "version": get_version(),
        "auth_token_preview": auth_token[:8] + "..." if auth_token else None,
    }


@app.post("/settings/twitter-cookies/verify")
def verify_twitter_cookies():
    """保存済みCookieで実際にTwitter APIを叩いて疎通確認する。"""
    import httpx as _httpx
    auth_token, ct0 = load_cookies()
    if not auth_token or not ct0:
        return {"valid": False, "error": "Cookieが保存されていません", "screen_name": None}

    _BEARER = (
        "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs="
        "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
    )
    import json as _json, os as _os
    ep = _os.getenv("TW_EP_USER_BY_SCREENNAME", "sLVLhk0bGj3MVFEKTdax1w")
    variables = _json.dumps({"screen_name": "x", "withSafetyModeUserFields": True})
    features = _json.dumps({
        "hidden_profile_likes_enabled": True,
        "hidden_profile_subscriptions_enabled": True,
        "responsive_web_graphql_exclude_directive_enabled": True,
        "verified_phone_label_enabled": False,
        "creator_subscriptions_tweet_preview_api_enabled": True,
        "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
        "responsive_web_graphql_timeline_navigation_enabled": True,
    })
    try:
        r = _httpx.get(
            f"https://x.com/i/api/graphql/{ep}/UserByScreenName",
            params={"variables": variables, "features": features},
            cookies={"auth_token": auth_token, "ct0": ct0},
            headers={
                "authorization": f"Bearer {_BEARER}",
                "x-csrf-token": ct0,
                "x-twitter-active-user": "yes",
                "x-twitter-auth-type": "OAuth2Session",
                "user-agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            },
            timeout=10,
            follow_redirects=True,
        )
        if r.status_code == 401:
            return {"valid": False, "error": "HTTP 401 — Cookieが無効または期限切れです", "screen_name": None}
        if r.status_code == 403:
            return {"valid": False, "error": "HTTP 403 — アクセスが拒否されました（Cookieが無効の可能性）", "screen_name": None}
        if r.status_code != 200:
            return {"valid": False, "error": f"HTTP {r.status_code}", "screen_name": None}
        data = r.json()
        errors = data.get("errors")
        if errors:
            return {"valid": False, "error": errors[0].get("message", "Twitter APIエラー"), "screen_name": None}
        # 接続・認証OK（screen_nameはチェック対象ユーザーではなくcookie所有者は不明なのでnull）
        return {"valid": True, "error": None, "screen_name": None}
    except Exception as e:
        return {"valid": False, "error": str(e), "screen_name": None}


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    """Cookie 入力 + ステータス表示のダッシュボード"""
    html_path = Path(__file__).parent / "dashboard.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/orders")
def list_orders(broker_env: str | None = Query(default=None)):
    with get_session() as s:
        rows = sync_orders(s)
        if broker_env:
            env = broker_env.upper()
            rows = [r for r in rows if r.broker_env == env]
        return jsonable_encoder(rows)


@app.patch("/orders/{order_id}")
def modify_order(order_id: int, payload: OrderModifyIn):
    with get_session() as s:
        order = s.get(Order, order_id)
        if not order:
            raise HTTPException(status_code=404, detail="order not found")
        if order.status.upper() not in {"PENDING", "NEW", "SUBMITTED", "EXECUTING", "PARTIALLY_FILLED"}:
            raise HTTPException(status_code=409, detail=f"order cannot be modified in status {order.status}")
        if payload.price is None and payload.qty is None:
            raise HTTPException(status_code=422, detail="price or qty is required")
        next_price = payload.price if payload.price is not None else order.price
        next_qty = payload.qty if payload.qty is not None else order.qty
        if next_qty is None or next_qty <= 0:
            raise HTTPException(status_code=422, detail="qty must be > 0")
        try:
            broker = get_broker(broker_name=order.broker, broker_env=order.broker_env)
            if order.order_id:
                broker.modify_order(order.order_id, next_qty, next_price)
            order.price = next_price
            order.qty = next_qty
            order.reason = None
            s.commit()
            s.refresh(order)
            return jsonable_encoder(order)
        except Exception as exc:
            s.rollback()
            raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.delete("/orders/{order_id}")
def cancel_order(order_id: int):
    with get_session() as s:
        order = s.get(Order, order_id)
        if not order:
            raise HTTPException(status_code=404, detail="order not found")
        if order.status.upper() not in {"PENDING", "NEW", "SUBMITTED", "EXECUTING", "PARTIALLY_FILLED"}:
            raise HTTPException(status_code=409, detail=f"order cannot be canceled in status {order.status}")
        try:
            broker = get_broker(broker_name=order.broker, broker_env=order.broker_env)
            if order.order_id:
                broker.cancel_order(order.order_id)
            order.status = "CANCELED"
            order.reason = "canceled by user"
            s.commit()
            s.refresh(order)
            return jsonable_encoder(order)
        except Exception as exc:
            s.rollback()
            raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/positions")
def list_positions(broker_env: str | None = Query(default=None), acc_type: str | None = Query(default=None)):
    env = (broker_env or str(_get("broker_env"))).upper()
    with get_session() as s:
        rows = sync_positions(s, broker_env=env)
        if acc_type:
            rows = [r for r in rows if r.acc_type.upper() == acc_type.upper()]
        return jsonable_encoder(rows)


@app.get("/executions")
def list_executions(broker_env: str | None = Query(default=None)):
    env = (broker_env or str(_get("broker_env"))).upper()
    with get_session() as s:
        sync_orders(s)
        sync_executions(s)
        sync_pnl(s, broker_env=env)
        rows = s.exec(
            select(Execution)
            .where(Execution.broker_env == env)
            .order_by(Execution.executed_at.desc())
        ).all()
        return jsonable_encoder(rows)


@app.get("/pnl")
def list_pnl(broker_env: str | None = Query(default=None)):
    env = (broker_env or str(_get("broker_env"))).upper()
    with get_session() as s:
        sync_trading_state(s, broker_env=env)
        rows = s.exec(select(PnL).where(PnL.broker_env == env).order_by(PnL.date.asc())).all()
        deduped = _dedupe_daily_pnl(rows)
        if len(deduped) != len(rows):
            s.exec(delete(PnL).where(PnL.broker_env == env))
            for row in deduped:
                s.add(row)
            s.commit()
        return jsonable_encoder(deduped)


@app.post("/sync")
def sync_state():
    with get_session() as s:
        synced = sync_trading_state(s)
        return {
            "orders": jsonable_encoder(synced["orders"]),
            "executions": jsonable_encoder(synced["executions"]),
            "positions": jsonable_encoder(synced["positions"]),
            "pnls": jsonable_encoder(synced["pnls"]),
        }


@app.get("/signals")
def list_signals():
    with get_session() as s:
        rows = s.exec(select(Signal).order_by(Signal.created_at.desc()).limit(100)).all()
        return rows


@app.post("/signals")
def receive_signal(payload: SignalIn):
    parent_ticker = (payload.meta.get("parent_ticker") or "").strip() or None

    parsed = extract_signal(payload.text, parent_ticker=parent_ticker)
    if not parsed:
        # 返信ツイートで親のtickerが分かっている場合はアクションを推定
        if parent_ticker:
            is_full_exit = _EXIT_RE.search(payload.text) and not _PARTIAL_EXIT_RE.search(payload.text)
            inferred_side = "SELL" if is_full_exit else "INFO"
            parsed = ExtractedSignal(ticker=parent_ticker, side=inferred_side)
            logger.info("reply fallback: ticker=%s side=%s text=%r", parent_ticker, inferred_side, payload.text[:60])
        else:
            logger.warning(
                "signal extraction failed, storing as raw signal source=%s meta=%s", payload.source, payload.meta
            )
            parsed = ExtractedSignal(ticker="?", side="INFO")

    url = payload.meta.get("url")
    message_id_candidates: List[str] = []
    for key in (payload.meta.get("message_id"), payload.meta.get("id"), url):
        if key:
            message_id_candidates.append(str(key))

    message_id = message_id_candidates[0] if message_id_candidates else None
    if not message_id:
        message_id = f"{payload.source}:{hashlib.sha256(payload.text.encode('utf-8')).hexdigest()}"

    author = (
        payload.meta.get("username")
        or payload.meta.get("author")
        or payload.meta.get("user")
        or payload.source
    )
    channel_id = ensure_int(
        payload.meta.get("channel_id")
        or payload.meta.get("chat_id")
        or payload.meta.get("user_id")
    )

    broker_env, source_auto_trade_enabled, acc_type = resolve_signal_policy(payload.source, payload.meta)

    with get_session() as s:
        persisted = persist_signal(
            s,
            payload,
            parsed,
            message_id,
            message_id_candidates,
            url,
            str(author),
            channel_id,
            parent_ticker,
        )
        if persisted.status == "duplicate":
            return {"status": "duplicate"}
        if persisted.status == "ignored":
            return {"signal": None, "broker_env": broker_env, "auto_trade_enabled": False, "order": None}
        signal = persisted.signal

    logger.info(
        "signal stored id=%s source=%s ticker=%s side=%s broker_env=%s auto_trade=%s meta=%s parsed=%s",
        signal.id,
        payload.source,
        parsed.ticker,
        parsed.side,
        broker_env,
        source_auto_trade_enabled,
        payload.meta,
        parsed.model_dump(),
    )

    # 自動注文実行
    order_result = None
    _notify_skipped = False
    _notify_skip_reason = ""
    _notify_delta: float | None = None
    _notify_original_entry: float | None = None
    _auto_trade_blocked_reason: str | None = None
    is_option_signal = signal.alert_type == "オプション"
    fill_outside_rth = signal.alert_type == "デイトレ"
    _notify_exit_fraction: float | None = (
        _parse_exit_fraction(payload.text) if parsed.side.upper() == "SELL" else None
    )

    if not source_auto_trade_enabled:
        _auto_trade_blocked_reason = "auto_trade=OFF"
    elif is_option_signal:
        _auto_trade_blocked_reason = "オプション専用処理待ち"
        logger.info(
            "option signal held without stock order signal_id=%s ticker=%s side=%s",
            signal.id,
            parsed.ticker,
            parsed.side,
        )
    elif parsed.side.upper() == "INFO":
        _auto_trade_blocked_reason = "extraction failed"
        # INFO でも逆指値引き上げなら price reminder だけ更新する
        if source_auto_trade_enabled and parent_ticker and "引き上げ" in payload.text:
            sl_m = _SL_RAISE_RE.search(payload.text)
            if sl_m:
                new_sl = float(sl_m.group(1))
                try:
                    broker = get_broker(broker_env=broker_env)
                    if hasattr(broker, "clear_price_reminders") and hasattr(broker, "set_price_reminders"):
                        broker.clear_price_reminders(parent_ticker)
                        broker.set_price_reminders(parent_ticker, sl=new_sl, tp_list=[], side="BUY")
                        _auto_trade_blocked_reason = f"SL更新 → {new_sl}"
                        logger.info("SL updated (INFO path) ticker=%s new_sl=%.4f", parent_ticker, new_sl)
                except Exception as sl_exc:
                    logger.warning("SL update (INFO path) failed: %s", sl_exc)

    if source_auto_trade_enabled and not is_option_signal and parsed.side.upper() != "INFO":
        try:
            broker = get_broker(broker_env=broker_env)
            _broker_acc_type = acc_type if broker_env == "REAL" else None

            if parsed.side.upper() == "SELL":
                # ── EXIT: 割合に応じたポジションをマーケット成行でクローズ ──────
                exit_fraction = _parse_exit_fraction(payload.text)
                try:
                    position_qty_fn = getattr(broker, "position_qty", None)
                    if callable(position_qty_fn):
                        pos_qty = position_qty_fn(parsed.ticker, _broker_acc_type)
                    else:
                        positions = broker.positions()
                        pos = positions.get(parsed.ticker)
                        pos_qty = float(pos.get("qty", 0)) if pos else 0.0

                    if exit_fraction is None:
                        # "一部利確" など割合不明 → 自動売買しない
                        _auto_trade_blocked_reason = "一部利確（割合不明）"
                        logger.info("partial exit skipped (unknown fraction) ticker=%s", parsed.ticker)
                    elif pos_qty <= 0:
                        _auto_trade_blocked_reason = "no open position"
                        logger.info("no position to exit ticker=%s broker_env=%s", parsed.ticker, broker_env)
                    else:
                        sell_qty = max(1.0, round(pos_qty * exit_fraction))
                        is_full_exit = exit_fraction >= 1.0 or sell_qty >= pos_qty
                        order_result = enqueue_order(
                            broker_name=broker.name,
                            broker_env=broker_env,
                            ticker=parsed.ticker,
                            side="SELL",
                            qty=sell_qty,
                            price=None,
                            order_type="MARKET",
                            tif="DAY",
                            fill_outside_rth=fill_outside_rth,
                            acc_type=_broker_acc_type,
                            signal_id=signal.id,
                        )
                        if order_result is None:
                            _auto_trade_blocked_reason = "risk limit exceeded"
                        logger.info(
                            "exit order queued signal_id=%s ticker=%s qty=%s/%s (%.0f%%) broker_env=%s status=%s",
                            signal.id, parsed.ticker, sell_qty, pos_qty,
                            exit_fraction * 100, broker_env, order_result.get("status") if order_result else "SKIPPED",
                        )
                        # 全量クローズ時のみ price reminder を削除
                        if is_full_exit and hasattr(broker, "clear_price_reminders"):
                            try:
                                broker.clear_price_reminders(parsed.ticker)
                            except Exception:
                                pass
                except Exception as exit_exc:
                    logger.warning("exit order failed ticker=%s: %s", parsed.ticker, exit_exc)

                # 逆指値引き上げ: 返信ツイートで SL 更新指示がある場合
                if parent_ticker and "引き上げ" in payload.text:
                    sl_m = _SL_RAISE_RE.search(payload.text)
                    if sl_m:
                        new_sl = float(sl_m.group(1))
                        if hasattr(broker, "clear_price_reminders") and hasattr(broker, "set_price_reminders"):
                            try:
                                broker.clear_price_reminders(parsed.ticker)
                                broker.set_price_reminders(parsed.ticker, sl=new_sl, tp_list=[], side="BUY")
                                logger.info("SL updated ticker=%s new_sl=%.4f", parsed.ticker, new_sl)
                            except Exception as sl_exc:
                                logger.warning("SL update failed: %s", sl_exc)

            else:
                # ── ENTRY (BUY): 既存ロジック ─────────────────────────────────
                requested_qty = ensure_float(payload.meta.get("qty"))
                requested_order_type = payload.meta.get("order_type")
                order_type = str(requested_order_type or ("LIMIT" if parsed.entry is not None else "MARKET")).upper()
                limit_price = ensure_float(
                    payload.meta.get("limit_price") or payload.meta.get("price") or parsed.entry
                )
                tif = str(payload.meta.get("tif") or "DAY").upper()

                qty = requested_qty if requested_qty and requested_qty > 0 else 1.0
                current_price: float | None = None
                quote_last_price = getattr(broker, "quote_last_price", None)
                if callable(quote_last_price):
                    try:
                        current_price = float(quote_last_price(parsed.ticker))
                        if current_price > 0 and requested_qty is None:
                            order_budget = _resolve_default_order_usd_for_env(broker_env)
                            qty = max(order_budget / current_price, 1.0)
                            logger.info(
                                "calculated order qty from live quote ticker=%s last_price=%s broker_env=%s budget_usd=%s qty=%s",
                                parsed.ticker, current_price, broker_env, order_budget, qty,
                            )
                    except Exception as quote_exc:
                        logger.warning("failed to fetch live quote for %s: %s", parsed.ticker, quote_exc)

                # 価格乖離補正
                signal_entry = ensure_float(parsed.entry)
                price_skip = False
                if signal_entry and current_price and current_price > 0:
                    delta = current_price - signal_entry
                    dev_pct = abs(delta) / signal_entry * 100
                    if dev_pct > settings.max_price_deviation_pct:
                        reason = f"price_deviation {delta:+.2f} ({dev_pct:.2f}%)"
                        logger.warning(
                            "price deviation too large signal_id=%s ticker=%s entry=%.4f current=%.4f deviation=%.2f%%",
                            signal.id, parsed.ticker, signal_entry, current_price, dev_pct,
                        )
                        with get_session() as s:
                            s.add(Order(
                                broker=broker.name,
                                broker_env=broker_env,
                                ticker=parsed.ticker,
                                side=parsed.side,
                                qty=qty,
                                price=signal_entry,
                                status="SKIPPED",
                                reason=reason,
                                signal_id=signal.id,
                            ))
                            s.commit()
                        price_skip = True
                        _notify_skipped = True
                        _notify_skip_reason = reason
                    else:
                        if parsed.entry is not None:
                            parsed.entry = round(parsed.entry + delta, 4)
                        if parsed.stop is not None:
                            parsed.stop = round(parsed.stop + delta, 4)
                        if parsed.take is not None:
                            parsed.take = round(parsed.take + delta, 4)
                        if parsed.targets:
                            parsed.targets = [round(t + delta, 4) for t in parsed.targets]
                        if limit_price is not None:
                            limit_price = round(limit_price + delta, 4)
                        _notify_delta = delta
                        _notify_original_entry = signal_entry
                        logger.info(
                            "price shift applied signal_id=%s ticker=%s delta=%+.4f (%.2f%%) entry=%.4f→%.4f",
                            signal.id, parsed.ticker, delta, dev_pct,
                            signal_entry, parsed.entry or signal_entry,
                        )

                if price_skip:
                    pass
                else:
                    order_result = enqueue_order(
                        broker_name=broker.name,
                        broker_env=broker_env,
                        ticker=parsed.ticker,
                        side=parsed.side,
                        qty=qty,
                        price=limit_price,
                        order_type=order_type,
                        tif=tif,
                        fill_outside_rth=fill_outside_rth,
                        acc_type=_broker_acc_type,
                        signal_id=signal.id,
                    )
                    if order_result is None:
                        _auto_trade_blocked_reason = "risk limit exceeded"
                    logger.info(
                        "auto order queued signal_id=%s ticker=%s side=%s broker_env=%s status=%s",
                        signal.id, parsed.ticker, parsed.side, broker_env,
                        order_result.get("status") if order_result else "SKIPPED",
                    )
                    if hasattr(broker, "set_price_reminders"):
                        try:
                            import json as _json
                            _sl = ensure_float(parsed.stop)
                            _tp_raw = parsed.targets or ([parsed.take] if parsed.take else [])
                            _tp_list = [float(t) for t in _tp_raw if t is not None]
                            broker.set_price_reminders(
                                ticker=parsed.ticker, sl=_sl, tp_list=_tp_list, side=parsed.side,
                            )
                        except Exception as remind_exc:
                            logger.warning("set_price_reminders failed: %s", remind_exc)

                # 逆指値引き上げ (BUY エントリー後の SL 更新ツイートとして届いた場合)
                if parent_ticker and "引き上げ" in payload.text and not price_skip:
                    sl_m = _SL_RAISE_RE.search(payload.text)
                    if sl_m:
                        new_sl = float(sl_m.group(1))
                        if hasattr(broker, "clear_price_reminders") and hasattr(broker, "set_price_reminders"):
                            try:
                                broker.clear_price_reminders(parsed.ticker)
                                broker.set_price_reminders(parsed.ticker, sl=new_sl, tp_list=[], side="BUY")
                                logger.info("SL updated ticker=%s new_sl=%.4f", parsed.ticker, new_sl)
                            except Exception as sl_exc:
                                logger.warning("SL update failed: %s", sl_exc)

        except Exception as e:
            reset_broker_cache()
            logger.error("auto order failed for signal_id=%s: %s", signal.id, e)

    # ── LINE 通知（INFO は送らない） ──────────────────────────────────────────
    if parsed.side.upper() != "INFO":
        try:
            from app.line_notify import notify_signal
            _entry = ensure_float(parsed.entry)
            _stop  = ensure_float(parsed.stop)
            _tp_raw = parsed.targets or ([parsed.take] if parsed.take else [])
            _targets = [float(t) for t in _tp_raw if t is not None]
            notify_signal(
                source=payload.source, ticker=parsed.ticker, side=parsed.side,
                entry=_entry, stop=_stop, targets=_targets,
                broker_env=broker_env, acc_type=acc_type,
                shift_delta=_notify_delta,
                original_entry=_notify_original_entry,
                skipped=_notify_skipped, skip_reason=_notify_skip_reason,
                order_placed=order_result is not None,
                order_status=order_result.get("status", "") if order_result else "",
                blocked_reason=_auto_trade_blocked_reason,
                exit_fraction=_notify_exit_fraction,
            )
        except Exception as _notify_exc:
            logger.warning("LINE notify failed: %s", _notify_exc)

    return {
        "signal": signal,
        "broker_env": broker_env,
        "auto_trade_enabled": source_auto_trade_enabled,
        "order": order_result,
    }


# ── LINE Webhook ───────────────────────────────────────
_line_captured_user_ids: list[str] = []
_line_captured_replies: list[dict] = []


@app.post("/line/webhook")
async def line_webhook(request: Request):
    try:
        body = await request.json()
        for event in body.get("events", []):
            uid = event.get("source", {}).get("userId")
            if uid and uid not in _line_captured_user_ids:
                _line_captured_user_ids.append(uid)
                logger.info("LINE userId captured: %s", uid)
            if event.get("type") == "message" and event.get("message", {}).get("type") == "text":
                text = event["message"].get("text", "").strip()
                logger.info("LINE reply received uid=%s text=%s", uid, text)
                _line_captured_replies.append({"uid": uid, "text": text})
                if len(_line_captured_replies) > 100:
                    _line_captured_replies.pop(0)
    except Exception:
        pass
    return {}


@app.get("/line/captured-users")
def line_captured_users():
    return {"user_ids": _line_captured_user_ids}


# ── Market Data ───────────────────────────────────────────────────────────────

@app.get("/market/snapshot")
def market_snapshot(codes: str = Query(..., description="カンマ区切りのティッカー")):
    tickers = [t.strip() for t in codes.split(",") if t.strip()]
    if not tickers:
        raise HTTPException(status_code=422, detail="codes is required")
    try:
        broker = get_broker()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
    if not hasattr(broker, "market_snapshot"):
        raise HTTPException(status_code=501, detail="market snapshot not supported by this broker")
    return broker.market_snapshot(tickers)


@app.get("/screener/unusual")
def screener_unusual(
    ticker: str = Query(..., description="銘柄コード"),
    type: str = Query("technical", description="technical | derivative"),
):
    try:
        broker = get_broker()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
    if not hasattr(broker, "screener_unusual"):
        raise HTTPException(status_code=501, detail="screener not supported by this broker")
    return broker.screener_unusual(ticker.upper(), type)


@app.get("/account/cash-flow")
def account_cash_flow(clearing_date: str = Query("", description="精算日 YYYY-MM-DD（空=当日）")):
    try:
        broker = get_broker()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
    if not hasattr(broker, "cash_flow"):
        raise HTTPException(status_code=501, detail="cash flow not supported by this broker")
    return broker.cash_flow(clearing_date)


@app.get("/executions/fees")
def execution_fees():
    """保存済み注文IDの手数料を moomoo から一括取得する。"""
    with get_session() as s:
        orders = s.exec(select(Order).where(Order.order_id.is_not(None))).all()
        order_ids = [o.order_id for o in orders if o.order_id]
    if not order_ids:
        return {}
    try:
        broker = get_broker()
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
    if not hasattr(broker, "order_fees"):
        raise HTTPException(status_code=501, detail="order fees not supported by this broker")
    return broker.order_fees(order_ids)


# ── Backtest ──────────────────────────────────────────────────────────────────

class SignalBacktestIn(BaseModel):
    ticker: str | None = None
    start: str | None = None
    end: str | None = None
    qty: float = 100.0
    interval: str = "5m"


@app.post("/backtest/signals")
def backtest_signals(body: SignalBacktestIn):
    from app.backtest import run_signal_backtest
    from dataclasses import asdict
    result = run_signal_backtest(
        ticker=body.ticker or None,
        start=body.start or None,
        end=body.end or None,
        qty=body.qty,
        interval=body.interval,
    )
    return asdict(result)


class SmaBacktestIn(BaseModel):
    symbol: str = "AAPL"
    timeframe: str = "1Day"
    start: str = "2024-01-01"
    end: str = "2024-12-31"
    short_window: int = 5
    long_window: int = 20
    initial_equity: float = 100_000.0


@app.post("/backtest/sma")
def backtest_sma(body: SmaBacktestIn):
    from app.backtest import run_sma_crossover
    from dataclasses import asdict
    result = run_sma_crossover(
        symbol=body.symbol,
        timeframe=body.timeframe,
        start=body.start,
        end=body.end,
        short_window=body.short_window,
        long_window=body.long_window,
        initial_equity=body.initial_equity,
    )
    return asdict(result)
