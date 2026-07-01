"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { formatDate } from "@/lib/format";
import type { AdminEvent, JobLog, NotificationItem } from "@/lib/types";
import { useAdminEvents } from "./use-admin-events";

const STORAGE_KEY = "rag-admin-live-logs-v2";
const SESSION_KEY = "rag-admin-live-log-session";
const MAX_LOGS = 700;
const terminalBatchStatuses = new Set(["COMPLETE", "PARTIALLY_COMPLETE", "FAILED", "CANCELLED"]);

interface StoredLogs {
  session_id: string;
  logs: string[];
}

function sessionId(): string {
  if (typeof window === "undefined") return "server";
  let id = window.sessionStorage.getItem(SESSION_KEY);
  if (!id) {
    id = `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    window.sessionStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

function readStoredLogs(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "null") as StoredLogs | null;
    if (!parsed || parsed.session_id !== sessionId()) return [];
    return Array.isArray(parsed.logs) ? parsed.logs.slice(0, MAX_LOGS).map(String) : [];
  } catch {
    return [];
  }
}

function writeStoredLogs(logs: string[]) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ session_id: sessionId(), logs: logs.slice(-MAX_LOGS) }));
}

function batchIdFromEvent(event: AdminEvent): string | null {
  if (event.batch_id) return event.batch_id;
  if (event.data && typeof event.data === "object") {
    const data = event.data as { batch_id?: string | null };
    return data.batch_id || null;
  }
  return null;
}

function formatJobLog(log: JobLog): string {
  const scope = [log.batch_id ? `batch=${log.batch_id.slice(0, 10)}` : null, log.document_id ? `doc=${log.document_id.slice(0, 10)}` : null]
    .filter(Boolean)
    .join(" ");
  return `[${formatDate(log.timestamp)}] ${log.level} ${log.stage}: ${log.message}${scope ? ` (${scope})` : ""}`;
}

function eventLine(event: AdminEvent): string | null {
  if (event.type === "log" && event.data && typeof event.data === "object") {
    return formatJobLog(event.data as JobLog);
  }
  if (event.type === "notification" && event.data && typeof event.data === "object") {
    const note = event.data as NotificationItem;
    if (["INGESTION_INITIATED", "INGESTION_COMPLETED", "ERROR", "STAGE_UPDATE"].includes(note.type)) {
      return `[${formatDate(note.created_at)}] ${note.type}: ${note.title} - ${note.message}`;
    }
  }
  if (event.type === "job_error") {
    return `[${new Date().toLocaleTimeString()}] ERROR ${event.status || "JOB"}: ${event.message || "Job failed"}`;
  }
  if (event.type === "job_update" && event.data && typeof event.data === "object") {
    const job = event.data as { stage?: string; status?: string; progress?: number; batch_id?: string | null; document_id?: string | null };
    return `[${new Date().toLocaleTimeString()}] JOB ${job.stage || "stage"}: ${job.status || ""}${typeof job.progress === "number" ? ` ${job.progress}%` : ""}`;
  }
  if (event.type === "document_update" || event.type === "batch_progress") {
    return `[${new Date().toLocaleTimeString()}] ${event.type}: ${event.status || event.message || ""}`;
  }
  return null;
}

export function useAdminLiveLogs() {
  const [logs, setLogs] = useState<string[]>([]);
  const activeBatchIds = useRef<Set<string>>(new Set());

  const append = useCallback((line: string) => {
    setLogs((current) => {
      const next = [...current, line].slice(-MAX_LOGS);
      writeStoredLogs(next);
      return next;
    });
  }, []);

  useEffect(() => {
    setLogs(readStoredLogs());
  }, []);

  useAdminEvents((event) => {
    const batchId = batchIdFromEvent(event);
    const status = event.status || ((event.data && typeof event.data === "object" && "status" in event.data) ? String((event.data as { status?: unknown }).status) : null);

    if (event.type === "notification" && event.data && typeof event.data === "object") {
      const note = event.data as NotificationItem;
      if (note.type === "INGESTION_INITIATED" && note.batch_id) activeBatchIds.current.add(note.batch_id);
      if (note.type === "INGESTION_COMPLETED" && note.batch_id) activeBatchIds.current.delete(note.batch_id);
    }
    if (batchId && !terminalBatchStatuses.has(String(status || ""))) activeBatchIds.current.add(batchId);

    const line = eventLine(event);
    if (line && (activeBatchIds.current.size > 0 || event.type === "notification" || event.type === "job_error")) {
      append(line);
    }

    if (batchId && terminalBatchStatuses.has(String(status || ""))) {
      activeBatchIds.current.delete(batchId);
    }
  });

  const clear = useCallback(() => {
    setLogs([]);
    writeStoredLogs([]);
  }, []);

  return { logs, clear };
}
