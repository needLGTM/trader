import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  ActionIcon,
  Badge,
  Box,
  Card,
  Divider,
  Grid,
  Group,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { RefreshCw, TrendingDown, TrendingUp } from "lucide-react";

const API = "/api";

type PnlRow = {
  id: number;
  date: string;
  realized: number;
  unrealized: number;
};

type ExecutionRow = {
  id: number;
  order_id: number;
  ticker: string;
  side: string;
  qty: number;
  price: number;
  executed_at: string;
  execution_type: string;
  matched_execution_ids: string | null;
  realized_pnl: number | null;
};

type PositionRow = {
  id: number;
  ticker: string;
  qty: number;
  avg_price: number;
  acc_type: string;
};

type SnapshotEntry = {
  last_price: number;
  prev_close: number;
  change_pct: number;
  volume: number;
};

function asFiniteNumber(value: unknown): number | null {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function PnlText({ value }: { value: number }) {
  const color = value > 0 ? "teal" : value < 0 ? "red" : undefined;
  return (
    <Text
      size="sm"
      c={color}
      fw={value !== 0 ? 600 : undefined}
      style={{ fontVariantNumeric: "tabular-nums" }}
    >
      {value >= 0 ? "+" : ""}
      {value.toFixed(2)}
    </Text>
  );
}

function SideBadge({ side }: { side: string }) {
  const s = side.toLowerCase();
  const color = s.includes("buy") ? "teal" : s.includes("sell") ? "red" : "gray";
  return <Badge color={color} variant="light" size="sm">{side}</Badge>;
}

function ExecutionTypeBadge({ type }: { type: string }) {
  const label = type === "EXIT" ? "EXIT" : type === "ENTRY_AND_EXIT" ? "ENTRY/EXIT" : "ENTRY";
  return <Badge color={type === "EXIT" ? "grape" : "blue"} variant="light" size="sm">{label}</Badge>;
}

function StatCard({
  label,
  value,
  sub,
  positive,
}: {
  label: string;
  value: string;
  sub?: string;
  positive?: boolean | null;
}) {
  const color = positive === true ? "teal" : positive === false ? "red" : "gray";
  const Icon = positive === true ? TrendingUp : positive === false ? TrendingDown : null;
  return (
    <Card withBorder>
      <Text size="xs" tt="uppercase" fw={700} c="dimmed" mb={6}>
        {label}
      </Text>
      <Group justify="space-between" align="flex-end">
        <Text
          fz={24}
          fw={800}
          c={positive === true ? "teal" : positive === false ? "red" : undefined}
          style={{ fontVariantNumeric: "tabular-nums" }}
        >
          {value}
        </Text>
        {Icon && (
          <Badge color={color} variant="light" p={6}>
            <Icon size={14} />
          </Badge>
        )}
      </Group>
      {sub && (
        <Text size="xs" c="dimmed" mt={4}>
          {sub}
        </Text>
      )}
    </Card>
  );
}

export function PerformancePage() {
  const [env, setEnv] = useState<"SIMULATE" | "REAL">(() => {
    const saved = localStorage.getItem("performance.env");
    return saved === "SIMULATE" || saved === "REAL" ? saved : "REAL";
  });
  const [accType, setAccType] = useState<"ALL" | "MARGIN" | "CASH">(() => {
    const saved = localStorage.getItem("performance.accType");
    return saved === "ALL" || saved === "MARGIN" || saved === "CASH" ? saved : "ALL";
  });
  const [pnl, setPnl] = useState<PnlRow[]>([]);
  const [executions, setExecutions] = useState<ExecutionRow[]>([]);
  const [positions, setPositions] = useState<PositionRow[]>([]);
  const [snapshot, setSnapshot] = useState<Record<string, SnapshotEntry>>({});
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const requestId = useRef(0);

  const fetchSnapshot = async (pos: PositionRow[], currentRequestId: number) => {
    if (pos.length === 0) {
      setSnapshot({});
      return;
    }
    const codes = [...new Set(pos.map((p) => p.ticker))].join(",");
    try {
      const res = await fetch(`${API}/market/snapshot?codes=${encodeURIComponent(codes)}`);
      if (res.ok && requestId.current === currentRequestId) {
        setSnapshot((await res.json()) as Record<string, SnapshotEntry>);
      }
    } catch {
      // snapshot is optional; silently ignore
    }
  };

  const fetchAll = async (e = env, at = accType) => {
    const currentRequestId = ++requestId.current;
    setRefreshing(true);
    setLoadError(null);
    try {
      const accParam = at !== "ALL" ? `&acc_type=${at}` : "";
      const [pnlRes, exRes, posRes] = await Promise.all([
        fetch(`${API}/pnl?broker_env=${e}`),
        fetch(`${API}/executions?broker_env=${e}`),
        fetch(`${API}/positions?broker_env=${e}${accParam}`),
      ]);
      if (requestId.current !== currentRequestId) return;
      if (!pnlRes.ok || !exRes.ok || !posRes.ok) {
        throw new Error(`データ取得に失敗しました (${[pnlRes, exRes, posRes].filter((r) => !r.ok).map((r) => r.status).join(", ")})`);
      }
      setPnl((await pnlRes.json()) as PnlRow[]);
      setExecutions((await exRes.json()) as ExecutionRow[]);
      if (requestId.current === currentRequestId) {
        const pos = (await posRes.json()) as PositionRow[];
        setPositions(pos);
        void fetchSnapshot(pos, currentRequestId);
      }
    } catch (error) {
      if (requestId.current === currentRequestId) {
        setLoadError(error instanceof Error ? error.message : "データ取得に失敗しました");
      }
    } finally {
      if (requestId.current === currentRequestId) setRefreshing(false);
    }
  };

  const handleEnvChange = (v: string) => {
    const next = v as "SIMULATE" | "REAL";
    localStorage.setItem("performance.env", next);
    setEnv(next);
    fetchAll(next, accType);
  };

  const handleAccTypeChange = (v: string) => {
    const next = v as "ALL" | "MARGIN" | "CASH";
    localStorage.setItem("performance.accType", next);
    setAccType(next);
    fetchAll(env, next);
  };

  useEffect(() => { fetchAll(env, accType); }, []);

  const liveUnrealized = useMemo(() => {
    return positions.reduce((sum, p) => {
      const snap = snapshot[p.ticker];
      if (!snap) return sum;
      return sum + (snap.last_price - p.avg_price) * p.qty;
    }, 0);
  }, [positions, snapshot]);

  const stats = useMemo(() => {
    const totalRealized = pnl.reduce((s, r) => s + r.realized, 0);
    const today = new Date().toISOString().slice(0, 10);
    const todayRow = pnl.find((r) => r.date === today);
    return { totalRealized, todayPnl: todayRow?.realized ?? null, tradeCount: executions.length };
  }, [pnl, executions]);

  const sortedPnl = useMemo(
    () => [...pnl].sort((a, b) => String(b.date ?? "").localeCompare(String(a.date ?? ""))),
    [pnl]
  );
  const sortedExec = useMemo(
    () => [...executions].sort((a, b) => String(b.executed_at ?? "").localeCompare(String(a.executed_at ?? ""))),
    [executions]
  );

  const hasSnapshot = Object.keys(snapshot).length > 0;

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-end">
        <Box>
          <Title order={2}>Performance</Title>
          <Text c="dimmed" size="sm" mt={2}>損益・約定履歴・ポジション</Text>
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

      {loadError && (
        <Card withBorder>
          <Text size="sm" c="red">{loadError}</Text>
        </Card>
      )}

      <SimpleGrid cols={{ base: 2, sm: 4 }} spacing="md">
        <StatCard
          label="Realized PnL"
          value={`${stats.totalRealized >= 0 ? "+" : ""}${stats.totalRealized.toFixed(2)}`}
          sub="全期間累積"
          positive={stats.totalRealized > 0 ? true : stats.totalRealized < 0 ? false : null}
        />
        <StatCard
          label="Today"
          value={stats.todayPnl == null ? "—" : `${stats.todayPnl >= 0 ? "+" : ""}${stats.todayPnl.toFixed(2)}`}
          sub="本日の実現損益"
          positive={stats.todayPnl == null ? null : stats.todayPnl > 0 ? true : stats.todayPnl < 0 ? false : null}
        />
        <StatCard
          label="Unrealized"
          value={hasSnapshot ? `${liveUnrealized >= 0 ? "+" : ""}${liveUnrealized.toFixed(2)}` : "—"}
          sub={hasSnapshot ? "リアルタイム含み損益" : "moomoo 接続時に表示"}
          positive={hasSnapshot ? (liveUnrealized > 0 ? true : liveUnrealized < 0 ? false : null) : null}
        />
        <StatCard
          label="Trades"
          value={String(stats.tradeCount)}
          sub="総約定件数"
        />
      </SimpleGrid>

      <Grid>
        <Grid.Col span={{ base: 12, md: 7 }}>
          <Card withBorder>
            <Text fw={700} mb="sm">
              Daily PnL <Text span c="dimmed" size="sm">({sortedPnl.length})</Text>
            </Text>
            <Divider mb="sm" />
            {sortedPnl.length === 0 ? (
              <Text size="sm" c="dimmed">PnL データがありません。</Text>
            ) : (
              <Table striped highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Date</Table.Th>
                    <Table.Th style={{ textAlign: "right" }}>Realized</Table.Th>
                    <Table.Th style={{ textAlign: "right" }}>Unrealized</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {sortedPnl.slice(0, 90).map((row) => {
                    const realized = asFiniteNumber(row.realized) ?? 0;
                    const unrealized = asFiniteNumber(row.unrealized) ?? 0;
                    return (
                    <Table.Tr key={row.id}>
                      <Table.Td style={{ fontSize: 13, fontVariantNumeric: "tabular-nums" }}>{row.date}</Table.Td>
                      <Table.Td style={{ textAlign: "right" }}><PnlText value={realized} /></Table.Td>
                      <Table.Td style={{ textAlign: "right" }}><PnlText value={unrealized} /></Table.Td>
                    </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </Table>
            )}
          </Card>
        </Grid.Col>

        <Grid.Col span={{ base: 12, md: 5 }}>
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
              <Text size="sm" c="dimmed">保有ポジションがありません。</Text>
            ) : (
              <Table striped highlightOnHover>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Ticker</Table.Th>
                    <Table.Th style={{ textAlign: "right" }}>Qty</Table.Th>
                    <Table.Th style={{ textAlign: "right" }}>Avg</Table.Th>
                    <Table.Th style={{ textAlign: "right" }}>Now</Table.Th>
                    <Table.Th style={{ textAlign: "right" }}>UnPnL</Table.Th>
                    {accType === "ALL" && <Table.Th>Type</Table.Th>}
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {positions.map((p) => {
                    const snap = snapshot[p.ticker];
                    const qty = asFiniteNumber(p.qty) ?? 0;
                    const avgPrice = asFiniteNumber(p.avg_price);
                    const lastPrice = snap ? asFiniteNumber(snap.last_price) : null;
                    const changePct = snap ? asFiniteNumber(snap.change_pct) : null;
                    const unrealized = lastPrice != null && avgPrice != null ? (lastPrice - avgPrice) * qty : null;
                    return (
                      <Table.Tr key={p.id}>
                        <Table.Td>
                          <Text fw={700} size="sm">{p.ticker}</Text>
                          {changePct != null && (
                            <Text size="xs" c={changePct >= 0 ? "teal" : "red"}>
                              {changePct >= 0 ? "+" : ""}{changePct.toFixed(2)}%
                            </Text>
                          )}
                        </Table.Td>
                        <Table.Td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums", fontSize: 13 }}>
                          <Text size="sm" c={qty > 0 ? "teal" : "red"} fw={600}>
                            {qty > 0 ? `+${qty}` : qty}
                          </Text>
                        </Table.Td>
                        <Table.Td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums", fontSize: 13 }}>
                          {avgPrice == null ? <Text size="xs" c="dimmed">—</Text> : avgPrice.toFixed(2)}
                        </Table.Td>
                        <Table.Td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums", fontSize: 13 }}>
                          {lastPrice == null ? <Text size="xs" c="dimmed">—</Text> : lastPrice.toFixed(2)}
                        </Table.Td>
                        <Table.Td style={{ textAlign: "right" }}>
                          {unrealized != null ? <PnlText value={unrealized} /> : <Text size="xs" c="dimmed">—</Text>}
                        </Table.Td>
                        {accType === "ALL" && (
                          <Table.Td>
                            <Badge size="xs" variant="outline" color={p.acc_type === "MARGIN" ? "blue" : "gray"}>
                              {p.acc_type}
                            </Badge>
                          </Table.Td>
                        )}
                      </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </Table>
            )}
          </Card>
        </Grid.Col>
      </Grid>

      <Card withBorder>
        <Text fw={700} mb="sm">
          Executions <Text span c="dimmed" size="sm">({sortedExec.length})</Text>
        </Text>
        <Divider mb="sm" />
        {sortedExec.length === 0 ? (
          <Text size="sm" c="dimmed">約定履歴がありません。</Text>
        ) : (
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Time</Table.Th>
                <Table.Th>Ticker</Table.Th>
                <Table.Th>Side</Table.Th>
                <Table.Th>Match</Table.Th>
                <Table.Th style={{ textAlign: "right" }}>Qty</Table.Th>
                <Table.Th style={{ textAlign: "right" }}>Price</Table.Th>
                <Table.Th style={{ textAlign: "right" }}>Realized</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {sortedExec.slice(0, 100).map((ex) => (
                <Table.Tr key={ex.id}>
                  <Table.Td style={{ whiteSpace: "nowrap", fontSize: 12 }}>
                    {new Date(ex.executed_at).toLocaleString("ja-JP")}
                  </Table.Td>
                  <Table.Td><Text fw={700} size="sm">{ex.ticker}</Text></Table.Td>
                  <Table.Td><SideBadge side={ex.side} /></Table.Td>
                  <Table.Td>
                    <ExecutionTypeBadge type={ex.execution_type ?? "ENTRY"} />
                    {ex.matched_execution_ids && (
                      <Text size="xs" c="dimmed">← #{JSON.parse(ex.matched_execution_ids).join(", #")}</Text>
                    )}
                  </Table.Td>
                  <Table.Td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums", fontSize: 13 }}>{ex.qty}</Table.Td>
                  <Table.Td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums", fontSize: 13 }}>
                    {ex.price.toFixed(2)}
                  </Table.Td>
                  <Table.Td style={{ textAlign: "right" }}>
                    {ex.realized_pnl == null ? <Text size="xs" c="dimmed">—</Text> : <PnlText value={ex.realized_pnl} />}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Card>
    </Stack>
  );
}
