"use client";

import { useEffect, useRef, useState } from "react";
import { adminEventsUrl } from "@/lib/api";
import type { AdminEvent } from "@/lib/types";

interface EventState {
  connected: boolean;
  lastEvent: AdminEvent | null;
}

export function useAdminEvents(onEvent?: (event: AdminEvent) => void): EventState {
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<AdminEvent | null>(null);
  const handlerRef = useRef(onEvent);

  useEffect(() => {
    handlerRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    const source = new EventSource(adminEventsUrl());

    function handleMessage(event: MessageEvent<string>) {
      try {
        const parsed = JSON.parse(event.data) as AdminEvent;
        setLastEvent(parsed);
        handlerRef.current?.(parsed);
      } catch {
        // Ignore malformed frames; the next heartbeat or event will update state.
      }
    }

    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.addEventListener("batch_progress", handleMessage);
    source.addEventListener("document_update", handleMessage);
    source.addEventListener("job_update", handleMessage);
    source.addEventListener("job_error", handleMessage);
    source.addEventListener("notification", handleMessage);
    source.addEventListener("ping", handleMessage);

    return () => source.close();
  }, []);

  return { connected, lastEvent };
}

