/**
 * Task pane entry point.
 *
 * Office.onReady fires when the Office.js library is ready. We render the
 * React shell only after Office is initialized so any subsequent feature
 * code (chat against the open document, skills, playbook execution — all
 * descoped to M4 / community contribution per DE-287) has the Office
 * context available without a separate readiness check.
 */
import { createRoot } from "react-dom/client";
import { App } from "@/components/App";
import { theme } from "@/taskpane/theme";
import { MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { AuthProvider } from "@/auth/AuthContext";
import { store } from "@/store";
import { Provider } from "jotai";
import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";
import "@/taskpane/taskpane.css";

Office.onReady(() => {
  const container = document.getElementById("lq-taskpane-root");
  if (!container) {
    // Defensive: HTML shell guarantees this element exists. If it's missing
    // we want a visible failure surface rather than a silent no-op.
    throw new Error("lq-taskpane-root element missing from taskpane.html");
  }
  const root = createRoot(container);
  root.render(
    <MantineProvider theme={theme}>
      {/* Portal target for actions.showNotification() (src/actions.ts) —
          notifications.show() no-ops without this mounted once in the tree. */}
      <Notifications />
      <Provider store={store}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </Provider>
    </MantineProvider>
  );
});
