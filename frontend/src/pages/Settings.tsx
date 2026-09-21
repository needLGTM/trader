import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Badge,
  Box,
  Button,
  Card,
  Divider,
  Group,
  Image,
  Loader,
  NumberInput,
  SegmentedControl,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { AlertTriangle, Check, Cookie, RefreshCw, Save, Twitter, X } from "lucide-react";

const API = "/api";

type TradingSettings = {
  broker: string;
  broker_env: string;
  twitter_broker_env: string;
  dexter_broker_env: string;
  twitter_acc_type: string;
  dexter_acc_type: string;
  auto_trade_enabled: boolean;
  twitter_polling_enabled: boolean;
  twitter_auto_trade_enabled: boolean;
  dexter_auto_trade_enabled: boolean;
  default_order_usd_real: number;
  default_order_usd_simulate: number;
};

type OpendStatus = {
  connected: boolean;
  verify_type: "captcha" | "sms" | null;
  captcha_pending: boolean;
  sms_pending: boolean;
  captcha_path: string | null;
};

type WorkerEntry = {
  last_seen: string | null;
  seconds_ago: number | null;
  alive: boolean;
  enabled: boolean;
};

type WorkersStatus = {
  twitter: WorkerEntry;
};

function EnvControl({
  label,
  sub,
  value,
  onChange,
  disabled,
}: {
  label: string;
  sub?: string;
  value: "REAL" | "SIMULATE";
  onChange: (v: "REAL" | "SIMULATE") => void;
  disabled?: boolean;
}) {
  return (
    <Group justify="space-between" align="center" wrap="nowrap">
      <Box>
        <Text size="sm" fw={600}>{label}</Text>
        {sub && <Text size="xs" c="dimmed">{sub}</Text>}
      </Box>
      <SegmentedControl
        size="xs"
        value={value}
        onChange={(v) => onChange(v as "REAL" | "SIMULATE")}
        disabled={disabled}
        data={[
          {
            value: "SIMULATE",
            label: <Text size="xs" fw={600}>SIMULATE</Text>,
          },
          {
            value: "REAL",
            label: (
              <Text size="xs" fw={700} c={value === "REAL" ? "orange" : undefined}>
                REAL
              </Text>
            ),
          },
        ]}
        styles={(theme) => ({
          root: { background: theme.colors.gray[1] },
          indicator: {
            background: value === "REAL" ? theme.colors.orange[1] : theme.white,
            border: value === "REAL" ? `1.5px solid ${theme.colors.orange[4]}` : undefined,
          },
        })}
      />
    </Group>
  );
}

function EnvAccControl({
  label,
  sub,
  brokerEnv,
  accType,
  onChange,
}: {
  label: string;
  sub?: string;
  brokerEnv: "REAL" | "SIMULATE";
  accType: string;
  onChange: (env: "REAL" | "SIMULATE", acc: "margin" | "cash") => void;
}) {
  const combined = brokerEnv === "SIMULATE" ? "SIMULATE" : accType === "cash" ? "REAL_CASH" : "REAL_MARGIN";
  const isReal = brokerEnv === "REAL";
  return (
    <Group justify="space-between" align="center" wrap="nowrap">
      <Box>
        <Text size="sm" fw={600}>{label}</Text>
        {sub && <Text size="xs" c="dimmed">{sub}</Text>}
      </Box>
      <SegmentedControl
        size="xs"
        value={combined}
        onChange={(v) => {
          if (v === "SIMULATE") onChange("SIMULATE", accType === "cash" ? "cash" : "margin");
          else if (v === "REAL_MARGIN") onChange("REAL", "margin");
          else onChange("REAL", "cash");
        }}
        data={[
          { value: "SIMULATE",    label: <Text size="xs" fw={600}>SIMULATE</Text> },
          { value: "REAL_MARGIN", label: <Text size="xs" fw={700} c={combined === "REAL_MARGIN" ? "orange" : undefined}>REAL 信用</Text> },
          { value: "REAL_CASH",   label: <Text size="xs" fw={700} c={combined === "REAL_CASH" ? "orange" : undefined}>REAL 現物</Text> },
        ]}
        styles={(theme) => ({
          root: { background: theme.colors.gray[1] },
          indicator: {
            background: isReal ? theme.colors.orange[1] : theme.white,
            border: isReal ? `1.5px solid ${theme.colors.orange[4]}` : undefined,
          },
        })}
      />
    </Group>
  );
}

function AutoTradeToggle({
  label,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <Group justify="space-between" align="center">
      <Text size="sm" fw={600}>{label}</Text>
      <Switch
        size="sm"
        checked={checked}
        onChange={(e) => onChange(e.currentTarget.checked)}
        disabled={disabled}
        color="teal"
        label={checked ? "ON" : "OFF"}
      />
    </Group>
  );
}

function VerifyForm({
  verifyType,
  onSubmit,
  submitting,
  message,
  captchaImg,
}: {
  verifyType: "captcha" | "sms";
  onSubmit: (code: string, type: "captcha" | "sms") => void;
  submitting: boolean;
  message: { ok: boolean; text: string } | null;
  captchaImg: string | null;
}) {
  const [code, setCode] = useState("");

  const handleSubmit = () => {
    if (!code.trim()) return;
    onSubmit(code.trim(), verifyType);
    setCode("");
  };

  return (
    <Stack gap="sm">
      <Alert color={verifyType === "sms" ? "blue" : "yellow"} variant="light">
        <Text size="sm" fw={600}>
          {verifyType === "sms" ? "SMS認証コードが必要です" : "キャプチャ認証が必要です"}
        </Text>
        <Text size="xs" mt={2}>
          {verifyType === "sms"
            ? "登録された電話番号にSMSが送信されました。届いたコードを入力してください。"
            : "画像のコードを入力して送信してください。時間切れで再起動した場合は新しい画像が自動表示されます。"}
        </Text>
      </Alert>
      {verifyType === "captcha" && captchaImg && (
        <Image src={captchaImg} alt="captcha" w={200} radius="sm" style={{ imageRendering: "pixelated" }} />
      )}
      <Group gap="sm" align="flex-end">
        <TextInput
          label={verifyType === "sms" ? "SMSコード" : "認証コード"}
          placeholder={verifyType === "sms" ? "例: 123456" : "例: AB12"}
          value={code}
          onChange={(e) => setCode(e.currentTarget.value)}
          onKeyDown={(e) => { if (e.key === "Enter") handleSubmit(); }}
          size="sm"
          style={{ flex: 1 }}
          autoFocus
        />
        <Button size="sm" onClick={handleSubmit} loading={submitting} disabled={!code.trim()}>
          送信
        </Button>
      </Group>
      {message && (
        <Text size="xs" c={message.ok ? "teal" : "red"}>{message.text}</Text>
      )}
    </Stack>
  );
}

function OpendCard() {
  const [status, setStatus] = useState<OpendStatus | null>(null);
  const [captchaImg, setCaptchaImg] = useState<string | null>(null);
  const [restarting, setRestarting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadStatus = async () => {
    try {
      const r = await fetch(`${API}/opend/status`);
      if (!r.ok) return;
      const s = (await r.json()) as OpendStatus;
      setStatus(s);
      if (s.captcha_pending) {
        const ir = await fetch(`${API}/opend/captcha-image`);
        if (ir.ok) {
          const newImg = ((await ir.json()) as { image: string }).image;
          setCaptchaImg((prev) => {
            if (prev !== newImg) setRestarting(false);
            return newImg;
          });
        }
      } else {
        setCaptchaImg(null);
        if (s.connected || !s.sms_pending) setRestarting(false);
      }
    } catch { /* silent */ }
  };

  const startPolling = (fast: boolean) => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(loadStatus, fast ? 3_000 : 15_000);
  };

  useEffect(() => {
    loadStatus();
    startPolling(false);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, []);

  useEffect(() => {
    const needFast = status?.captcha_pending || status?.sms_pending || restarting;
    startPolling(needFast ? true : false);
  }, [status?.captcha_pending, status?.sms_pending, restarting]);

  const submit = async (code: string, verifyType: "captcha" | "sms") => {
    setSubmitting(true);
    setMessage(null);
    try {
      const r = await fetch(`${API}/opend/submit-captcha`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, verify_type: verifyType }),
      });
      const data = await r.json();
      if (r.ok) {
        setMessage({ ok: true, text: "送信しました。結果を確認中…" });
        startPolling(true);
        setTimeout(loadStatus, 1500);
      } else if (typeof data.detail === "string" && data.detail.startsWith("restarting:")) {
        setRestarting(true);
        setMessage({ ok: false, text: "OpenDが再起動中です。しばらくお待ちください…" });
        startPolling(true);
      } else {
        setMessage({ ok: false, text: data.detail ?? "エラー" });
      }
    } catch (e) {
      setMessage({ ok: false, text: String(e) });
    } finally {
      setSubmitting(false);
    }
  };

  const verifyType = status?.verify_type ?? null;

  return (
    <Card withBorder>
      <Group justify="space-between" mb="sm">
        <Text fw={700}>Moomoo OpenD</Text>
        <Group gap="xs">
          {restarting ? (
            <Badge color="orange" variant="dot" size="sm">RESTARTING</Badge>
          ) : status ? (
            <Badge color={status.connected ? "teal" : "red"} variant="dot" size="sm">
              {status.connected ? "CONNECTED" : "DISCONNECTED"}
            </Badge>
          ) : (
            <Badge color="gray" variant="dot" size="sm">UNKNOWN</Badge>
          )}
          <Button variant="subtle" size="xs" leftSection={<RefreshCw size={12} />} onClick={loadStatus}>
            更新
          </Button>
        </Group>
      </Group>
      <Divider mb="md" />

      {restarting ? (
        <Stack gap="sm">
          <Alert color="orange" variant="light">
            <Text size="sm" fw={600}>OpenDが再起動中です</Text>
            <Text size="xs" mt={2}>認証コードの入力待ち画面が自動的に表示されます。</Text>
          </Alert>
          <Loader size="xs" />
        </Stack>
      ) : verifyType === "captcha" || verifyType === "sms" ? (
        <VerifyForm
          verifyType={verifyType}
          onSubmit={submit}
          submitting={submitting}
          message={message}
          captchaImg={captchaImg}
        />
      ) : (
        <Text size="sm" c={status?.connected ? "teal" : "dimmed"}>
          {status?.connected
            ? "OpenD は正常に接続されています。"
            : "OpenD が起動していません。docker compose --profile moomoo up -d opend で起動してください。"}
        </Text>
      )}
    </Card>
  );
}

type CookieStatus = {
  has_cookies: boolean;
  version: string | null;
  auth_token_preview: string | null;
};

function parseCookiePaste(raw: string): { auth_token: string; ct0: string } {
  let auth_token = "", ct0 = "";
  for (const p of raw.split(/;\s*/)) {
    const [k, ...v] = p.split("=");
    const key = k.trim(), val = v.join("=").trim();
    if (key === "auth_token") auth_token = val;
    if (key === "ct0") ct0 = val;
  }
  return { auth_token, ct0 };
}

function TwitterCookieCard() {
  const [status, setStatus] = useState<CookieStatus | null>(null);
  const [cookiePaste, setCookiePaste] = useState("");
  const [authToken, setAuthToken] = useState("");
  const [ct0, setCt0] = useState("");
  const [saving, setSaving] = useState(false);
  const [checking, setChecking] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);

  const parsed = useMemo(() => parseCookiePaste(cookiePaste), [cookiePaste]);
  useEffect(() => {
    if (parsed.auth_token) setAuthToken(parsed.auth_token);
    if (parsed.ct0) setCt0(parsed.ct0);
  }, [parsed.auth_token, parsed.ct0]);

  const fetchStatus = async () => {
    try {
      const r = await fetch(`${API}/settings/twitter-cookies`);
      if (r.ok) setStatus(await r.json());
    } catch {}
  };
  useEffect(() => { fetchStatus(); }, []);

  const save = async () => {
    setSaving(true);
    setNotice(null);
    try {
      if (!authToken.trim() || !ct0.trim()) {
        setNotice({ kind: "err", msg: "auth_token と ct0 を入力してください" });
        return;
      }
      const r = await fetch(`${API}/settings/twitter-cookies`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ auth_token: authToken.trim(), ct0: ct0.trim() }),
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) { setNotice({ kind: "err", msg: data.detail ?? "保存失敗" }); return; }
      setNotice(data.valid
        ? { kind: "ok", msg: `保存成功 ${data.version ? `(${data.version})` : ""}` }
        : { kind: "err", msg: `保存済み / 検証失敗: ${data.error ?? "不明"}` });
      await fetchStatus();
    } catch (e) {
      setNotice({ kind: "err", msg: String(e) });
    } finally {
      setSaving(false);
    }
  };

  const verify = async () => {
    setChecking(true);
    setNotice(null);
    try {
      const r = await fetch(`${API}/settings/twitter-cookies/verify`, { method: "POST" });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) { setNotice({ kind: "err", msg: data.detail ?? "エラー" }); return; }
      setNotice(data.valid
        ? { kind: "ok", msg: `接続成功${data.screen_name ? ` @${data.screen_name}` : ""}` }
        : { kind: "err", msg: `接続失敗: ${data.error ?? "不明"}` });
    } catch (e) {
      setNotice({ kind: "err", msg: String(e) });
    } finally {
      setChecking(false);
    }
  };

  return (
    <Card withBorder>
      <Group justify="space-between" mb="sm">
        <Group gap="sm">
          <Twitter size={18} />
          <Text fw={700}>Twitter Cookie</Text>
        </Group>
        {status && (
          <Badge color={status.has_cookies ? "teal" : "gray"} variant="light" size="sm" leftSection={<Cookie size={12} />}>
            {status.has_cookies ? `設定済み (${status.auth_token_preview ?? ""})` : "未設定"}
          </Badge>
        )}
      </Group>
      <Divider mb="md" />
      <Stack gap="sm">
        {notice && (
          <Alert
            color={notice.kind === "ok" ? "teal" : "red"}
            variant="light"
            withCloseButton
            onClose={() => setNotice(null)}
            icon={notice.kind === "ok" ? <Check size={14} /> : <X size={14} />}
          >
            <Text size="sm">{notice.msg}</Text>
          </Alert>
        )}
        <Textarea
          label="Cookie 貼り付け（自動解析）"
          placeholder="auth_token=xxxxx; ct0=yyyyy; …"
          value={cookiePaste}
          onChange={(e) => setCookiePaste(e.currentTarget.value)}
          minRows={2}
          autosize
        />
        <TextInput
          label="auth_token"
          value={authToken}
          onChange={(e) => setAuthToken(e.currentTarget.value)}
          placeholder="40文字の16進文字列"
          styles={{ input: { fontFamily: "monospace", fontSize: 12 } }}
        />
        <TextInput
          label="ct0"
          value={ct0}
          onChange={(e) => setCt0(e.currentTarget.value)}
          placeholder="ct0 の値"
          styles={{ input: { fontFamily: "monospace", fontSize: 12 } }}
        />
        <Group gap="sm">
          <Button size="xs" leftSection={<Save size={13} />} onClick={save} loading={saving}>
            保存 & テスト
          </Button>
          <Button size="xs" variant="light" leftSection={<RefreshCw size={13} />} onClick={verify} loading={checking}>
            疎通確認
          </Button>
        </Group>
        <Text size="xs" c="dimmed">
          x.com → DevTools → Application → Cookies → auth_token / ct0 をコピー
        </Text>
      </Stack>
    </Card>
  );
}

function WorkerStatusCard({
  workers,
  onToggle,
  pollingEnabled,
}: {
  workers: WorkersStatus | null;
  onToggle: (enabled: boolean) => void;
  pollingEnabled: boolean;
}) {
  const tw = workers?.twitter;

  const agoLabel = (sec: number | null | undefined) => {
    if (sec == null) return "不明";
    if (sec < 60) return `${sec}秒前`;
    return `${Math.floor(sec / 60)}分${sec % 60}秒前`;
  };

  return (
    <Card withBorder>
      <Text fw={700} mb="sm">Worker Status</Text>
      <Divider mb="md" />
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Group gap="sm" align="center">
          <Twitter size={18} />
          <Box>
            <Text size="sm" fw={600}>Twitter Polling</Text>
            <Text size="xs" c="dimmed">
              {tw ? (tw.alive ? `最終応答: ${agoLabel(tw.seconds_ago)}` : `最終応答: ${agoLabel(tw.seconds_ago)}`) : "読み込み中…"}
            </Text>
          </Box>
          {tw ? (
            <Badge color={tw.alive ? "teal" : "red"} variant="dot" size="sm">
              {tw.alive ? "ALIVE" : "DOWN"}
            </Badge>
          ) : (
            <Badge color="gray" variant="dot" size="sm">UNKNOWN</Badge>
          )}
        </Group>
        <Switch
          size="sm"
          checked={pollingEnabled}
          onChange={(e) => onToggle(e.currentTarget.checked)}
          label={pollingEnabled ? "ON" : "OFF"}
          color="teal"
        />
      </Group>
    </Card>
  );
}

export function SettingsPage() {
  const [settings, setSettings] = useState<TradingSettings | null>(null);
  const [workers, setWorkers] = useState<WorkersStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const workerTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/settings/trading`);
      if (r.ok) setSettings(await r.json());
    } finally {
      setLoading(false);
    }
  };

  const loadWorkers = async () => {
    try {
      const r = await fetch(`${API}/workers/status`);
      if (r.ok) setWorkers(await r.json());
    } catch { /* silent */ }
  };

  useEffect(() => {
    load();
    loadWorkers();
    workerTimerRef.current = setInterval(loadWorkers, 15_000);
    return () => { if (workerTimerRef.current) clearInterval(workerTimerRef.current); };
  }, []);

  const patch = async (update: Partial<TradingSettings>) => {
    if (!settings) return;
    setSaving(true);
    const optimistic = { ...settings, ...update };
    setSettings(optimistic);
    try {
      const r = await fetch(`${API}/settings/trading`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(update),
      });
      if (r.ok) setSettings(await r.json());
    } catch {
      load();
    } finally {
      setSaving(false);
    }
  };

  const anyReal =
    settings?.broker_env === "REAL" ||
    settings?.twitter_broker_env === "REAL" ||
    settings?.dexter_broker_env === "REAL";

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-end">
        <Box>
          <Title order={2}>Settings</Title>
          <Text c="dimmed" size="sm" mt={2}>取引環境・自動注文の設定</Text>
        </Box>
        {saving && <Loader size="xs" />}
      </Group>

      {anyReal && (
        <Alert icon={<AlertTriangle size={16} />} color="orange" variant="light">
          <Text size="sm" fw={600}>REAL口座が有効です</Text>
          <Text size="xs" mt={2}>実際の資金で取引されます。設定を十分に確認してください。</Text>
        </Alert>
      )}

      <OpendCard />

      <WorkerStatusCard
        workers={workers}
        onToggle={(enabled) => patch({ twitter_polling_enabled: enabled })}
        pollingEnabled={settings?.twitter_polling_enabled ?? true}
      />

      <TwitterCookieCard />

      {loading ? (
        <Loader size="sm" />
      ) : settings ? (
        <>
          {/* Broker Environment */}
          <Card withBorder>
            <Text fw={700} mb="sm">
              Broker Environment
              <Badge ml="sm" size="xs" color="gray" variant="outline">{settings.broker}</Badge>
            </Text>
            <Text size="xs" c="dimmed" mb="md">
              シグナルソースごとに注文先口座（REAL / SIMULATE）を設定します。<br />
              REAL は実口座、SIMULATE は紙トレードです。
            </Text>
            <Divider mb="md" />
            <Stack gap="md">
              <EnvControl
                label="Default"
                sub="手動 POST シグナルなどのデフォルト"
                value={settings.broker_env as "REAL" | "SIMULATE"}
                onChange={(v) => patch({ broker_env: v })}
              />
              <Divider />
              <EnvAccControl
                label="Twitter"
                sub="Twitter/X から取得したシグナル"
                brokerEnv={settings.twitter_broker_env as "REAL" | "SIMULATE"}
                accType={settings.twitter_acc_type || "margin"}
                onChange={(env, acc) => patch({ twitter_broker_env: env, twitter_acc_type: acc })}
              />
              <Divider />
              <EnvAccControl
                label="Dexter"
                sub="Dexter エージェントが生成したシグナル"
                brokerEnv={settings.dexter_broker_env as "REAL" | "SIMULATE"}
                accType={settings.dexter_acc_type || "margin"}
                onChange={(env, acc) => patch({ dexter_broker_env: env, dexter_acc_type: acc })}
              />
            </Stack>
          </Card>

          {/* Auto Trade */}
          <Card withBorder>
            <Text fw={700} mb="sm">Auto Trade</Text>
            <Text size="xs" c="dimmed" mb="md">
              信頼度が閾値を超えたシグナルを自動的に発注するかどうかの設定です。
            </Text>
            <Divider mb="md" />
            <Stack gap="md">
              <AutoTradeToggle
                label="Default"
                checked={settings.auto_trade_enabled}
                onChange={(v) => patch({ auto_trade_enabled: v })}
              />
              <Divider />
              <AutoTradeToggle
                label="Twitter (Auto Trade)"
                checked={settings.twitter_auto_trade_enabled}
                onChange={(v) => patch({ twitter_auto_trade_enabled: v })}
              />
              <Divider />
              <AutoTradeToggle
                label="Dexter"
                checked={settings.dexter_auto_trade_enabled}
                onChange={(v) => patch({ dexter_auto_trade_enabled: v })}
              />
              <Divider />
              <Stack gap="sm">
                <Text size="sm" fw={700}>売買金額（自動エントリー）</Text>
                <Group justify="space-between" align="center" wrap="nowrap">
                  <Box style={{ flex: 1 }}>
                    <Text size="sm" fw={600}>REAL</Text>
                    <Text size="xs" c="dimmed">実口座の1注文あたりドル金額</Text>
                  </Box>
                  <NumberInput
                    value={settings.default_order_usd_real}
                    onChange={(value) => patch({ default_order_usd_real: Number(value ?? 0) })}
                    min={1}
                    step={50}
                    suffix=" USD"
                    w={170}
                    styles={{ input: { fontSize: 16, fontWeight: 700 } }}
                  />
                </Group>
                <Group justify="space-between" align="center" wrap="nowrap">
                  <Box style={{ flex: 1 }}>
                    <Text size="sm" fw={600}>SIMULATE</Text>
                    <Text size="xs" c="dimmed">紙トレードの1注文あたりドル金額</Text>
                  </Box>
                  <NumberInput
                    value={settings.default_order_usd_simulate}
                    onChange={(value) => patch({ default_order_usd_simulate: Number(value ?? 0) })}
                    min={1}
                    step={50}
                    suffix=" USD"
                    w={170}
                    styles={{ input: { fontSize: 16, fontWeight: 700 } }}
                  />
                </Group>
              </Stack>
            </Stack>
          </Card>
        </>
      ) : (
        <Text c="dimmed" size="sm">設定の読み込みに失敗しました。</Text>
      )}
    </Stack>
  );
}
