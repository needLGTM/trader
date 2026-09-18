# backend 設定リファレンス

## 環境変数

シークレットは `backend/.env.local` に記載し、`backend/.env` はテンプレートとして保持する。

---

## LLM（シグナル抽出）

`LLM_PROVIDER` 環境変数で実装を切り替える。

### Groq（デフォルト推奨・無料枠あり）

```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=gsk_xxxx          # Groq API キー
OPENAI_API_BASE=https://api.groq.com/openai/v1
OPENAI_MODEL=llama-3.3-70b-versatile
```

### Ollama（ローカル）

```bash
ollama pull qwen3:14b && ollama serve
```

```bash
LLM_PROVIDER=ollama
OPENAI_API_BASE=http://127.0.0.1:11434/v1
OPENAI_API_KEY=ollama
OPENAI_MODEL=qwen3:14b
```

---

## Twitter ワーカー

```bash
TWITTER_USERS=snatchan_comm      # 監視アカウント（カンマ区切りで複数可）
POLL_INTERVAL_SEC=30
```

Cookie は Settings 画面から登録する（DevTools → Application → Cookies → x.com から `auth_token` / `ct0` を取得）。

GraphQL エンドポイント ID が変わった場合は環境変数で上書き：

```bash
TW_EP_USER_TWEETS=naBcZ4al-iTCFBYGOAMzBQ
TW_EP_USER_BY_SCREENNAME=sLVLhk0bGj3MVFEKTdax1w
TW_EP_USER_TWEETS_AND_REPLIES=Y9WM4Id6UcGFE5J9jIJFUA
```

### LINE 通知

```bash
LINE_CHANNEL_ACCESS_TOKEN=xxxx
LINE_USER_ID=Uxxxx
```

---

## Moomoo OpenD

日本の moomoo/FUTU JP アカウントは `MOOMOO_LOGIN_REGION=jp` が必要。

### 環境変数

```bash
BROKER=moomoo
BROKER_ENV=SIMULATE              # REAL にすると本番取引
TWITTER_BROKER_ENV=REAL
DEXTER_BROKER_ENV=SIMULATE
TWITTER_AUTO_TRADE_ENABLED=true
DEXTER_AUTO_TRADE_ENABLED=false
MARKET=US
MOOMOO_OPEND_HOST=opend          # Docker 内のサービス名
MOOMOO_OPEND_PORT=11111
MOOMOO_LOGIN_REGION=jp
MOOMOO_SECURITY_FIRM=auto
MOOMOO_PREFERRED_ACC_TYPE=auto
MOOMOO_TRADE_PASSWORD_MD5=<MD5>
MOOMOO_ACC_ID=<任意>
SYNC_INTERVAL_MINUTES=5
```

`backend/.env.local` に追加：

```bash
MOOMOO_LOGIN_ACCOUNT=your_account
MOOMOO_LOGIN_PASSWORD_MD5=your_md5
MOOMOO_LOGIN_REGION=jp
MOOMOO_TRADE_PASSWORD_MD5=your_trade_md5
MOOMOO_LANG=en
```

### 起動

```bash
docker compose --profile moomoo up -d
```

OpenD と backend は同一 Docker ネットワーク（`trader_net`）上に配置される。

### 接続テスト

```bash
./scripts/run_moomoo_connection_test.sh
```

### MD5 生成

```bash
./scripts/generate_md5.sh "your_password"
```

---

## Dexter（AI エージェント）

Dexter は別プロセスの調査エージェント（`/home/daiki/dexter` をマウント）。
**Anthropic API クレジットが必要**（console.anthropic.com で購入）。

```bash
DEXTER_DIR=/home/daiki/dexter
DEXTER_MODEL=claude-sonnet-4-6
ANTHROPIC_API_KEY=sk-ant-xxxx
DEXTER_POLL_INTERVAL_SEC=1800
DEXTER_AUTO_TRADE_ENABLED=false
DEXTER_BROKER_ENV=SIMULATE
```

手動でシグナル投入：

```bash
python scripts/run_dexter_signal.py "Find one US momentum trade for today"
```

---

## Paper ブローカー

`BROKER=paper` はローカル DB 上のシミュレーション。OpenD 不要。

```bash
BROKER=paper
BROKER_ENV=SIMULATE
```

---

## Strategy Autopilot（既定で停止・ペーパー取引）

SNSシグナルとは別に、保存済み `MarketBar` を対象として SMA モメンタム、RSI 平均回帰、20日ブレイクアウトを実行できる。戦略は注文を直接発行せず、必ずバックエンドのリスクチェックを通る。

```bash
STRATEGY_INTERVAL_MINUTES=60
STRATEGY_ORDER_USD=200
STRATEGY_INITIAL_EQUITY=10000
MAX_OPEN_POSITIONS=5
MAX_DAILY_LOSS=500
MAX_DRAWDOWN_PCT=10
```

`GET/PATCH /autopilot` で戦略と銘柄を設定し、`POST /autopilot/run` で一回実行する。初期値は `enabled: false`、`broker_env: SIMULATE`。

`POST /risk/kill-switch` は `confirmation: "HALT TRADING"` を必須とし、全注文を取り消して以降の自動戦略注文を停止する。`flatten_positions: true` は明示時だけ成行でポジションを閉じる。

自動戦略を REAL で有効にする場合も、UI/API の切替だけでは不可能で、サーバー上に `STRATEGY_LIVE_CONFIRMED=true` を設定する必要がある。まずは十分なバックテストとペーパー運用を行ってから設定すること。

---

## バックテスト

Signals 画面で記録されたシグナルを yfinance の実データでシミュレートできる。
5m / 15m / 1h / 1d のバーサイズを選択可能（直近 60 日以内は分足、それ以前は日足にフォールバック）。
