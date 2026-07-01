"use client";

import { useEffect, useRef, useState } from "react";
import { adminEventsUrl } from "@/lib/api";
import type { AdminEvent } from "@/lib/types";

interface EventState {
  connected: boolean;
  status: "connecting" | "live" | "reconnecting" | "down";
  lastEvent: AdminEvent | null;
  lastError: string | null;
  disconnectedSince: string | null;
}

const EVENT_TYPES = [
  "batch_progress",
  "document_update",
  "job_update",
  "job_error",
  "log",
  "notification",
  "warehouse_update",
  "stats_update",
  "review_update",
  "ping"
];

export function useAdminEvents(onEvent?: (event: AdminEvent) => void, enabled = true): EventState {
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState<EventState["status"]>("connecting");
  const [lastEvent, setLastEvent] = useState<AdminEvent | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const [disconnectedSince, setDisconnectedSince] = useState<string | null>(null);
  const handlerRef = useRef(onEvent);

  useEffect(() => {
    handlerRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    if (!enabled) {
      setConnected(false);
      setStatus("connecting");
      setLastEvent(null);
      setLastError(null);
      setDisconnectedSince(null);
      return;
    }
    let source: EventSource | null = null;
    let reconnectTimer: number | null = null;
    let downTimer: number | null = null;
    let staleTimer: number | null = null;
    let closed = false;
    let reconnectAttempt = 0;
    let lastSeenAt = Date.now();

    function clearTimer(timer: number | null) {
      if (timer !== null) window.clearTimeout(timer);
    }

    function clearAllTimers() {
      clearTimer(reconnectTimer);
      clearTimer(downTimer);
      clearTimer(staleTimer);
      reconnectTimer = null;
      downTimer = null;
      staleTimer = null;
    }

    function closeSource() {
      if (source) {
        source.close();
        source = null;
      }
    }

    function scheduleReconnect(reason: string) {
      if (closed) return;
      closeSource();
      clearTimer(reconnectTimer);
      clearTimer(staleTimer);
      setConnected(false);
      setStatus((current) => (current === "connecting" ? "connecting" : "reconnecting"));
      setLastError(reason);
      setDisconnectedSince((current) => current || new Date().toISOString());
      clearTimer(downTimer);
      downTimer = window.setTimeout(() => {
        setStatus("down");
        setLastError(`SSE reconnect timed out. Retrying in the background. Confirm ${adminEventsUrl()} is reachable if this persists.`);
      }, 30000);
      const delay = Math.min(12000, 750 * 2 ** Math.min(reconnectAttempt, 4)) + Math.floor(Math.random() * 300);
      reconnectAttempt += 1;
      reconnectTimer = window.setTimeout(connect, delay);
    }

    function armStaleWatch() {
      clearTimer(staleTimer);
      staleTimer = window.setTimeout(() => {
        if (Date.now() - lastSeenAt > 65000) {
          scheduleReconnect(`No SSE heartbeat received from ${adminEventsUrl()} for more than 65 seconds.`);
        } else {
          armStaleWatch();
        }
      }, 35000);
    }

    function handleMessage(event: MessageEvent<string>) {
      lastSeenAt = Date.now();
      try {
        const parsed = JSON.parse(event.data || "{}") as AdminEvent;
        const typed = { ...parsed, type: parsed.type || event.type };
        setLastEvent(typed);
        if (typed.type !== "ping") handlerRef.current?.(typed);
      } catch {
        // Ignore malformed frames; the next heartbeat or event will update state.
      }
    }

    function connect() {
      if (closed) return;
      closeSource();
      setStatus((current) => (current === "live" ? "live" : reconnectAttempt > 0 ? "reconnecting" : "connecting"));
      source = new EventSource(adminEventsUrl());
      source.onopen = () => {
        clearTimer(downTimer);
        downTimer = null;
        reconnectAttempt = 0;
        lastSeenAt = Date.now();
        setConnected(true);
        setStatus("live");
        setLastError(null);
        setDisconnectedSince(null);
        armStaleWatch();
      };
      source.onerror = () => {
        scheduleReconnect(`Unable to maintain SSE connection to ${adminEventsUrl()}. Reconnecting automatically.`);
      };
      EVENT_TYPES.forEach((type) => source?.addEventListener(type, handleMessage));
    }

    connect();

    return () => {
      closed = true;
      clearAllTimers();
      closeSource();
    };
  }, [enabled]);

  return { connected, status, lastEvent, lastError, disconnectedSince };
}
