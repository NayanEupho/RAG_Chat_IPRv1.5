import { useState, useEffect, useRef, useCallback } from 'react';

interface Interaction {
  role: 'user' | 'bot';
  content: string;
  intent?: string;
  sources?: string[];
  targeted_docs?: string[];
  status?: string;
  thoughts?: { type: 'thought' | 'tool_call' | 'error' | 'status' | 'result', content: string }[];
}

export function useChat() {
  const [messages, setMessages] = useState<Interaction[]>([
    { role: 'bot', content: 'Hello! I am your IPR Assistant. Ask me anything or upload documents.', thoughts: [] }
  ]);
  const [loading, setLoading] = useState(false);
  const [currentStatus, setCurrentStatus] = useState<string>('');

  // Session Persistence
  const [sessionId, setSessionId] = useState<string>('');
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let stored = localStorage.getItem('rag_session_id');
    if (!stored) {
      stored = `web_${Math.random().toString(36).substring(7)}`;
      localStorage.setItem('rag_session_id', stored);
    }
    setSessionId(stored);
    loadHistory(stored);
  }, []);

  const stopGeneration = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      setLoading(false);
      setCurrentStatus('Generation stopped.');
    }
  };

  const fetchDocuments = useCallback(async () => {
    try {
      const hostname = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
      const port = '443';
      const res = await fetch(`https://${hostname}:${port}/api/documents`);
      const data = await res.json();
      console.log(`[useChat] Fetched ${data.documents?.length || 0} documents from ${hostname}:${port}`);
      return data.documents || [];
    } catch (e) {
      console.error("Failed to fetch documents", e);
      return [];
    }
  }, []);

  const getApiBase = () => {
    const hostname = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
    return `https://${hostname}:443/api`;
  };

  const loadHistory = async (sid: string) => {
    try {
      const res = await fetch(`${getApiBase()}/history/${sid}`);
      const data = await res.json();
      if (data.messages && data.messages.length > 0) {
        const mapped: Interaction[] = data.messages.map((m: any) => ({
          role: m.role,
          content: m.content,
          intent: m.intent,
          sources: m.sources,
          targeted_docs: m.metadata?.targeted_docs,
          thoughts: m.thoughts || []
        }));
        setMessages(mapped);
      } else {
        setMessages([{ role: 'bot', content: 'Hello! I am your IPR Assistant. Chat history is empty.' }]);
      }
    } catch (e) {
      console.error("Failed to load history", e);
    }
  };

  const sendMessage = async (text: string, mode: string = 'auto') => {
    if (!text.trim()) return;

    // Create new abort controller for this request
    const controller = new AbortController();
    abortControllerRef.current = controller;

    // Add User Message AND Placeholder Bot Message in a single atomic update
    // This prevents React's async state batching from causing incorrect ordering
    const userMsg: Interaction = { role: 'user', content: text };
    const botPlaceholder: Interaction = { role: 'bot', content: '', status: 'Thinking...', thoughts: [] };
    setMessages(prev => [...prev, userMsg, botPlaceholder]);
    setLoading(true);
    setCurrentStatus('Thinking...');

    try {
      const response = await fetch(`${getApiBase()}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sessionId, mode }),
        signal: controller.signal
      });

      if (!response.body) throw new Error("No response body");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let accumulatedContent = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n\n');

        for (const line of lines) {
          if (!line.trim()) continue;

          const eventMatch = line.match(/^event: (.*)\ndata: (.*)$/m);
          if (!eventMatch) continue;

          const eventType = eventMatch[1].trim();
          const eventData = eventMatch[2].trim();

          if (eventType === 'status') {
            setCurrentStatus(eventData);
            setMessages(prev => {
              const next = [...prev];
              for (let i = next.length - 1; i >= 0; i--) {
                if (next[i].role === 'bot') {
                  // Determine thought type based on content
                  let type: any = 'status';
                  if (eventData.includes('Analyzing')) type = 'thought';
                  else if (eventData.includes('Refining')) type = 'thought';
                  else if (eventData.includes('Searching')) type = 'tool_call';
                  else if (eventData.includes('Generating')) type = 'thought';

                  const newThought = { type, content: eventData };

                  // Avoid duplicates if the last thought is identical
                  const currentThoughts = next[i].thoughts || [];
                  const lastThought = currentThoughts[currentThoughts.length - 1];

                  if (!lastThought || lastThought.content !== eventData) {
                    next[i] = {
                      ...next[i],
                      status: eventData,
                      thoughts: [...(currentThoughts), newThought]
                    };
                  }
                  break;
                }
              }
              return next;
            });
          } else if (eventType === 'token') {
            try {
              const token = JSON.parse(eventData);
              accumulatedContent += token;
              setMessages(prev => {
                const next = [...prev];
                // Find the latest bot message to update its content
                for (let i = next.length - 1; i >= 0; i--) {
                  if (next[i].role === 'bot') {
                    next[i] = { ...next[i], content: accumulatedContent };
                    break;
                  }
                }
                return next;
              });
            } catch (e) {
              console.error("Token parse error", e);
            }
          } else if (eventType === 'end') {
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
            } catch (e) { }
          }
        }
      }

    } catch (error: any) {
      if (error.name === 'AbortError') {
        console.log('Fetch aborted');
      } else {
        setMessages(prev => [...prev, { role: 'bot', content: 'Network Error.' }]);
      }
    } finally {
      setLoading(false);
      setCurrentStatus('');
      abortControllerRef.current = null;
    }
  };

  return { messages, sendMessage, loading, currentStatus, sessionId, setSessionId, loadHistory, stopGeneration, fetchDocuments };
}
