import React, { useEffect, useMemo, useState } from "react";
import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Card,
  Divider,
  Grid,
  Group,
  Loader,
  SegmentedControl,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { RefreshCw, Search, Telescope } from "lucide-react";

const API = "/api";

type SignalRow = {
  id: number;
  author: string;
  ticker: string;
  side: string;
  signal_type: string | null;
  confidence: number | null;
  alert_type: string | null;
  entry: number | null;
  stop: number | null;
  take: number | null;
  targets: string | null;
  timeframe: string | null;
  created_at: string;
};

type OrderRow = {
  id: number;
  broker: string;
  broker_env: string;
  signal_id: number | null;
  ticker: string;
  side: string;
  qty: number;
  price: number | null;
  status: string;
  reason: string | null;
  created_at: string;
};

type PositionRow = {
  id: number;
  ticker: string;
  qty: number;
  avg_price: number;
  acc_type: string;
};

function SideBadge({ side }: { side: string }) {
  const s = side.toLowerCase();
  const color = s.includes("buy") ? "teal" : s.includes("sell") ? "red" : s === "info" ? "violet" : "gray";
  return <Badge color={color} variant="light" size="sm">{side}</Badge>;
}

function SignalTypeBadge({ type }: { type: string | null }) {
  if (!type) return <Text size="xs" c="dimmed">—</Text>;
  const t = type.toUpperCase();
  const color = t === "ENTRY" ? "blue" : t === "EXIT" ? "grape" : "gray";
  const label = t === "ENTRY" ? "エントリー" : t === "EXIT" ? "エグジット" : type;
  return <Badge color={color} variant="filled" size="sm">{label}</Badge>;
}

function StatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase();
  const color = s === "filled" ? "teal" : s === "canceled" ? "gray" : s === "rejected" ? "red" : s === "skipped" ? "orange" : "blue";
  return <Badge color={color} variant="light" size="sm">{status}</Badge>;
}

function EnvBadge({ env }: { env: string }) {
  return (
    <Badge color={env === "REAL" ? "orange" : "gray"} variant="outline" size="xs">
      {env}
    </Badge>
  );
}

type ScreenerResult = Record<string, unknown>;

export function SignalsPage() {
  const [env, setEnv] = useState<"SIMULATE" | "REAL">("REAL");
  const [accType, setAccType] = useState<"ALL" | "MARGIN" | "CASH">("ALL");
  const [signals, setSignals] = useState<SignalRow[]>([]);
  const [orders, setOrders] = useState<OrderRow[]>([]);
  const [positions, setPositions] = useState<PositionRow[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<"ALL" | "ENTRY" | "EXIT">("ALL");

  // Screener state
  const [screenerTicker, setScreenerTicker] = useState("");
  const [screenerType, setScreenerType] = useState<"technical" | "derivative">("technical");
  const [screenerLoading, setScreenerLoading] = useState(false);
  const [screenerResults, setScreenerResults] = useState<ScreenerResult[] | null>(null);
  const [screenerError, setScreenerError] = useState<string | null>(null);

  const fetchAll = async (e = env, at = accType) => {
    setRefreshing(true);
    try {
      const accParam = at !== "ALL" ? `&acc_type=${at}` : "";
      const [sigRes, ordRes, posRes] = await Promise.all([
        fetch(`${API}/signals`),
        fetch(`${API}/orders?broker_env=${e}`),
        fetch(`${API}/positions?broker_env=${e}${accParam}`),
      ]);
      if (sigRes.ok) setSignals((await sigRes.json()) as SignalRow[]);
      if (ordRes.ok) setOrders((await ordRes.json()) as OrderRow[]);
      if (posRes.ok) setPositions((await posRes.json()) as PositionRow[]);
    } finally {
      setRefreshing(false);
    }
  };

  const handleEnvChange = (v: string) => {
    const next = v as "SIMULATE" | "REAL";
    setEnv(next);
    fetchAll(next, accType);
  };

  const handleAccTypeChange = (v: string) => {
    const next = v as "ALL" | "MARGIN" | "CASH";
    setAccType(next);
    fetchAll(env, next);
  };

  useEffect(() => { fetchAll(env, accType); }, []);

  const runScreener = async () => {
    const ticker = screenerTicker.trim().toUpperCase();
    if (!ticker) return;
    setScreenerLoading(true);
    setScreenerError(null);
    setScreenerResults(null);
    try {
      const res = await fetch(`/api/screener/unusual?ticker=${encodeURIComponent(ticker)}&type=${screenerType}`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        setScreenerError(err.detail ?? res.statusText);
        return;
      }
      const data = await res.json() as ScreenerResult[];
      setScreenerResults(data);
    } catch (e) {
      setScreenerError(String(e));
    } finally {
      setScreenerLoading(false);
    }
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return signals.filter((s) => {
      if (q && !s.ticker.toLowerCase().includes(q) && !s.author.toLowerCase().includes(q)) {
        return false;
      }
      if (typeFilter === "ALL") return true;
      const t = (s.signal_type ?? "").toUpperCase();
      return t === typeFilter;
    });
  }, [signals, query, typeFilter]);

  const ordersBySignal = useMemo(() => {
    const map = new Map<number, OrderRow>();
    for (const order of orders) {
      if (order.signal_id != null && !map.has(order.signal_id)) {
        map.set(order.signal_id, order);
      }
    }
    return map;
  }, [orders]);

  const entryCount = useMemo(
    () => signals.filter((s) => (s.signal_type ?? "").toUpperCase() === "ENTRY").length,
    [signals]
  );
  const exitCount = useMemo(
    () => signals.filter((s) => (s.signal_type ?? "").toUpperCase() === "EXIT").length,
    [signals]
  );

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-end">
        <Box>
          <Title order={2}>Signals</Title>
          <Text c="dimmed" size="sm" mt={2}>シグナル・注文・ポジションの監視</Text>
        </Box>
        <Group gap="sm">
          <SegmentedControl
            size="xs"
            value={env}
            onChange={handleEnvChange}
            data={[
              { value: "SIMULATE", label: "SIMULATE" },
              { value: "REAL", label: "REAL" },
            ]}
            color={env === "REAL" ? "orange" : "blue"}
          />
          <Tooltip label="再読み込み">
            <ActionIcon variant="subtle" size="lg" onClick={() => fetchAll(env)} loading={refreshing} aria-label="refresh">
              <RefreshCw size={18} />
            </ActionIcon>
          </Tooltip>
        </Group>
      </Group>

      {/* シグナル */}
      <Card withBorder>
        <Group justify="space-between" mb="sm">
          <Text fw={700}>Signals <Text span c="dimmed" size="sm">({filtered.length})</Text></Text>
          <Group gap="sm">
            <SegmentedControl
              size="xs"
              value={typeFilter}
              onChange={(v) => setTypeFilter(v as "ALL" | "ENTRY" | "EXIT")}
              data={[
                { value: "ALL", label: `ALL (${signals.length})` },
                { value: "ENTRY", label: `エントリー (${entryCount})` },
                { value: "EXIT", label: `エグジット (${exitCount})` },
              ]}
            />
            <TextInput
              size="xs"
              leftSection={<Search size={13} />}
              placeholder="ticker / author"
              value={query}
              onChange={(e) => setQuery(e.currentTarget.value)}
              style={{ width: 160 }}
            />
          </Group>
        </Group>
        <Divider mb="sm" />
        {filtered.length === 0 ? (
          <Text size="sm" c="dimmed">シグナルがありません。</Text>
        ) : (
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Time</Table.Th>
                <Table.Th>Alert</Table.Th>
                <Table.Th>Type</Table.Th>
                <Table.Th>Ticker</Table.Th>
                <Table.Th>Side</Table.Th>
                <Table.Th>Order status</Table.Th>
                <Table.Th>Reason</Table.Th>
                <Table.Th style={{ textAlign: "right" }}>Entry</Table.Th>
                <Table.Th style={{ textAlign: "right" }}>Stop</Table.Th>
                <Table.Th style={{ textAlign: "right" }}>Target</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {filtered.slice(0, 100).map((s) => (
                (() => {
                  const order = ordersBySignal.get(s.id);
                  return (
                  <Table.Tr key={s.id}>
                  <Table.Td style={{ whiteSpace: "nowrap", fontSize: 12 }}>
                    {new Date(s.created_at).toLocaleString("ja-JP")}
                  </Table.Td>
                  <Table.Td>
                    {s.alert_type ? (
                      <Badge size="sm" variant="light"
                        color={s.alert_type === "オプション" ? "violet" : s.alert_type === "スイング" ? "blue" : "orange"}>
                        {s.alert_type}
                      </Badge>
                    ) : <Text size="xs" c="dimmed">—</Text>}
                  </Table.Td>
                  <Table.Td><SignalTypeBadge type={s.signal_type} /></Table.Td>
                  <Table.Td>
                    <Group gap={4} wrap="nowrap">
                      <Text fw={700} size="sm">{s.ticker}</Text>
                    </Group>
                    {s.timeframe && <Text size="xs" c="dimmed">{s.timeframe}</Text>}
                  </Table.Td>
                  <Table.Td><SideBadge side={s.side} /></Table.Td>
                  <Table.Td>
                    {order ? <StatusBadge status={order.status} /> : <Text size="xs" c="dimmed">注文なし</Text>}
                  </Table.Td>
                  <Table.Td style={{ fontSize: 11, color: "var(--mantine-color-dimmed)", maxWidth: 180 }}>
                    {order?.reason ?? ""}
                  </Table.Td>
                  <Table.Td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums", fontSize: 13 }}>
                    {s.entry == null ? <Text size="xs" c="dimmed">—</Text> : <Text size="sm" fw={600}>${Number(s.entry).toFixed(2)}</Text>}
                  </Table.Td>
                  <Table.Td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums", fontSize: 13 }}>
                    {s.stop == null ? <Text size="xs" c="dimmed">—</Text> : <Text size="sm" c="red">${Number(s.stop).toFixed(2)}</Text>}
                  </Table.Td>
                  <Table.Td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums", fontSize: 13 }}>
                    {(() => {
                      const ts: number[] = s.targets ? JSON.parse(s.targets) : s.take != null ? [Number(s.take)] : [];
                      if (ts.length === 0) return <Text size="xs" c="dimmed">—</Text>;
                      return <Text size="sm" c="teal">{ts.map(t => `$${Number(t).toFixed(2)}`).join(" / ")}</Text>;
                    })()}
                  </Table.Td>
                  </Table.Tr>
                  );
                })()
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Card>

      <Grid>
        {/* 注文 */}
        <Grid.Col span={{ base: 12, md: 8 }}>
          <Card withBorder>
            <Group justify="space-between" mb="sm">
              <Text fw={700}>Orders <Text span c="dimmed" size="sm">({orders.length})</Text></Text>
              <Button variant="subtle" size="xs" leftSection={<RefreshCw size={13} />} onClick={fetchAll} loading={refreshing}>
                Refresh
              </Button>
            </Group>
            <Divider mb="sm" />
            {orders.length === 0 ? (
              <Text size="sm" c="dimmed">注文がありません。</Text>
            ) : (
              <Table striped highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Time</Table.Th>
                    <Table.Th>Ticker</Table.Th>
                    <Table.Th>Side</Table.Th>
                    <Table.Th style={{ textAlign: "right" }}>Qty</Table.Th>
                    <Table.Th>Status</Table.Th>
                    <Table.Th>Env</Table.Th>
                    <Table.Th>Reason</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {orders.slice(0, 100).map((o) => (
                    <Table.Tr key={o.id}>
                      <Table.Td style={{ whiteSpace: "nowrap", fontSize: 12 }}>
                        {new Date(o.created_at).toLocaleString("ja-JP")}
                      </Table.Td>
                      <Table.Td><Text fw={700} size="sm">{o.ticker}</Text></Table.Td>
                      <Table.Td><SideBadge side={o.side} /></Table.Td>
                      <Table.Td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums", fontSize: 13 }}>{o.qty}</Table.Td>
                      <Table.Td><StatusBadge status={o.status} /></Table.Td>
                      <Table.Td><EnvBadge env={o.broker_env} /></Table.Td>
                      <Table.Td style={{ fontSize: 11, color: "var(--mantine-color-dimmed)" }}>
                        {o.reason ?? ""}
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            )}
          </Card>
        </Grid.Col>

        {/* ポジション */}
        <Grid.Col span={{ base: 12, md: 4 }}>
          <Card withBorder h="100%">
            <Group justify="space-between" mb="sm">
              <Text fw={700}>
                Positions <Text span c="dimmed" size="sm">({positions.length})</Text>
              </Text>
              <SegmentedControl
                size="xs"
                value={accType}
                onChange={handleAccTypeChange}
                data={[
                  { value: "ALL", label: "ALL" },
                  { value: "MARGIN", label: "MARGIN" },
                  { value: "CASH", label: "CASH" },
                ]}
              />
            </Group>
            <Divider mb="sm" />
            {positions.length === 0 ? (
              <Text size="sm" c="dimmed">ポジションがありません。</Text>
            ) : (
              <Table striped highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Ticker</Table.Th>
                    <Table.Th style={{ textAlign: "right" }}>Qty</Table.Th>
                    <Table.Th style={{ textAlign: "right" }}>Avg</Table.Th>
                    {accType === "ALL" && <Table.Th>Type</Table.Th>}
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {positions.map((p) => (
                    <Table.Tr key={p.id}>
                      <Table.Td><Text fw={700} size="sm">{p.ticker}</Text></Table.Td>
                      <Table.Td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums", fontSize: 13 }}>
                        {p.qty > 0 ? `+${p.qty}` : p.qty}
                      </Table.Td>
                      <Table.Td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums", fontSize: 13 }}>
                        {p.avg_price.toFixed(2)}
                      </Table.Td>
                      {accType === "ALL" && (
                        <Table.Td>
                          <Badge size="xs" variant="outline" color={p.acc_type === "MARGIN" ? "blue" : "gray"}>
                            {p.acc_type}
                          </Badge>
                        </Table.Td>
                      )}
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            )}
          </Card>
        </Grid.Col>
      </Grid>

      {/* Stock Screener (Unusual Activity) */}
      <Card withBorder>
        <Group mb="sm" gap="sm">
          <Telescope size={16} />
          <Text fw={700}>Stock Screener</Text>
          <Text span c="dimmed" size="sm">moomoo 異動分析（銘柄指定）</Text>
        </Group>
        <Divider mb="sm" />
        <Group gap="sm" mb="md" wrap="nowrap">
          <TextInput
            placeholder="AAPL"
            value={screenerTicker}
            onChange={(e) => setScreenerTicker(e.currentTarget.value)}
            onKeyDown={(e) => e.key === "Enter" && runScreener()}
            style={{ width: 120 }}
            size="xs"
          />
          <SegmentedControl
            size="xs"
            value={screenerType}
            onChange={(v) => setScreenerType(v as "technical" | "derivative")}
            data={[
              { value: "technical", label: "テクニカル" },
              { value: "derivative", label: "デリバティブ" },
            ]}
          />
          <Button size="xs" onClick={runScreener} loading={screenerLoading} leftSection={<Search size={13} />}>
            検索
          </Button>
        </Group>

        {screenerLoading && <Loader size="sm" />}
        {screenerError && (
          <Alert color="red" title="エラー" mb="sm">{screenerError}</Alert>
        )}
        {screenerResults !== null && screenerResults.length === 0 && (
          <Text size="sm" c="dimmed">結果がありません（moomoo 接続・銘柄コードを確認してください）</Text>
        )}
        {screenerResults && screenerResults.length > 0 && (
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                {Object.keys(screenerResults[0]).slice(0, 8).map((col) => (
                  <Table.Th key={col} style={{ whiteSpace: "nowrap", fontSize: 12 }}>{col}</Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {screenerResults.map((row, i) => (
                <Table.Tr key={i}>
                  {Object.values(row).slice(0, 8).map((val, j) => (
                    <Table.Td key={j} style={{ fontSize: 12, whiteSpace: "nowrap" }}>
                      {String(val ?? "—")}
                    </Table.Td>
                  ))}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Card>
    </Stack>
  );
}
