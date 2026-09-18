import "@mantine/core/styles.css";
import "./index.css";
import React from "react";
import ReactDOM from "react-dom/client";
import { MantineProvider, createTheme } from "@mantine/core";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Dashboard } from "./pages/Dashboard";
import { AppLayout } from "./pages/Layout";
import { SignalsPage } from "./pages/Signals";
import { PerformancePage } from "./pages/Performance";
import { BacktestPage } from "./pages/Backtest";
import { DexterPage } from "./pages/Dexter";
import { SettingsPage } from "./pages/Settings";
import { AutopilotPage } from "./pages/Autopilot";

const theme = createTheme({
  primaryColor: "blue",
  defaultRadius: "md",
  fontFamily: "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
  headings: { fontFamily: "'Inter', sans-serif", fontWeight: "600" },
  components: {
    Card: {
      defaultProps: { shadow: "sm", padding: "lg", radius: "md" },
    },
    Table: {
      defaultProps: { withTableBorder: true, withColumnBorders: false },
    },
  },
});

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <MantineProvider theme={theme}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/" element={<PerformancePage />} />
            <Route path="/signals" element={<SignalsPage />} />
            <Route path="/performance" element={<PerformancePage />} />

            <Route path="/backtest" element={<BacktestPage />} />
            <Route path="/autopilot" element={<AutopilotPage />} />
            <Route path="/dexter" element={<DexterPage />} />
            <Route path="/settings" element={<SettingsPage />} />

            {/* Legacy: old all-in-one tabs dashboard */}
            <Route path="/legacy" element={<Dashboard />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </MantineProvider>
  </React.StrictMode>,
);
