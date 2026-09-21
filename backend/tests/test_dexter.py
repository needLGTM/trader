import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


# ── /dexter/query エンドポイント ──────────────────────────

class TestDexterQueryEndpoint:
    def test_empty_query_rejected(self):
        r = client.post("/dexter/query", json={"query": "   "})
        assert r.status_code == 422

    def test_missing_field_rejected(self):
        r = client.post("/dexter/query", json={})
        assert r.status_code == 422

    def test_dexter_dir_not_set_returns_500(self):
        """DEXTER_DIR が未設定なら 500 + エラー詳細を返す"""
        with patch("app.dexter_bridge.get_dexter_dir_from_env",
                   side_effect=RuntimeError("DEXTER_DIR is not set.")):
            r = client.post("/dexter/query", json={"query": "AAPLについて教えて"})
        assert r.status_code == 500
        assert "DEXTER_DIR" in r.json()["detail"]

    def test_success_returns_answer(self):
        """run_dexter_once が答えを返したら 200 で answer を含む"""
        expected = "AAPLは直近で上昇トレンド。押し目買いが有効。$AAPL BUY"
        with patch("app.dexter_bridge.get_dexter_dir_from_env", return_value=Path("/fake")), \
             patch("app.dexter_bridge.run_dexter_once", return_value=expected):
            r = client.post("/dexter/query", json={"query": "AAPLについて教えて"})
        assert r.status_code == 200
        assert r.json()["answer"] == expected

    def test_bun_not_installed_returns_500(self):
        """bun がなければ 500 でその旨を返す"""
        with patch("app.dexter_bridge.get_dexter_dir_from_env", return_value=Path("/fake")), \
             patch("app.dexter_bridge.run_dexter_once",
                   side_effect=RuntimeError("bun is not installed. Install Bun before running Dexter.")):
            r = client.post("/dexter/query", json={"query": "TSLAは？"})
        assert r.status_code == 500
        assert "bun" in r.json()["detail"]

    def test_dexter_execution_failed_returns_500(self):
        """Dexter の実行が失敗したら 500"""
        with patch("app.dexter_bridge.get_dexter_dir_from_env", return_value=Path("/fake")), \
             patch("app.dexter_bridge.run_dexter_once",
                   side_effect=RuntimeError("Dexter execution failed")):
            r = client.post("/dexter/query", json={"query": "NVDAは？"})
        assert r.status_code == 500


# ── get_dexter_dir_from_env 単体 ──────────────────────────

class TestGetDexterDirFromEnv:
    def test_raises_when_not_set(self):
        from app.dexter_bridge import get_dexter_dir_from_env
        env = {k: v for k, v in os.environ.items() if k != "DEXTER_DIR"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(RuntimeError, match="DEXTER_DIR is not set"):
                get_dexter_dir_from_env()

    def test_raises_when_dir_not_found(self, tmp_path):
        from app.dexter_bridge import get_dexter_dir_from_env
        nonexistent = str(tmp_path / "no_such_dir")
        with patch.dict(os.environ, {"DEXTER_DIR": nonexistent}):
            with pytest.raises(RuntimeError, match="not found"):
                get_dexter_dir_from_env()

    def test_returns_path_when_valid(self, tmp_path):
        from app.dexter_bridge import get_dexter_dir_from_env
        with patch.dict(os.environ, {"DEXTER_DIR": str(tmp_path)}):
            result = get_dexter_dir_from_env()
        assert result == tmp_path


class TestDailyPnlDeduplication:
    def test_duplicate_date_rows_are_merged(self):
        from app.models import PnL
        from app.state_sync import _dedupe_daily_pnl

        rows = [
            PnL(date="2024-01-01", realized=10.0, unrealized=0.0, broker_env="SIMULATE"),
            PnL(date="2024-01-01", realized=20.0, unrealized=5.0, broker_env="SIMULATE"),
            PnL(date="2024-01-02", realized=7.5, unrealized=1.5, broker_env="SIMULATE"),
        ]

        deduped = _dedupe_daily_pnl(rows)

        assert [row.date for row in deduped] == ["2024-01-01", "2024-01-02"]
        assert deduped[0].realized == 30.0
        assert deduped[0].unrealized == 5.0
        assert deduped[1].realized == 7.5


class TestDefaultOrderUsdByBrokerEnv:
    def test_uses_real_or_simulate_value_by_env(self):
        from api.main import _resolve_default_order_usd_for_env

        original = dict(__import__("api.main", fromlist=["_rt"])._rt)
        try:
            __import__("api.main", fromlist=["_rt"])._rt.clear()
            __import__("api.main", fromlist=["_rt"])._rt.update({
                "default_order_usd_real": 300.0,
                "default_order_usd_simulate": 120.0,
            })
            assert _resolve_default_order_usd_for_env("REAL") == 300.0
            assert _resolve_default_order_usd_for_env("SIMULATE") == 120.0
            assert _resolve_default_order_usd_for_env(None) == 120.0
        finally:
            __import__("api.main", fromlist=["_rt"])._rt.clear()
            __import__("api.main", fromlist=["_rt"])._rt.update(original)
