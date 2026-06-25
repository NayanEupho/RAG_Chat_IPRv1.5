"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { adminApi } from "@/lib/api";
import { useAdminData } from "./use-admin-data";

const navItems = [
  { href: "/", label: "Monitoring" },
  { href: "/control-panel", label: "Control Panel" },
  { href: "/upload", label: "Upload" },
  { href: "/review", label: "Review" },
  { href: "/warehouse", label: "Document Warehouse" },
  { href: "/chunks", label: "Chunks" },
  { href: "/vector-stats", label: "Vector Stats" },
  { href: "/history-logs", label: "History & Logs" }
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const notifications = useAdminData(() => adminApi.notifications(), 15000);
  const unread = notifications.data?.unread_count || 0;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">IPR</span>
          <div>
            <strong>RAG Admin</strong>
            <small>Ingestion dashboard</small>
          </div>
        </div>
        <nav className="nav-list">
          {navItems.map((item) => (
            <Link key={item.href} href={item.href} className={pathname === item.href ? "active" : ""}>
              {item.label}
            </Link>
          ))}
        </nav>
      </aside>
      <main className="main">
        <header className="topbar">
          <div>
            <strong>Admin Dashboard</strong>
            <span>SQLite workflow state · Chroma vector store</span>
          </div>
          <button className="icon-button" type="button" onClick={() => void notifications.refresh()} title="Refresh notifications">
            Bell {unread > 0 ? <span className="count">{unread}</span> : null}
          </button>
        </header>
        {children}
      </main>
    </div>
  );
}

