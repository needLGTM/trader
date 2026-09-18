import React from "react";
import {
  AppShell,
  Box,
  Burger,
  Container,
  Group,
  NavLink,
  ScrollArea,
  Stack,
  Text,
  Title,
  Tooltip,
  UnstyledButton,
} from "@mantine/core";
import { Link, NavLink as RRNavLink, Outlet, useLocation } from "react-router-dom";
import { Activity, Bot, ChevronLeft, ChevronRight, FlaskConical, Settings, Sparkles, RadioTower } from "lucide-react";

const NAV_ITEMS = [
  { to: "/", label: "Performance", icon: <Activity size={18} /> },
  { to: "/signals", label: "Signals", icon: <Sparkles size={18} /> },
  { to: "/backtest", label: "Backtest", icon: <FlaskConical size={18} /> },
  { to: "/autopilot", label: "Autopilot", icon: <RadioTower size={18} /> },
  { to: "/dexter", label: "Dexter", icon: <Bot size={18} /> },
  { to: "/settings", label: "Settings", icon: <Settings size={18} /> },
];

function Sidebar({
  onNavigate,
  collapsed,
  onToggleCollapsed,
}: {
  onNavigate?: () => void;
  collapsed: boolean;
  onToggleCollapsed: () => void;
}) {
  const { pathname } = useLocation();

  return (
    <Stack gap="md" p={collapsed ? "sm" : "md"} h="100%">
      <Group justify={collapsed ? "center" : "space-between"} wrap="nowrap">
        <Box
          component={Link}
          to="/"
          style={{ textDecoration: "none", color: "inherit" }}
          onClick={onNavigate}
        >
          {collapsed ? (
            <Title order={4} fw={900} lh={1}>
              T
            </Title>
          ) : (
            <>
              <Title order={4} fw={800} lh={1.2}>
                Social Signal Trader
              </Title>
              <Text size="xs" c="dimmed" mt={2}>
                シグナル・バックテスト・運用モニタリング
              </Text>
            </>
          )}
        </Box>

        {/* desktop collapse toggle */}
        <Tooltip label={collapsed ? "Expand" : "Collapse"} position="right">
          <UnstyledButton
            onClick={onToggleCollapsed}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 28,
              height: 28,
              borderRadius: 8,
            }}
          >
            {collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
          </UnstyledButton>
        </Tooltip>
      </Group>

      <Stack gap={6}>
        {NAV_ITEMS.map((it) => {
          const active = pathname === it.to;
          return (
            <Tooltip key={it.to} label={it.label} position="right" disabled={!collapsed}>
              <NavLink
                component={RRNavLink}
                to={it.to}
                label={collapsed ? undefined : it.label}
                leftSection={it.icon}
                active={active}
                onClick={onNavigate}
                style={{
                  borderRadius: 10,
                  justifyContent: collapsed ? "center" : undefined,
                }}
              />
            </Tooltip>
          );
        })}
      </Stack>

    </Stack>
  );
}

export function AppLayout() {
  const [mobileOpened, setMobileOpened] = React.useState(false);
  const [collapsed, setCollapsed] = React.useState(false);

  const closeMobile = () => setMobileOpened(false);

  return (
    <AppShell
      header={{ height: 64 }}
      navbar={{
        width: collapsed ? 76 : 280,
        breakpoint: "sm",
        collapsed: { mobile: !mobileOpened },
      }}
      padding={0}
      styles={{
        main: {
          height: "calc(100dvh - 64px)",
          overflow: "hidden",
        },
        navbar: {
          height: "calc(100dvh - 64px)",
        },
      }}
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="sm">
            <Burger
              opened={mobileOpened}
              onClick={() => setMobileOpened((o) => !o)}
              hiddenFrom="sm"
              size="sm"
            />
            <Text fw={800}>Trader</Text>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar>
        <ScrollArea type="auto" h="100%">
          <Sidebar
            onNavigate={closeMobile}
            collapsed={collapsed}
            onToggleCollapsed={() => setCollapsed((c) => !c)}
          />
        </ScrollArea>
      </AppShell.Navbar>

      <AppShell.Main>
        <Box h="100%" style={{ overflow: "auto" }}>
          <Container size="xl" py="lg">
            <Outlet />
          </Container>
        </Box>
      </AppShell.Main>
    </AppShell>
  );
}
