# trader

Twitter の投稿を LLM で解析し、moomoo 証券（OpenD）へ自動発注するシステム。
ペーパー取引用の `paper` ブローカーも内蔵しており、ローカルで完結した動作確認ができる。

---

## アーキテクチャ

```
Twitter（httpx + GraphQL）
        │  アラートツイートを検出
        ▼
twitter_worker（workers/twitter_poll.py）
        │  POST /signals  {text, source:"twitter", meta}
        │  LINE Push 通知（新規アラート）
        ▼
FastAPI（api/main.py）
        │  1. LLM でティッカー・売買方向・エントリー・SL/TP・信頼度を抽出
        │  2. 重複チェック（message_id / URL）
        │  3. Signal を PostgreSQL に保存
        │  4. AUTO_TRADE_ENABLED かつ信頼度 ≥ MIN_CONFIDENCE なら発注
        ▼
moomoo OpenD（Docker コンテナ）
        │  REAL / SIMULATE アカウントへ注文送信
        ▼
moomoo 証券

────── 状態同期（別経路）──────

sync_worker（workers/scheduler.py）
        │  POST /sync を定期実行
        ▼
FastAPI /sync → moomoo OpenD → PostgreSQL（orders / positions / pnl）
```

---

## 機能一覧

### シグナル取り込み

| ソース | Worker | 説明 |
|--------|--------|------|
| Twitter | `twitter_poll.py` | 指定アカウントのツイートを GraphQL で定期取得。アラートハッシュタグ（`#デイトレアラート` `#スイングアラート` `#オプションアラート`）または `$TICKER` を含む投稿を転送 |
| Dexter | `dexter_poll.py` | Dexter AI エージェントを定期実行し、シグナルを自動投入 |
| 手動 | — | `POST /signals` で任意のテキストを直接投入可能 |

### LLM 抽出

Groq（デフォルト）または Ollama で以下を JSON 抽出する：

- ティッカー・売買方向（BUY / SELL）
- 信頼度（0〜1）
- エントリー価格・逆指値・ターゲット（複数可）
- タイムフレーム・アラート種別

### 発注制御

- ソース別（Twitter / Dexter）に `AUTO_TRADE_ENABLED` と `BROKER_ENV`（REAL / SIMULATE）を設定
- `MIN_CONFIDENCE` を下回るシグナルは発注しない
- 発注数量は `DEFAULT_ORDER_USD / 直近株価` で自動計算

### フロントエンド（ポート 80）

| 画面 | 説明 |
|------|------|
| Performance | 損益・約定・ポジション一覧 |
| Signals | シグナル・注文・ポジション監視 |
| Backtest | 記録済みシグナルの yfinance 実データによるシミュレーション |
| Dexter | AI エージェントへの質問 |
| Settings | 取引環境・Twitter Cookie・Worker 状態管理 |

### LINE 通知

新規アラートツイートを検出すると LINE Push で通知する。
エントリー・逆指値・ターゲット情報も含む。

---

## クイックスタート

```bash
# .env.local を作成
cp backend/.env backend/.env.local
# 必要な値を記入（OPENAI_API_KEY など）

# ペーパー取引（OpenD 不要）
docker compose up -d

# moomoo（OpenD 込み）
docker compose --profile moomoo up -d
```

### 自動起動

通常の起動・停止：

```bash
docker compose --profile moomoo up -d
docker compose --profile moomoo stop
```

Dockerデーモン再起動後も各コンテナは `unless-stopped` で復帰します。ホスト起動時にもComposeを起動する場合：

Linuxでsystemdが動いている環境：

```bash
sudo cp trader-compose.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now trader-compose.service
```

状態確認：

```bash
docker compose ps
sudo systemctl status trader-compose.service
```

WSL（systemd未有効）の場合は `systemctl` を使わず、Docker Desktopの `Start Docker Desktop when you sign in` を有効にしてください。Docker Desktop起動後、`restart: unless-stopped` のコンテナは自動復帰します。手動起動・停止は以下です。

```bash
docker compose --profile moomoo up -d
docker compose --profile moomoo stop
```

詳細な設定は [backend/README.md](backend/README.md) を参照。

---

## データベース

PostgreSQL 16（`trader-postgres` コンテナ）。`docker compose up` で自動起動する。

接続情報（デフォルト）：
- Host: `postgres` (Docker 内) / `localhost:5432` (外部)
- DB: `trader` / User: `trader` / Password: `trader`
