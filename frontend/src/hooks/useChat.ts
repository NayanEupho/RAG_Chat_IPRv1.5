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

  const getApiBase = useCallback(() => {
    return '/api';
  }, []);

  const loadHistory = useCallback(async (sid: string) => {
    try {
      const res = await fetch(`${getApiBase()}/history/${sid}`, { credentials: 'include' });
      const data = await res.json();
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
        setMessages(mapped);
      } else {
        setMessages([{ role: 'bot', content: 'Hello! I am your IPR Assistant. Chat history is empty.' }]);
      }
    } catch {
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
      const response = await fetch(`${getApiBase()}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sid, mode }),
        signal: controller.signal,
        credentials: 'include'
      });

      if (!response.body) throw new Error("No response body");

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let leftover = ''; // Buffer for fragmented lines
      let accumulatedContent = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = (leftover + chunk).split('\n');
        leftover = lines.pop() || ''; // Keep the last partial line

        let currentEvent: string | null = null;

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
                setMessages(prev => {
                  const next = [...prev];
                  for (let i = next.length - 1; i >= 0; i--) {
                    if (next[i].role === 'bot') {
                      const nextBot = { ...next[i], content: accumulatedContent };
                      if (nextBot.ttft === undefined) {
                        nextBot.ttft = Date.now() - requestStartTime;
                      }
                      next[i] = nextBot;
                      break;
                    }
                  }
                  return next;
                });
              } catch { }
            } else if (currentEvent === 'end') {
              try {
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
                        status: undefined
                      };
                      break;
                    }
                  }
                  return next;
                });
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
    } catch (error: unknown) {
      if (error instanceof Error && error.name !== 'AbortError') {
        setMessages(prev => [...prev, { role: 'bot', content: 'Network Error.' }]);
      }
    } finally {
      setLoading(false);
      setCurrentStatus('');
      abortControllerRef.current = null;
    }
  }, [getApiBase]);

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
    messages, sendMessage, loading, currentStatus,
    sessionId, setSessionId, loadHistory, stopGeneration,
    fetchDocuments, messageQueue
  };
}
