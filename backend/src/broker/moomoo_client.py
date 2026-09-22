from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import pandas as pd
from moomoo import (
    AuType,
    KLType,
    Market,
    ModifyOrderOp,
    OpenQuoteContext,
    OpenSecTradeContext,
    OrderStatus,
    OrderType,
    PriceReminderFreq,
    PriceReminderType,
    RET_OK,
    SecurityFirm,
    SetPriceReminderOp,
    SubType,
    TimeInForce,
    TrailType,
    TrdEnv,
    TrdMarket,
    TrdSide,
)

from .base import Broker
from .moomoo_sdk import configure_sdk_encryption

log = logging.getLogger(__name__)

_ENV_MAP: Dict[str, TrdEnv] = {
    "SIMULATE": TrdEnv.SIMULATE,
    "REAL": TrdEnv.REAL,
}

_MARKET_MAP: Dict[str, TrdMarket] = {
    "US": TrdMarket.US,
    "JP": TrdMarket.JP,
    "HK": TrdMarket.HK,
}

_SECURITY_FIRM_MAP: Dict[str, SecurityFirm] = {
    "FUTUSECURITIES": SecurityFirm.FUTUSECURITIES,
    "FUTUINC": SecurityFirm.FUTUINC,
    "FUTUJP": SecurityFirm.FUTUJP,
}

_SIDE_MAP: Dict[str, TrdSide] = {
    "BUY": TrdSide.BUY,
    "SELL": TrdSide.SELL,
}

_ORDER_TYPE_MAP: Dict[str, OrderType] = {
    "LIMIT": OrderType.NORMAL,
    "MARKET": OrderType.MARKET,
    "TRAILING_STOP": OrderType.TRAILING_STOP,
    "TRAILING_STOP_LIMIT": OrderType.TRAILING_STOP_LIMIT,
}

_TRAIL_TYPE_MAP: Dict[str, TrailType] = {
    "RATIO": TrailType.RATIO,
    "AMOUNT": TrailType.AMOUNT,
}

_KTYPE_MAP: Dict[str, KLType] = {
    "1m": KLType.K_1M,
    "5m": KLType.K_5M,
    "15m": KLType.K_15M,
    "30m": KLType.K_30M,
    "1h": KLType.K_60M,
    "60m": KLType.K_60M,
    "1d": KLType.K_DAY,
    "1D": KLType.K_DAY,
}

_MARKET_QOT_MAP: Dict[str, Market] = {
    "US": Market.US,
    "HK": Market.HK,
    "JP": Market.JP,
    "SH": Market.SH,
    "SZ": Market.SZ,
}

_TIF_MAP: Dict[str, TimeInForce] = {
    "DAY": TimeInForce.DAY,
    "GTC": TimeInForce.GTC,
}

_ORDER_STATUS_MAP: Dict[str, str] = {
    "SUBMITTED": "NEW",
    "SUBMITTING": "NEW",
    "WAITING_SUBMIT": "NEW",
    "PENDING_SUBMIT": "NEW",
    "FILLED_PART": "PARTIALLY_FILLED",
    "FILLED_ALL": "FILLED",
    "CANCELLED_PART": "PARTIALLY_CANCELED",
    "CANCELLED_ALL": "CANCELED",
    "FAILED": "REJECTED",
    "REJECTED": "REJECTED",
}

_CANCELABLE_STATUSES = [
    OrderStatus.SUBMITTED,
    OrderStatus.SUBMITTING,
    OrderStatus.WAITING_SUBMIT,
    OrderStatus.FILLED_PART,
]

_ACCOUNT_TYPE_PRIORITY: Dict[str, int] = {
    "MARGIN": 0,
    "CASH": 1,
    "DERIVATIVES": 2,
}

_SUPPORTED_ACCOUNT_TYPES = set(_ACCOUNT_TYPE_PRIORITY)


class MoomooBroker(Broker):
    name = "moomoo"

    def __init__(
        self,
        host: str,
        port: int,
        trd_env: str,
        rsa_private_key_path: str = "",
        acc_id: Optional[int] = None,
        market: str = "US",
        login_region: str = "",
        security_firm: str = "auto",
        preferred_acc_type: str = "auto",
        trade_password: str = "",
        trade_password_md5: str = "",
    ):
        self._host = host
        self._port = port
        self._market = (market or "US").upper()
        self._login_region = (login_region or "").strip().lower()
        self._security_firm = self._parse_security_firm(security_firm)
        self._preferred_acc_type = self._parse_preferred_acc_type(preferred_acc_type)
        self._trade_password = trade_password.strip()
        self._trade_password_md5 = trade_password_md5.strip()
        self._trd_env = self._parse_env(trd_env)
        self._rsa_private_key_path = rsa_private_key_path.strip()
        self._ctx = self._connect()
        try:
            self._unlock_trade_if_configured()
            self._acc_id = self._initialise_account(acc_id)
            # {acc_type_upper: acc_id} — for per-order account routing
            self._acc_id_by_type: Dict[str, int] = self._build_acc_type_map()
        except Exception:
            self._ctx.close()
            raise

    # --------------------------------------------------------------------- #
    # Lifecycle helpers
    # --------------------------------------------------------------------- #
    def _parse_env(self, env: str) -> TrdEnv:
        try:
            return _ENV_MAP[env.upper()]
        except KeyError as exc:
            raise ValueError(f"Unsupported trade environment '{env}'. Use SIMULATE or REAL.") from exc

    def _connect(self) -> OpenSecTradeContext:
        # moomoo証券（日本）などは OpenUSTradeContext ではなく Universal / Sec コンテキストが必要
        try:
            is_encrypt = configure_sdk_encryption(self._rsa_private_key_path)
            ctx = OpenSecTradeContext(
                filter_trdmarket=self._resolve_trade_market(),
                host=self._host,
                port=self._port,
                is_encrypt=is_encrypt,
                security_firm=self._security_firm,
            )
        except Exception as exc:  # pragma: no cover - SDK raises varied exceptions
            log.exception("Failed to connect to Moomoo OpenD at %s:%s", self._host, self._port)
            raise RuntimeError("Unable to connect to Moomoo OpenD") from exc
        log.info(
            "Connected to Moomoo OpenD at %s:%s market=%s security_firm=%s",
            self._host,
            self._port,
            self._market,
            self._security_firm,
        )
        return ctx

    def _quote_context(self) -> OpenQuoteContext:
        is_encrypt = configure_sdk_encryption(self._rsa_private_key_path)
        return OpenQuoteContext(host=self._host, port=self._port, is_encrypt=is_encrypt)

    def _filter_by_market_auth(self, acc_df: pd.DataFrame) -> pd.DataFrame:
        """trd_market_auth に MARKET（US/JP/HK 等）が含まれる口座に絞る。列がない・合致なしはそのまま。"""
        try:
            tm = self._resolve_trade_market()
        except ValueError:
            log.warning("Unknown MARKET=%s for Moomoo; skipping trd_market_auth filter", self._market)
            return acc_df
        col = acc_df.get("trd_market_auth")
        if col is None:
            col = acc_df.get("trdmarket_auth")
        if col is None:
            return acc_df

        def has_auth(val: Any) -> bool:
            if isinstance(val, (list, tuple)):
                if tm in val:
                    return True
                market_name = getattr(tm, "name", str(tm))
                return market_name in val or self._market in val
            return False

        filtered = acc_df[col.apply(has_auth)]
        if filtered.empty:
            log.warning(
                "No Moomoo account with trd_market_auth containing %s; using env-matched accounts only",
                self._market,
            )
            return acc_df
        return filtered

    def _resolve_trade_market(self) -> TrdMarket:
        market = _MARKET_MAP.get(self._market)
        if market is None:
            raise ValueError(f"Unsupported Moomoo market '{self._market}'.")
        return market

    def _parse_security_firm(self, security_firm: str) -> SecurityFirm:
        normalized = (security_firm or "auto").strip().upper()
        if normalized in {"", "AUTO"}:
            if self._login_region == "jp":
                return SecurityFirm.FUTUJP
            return SecurityFirm.FUTUSECURITIES
        parsed = _SECURITY_FIRM_MAP.get(normalized)
        if parsed is None:
            raise ValueError(
                f"Unsupported Moomoo security firm '{security_firm}'. "
                "Use auto, FUTUSECURITIES, FUTUINC, or FUTUJP."
            )
        return parsed

    def _parse_preferred_acc_type(self, preferred_acc_type: str) -> str | None:
        normalized = (preferred_acc_type or "auto").strip().upper()
        if normalized in {"", "AUTO"}:
            return None
        if normalized not in _SUPPORTED_ACCOUNT_TYPES:
            raise ValueError(
                f"Unsupported Moomoo account type preference '{preferred_acc_type}'. "
                "Use auto, CASH, MARGIN, or DERIVATIVES."
            )
        return normalized

    def _initialise_account(self, requested_acc_id: Optional[int]) -> int:
        ret, acc_df = self._ctx.get_acc_list()
        if ret != RET_OK:
            msg = acc_df if isinstance(acc_df, str) else "Unknown error"
            log.error("Failed to fetch Moomoo account list: %s", msg)
            raise RuntimeError(f"Failed to fetch Moomoo account list: {msg}")
        if acc_df.empty:
            raise RuntimeError("No Moomoo trading accounts available for the requested environment.")
        target_env = str(self._trd_env).upper()
        env_col = acc_df.get("trd_env")
        if env_col is not None:
            acc_df = acc_df[env_col.astype(str).str.upper() == target_env]
        if acc_df.empty:
            raise RuntimeError(f"No Moomoo accounts available for environment {target_env}.")
        acc_df = self._filter_by_market_auth(acc_df)
        if acc_df.empty:
            raise RuntimeError(f"No Moomoo accounts available for environment {target_env} after market filter.")
        if "acc_id" in acc_df.columns:
            available_ids = [int(v) for v in acc_df["acc_id"] if not pd.isna(v)]
        elif "acc_index" in acc_df.columns:
            available_ids = [int(v) for v in acc_df["acc_index"] if not pd.isna(v)]
        else:
            available_ids = []
        if not available_ids:
            raise RuntimeError("Could not determine account identifiers from Moomoo response.")
        if requested_acc_id is not None:
            if requested_acc_id not in available_ids:
                raise RuntimeError(
                    f"Requested Moomoo account {requested_acc_id} not found. Available accounts: {available_ids}"
                )
            selected = requested_acc_id
        else:
            selected = self._select_best_account(acc_df, available_ids)
        log.info(
            "Using Moomoo account %s in %s environment",
            selected,
            target_env,
        )
        return selected

    def _select_best_account(self, acc_df: pd.DataFrame, available_ids: list[int]) -> int:
        candidates: list[tuple[int, int, float, int]] = []
        preferred_currency = "USD" if self._market == "US" else "JPY"
        candidate_df = acc_df

        if self._preferred_acc_type:
            filtered = acc_df[acc_df["acc_type"].astype(str).str.upper() == self._preferred_acc_type]
            if filtered.empty:
                log.warning(
                    "Requested Moomoo account type %s not found in eligible accounts; falling back to default priority.",
                    self._preferred_acc_type,
                )
            else:
                candidate_df = filtered

        for _, row in candidate_df.iterrows():
            acc_id_raw = row.get("acc_id")
            if pd.isna(acc_id_raw):
                continue
            acc_id = int(acc_id_raw)
            if acc_id not in available_ids:
                continue
            acc_type = str(row.get("acc_type", "")).upper()
            priority = _ACCOUNT_TYPE_PRIORITY.get(acc_type, 99)
            buying_power = self._query_buying_power(acc_id, preferred_currency)
            candidates.append((priority, -buying_power, acc_id, buying_power))

        if not candidates:
            return available_ids[0]

        candidates.sort()
        selected_priority, _, selected_acc_id, selected_power = candidates[0]
        log.info(
            "Selected Moomoo account %s with acc_type_priority=%s buying_power=%s currency=%s preferred_acc_type=%s",
            selected_acc_id,
            selected_priority,
            selected_power,
            preferred_currency,
            self._preferred_acc_type or "auto",
        )
        return selected_acc_id

    def _build_acc_type_map(self) -> Dict[str, int]:
        """Build {MARGIN: acc_id, CASH: acc_id} map for per-order account routing."""
        result: Dict[str, int] = {}
        try:
            ret, acc_df = self._ctx.get_acc_list()
            if ret != RET_OK or acc_df.empty:
                return result
            target_env = str(self._trd_env).upper()
            if "trd_env" in acc_df.columns:
                acc_df = acc_df[acc_df["trd_env"].astype(str).str.upper() == target_env]
            acc_df = self._filter_by_market_auth(acc_df)
            for _, row in acc_df.iterrows():
                acc_id_raw = row.get("acc_id")
                if pd.isna(acc_id_raw):
                    continue
                acc_type = str(row.get("acc_type", "")).upper()
                if acc_type in _SUPPORTED_ACCOUNT_TYPES and acc_type != "DERIVATIVES":
                    result[acc_type] = int(acc_id_raw)
        except Exception:
            log.warning("Failed to build acc_type map", exc_info=True)
        log.info("Account type map: %s", result)
        return result

    def acc_type_map(self) -> Dict[str, int]:
        """Return a copy of the acc_type → acc_id map (read-only)."""
        return dict(self._acc_id_by_type)

    def _resolve_acc_id(self, acc_type: Optional[str]) -> int:
        """Return the acc_id for the given account type, falling back to default."""
        if not acc_type or acc_type.upper() == "AUTO":
            return self._acc_id
        mapped = self._acc_id_by_type.get(acc_type.upper())
        if mapped is None:
            log.warning("acc_type=%s not found in map %s, using default", acc_type, self._acc_id_by_type)
            return self._acc_id
        return mapped

    def _query_buying_power(self, acc_id: int, currency: str) -> float:
        try:
            ret, info = self._ctx.accinfo_query(
                trd_env=self._trd_env,
                acc_id=acc_id,
                currency=currency,
            )
            if ret != RET_OK or getattr(info, "empty", True):
                return 0.0
            row = info.iloc[0]
            value = row.get("power")
            if value in (None, "N/A"):
                value = row.get("usd_net_cash_power" if currency == "USD" else "jpy_net_cash_power")
            return float(value or 0.0)
        except Exception:
            log.warning("Failed to query buying power for Moomoo account %s", acc_id, exc_info=True)
            return 0.0

    def _unlock_trade_if_configured(self) -> None:
        if self._trd_env != TrdEnv.REAL:
            return
        if not self._trade_password and not self._trade_password_md5:
            return
        kwargs: Dict[str, Any] = {"is_unlock": True}
        if self._trade_password_md5:
            kwargs["password_md5"] = self._trade_password_md5
        else:
            kwargs["password"] = self._trade_password
        ret, data = self._ctx.unlock_trade(**kwargs)
        if ret != RET_OK:
            msg = data if isinstance(data, str) else "Unknown error"
            raise RuntimeError(f"Moomoo trade unlock failed: {msg}")
        log.info("Moomoo trade unlock succeeded for REAL environment")

    def close(self) -> None:
        try:
            self._ctx.close()
        except Exception:  # pragma: no cover - best effort close
            log.debug("Failed to close Moomoo trade context cleanly.", exc_info=True)

    def __del__(self) -> None:  # pragma: no cover - destructor path hard to test
        self.close()

    # --------------------------------------------------------------------- #
    # Utility
    # --------------------------------------------------------------------- #
    def _normalise_symbol(self, ticker: str) -> str:
        if "." in ticker:
            return ticker
        return f"{self._market}.{ticker}"

    def _strip_symbol(self, code: str) -> str:
        return code.split(".", 1)[-1] if "." in code else code

    def _normalise_status(self, status: str) -> str:
        upper_status = status.upper()
        return _ORDER_STATUS_MAP.get(upper_status, upper_status)

    def _build_order_payload(
        self,
        ticker: str,
        side: str,
        qty: float,
        price: Optional[float],
        order_type: str,
        tif: str,
        trail_type: Optional[str] = None,
        trail_value: Optional[float] = None,
    ) -> Dict[str, Any]:
        mapped_side = _SIDE_MAP.get(side.upper())
        if mapped_side is None:
            raise ValueError(f"Unsupported order side '{side}'. Expected BUY or SELL.")
        mapped_order_type = _ORDER_TYPE_MAP.get(order_type.upper())
        if mapped_order_type is None:
            raise ValueError(f"Unsupported order type '{order_type}'. Expected LIMIT, MARKET, TRAILING_STOP, or TRAILING_STOP_LIMIT.")
        mapped_tif = _TIF_MAP.get(tif.upper())
        if mapped_tif is None:
            raise ValueError(f"Unsupported time-in-force '{tif}'. Expected DAY, GTC, or IOC.")
        if mapped_order_type == OrderType.NORMAL and price is None:
            raise ValueError("Limit orders require a price.")
        is_trailing = mapped_order_type in (OrderType.TRAILING_STOP, OrderType.TRAILING_STOP_LIMIT)
        mapped_trail_type = None
        if is_trailing and trail_type:
            mapped_trail_type = _TRAIL_TYPE_MAP.get(trail_type.upper())
        return {
            "price": price or 0.0,
            "qty": qty,
            "code": self._normalise_symbol(ticker),
            "side": mapped_side,
            "order_type": mapped_order_type,
            "tif": mapped_tif,
            "trail_type": mapped_trail_type,
            "trail_value": trail_value,
        }

    def _format_order_response(
        self,
        resp_row: Dict[str, Any],
        fallback_ticker: str,
        fallback_side: str,
        fallback_qty: float,
        fallback_price: Optional[float],
    ) -> Dict[str, Any]:
        order_status = str(resp_row.get("order_status", "")).upper()
        last_err = resp_row.get("last_err_msg") or None
        price = resp_row.get("price") or resp_row.get("dealt_avg_price") or fallback_price
        qty = resp_row.get("qty") or resp_row.get("qty_all") or fallback_qty
        return {
            "broker": self.name,
            "ticker": self._strip_symbol(str(resp_row.get("code", fallback_ticker))),
            "side": str(resp_row.get("trd_side", fallback_side)).upper(),
            "qty": float(qty) if qty is not None else None,
            "price": float(price) if price is not None else None,
            "status": self._normalise_status(order_status),
            "reason": last_err,
            "order_id": str(resp_row.get("order_id")) if resp_row.get("order_id") is not None else None,
        }

    # --------------------------------------------------------------------- #
    # Broker interface
    # --------------------------------------------------------------------- #
    def place_order(
        self,
        ticker: str,
        side: str,
        qty: float,
        price: Optional[float] = None,
        order_type: str = "LIMIT",
        tif: str = "DAY",
        fill_outside_rth: bool = False,
        trail_type: Optional[str] = None,
        trail_value: Optional[float] = None,
        acc_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        resolved_acc_id = self._resolve_acc_id(acc_type)
        payload = self._build_order_payload(ticker, side, qty, price, order_type, tif, trail_type, trail_value)
        log.debug(
            "Placing order via Moomoo: %s %s %s qty=%s price=%s type=%s tif=%s acc_type=%s trail_type=%s trail_value=%s",
            payload["code"], side, self._trd_env, qty, price, order_type, tif, acc_type, trail_type, trail_value,
        )
        ret, data = self._ctx.place_order(
            payload["price"],
            payload["qty"],
            payload["code"],
            payload["side"],
            order_type=payload["order_type"],
            time_in_force=payload["tif"],
            fill_outside_rth=fill_outside_rth,
            session="ETH" if fill_outside_rth else "N/A",
            trd_env=self._trd_env,
            acc_id=resolved_acc_id,
            trail_type=payload.get("trail_type"),
            trail_value=payload.get("trail_value"),
        )
        if ret != RET_OK:
            msg = data if isinstance(data, str) else "Unknown error"
            log.error("Failed to place order with Moomoo: %s", msg)
            raise RuntimeError(f"Moomoo order placement failed: {msg}")
        resp_row = data.iloc[0].to_dict() if not data.empty else {}
        order_summary = self._format_order_response(
            resp_row,
            fallback_ticker=ticker,
            fallback_side=side,
            fallback_qty=qty,
            fallback_price=price,
        )
        log.info("Order submitted to Moomoo: id=%s status=%s", order_summary.get("order_id"), order_summary["status"])
        return order_summary

    def positions(self) -> Dict[str, Dict[str, Any]]:
        ret, data = self._ctx.position_list_query(trd_env=self._trd_env, acc_id=self._acc_id)
        if ret != RET_OK:
            msg = data if isinstance(data, str) else "Unknown error"
            log.error("Failed to fetch positions from Moomoo: %s", msg)
            raise RuntimeError(f"Moomoo positions retrieval failed: {msg}")
        if data.empty:
            return {}
        positions: Dict[str, Dict[str, Any]] = {}
        for _, row in data.iterrows():
            code = str(row.get("code", ""))
            ticker = self._strip_symbol(code)
            qty = float(row.get("qty", 0.0))
            avg_price = float(row.get("cost_price", 0.0))
            positions[ticker] = {"qty": qty, "avg_price": avg_price}
        log.debug("Fetched %d positions from Moomoo", len(positions))
        return positions

    def positions_by_type(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """Return {acc_type: {ticker: {qty, avg_price}}} for all queryable accounts."""
        ret, acc_df = self._ctx.get_acc_list()
        if ret != RET_OK or acc_df.empty:
            return {}
        target_env = str(self._trd_env).upper()
        if "trd_env" in acc_df.columns:
            acc_df = acc_df[acc_df["trd_env"].astype(str).str.upper() == target_env]
        result: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for _, row in acc_df.iterrows():
            acc_id = int(row.get("acc_id", 0))
            acc_type = str(row.get("acc_type", "UNKNOWN")).upper()
            if acc_type == "DERIVATIVES":
                continue  # requires extra parameters not supported here
            ret2, pos_df = self._ctx.position_list_query(trd_env=self._trd_env, acc_id=acc_id)
            if ret2 != RET_OK or not hasattr(pos_df, "iterrows") or pos_df.empty:
                continue
            positions: Dict[str, Dict[str, Any]] = {}
            for _, prow in pos_df.iterrows():
                code = str(prow.get("code", ""))
                ticker = self._strip_symbol(code)
                if not ticker:
                    continue
                positions[ticker] = {
                    "qty": float(prow.get("qty", 0.0)),
                    "avg_price": float(prow.get("cost_price", 0.0)),
                }
            result[acc_type] = positions
            log.debug("Fetched %d positions for acc_type=%s acc_id=%s", len(positions), acc_type, acc_id)
        return result

    def position_qty(self, ticker: str, acc_type: Optional[str] = None) -> float:
        """Return current long qty for ticker in the given account type (0 if none)."""
        if acc_type:
            by_type = self.positions_by_type()
            normalized = acc_type.upper()
            for key, positions in by_type.items():
                if key.upper() == normalized:
                    return float(positions.get(ticker, {}).get("qty", 0.0))
            return 0.0
        pos = self.positions().get(ticker)
        return float(pos.get("qty", 0.0)) if pos else 0.0

    def quote_last_price(self, ticker: str) -> float:
        code = self._normalise_symbol(ticker)
        quote_ctx: OpenQuoteContext | None = None
        try:
            quote_ctx = self._quote_context()
            ret, data = quote_ctx.subscribe([code], [SubType.QUOTE], subscribe_push=False)
            if ret != RET_OK:
                msg = data if isinstance(data, str) else "Unknown error"
                raise RuntimeError(f"Moomoo quote subscribe failed: {msg}")
            ret, data = quote_ctx.get_stock_quote([code])
            if ret != RET_OK:
                msg = data if isinstance(data, str) else "Unknown error"
                raise RuntimeError(f"Moomoo stock quote retrieval failed: {msg}")
            if data.empty:
                raise RuntimeError(f"Moomoo stock quote returned no rows for {code}")
            row = data.iloc[0]
            price = row.get("last_price", row.get("cur_price"))
            if price is None:
                raise RuntimeError(f"Moomoo stock quote returned no last price for {code}")
            return float(price)
        finally:
            if quote_ctx is not None:
                quote_ctx.close()

    # --------------------------------------------------------------------- #
    # Market data helpers
    # --------------------------------------------------------------------- #

    def market_snapshot(self, tickers: list[str]) -> Dict[str, Dict[str, Any]]:
        """Return {ticker: {last_price, prev_close, change_pct, volume}} for each ticker."""
        codes = [self._normalise_symbol(t) for t in tickers]
        qctx = self._quote_context()
        try:
            ret, df = qctx.get_market_snapshot(codes)
            if ret != RET_OK or df.empty:
                return {}
            result: Dict[str, Dict[str, Any]] = {}
            for _, row in df.iterrows():
                ticker = self._strip_symbol(str(row.get("code", "")))
                result[ticker] = {
                    "last_price": float(row.get("last_price") or 0),
                    "prev_close": float(row.get("prev_close_price") or 0),
                    "change_pct": float(row.get("change_rate") or 0),
                    "volume": float(row.get("volume") or 0),
                }
            return result
        finally:
            qctx.close()

    def history_kline(
        self,
        ticker: str,
        start: str,
        end: str,
        interval: str = "1d",
    ) -> Optional[Any]:
        """Download historical OHLCV from moomoo OpenD. Returns pandas DataFrame or None."""
        import pandas as pd
        code = self._normalise_symbol(ticker)
        ktype = _KTYPE_MAP.get(interval, KLType.K_DAY)
        qctx = self._quote_context()
        try:
            ret, df, _ = qctx.request_history_kline(
                code, start=start, end=end,
                ktype=ktype, autype=AuType.QFQ, max_count=3000,
            )
            if ret != RET_OK or df.empty:
                return None
            df = df.rename(columns={
                "time_key": "Datetime", "open": "Open",
                "high": "High", "low": "Low",
                "close": "Close", "volume": "Volume",
            })
            df["Datetime"] = pd.to_datetime(df["Datetime"])
            df = df.set_index("Datetime")
            return df
        except Exception:
            log.debug("history_kline failed for %s, will fallback", ticker, exc_info=True)
            return None
        finally:
            qctx.close()

    # --------------------------------------------------------------------- #
    # Account helpers
    # --------------------------------------------------------------------- #

    def order_fees(self, order_ids: list[str]) -> Dict[str, float]:
        """Return {order_id: handling_fee} for completed orders."""
        if not order_ids:
            return {}
        try:
            ret, df = self._ctx.order_fee_query(
                order_id_list=order_ids,
                trd_env=self._trd_env,
                acc_id=self._acc_id,
            )
            if ret != RET_OK or df.empty:
                return {}
            result: Dict[str, float] = {}
            for _, row in df.iterrows():
                oid = str(row.get("order_id", ""))
                fee = float(row.get("handling_fee") or 0)
                if oid:
                    result[oid] = fee
            return result
        except Exception:
            log.warning("order_fees query failed", exc_info=True)
            return {}

    def history_deals(self, start: str, end: str) -> list[Dict[str, Any]]:
        """Return filled deals [{deal_id, ticker, side, qty, price, executed_at, broker_env}]."""
        try:
            ret, df = self._ctx.history_deal_list_query(
                start=start, end=end,
                trd_env=self._trd_env, acc_id=self._acc_id,
            )
            if ret != RET_OK or df is None or (hasattr(df, "empty") and df.empty):
                return []
            rows = []
            for _, row in df.iterrows():
                status = str(row.get("status", "")).upper()
                if status not in ("OK", ""):
                    continue
                side_raw = str(row.get("trd_side", "")).upper()
                side = "BUY" if side_raw in ("BUY",) else "SELL" if side_raw in ("SELL",) else None
                if side is None:
                    continue
                code = str(row.get("code", ""))
                ticker = self._strip_symbol(code)
                if not ticker:
                    continue
                rows.append({
                    "deal_id": str(row.get("deal_id", "")),
                    "ticker": ticker,
                    "side": side,
                    "qty": float(row.get("qty", 0)),
                    "price": float(row.get("price", 0)),
                    "executed_at": str(row.get("create_time", "")),
                    "broker_env": "REAL" if self._trd_env == TrdEnv.REAL else "SIMULATE",
                })
            return rows
        except Exception:
            log.warning("history_deals query failed", exc_info=True)
            return []

    def cash_flow(self, clearing_date: str = "") -> list[Dict[str, Any]]:
        """Return cash flow entries for the given clearing date (empty = today)."""
        try:
            ret, df = self._ctx.get_acc_cash_flow(
                clearing_date=clearing_date,
                trd_env=self._trd_env,
                acc_id=self._acc_id,
            )
            if ret != RET_OK or df.empty:
                return []
            rows = []
            for _, row in df.iterrows():
                rows.append({
                    "time": str(row.get("cash_flow_time", "")),
                    "direction": str(row.get("cash_flow_direction", "")),
                    "amount": float(row.get("amount") or 0),
                    "remark": str(row.get("remark", "")),
                })
            return rows
        except Exception:
            log.warning("cash_flow query failed", exc_info=True)
            return []

    # --------------------------------------------------------------------- #
    # Screener helpers
    # --------------------------------------------------------------------- #

    def screener_unusual(
        self,
        ticker: str,
        unusual_type: str = "technical",
    ) -> list[Dict[str, Any]]:
        """Return unusual activity for a specific ticker (technical or derivative)."""
        code = self._normalise_symbol(ticker)
        qctx = self._quote_context()
        try:
            if unusual_type == "derivative":
                ret, df = qctx.get_derivative_unusual(code)
            else:
                ret, df = qctx.get_technical_unusual(code)
            if ret != RET_OK or df is None or (hasattr(df, "empty") and df.empty):
                return []
            if hasattr(df, "to_dict"):
                return df.to_dict(orient="records")
            return []
        except Exception:
            log.warning("screener_unusual failed for %s", ticker, exc_info=True)
            return []
        finally:
            qctx.close()

    # --------------------------------------------------------------------- #
    # Price reminder helpers
    # --------------------------------------------------------------------- #

    def set_price_reminders(
        self,
        ticker: str,
        sl: Optional[float],
        tp_list: list[float],
        side: str,
    ) -> None:
        """Register SL/TP price reminders via OpenD. Fires a LINE push when hit."""
        code = self._normalise_symbol(ticker)
        qctx = self._quote_context()
        try:
            is_long = side.upper() == "BUY"
            reminders: list[tuple[float, PriceReminderType, str]] = []
            if sl is not None:
                r_type = PriceReminderType.PRICE_DOWN if is_long else PriceReminderType.PRICE_UP
                reminders.append((sl, r_type, f"SL {ticker}"))
            for i, tp in enumerate(tp_list, 1):
                r_type = PriceReminderType.PRICE_UP if is_long else PriceReminderType.PRICE_DOWN
                reminders.append((tp, r_type, f"TP{i} {ticker}"))
            for value, r_type, note in reminders:
                ret, data = qctx.set_price_reminder(
                    code=code,
                    op=SetPriceReminderOp.ADD,
                    reminder_type=r_type,
                    reminder_freq=PriceReminderFreq.ONCE,
                    value=value,
                    note=note,
                )
                if ret == RET_OK:
                    log.info("Price reminder set: %s %.2f (%s)", code, value, note)
                else:
                    log.warning("Failed to set price reminder %s %.2f: %s", code, value, data)
        except Exception:
            log.warning("set_price_reminders failed for %s", ticker, exc_info=True)
        finally:
            qctx.close()

    def clear_price_reminders(self, ticker: str) -> None:
        """Delete all price reminders for a ticker."""
        code = self._normalise_symbol(ticker)
        qctx = self._quote_context()
        try:
            qctx.set_price_reminder(code=code, op=SetPriceReminderOp.DEL_ALL)
        except Exception:
            log.warning("clear_price_reminders failed for %s", ticker, exc_info=True)
        finally:
            qctx.close()

    def cancel_all(self) -> None:
        ret, data = self._ctx.order_list_query(
            trd_env=self._trd_env,
            acc_id=self._acc_id,
            status_filter_list=_CANCELABLE_STATUSES,
        )
        if ret != RET_OK:
            msg = data if isinstance(data, str) else "Unknown error"
            log.error("Failed to query open orders for cancellation: %s", msg)
            raise RuntimeError(f"Moomoo order query failed: {msg}")
        if data.empty:
            log.info("No open Moomoo orders to cancel.")
            return
        for _, row in data.iterrows():
            order_id = row.get("order_id")
            if order_id is None:
                continue
            ret, err = self._ctx.modify_order(
                ModifyOrderOp.CANCEL,
                order_id=order_id,
                qty=0,
                price=0,
                trd_env=self._trd_env,
                acc_id=self._acc_id,
            )
            if ret != RET_OK:
                log.warning("Failed to cancel order %s: %s", order_id, err)
            else:
                log.info("Cancelled Moomoo order %s", order_id)

    def cancel_order(self, order_id: str) -> None:
        ret, err = self._ctx.modify_order(
            ModifyOrderOp.CANCEL,
            order_id=order_id,
            qty=0,
            price=0,
            trd_env=self._trd_env,
            acc_id=self._acc_id,
        )
        if ret != RET_OK:
            msg = err if isinstance(err, str) else "Unknown error"
            raise RuntimeError(f"Moomoo order cancellation failed: {msg}")

    def modify_order(self, order_id: str, qty: float, price: float | None) -> None:
        ret, err = self._ctx.modify_order(
            ModifyOrderOp.NORMAL,
            order_id=order_id,
            qty=qty,
            price=price or 0.0,
            trd_env=self._trd_env,
            acc_id=self._acc_id,
        )
        if ret != RET_OK:
            msg = err if isinstance(err, str) else "Unknown error"
            raise RuntimeError(f"Moomoo order modification failed: {msg}")

    def sync_order(self, order_id: str) -> Dict[str, Any] | None:
        ret, data = self._ctx.order_list_query(
            order_id=order_id,
            trd_env=self._trd_env,
            acc_id=self._acc_id,
        )
        if ret != RET_OK:
            msg = data if isinstance(data, str) else "Unknown error"
            raise RuntimeError(f"Moomoo order sync failed: {msg}")
        if data.empty:
            return None
        row = data.iloc[0].to_dict()
        return self._format_order_response(
            row,
            fallback_ticker=self._strip_symbol(str(row.get("code", ""))),
            fallback_side=str(row.get("trd_side", "")),
            fallback_qty=float(row.get("qty") or 0.0),
            fallback_price=float(row.get("price") or 0.0),
        )
