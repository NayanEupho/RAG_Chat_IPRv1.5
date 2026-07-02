"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { adminApi, adminApiBaseUrl, adminEventsUrl, type AdminHealth } from "@/lib/api";
import { clearAdminSession, readAdminSession, saveAdminSession, type AdminSession } from "@/lib/auth";
import { formatDate } from "@/lib/format";
import { invalidateAdminData, prefetchAdminData, setAdminDataCache, useAdminData } from "./use-admin-data";
import { useAdminEvents } from "./use-admin-events";
import { RefreshIconButton } from "./refresh-icon-button";
import type { NotificationItem } from "@/lib/types";

const navItems = [
  { href: "/", label: "Overview", icon: "01" },
  { href: "/ingestion", label: "Ingestion", icon: "02" },
  { href: "/monitoring", label: "Monitoring", icon: "03" },
  { href: "/review", label: "Review", icon: "04" },
  { href: "/warehouse", label: "Document Warehouse", icon: "05" },
  { href: "/chunks", label: "Chunk Viewer", icon: "06" },
  { href: "/vector-stats", label: "Vector Stats", icon: "07" },
  { href: "/control-center", label: "Control Center", icon: "08" },
  { href: "/past-jobs", label: "Past Jobs", icon: "09" },
  { href: "/errors", label: "Error Logs", icon: "10" },
  { href: "/help", label: "Help & Contact", icon: "11" },
  { href: "/about", label: "About", icon: "12" }
];

function alertTone(notification: NotificationItem): "success" | "danger" | "info" {
  const text = `${notification.type} ${notification.title} ${notification.message}`.toLowerCase();
  if (text.includes("error") || text.includes("failed")) return "danger";
  if (text.includes("indexed") || text.includes("complete") || text.includes("success")) return "success";
  return "info";
}

function alertLabel(notification: NotificationItem): string {
  const tone = alertTone(notification);
  if (tone === "danger") return "Ingestion error";
  if (tone === "success") return "Ingestion completed";
  return "Ingestion initiated";
}

function connectionLabel(status: ReturnType<typeof useAdminEvents>["status"]): string {
  if (status === "live") return "Live";
  if (status === "down") return "Down";
  if (status === "connecting") return "Connecting";
  return "Reconnecting";
}

function BellIcon() {
  return (
    <svg aria-hidden="true" className="bell-icon" viewBox="0 0 24 24">
      <path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9" />
      <path d="M13.7 21a2 2 0 0 1-3.4 0" />
    </svg>
  );
}

function EyeIcon({ open }: { open: boolean }) {
  return (
    <svg aria-hidden="true" className="eye-icon" viewBox="0 0 24 24">
      <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z" />
      {open ? <circle cx="12" cy="12" r="3" /> : <path d="M4 4l16 16" />}
    </svg>
  );
}

type BackendGateState = {
  status: "checking" | "ready" | "failed";
  attempt: number;
  error: string | null;
  lastCheckedAt: string | null;
  latencyMs: number | null;
  health: AdminHealth | null;
};

function errorMessage(caught: unknown): string {
  if (caught instanceof DOMException && caught.name === "AbortError") {
    return "Health check timed out before the backend replied.";
  }
  if (caught instanceof TypeError && String(caught.message).toLowerCase().includes("fetch")) {
    return "Browser could not reach the backend API. Confirm the backend server is running and CORS is allowed.";
  }
  return caught instanceof Error ? caught.message : "Backend health check failed.";
}

function useBackendGate() {
  const [retryNonce, setRetryNonce] = useState(0);
  const [state, setState] = useState<BackendGateState>({
    status: "checking",
    attempt: 1,
    error: null,
    lastCheckedAt: null,
    latencyMs: null,
    health: null
  });

  useEffect(() => {
    let cancelled = false;
    let retryTimer: number | null = null;

    async function probe(attempt: number) {
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 2500);
      const started = performance.now();
      setState((current) => ({
        ...current,
        status: current.status === "ready" ? "ready" : "checking",
        attempt,
        error: null
      }));

      try {
        const health = await adminApi.health(controller.signal);
        window.clearTimeout(timeout);
        if (cancelled) return;
        const latencyMs = Math.round(performance.now() - started);
        if (!health.healthy) {
          throw new Error(health.error || `Backend replied, but admin database status is ${health.database}.`);
        }
        setState({
          status: "ready",
          attempt,
          error: null,
          lastCheckedAt: health.checked_at || new Date().toISOString(),
          latencyMs: health.latency_ms ?? latencyMs,
          health
        });
      } catch (caught) {
        window.clearTimeout(timeout);
        if (cancelled) return;
        const nextDelay = Math.min(5000, 700 * 2 ** Math.min(attempt - 1, 3));
        setState({
          status: "failed",
          attempt,
          error: errorMessage(caught),
          lastCheckedAt: new Date().toISOString(),
          latencyMs: Math.round(performance.now() - started),
          health: null
        });
        retryTimer = window.setTimeout(() => probe(attempt + 1), nextDelay);
      }
    }

    void probe(1);
    return () => {
      cancelled = true;
      if (retryTimer !== null) window.clearTimeout(retryTimer);
    };
  }, [retryNonce]);

  return {
    ...state,
    retry: () => setRetryNonce((current) => current + 1)
  };
}

function StatusDot({ state }: { state: "ready" | "checking" | "failed" }) {
  return <span className={`gate-dot ${state}`} aria-hidden="true" />;
}

function invalidationKeysForEvent(type: string): string[] {
  switch (type) {
    case "warehouse_update":
      return ["indexedDocuments", "stats", "vectorStatsDetail", "chunks:*"];
    case "stats_update":
      return ["stats", "vectorStatsDetail"];
    case "document_update":
      return ["documents", "reviewPending", "batchesWithDocuments", "terminalBatchesWithDocuments", "document:*", "chunks:*"];
    case "review_update":
      return ["documents", "reviewPending", "batchesWithDocuments", "terminalBatchesWithDocuments", "document:*", "notifications"];
    case "batch_progress":
      return ["batches", "batchesWithDocuments", "terminalBatchesWithDocuments", "draftBatches", "stats"];
    case "job_update":
      return ["batchesWithDocuments", "logs"];
    case "job_error":
      return ["logs", "notifications", "batchesWithDocuments", "terminalBatchesWithDocuments"];
    case "notification":
    case "notification_update":
      return ["notifications"];
    default:
      return [];
  }
}

function prefetchDataForRoute(href: string) {
  const loaders: Record<string, Array<[string, () => Promise<unknown>]>> = {
    "/": [
      ["stats", () => adminApi.stats()],
      ["batches", () => adminApi.batches()],
      ["indexedDocuments", () => adminApi.indexedDocuments()],
      ["reviewPending", () => adminApi.documents("&status=REVIEW_PENDING")],
      ["logs", () => adminApi.logs("&level=ERROR")],
      ["runtimeConfig", () => adminApi.runtimeConfig()]
    ],
    "/ingestion": [
      ["batchesWithDocuments", () => adminApi.batches("&include_documents=true")],
      ["runtimeConfig", () => adminApi.runtimeConfig()]
    ],
    "/monitoring": [["batchesWithDocuments", () => adminApi.batches("&include_documents=true")]],
    "/review": [["documents", () => adminApi.documents()]],
    "/warehouse": [["indexedDocuments", () => adminApi.indexedDocuments()]],
    "/chunks": [["indexedDocuments", () => adminApi.indexedDocuments()]],
    "/vector-stats": [
      ["vectorStatsDetail", () => adminApi.vectorStatsDetail()],
      ["indexedDocuments", () => adminApi.indexedDocuments()]
    ],
    "/control-center": [["indexedDocuments", () => adminApi.indexedDocuments()]],
    "/past-jobs": [["terminalBatchesWithDocuments", () => adminApi.batches("&status=COMPLETE,PARTIALLY_COMPLETE,FAILED,CANCELLED&include_documents=true")]],
    "/errors": [["logs", () => adminApi.logs("&level=ERROR")]]
  };
  void Promise.allSettled((loaders[href] || []).map(([key, loader]) => prefetchAdminData(key, loader)));
}

function ConnectionGate({
  gate,
  events,
  adminEmail,
  onLogout
}: {
  gate: ReturnType<typeof useBackendGate>;
  events: ReturnType<typeof useAdminEvents>;
  adminEmail?: string | null;
  onLogout?: () => void;
}) {
  const httpReady = gate.status === "ready";
  const streamReady = events.status === "live";
  const title = !httpReady
    ? "Connecting to Admin Backend"
    : !streamReady
      ? "Opening Live Event Stream"
      : "Preparing Dashboard";
  const error = gate.error || (httpReady && events.status !== "connecting" && !streamReady ? events.lastError : null);

  return (
    <main className="connection-gate" aria-busy={!httpReady || !streamReady}>
      <section className="connection-gate-card">
        <div className="gate-header">
          <div className="gate-brand">
            <span className="brand-mark">IPR</span>
            <div>
              <strong>RAG Admin</strong>
              <span>{adminEmail || "Connection verification"}</span>
            </div>
          </div>
          {onLogout ? <button className="button" type="button" onClick={onLogout}>Logout</button> : null}
        </div>
        <div className="gate-orbit" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <h1>{title}</h1>
        <p>
          The dashboard is locked until the admin API and live event stream are verified. This prevents stale page data
          and blocks ingestion, review, delete, and navigation actions before the backend is ready.
        </p>
        <div className="gate-steps">
          <div className="gate-step">
            <StatusDot state={httpReady ? "ready" : gate.status === "failed" ? "failed" : "checking"} />
            <span>
              <strong>Admin API</strong>
              <small>{httpReady ? `Ready${gate.latencyMs != null ? ` in ${gate.latencyMs}ms` : ""}` : gate.status === "failed" ? "Retrying automatically" : "Checking /health"}</small>
            </span>
          </div>
          <div className="gate-step">
            <StatusDot state={streamReady ? "ready" : events.status === "down" ? "failed" : "checking"} />
            <span>
              <strong>Live updates</strong>
              <small>{streamReady ? "Event stream connected" : httpReady ? connectionLabel(events.status) : "Waiting for API check"}</small>
            </span>
          </div>
        </div>
        {error ? (
          <div className="gate-debug">
            <strong>Connection details</strong>
            <dl>
              <div><dt>API base</dt><dd>{adminApiBaseUrl()}</dd></div>
              <div><dt>Health endpoint</dt><dd>{adminApiBaseUrl()}/health</dd></div>
              <div><dt>Events endpoint</dt><dd>{adminEventsUrl()}</dd></div>
              <div><dt>Attempt</dt><dd>{gate.attempt}</dd></div>
              <div><dt>Last checked</dt><dd>{gate.lastCheckedAt ? formatDate(gate.lastCheckedAt) : "Not available"}</dd></div>
              <div><dt>Error</dt><dd>{error}</dd></div>
            </dl>
          </div>
        ) : null}
        <div className="gate-actions">
          <button className="button" type="button" onClick={gate.retry}>Retry now</button>
        </div>
      </section>
    </main>
  );
}
function LoginScreen({ onLogin }: { onLogin: (session: AdminSession) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const result = await adminApi.login({ email, password });
      if (!result.authenticated) throw new Error("Invalid admin email or password");
      onLogin(saveAdminSession(result.email));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Login failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-screen">
      <section className="login-panel">
        <div className="gate-brand">
          <span className="brand-mark">IPR</span>
          <div>
            <strong>RAG Admin</strong>
            <span>Ingestion dashboard</span>
          </div>
        </div>
        <div>
          <h1>Admin Login</h1>
          <p>Use the admin email and password configured on this machine.</p>
        </div>
        <form className="login-form" onSubmit={submit}>
          <div className="field">
            <label htmlFor="admin-email">Email</label>
            <input
              id="admin-email"
              autoComplete="email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="admin@example.com"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="admin-password">Password</label>
            <div className="password-field">
              <input
                id="admin-password"
                autoComplete="current-password"
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Enter password"
                required
              />
              <button
                className="password-toggle"
                type="button"
                onClick={() => setShowPassword((current) => !current)}
                aria-label={showPassword ? "Hide password" : "Show password"}
                title={showPassword ? "Hide password" : "Show password"}
              >
                <EyeIcon open={showPassword} />
              </button>
            </div>
          </div>
          {error ? <div className="login-error">{error}</div> : null}
          <button className="button primary" type="submit" disabled={submitting || !email.trim() || !password}>
            {submitting ? "Checking" : "Login"}
          </button>
        </form>
      </section>
    </main>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const gate = useBackendGate();
  const [session, setSession] = useState<AdminSession>({ email: null, isAuthenticated: false, isLoading: true });
  const [navigatingTo, setNavigatingTo] = useState<string | null>(null);
  const [alertsOpen, setAlertsOpen] = useState(false);
  const [alertRefreshing, setAlertRefreshing] = useState(false);
  const [alertRefreshMessage, setAlertRefreshMessage] = useState<string | null>(null);
  const [newAlertIds, setNewAlertIds] = useState<Set<string>>(new Set());
  const notificationsRef = useRef<{ refresh: () => Promise<void> } | null>(null);
  useEffect(() => {
    setSession(readAdminSession());
  }, []);

  const events = useAdminEvents((event) => {
    if (event.type === "notification" || event.type === "job_error" || event.type === "notification_update" || event.type === "review_update") {
      void notificationsRef.current?.refresh();
    }
    const keys = invalidationKeysForEvent(event.type);
    if (keys.length) invalidateAdminData(keys);
  }, gate.status === "ready" && session.isAuthenticated);
  const backendReady = session.isAuthenticated && gate.status === "ready" && events.status === "live";
  const notifications = useAdminData(() => adminApi.notifications(), 0, "notifications", backendReady);
  const unread = notifications.data?.unread_count || 0;
  const alerts = notifications.data?.items || [];
  const pendingReview = useAdminData(() => adminApi.documents("&status=REVIEW_PENDING"), 0, "reviewPending", backendReady);
  const pendingReviewCount = pendingReview.data?.total || 0;

  useEffect(() => {
    notificationsRef.current = notifications;
  }, [notifications]);

  useEffect(() => {
    if (!backendReady) return;
    navItems.forEach((item) => router.prefetch(item.href));
  }, [backendReady, router]);

  useEffect(() => {
    setNavigatingTo(null);
  }, [pathname]);

  async function openAlert(notification: NotificationItem) {
    if (!notification.read) {
      await adminApi.markNotificationRead(notification.notification_id);
      await notifications.refresh();
    }
    if (notification.batch_id) {
      router.push(`/monitoring?batchId=${encodeURIComponent(notification.batch_id)}`);
      setAlertsOpen(false);
    } else if (alertTone(notification) === "danger") {
      router.push("/errors");
      setAlertsOpen(false);
    }
  }

  async function clearAlert(notificationId: string) {
    await adminApi.deleteNotification(notificationId);
    setNewAlertIds((current) => {
      const next = new Set(current);
      next.delete(notificationId);
      return next;
    });
    await notifications.refresh();
  }

  async function clearAllAlerts() {
    await Promise.all(alerts.map((alert) => adminApi.deleteNotification(alert.notification_id)));
    setNewAlertIds(new Set());
    await notifications.refresh();
  }

  async function refreshAlerts() {
    setAlertRefreshing(true);
    setAlertRefreshMessage(null);
    try {
      const previousIds = new Set(alerts.map((alert) => alert.notification_id));
      const next = await adminApi.notifications();
      const addedIds = next.items
        .filter((alert) => !previousIds.has(alert.notification_id))
        .map((alert) => alert.notification_id);
      setAdminDataCache("notifications", next);
      if (addedIds.length > 0) {
        setNewAlertIds((current) => new Set([...current, ...addedIds]));
        setAlertRefreshMessage(`${addedIds.length} new notification${addedIds.length === 1 ? "" : "s"}`);
        window.setTimeout(() => {
          setNewAlertIds((current) => {
            const updated = new Set(current);
            addedIds.forEach((id) => updated.delete(id));
            return updated;
          });
        }, 5200);
      } else {
        setAlertRefreshMessage("Nothing new");
      }
    } catch (caught) {
      setAlertRefreshMessage(caught instanceof Error ? `Refresh failed: ${caught.message}` : "Refresh failed");
    } finally {
      setAlertRefreshing(false);
      window.setTimeout(() => setAlertRefreshMessage(null), 2600);
    }
  }

  async function toggleAlerts() {
    const nextOpen = !alertsOpen;
    setAlertsOpen(nextOpen);
    if (!nextOpen) {
      setNewAlertIds(new Set());
      setAlertRefreshMessage(null);
      return;
    }
    if (nextOpen) {
      await notifications.refresh();
      if (unread > 0) {
        await adminApi.markAllNotificationsRead();
        await notifications.refresh();
      }
    }
  }

  if (session.isLoading) {
    return (
      <main className="connection-gate" aria-busy="true">
        <section className="connection-gate-card">
          <div className="gate-orbit" aria-hidden="true"><span /><span /><span /></div>
          <h1>Preparing Admin Login</h1>
          <p>Checking the local dashboard login state.</p>
        </section>
      </main>
    );
  }

  if (!session.isAuthenticated) {
    return <LoginScreen onLogin={setSession} />;
  }

  if (!backendReady) {
    return <ConnectionGate gate={gate} events={events} adminEmail={session.email} onLogout={() => setSession(clearAdminSession())} />;
  }

  return (
    <div className="app-shell">
      {navigatingTo ? <div className="route-progress" aria-label="Loading page" /> : null}
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">IPR</span>
          <div>
            <strong>RAG Admin</strong>
            <small>Ingestion dashboard</small>
          </div>
        </div>
        <nav className="nav-list" aria-label="Primary navigation">
          {navItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              prefetch
              onPointerDown={() => {
                router.prefetch(item.href);
                prefetchDataForRoute(item.href);
              }}
              onMouseEnter={() => {
                router.prefetch(item.href);
                prefetchDataForRoute(item.href);
              }}
              onFocus={() => {
                router.prefetch(item.href);
                prefetchDataForRoute(item.href);
              }}
              onClick={() => {
                if (pathname !== item.href) setNavigatingTo(item.href);
              }}
              className={pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href)) ? "active" : ""}
            >
              <span className="nav-index">{item.icon}</span>
              <span>{item.label}</span>
              {item.href === "/review" && pendingReviewCount > 0 ? <span className="nav-count">{pendingReviewCount}</span> : null}
            </Link>
          ))}
        </nav>
      </aside>
      <main className="main">
        <header className="topbar">
          <div>
            <div className="topbar-title">
              <strong>Admin Dashboard</strong>
              <span className={`connection ${events.status}`}>{connectionLabel(events.status)}</span>
            </div>
            <span>SQLite workflow state - Chroma vector store</span>
            {events.status !== "live" ? (
              <div className={`connection-detail ${events.status === "down" ? "danger" : "warning"}`}>
                {events.lastError || "Waiting for backend event stream."}
                {events.disconnectedSince ? ` Disconnected since ${formatDate(events.disconnectedSince)}.` : ""}
              </div>
            ) : null}
          </div>
          <div className="topbar-actions">
            <div className="admin-account">
              {session.email ? <span className="admin-identity">{session.email}</span> : null}
              <button className="button" type="button" onClick={() => setSession(clearAdminSession())}>Logout</button>
            </div>
            <div className="alerts-menu">
              <button
                className="icon-button alert-trigger"
                type="button"
                onClick={() => void toggleAlerts()}
                aria-expanded={alertsOpen}
                aria-haspopup="dialog"
                title="Notifications"
                aria-label="Notifications"
              >
                <BellIcon />
                {unread > 0 ? <span className="count">{unread}</span> : null}
              </button>
              {alertsOpen ? (
                <div className="alerts-panel" role="dialog" aria-label="Alerts">
                  <div className="alerts-header">
                    <div>
                      <strong>Alerts</strong>
                      <span>{unread} unread</span>
                    </div>
                    <div className="actions">
                      <RefreshIconButton refreshing={alertRefreshing} label="Refresh alerts" onRefresh={() => void refreshAlerts()} />
                      <button className="button" type="button" disabled={!alerts.length} onClick={() => void clearAllAlerts()}>Clear all</button>
                    </div>
                  </div>
                  {alertRefreshMessage ? (
                    <div
                      className={`refresh-status ${
                        alertRefreshMessage.startsWith("Refresh failed")
                          ? "error"
                          : alertRefreshMessage === "Nothing new"
                            ? "neutral"
                            : "success"
                      }`}
                    >
                      {alertRefreshMessage}
                    </div>
                  ) : null}
                  <div className="alerts-list">
                    {notifications.loading && !notifications.data ? (
                      <div className="alert-row"><span className="skeleton-line wide" /><span className="skeleton-line medium" /></div>
                    ) : null}
                    {alerts.map((alert) => {
                      const tone = alertTone(alert);
                      const rowClassName = [
                        "alert-row",
                        alert.read ? "" : "unread",
                        newAlertIds.has(alert.notification_id) && tone !== "danger" ? "new" : "",
                        tone === "danger" ? "error" : ""
                      ].filter(Boolean).join(" ");
                      return (
                        <div className={rowClassName} key={alert.notification_id}>
                          <button className="alert-content" type="button" onClick={() => void openAlert(alert)}>
                            <span className={`badge ${tone}`}>{alertLabel(alert)}</span>
                            <strong>{alert.title}</strong>
                            <span>{alert.message}</span>
                            <small>{formatDate(alert.created_at)}{alert.batch_id ? ` - Batch ${alert.batch_id.slice(0, 10)}` : ""}</small>
                          </button>
                          <button className="icon-button" type="button" onClick={() => void clearAlert(alert.notification_id)} title="Clear alert" aria-label={`Clear ${alert.title}`}>
                            Clear
                          </button>
                        </div>
                      );
                    })}
                    {!notifications.loading && !alerts.length ? (
                      <div className="empty-state"><strong>No alerts</strong><span>Ingestion events and errors will appear here.</span></div>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}
