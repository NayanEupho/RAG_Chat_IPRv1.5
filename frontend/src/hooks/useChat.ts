import { useState, useEffect, useRef, useCallback } from 'react';
import { toast } from 'sonner';

interface Interaction {
  role: 'user' | 'bot';
  content: string;
  intent?: string;
  sources?: string[];
  targeted_docs?: string[];
  status?: string;
  ttft?: number;
  thoughts?: { type: 'thought' | 'tool_call' | 'error' | 'status' | 'result', content: string }[];
}

export function useChat() {
  const [messages, setMessages] = useState<Interaction[]>([
    { role: 'bot', content: 'Hello! I am your IPR Assistant. Ask me anything or upload documents.', thoughts: [] }
  ]);
  const [loading, setLoading] = useState(false);
  const [currentStatus, setCurrentStatus] = useState<string>('');
  const [messageQueue, setMessageQueue] = useState<{ text: string, mode: string }[]>([]);
  const isProcessing = useRef(false);

  // Session Persistence
  const [sessionId, setSessionId] = useState<string>('');
  const abortControllerRef = useRef<AbortController | null>(null);
  const historyRequestRef = useRef(0);
  const historyCacheRef = useRef<Map<string, Interaction[]>>(new Map());

  const getApiBase = useCallback(() => {
    return "/api";
  }, []);

  const getStreamingBackendBase = useCallback(() => {
    const configured = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000';

    if (typeof window === 'undefined') {
      return configured;
    }

    try {
      const backendUrl = new URL(configured);
      const pageHost = window.location.hostname;
      const backendHost = backendUrl.hostname;
      const pageIsLoopback = ['localhost', '127.0.0.1', '::1'].includes(pageHost);
      const backendIsLoopback = ['localhost', '127.0.0.1', '::1'].includes(backendHost);

      if (backendIsLoopback && !pageIsLoopback) {
        backendUrl.hostname = pageHost;
        return backendUrl.toString().replace(/\/$/, '');
      }

      return configured.replace(/\/$/, '');
    } catch {
      return configured.replace(/\/$/, '');
    }
  }, []);

  const loadHistory = useCallback(async (sid: string) => {
    const requestId = ++historyRequestRef.current;

    if (!sid) {
      setMessages([{ role: 'bot', content: 'Hello! I am your IPR Assistant. Ask me anything or upload documents.', thoughts: [] }]);
      return;
    }

    const cached = historyCacheRef.current.get(sid);
    if (cached) {
      setMessages(cached);
    }

    try {
      const res = await fetch(`${getApiBase()}/history/${sid}`, { credentials: 'include' });
      const data = await res.json();
      if (requestId !== historyRequestRef.current) return;

      if (data.messages && data.messages.length > 0) {
        const mapped: Interaction[] = data.messages.map((m: {
          role: 'user' | 'bot';
          content: string;
          intent: string;
          sources: string[];
          metadata: { targeted_docs?: string[]; ttft?: number };
          thoughts?: unknown[];
        }) => ({
          role: m.role,
          content: m.content,
          intent: m.intent,
          sources: m.sources,
          targeted_docs: m.metadata?.targeted_docs,
          ttft: m.metadata?.ttft,
          thoughts: (m.thoughts || []) as { type: 'thought' | 'tool_call' | 'error' | 'status' | 'result', content: string }[]
        }));
        historyCacheRef.current.set(sid, mapped);
        setMessages(mapped);
      } else {
        const emptyHistory = [{ role: 'bot' as const, content: 'Hello! I am your IPR Assistant. Chat history is empty.' }];
        historyCacheRef.current.set(sid, emptyHistory);
        setMessages(emptyHistory);
      }
    } catch {
      if (requestId !== historyRequestRef.current) return;
      console.error("Failed to load history");
    }
  }, [getApiBase]);

  useEffect(() => {
    let stored = localStorage.getItem('rag_session_id');
    if (!stored) {
      stored = `web_${Math.random().toString(36).substring(7)}`;
      localStorage.setItem('rag_session_id', stored);
    }
    setSessionId(stored);
    loadHistory(stored);
  }, [loadHistory]);

  const stopGeneration = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      setLoading(false);
      setCurrentStatus('Generation stopped.');
      isProcessing.current = false;
      setMessageQueue([]);
    }
  };

  const startEmptySession = useCallback((sid: string) => {
    historyRequestRef.current += 1;
    const welcome = [{ role: 'bot' as const, content: 'Hello! I am your IPR Assistant. Ask me anything or upload documents.', thoughts: [] }];
    if (sid) historyCacheRef.current.set(sid, welcome);
    setMessages(welcome);
  }, []);

  const fetchDocuments = useCallback(async () => {
    try {
      const res = await fetch(`/api/documents`, { credentials: 'include' });
      const data = await res.json();
      return data.documents || [];
    } catch (e) {
      console.error("Failed to fetch documents", e);
      return [];
    }
  }, []);


  const processMessage = useCallback(async (text: string, mode: string = 'auto', sid: string) => {
    const controller = new AbortController();
    abortControllerRef.current = controller;

    const botPlaceholder: Interaction = { role: 'bot', content: '', status: 'Thinking...', thoughts: [] };
    setMessages(prev => [...prev, botPlaceholder]);
    setLoading(true);
    setCurrentStatus('Thinking...');

    const requestStartTime = Date.now();

    try {
      // SSE Streaming Strategy:
      // - Development: Bypass Next.js rewrite proxy (it buffers SSE responses)
      //   and fetch directly from the backend URL.
      // - Production: Use relative URL through Nginx reverse proxy, which
      //   supports SSE natively with proxy_buffering off.
      const isDev = process.env.NODE_ENV === 'development';
      const streamUrl = isDev
        ? `${getStreamingBackendBase()}/api/chat/stream`
        : `/api/chat/stream`;

      console.log(`[useChat] Streaming to: ${streamUrl} (isDev=${isDev})`);

      const response = await fetch(streamUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sid, mode }),
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`Server returned ${response.status}: ${response.statusText}`);
      }

      if (!response.body) throw new Error("No response body");

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let leftover = ''; // Buffer for fragmented lines
      let accumulatedContent = '';
      let currentEvent: string | null = null;
      let firstTokenAt: number | undefined;
      let animationFrame: number | null = null;
      let tokenFlushTimer: number | null = null;
      let lastTokenFlushAt = 0;
      let streamEnded = false;

      const flushTokenContent = () => {
        animationFrame = null;
        tokenFlushTimer = null;
        lastTokenFlushAt = performance.now();
        setMessages(prev => {
          const next = [...prev];
          for (let i = next.length - 1; i >= 0; i--) {
            if (next[i].role === 'bot') {
              const nextBot = { ...next[i], content: accumulatedContent };
              if (nextBot.ttft === undefined && firstTokenAt !== undefined) {
                nextBot.ttft = firstTokenAt - requestStartTime;
              }
              next[i] = nextBot;
              break;
            }
          }
          return next;
        });
      };

      const scheduleTokenFlush = () => {
        if (animationFrame !== null || tokenFlushTimer !== null) return;
        const elapsedSinceFlush = performance.now() - lastTokenFlushAt;
        const delay = Math.max(0, 50 - elapsedSinceFlush);
        tokenFlushTimer = window.setTimeout(() => {
          tokenFlushTimer = null;
          if (animationFrame !== null) return;
          animationFrame = window.requestAnimationFrame(flushTokenContent);
        }, delay);
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = (leftover + chunk).split('\n');
        leftover = lines.pop() || ''; // Keep the last partial line

        for (const line of lines) {
          const trimmedLine = line.trim();
          if (!trimmedLine) continue;

          if (trimmedLine.startsWith('event: ')) {
            currentEvent = trimmedLine.replace('event: ', '');
          } else if (trimmedLine.startsWith('data: ') && currentEvent) {
            const eventData = trimmedLine.replace('data: ', '');

            if (currentEvent === 'status') {
              setCurrentStatus(eventData);
              setMessages(prev => {
                const next = [...prev];
                for (let i = next.length - 1; i >= 0; i--) {
                  if (next[i].role === 'bot') {
                    let type: 'status' | 'thought' | 'tool_call' | 'error' | 'result' = 'status';
                    if (eventData.includes('Analyzing')) type = 'thought';
                    else if (eventData.includes('Refining')) type = 'thought';
                    else if (eventData.includes('Searching')) type = 'tool_call';
                    else if (eventData.includes('Generating')) type = 'thought';

                    const newThought = { type, content: eventData };
                    const currentThoughts = next[i].thoughts || [];
                    const lastThought = currentThoughts[currentThoughts.length - 1];

                    if (!lastThought || lastThought.content !== eventData) {
                      next[i] = {
                        ...next[i],
                        status: eventData,
                        thoughts: [...currentThoughts, newThought]
                      };
                    }
                    break;
                  }
                }
                return next;
              });
            } else if (currentEvent === 'token') {
              try {
                const token = JSON.parse(eventData);
                accumulatedContent += token;
                if (firstTokenAt === undefined) firstTokenAt = Date.now();
                scheduleTokenFlush();
              } catch { }
            } else if (currentEvent === 'end') {
              streamEnded = true;
              try {
                if (animationFrame !== null) {
                  window.cancelAnimationFrame(animationFrame);
                  animationFrame = null;
                }
                if (tokenFlushTimer !== null) {
                  window.clearTimeout(tokenFlushTimer);
                  tokenFlushTimer = null;
                }
                flushTokenContent();
                const metadata = JSON.parse(eventData);
                setMessages(prev => {
                  const next = [...prev];
                  for (let i = next.length - 1; i >= 0; i--) {
                    if (next[i].role === 'bot') {
                      next[i] = {
                        ...next[i],
                        intent: metadata.intent,
                        sources: metadata.sources,
                        targeted_docs: metadata.targeted_docs,
                        ttft: next[i].ttft ?? metadata.ttft_ms,
                        status: undefined
                      };
                      break;
                    }
                  }
                  historyCacheRef.current.set(sid, next);
                  return next;
                });
                if (metadata.session_title) {
                  window.dispatchEvent(new CustomEvent('session-title-updated', {
                    detail: { session_id: sid, title: metadata.session_title }
                  }));
                }
              } catch { }
            } else if (currentEvent === 'error') {
              toast.error(`System Error: ${eventData}`);
              setMessages(prev => {
                const next = [...prev];
                for (let i = next.length - 1; i >= 0; i--) {
                  if (next[i].role === 'bot') {
                    next[i] = {
                      ...next[i],
                      content: `Error: ${eventData}`,
                      thoughts: [...(next[i].thoughts || []), { type: 'error', content: eventData }]
                    };
                    break;
                  }
                }
                return next;
              });
            }
          }
        }
      }
      if (!streamEnded) {
        flushTokenContent();
      }
    } catch (error: unknown) {
      if (error instanceof Error && error.name !== 'AbortError') {
        setMessages(prev => [...prev, { role: 'bot', content: 'Network Error.' }]);
      }
    } finally {
      setLoading(false);
      setCurrentStatus('');
      abortControllerRef.current = null;
    }
  }, [getStreamingBackendBase]);

  const processQueue = useCallback(async () => {
    if (isProcessing.current || messageQueue.length === 0) return;
    isProcessing.current = true;
    const nextMsg = messageQueue[0];
    setMessageQueue(prev => prev.slice(1));
    await processMessage(nextMsg.text, nextMsg.mode, sessionId);
    isProcessing.current = false;
  }, [messageQueue, sessionId, processMessage]);

  useEffect(() => {
    if (!loading && !isProcessing.current && messageQueue.length > 0) {
      processQueue();
    }
  }, [loading, messageQueue, processQueue]);

  const sendMessage = useCallback((text: string, mode: string = 'auto') => {
    if (!text.trim()) return;
    if (messageQueue.length >= 3) {
      toast.error("Queue limit reached (max 3 pending messages)");
      return;
    }
    setMessages(prev => [...prev, { role: 'user', content: text }]);
    setMessageQueue(prev => [...prev, { text, mode }]);
  }, [messageQueue.length]);

  return {
    messages, setMessages, sendMessage, loading, currentStatus,
    sessionId, setSessionId, loadHistory, stopGeneration,
    fetchDocuments, messageQueue, startEmptySession
  };
}
