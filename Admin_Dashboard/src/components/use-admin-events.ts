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

const INITIAL_STATE: EventState = {
  connected: false,
  status: "connecting",
  lastEvent: null,
  lastError: null,
  disconnectedSince: null
};

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

let sharedState: EventState = INITIAL_STATE;
let sharedSource: EventSource | null = null;
let reconnectTimer: number | null = null;
let downTimer: number | null = null;
let staleTimer: number | null = null;
let reconnectAttempt = 0;
let lastSeenAt = Date.now();

const stateSubscribers = new Set<(state: EventState) => void>();
const eventSubscribers = new Set<(event: AdminEvent) => void>();

function publishState(next: Partial<EventState>) {
  sharedState = { ...sharedState, ...next };
  stateSubscribers.forEach((subscriber) => subscriber(sharedState));
}

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

function closeSharedSource() {
  if (sharedSource) {
    sharedSource.close();
    sharedSource = null;
  }
}

function stopSharedEvents() {
  clearAllTimers();
  closeSharedSource();
  reconnectAttempt = 0;
  publishState(INITIAL_STATE);
}

function scheduleReconnect(reason: string) {
  if (!stateSubscribers.size) return;
  closeSharedSource();
  clearTimer(reconnectTimer);
  clearTimer(staleTimer);
  publishState({
    connected: false,
    status: sharedState.status === "connecting" ? "connecting" : "reconnecting",
    lastError: reason,
    disconnectedSince: sharedState.disconnectedSince || new Date().toISOString()
  });
  clearTimer(downTimer);
  downTimer = window.setTimeout(() => {
    publishState({
      status: "down",
      lastError: `SSE reconnect timed out. Retrying in the background. Confirm ${adminEventsUrl()} is reachable if this persists.`
    });
  }, 30000);
  const delay = Math.min(60000, 750 * 2 ** Math.min(reconnectAttempt, 6)) + Math.floor(Math.random() * 1000);
  reconnectAttempt += 1;
  reconnectTimer = window.setTimeout(connectSharedEvents, delay);
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

function handleSharedMessage(event: MessageEvent<string>) {
  lastSeenAt = Date.now();
  try {
    const parsed = JSON.parse(event.data || "{}") as AdminEvent;
    const typed = { ...parsed, type: parsed.type || event.type };
    publishState({ lastEvent: typed });
    if (typed.type !== "ping") eventSubscribers.forEach((subscriber) => subscriber(typed));
  } catch {
    // Ignore malformed frames; the next heartbeat or event will update state.
  }
}

function connectSharedEvents() {
  if (!stateSubscribers.size) return;
  closeSharedSource();
  publishState({ status: sharedState.status === "live" ? "live" : reconnectAttempt > 0 ? "reconnecting" : "connecting" });
  sharedSource = new EventSource(adminEventsUrl());
  sharedSource.onopen = () => {
    clearTimer(downTimer);
    downTimer = null;
    reconnectAttempt = 0;
    lastSeenAt = Date.now();
    publishState({ connected: true, status: "live", lastError: null, disconnectedSince: null });
    armStaleWatch();
  };
  sharedSource.onerror = () => {
    scheduleReconnect(`Unable to maintain SSE connection to ${adminEventsUrl()}. Reconnecting automatically.`);
  };
  EVENT_TYPES.forEach((type) => sharedSource?.addEventListener(type, handleSharedMessage));
}

export function useAdminEvents(onEvent?: (event: AdminEvent) => void, enabled = true): EventState {
  const [state, setState] = useState<EventState>(sharedState);
  const handlerRef = useRef(onEvent);

  useEffect(() => {
    handlerRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    if (!enabled) {
      setState(INITIAL_STATE);
      return;
    }
    const stateSubscriber = (next: EventState) => setState(next);
    const eventSubscriber = (event: AdminEvent) => handlerRef.current?.(event);
    stateSubscribers.add(stateSubscriber);
    eventSubscribers.add(eventSubscriber);
    setState(sharedState);
    if (!sharedSource) connectSharedEvents();

    return () => {
      stateSubscribers.delete(stateSubscriber);
      eventSubscribers.delete(eventSubscriber);
      if (!stateSubscribers.size) stopSharedEvents();
    };
  }, [enabled]);

  return state;
}
