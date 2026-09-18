import { useCallback, useEffect, useState } from "react";
import { Alert, Badge, Button, Card, Group, Loader, Stack, Switch, Text, TextInput, Title } from "@mantine/core";
import { ShieldAlert, Play, RefreshCw } from "lucide-react";

const API = import.meta.env.VITE_API_BASE ?? "";

type Strategy = { id: string; name: string; description: string; enabled: boolean; symbols: string[] };
type Autopilot = { enabled: boolean; broker_env: string; allocation_method: string };
type Risk = { halted: boolean; daily_pnl: number; open_positions: number; max_open_positions: number; max_daily_loss: number };

export function AutopilotPage() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [autopilot, setAutopilot] = useState<Autopilot | null>(null);
  const [risk, setRisk] = useState<Risk | null>(null);
  const [busy, setBusy] = useState(false);
  const [haltText, setHaltText] = useState("");

  const load = useCallback(async () => {
    const [strategiesRes, autopilotRes, riskRes] = await Promise.all([fetch(`${API}/strategies`), fetch(`${API}/autopilot`), fetch(`${API}/risk/status`)]);
    if (strategiesRes.ok) setStrategies(await strategiesRes.json());
    if (autopilotRes.ok) setAutopilot(await autopilotRes.json());
    if (riskRes.ok) setRisk(await riskRes.json());
  }, []);
  useEffect(() => { void load(); }, [load]);

  const patch = async (body: object) => {
    setBusy(true);
    try {
      const response = await fetch(`${API}/autopilot`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!response.ok) throw new Error(await response.text());
      setAutopilot(await response.json());
      await load();
    } finally { setBusy(false); }
  };

  const run = async () => {
    setBusy(true);
    try { await fetch(`${API}/autopilot/run`, { method: "POST" }); await load(); }
    finally { setBusy(false); }
  };
  const halt = async () => {
    setBusy(true);
    try {
      await fetch(`${API}/risk/kill-switch`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirmation: haltText, flatten_positions: false }) });
      setHaltText("");
      await load();
    } finally { setBusy(false); }
  };

  if (!autopilot) return <Loader />;
  return <Stack gap="lg">
    <Group justify="space-between"><div><Title order={2}>Strategy Autopilot</Title><Text c="dimmed">戦略はリスク層を通過した場合だけ注文されます。</Text></div><Button leftSection={<RefreshCw size={16} />} variant="default" onClick={() => void load()}>更新</Button></Group>
    {risk?.halted && <Alert color="red" icon={<ShieldAlert />}>キルスイッチが有効です。自動取引は停止しています。</Alert>}
    <Group align="stretch" grow>
      <Card withBorder><Text size="sm" c="dimmed">運用モード</Text><Badge color={autopilot.broker_env === "REAL" ? "red" : "blue"} size="lg" mt="xs">{autopilot.broker_env}</Badge><Text size="xs" mt="sm">新規戦略は既定で SIMULATE。REAL はサーバー確認が必要です。</Text></Card>
      <Card withBorder><Text size="sm" c="dimmed">日次損益 / 上限</Text><Text fw={700}>{risk?.daily_pnl.toFixed(2) ?? "—"} / -{risk?.max_daily_loss ?? "—"}</Text></Card>
      <Card withBorder><Text size="sm" c="dimmed">保有ポジション</Text><Text fw={700}>{risk?.open_positions ?? "—"} / {risk?.max_open_positions ?? "—"}</Text></Card>
    </Group>
    <Card withBorder><Group justify="space-between"><div><Text fw={700}>Autopilot</Text><Text size="sm" c="dimmed">スケジューラーによる定期実行</Text></div><Switch checked={autopilot.enabled} disabled={busy || Boolean(risk?.halted)} onChange={(e) => void patch({ enabled: e.currentTarget.checked })} /></Group><Group mt="md"><Button leftSection={<Play size={16} />} onClick={() => void run()} loading={busy} disabled={!autopilot.enabled || Boolean(risk?.halted)}>今すぐ実行</Button></Group></Card>
    <Card withBorder bg="red.0"><Text fw={700} c="red">Kill switch</Text><Text size="sm" c="dimmed" mt={4}>保留注文を取り消し、新しい自動注文を停止します。ポジションの成行決済は API で明示指定した場合だけ実行されます。</Text><Group mt="sm" align="end"><TextInput label='確認のため「HALT TRADING」と入力' value={haltText} onChange={(e) => setHaltText(e.currentTarget.value)} /><Button color="red" leftSection={<ShieldAlert size={16} />} disabled={busy || haltText !== "HALT TRADING"} onClick={() => void halt()}>取引を停止</Button></Group></Card>
    <Stack>{strategies.map((strategy) => <Card withBorder key={strategy.id}><Group justify="space-between" align="start"><div><Text fw={700}>{strategy.name}</Text><Text size="sm" c="dimmed">{strategy.description}</Text></div><Switch checked={strategy.enabled} disabled={busy} onChange={(e) => void patch({ strategies: { [strategy.id]: e.currentTarget.checked } })} /></Group><TextInput mt="md" label="対象銘柄（カンマ区切り）" value={strategy.symbols.join(", ")} onBlur={(e) => { const symbols = e.currentTarget.value.split(",").map(s => s.trim().toUpperCase()).filter(Boolean); void patch({ symbols: { [strategy.id]: symbols } }); }} /></Card>)}</Stack>
  </Stack>;
}
