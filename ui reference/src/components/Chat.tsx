"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { ChatMessage, getSessionHistory, createSession } from "../lib/api";
import EmptyState from "./chat/EmptyState";
import MessageBubble from "./chat/MessageBubble";
import ChatInput from "./chat/ChatInput";
import { toast } from "sonner";
import { motion, AnimatePresence } from "framer-motion";
import styles from "./Chat.module.css";

interface ChatProps {
    sessionId?: string;
}

interface ThoughtItem {
    type: "thought" | "tool_call" | "error" | "status" | "result";
    content: string;
}

export default function Chat({ sessionId }: ChatProps) {
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [input, setInput] = useState("");
    const [isLoading, setIsLoading] = useState(false);

    // We store thought streams mapped by message index (AI messages only)
    const [messageThoughts, setMessageThoughts] = useState<Record<number, ThoughtItem[]>>({});

    // Active thoughts for the CURRENT streaming message
    const [activeThoughts, setActiveThoughts] = useState<ThoughtItem[]>([]);
    const [mcpContext, setMcpContext] = useState("auto");

    const abortControllerRef = useRef<AbortController | null>(null);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const scrollContainerRef = useRef<HTMLDivElement>(null);

    // Confirmation State
    const [confirmationReq, setConfirmationReq] = useState<{ tool: string, arguments: any, risk?: any } | null>(null);
    const [isConfirming, setIsConfirming] = useState(false);

    // Load history
    const [historyLoading, setHistoryLoading] = useState(false);
    const [localSessionId, setLocalSessionId] = useState<string | undefined>(sessionId);
    const justCreatedSessionRef = useRef(false);

    // Sync local ID
    useEffect(() => { setLocalSessionId(sessionId); }, [sessionId]);

    // Load History Effect
    useEffect(() => {
        if (localSessionId) {
            // If we JUST created this session, don't clear/reload.
            // This prevents wiping out the message the user just sent while the URL updates.
            if (justCreatedSessionRef.current) {
                justCreatedSessionRef.current = false;
                return;
            }

            setMessages([]);
            setMessageThoughts({});
            setHistoryLoading(true);

            getSessionHistory(localSessionId)
                .then(data => {
                    if (data && data.messages) {
                        setMessages(data.messages);

                        // Parse historical thoughts
                        const thoughtsMap: Record<number, ThoughtItem[]> = {};
                        data.messages.forEach((msg: any, idx: number) => {
                            if (msg.role !== 'user' && msg.thoughts) {
                                thoughtsMap[idx] = msg.thoughts;
                            }
                        });
                        setMessageThoughts(thoughtsMap);
                    }
                })
                .catch(err => {
                    console.error("Failed to load history:", err);
                    toast.error("Failed to load session history");
                })
                .finally(() => setHistoryLoading(false));
        } else {
            setMessages([]);
            setHistoryLoading(false);
        }
    }, [localSessionId]);

    // Auto-scroll
    const scrollToBottom = (instant = false) => {
        if (messagesEndRef.current) {
            messagesEndRef.current.scrollIntoView({ behavior: instant ? "auto" : "smooth" });
        }
    };

    useEffect(() => {
        scrollToBottom();
    }, [messages, activeThoughts, historyLoading]);

    // Update messageThoughts when activeThoughts change
    useEffect(() => {
        if (messages.length > 0 && activeThoughts.length > 0) {
            const lastIdx = messages.length - 1;
            setMessageThoughts(prev => ({
                ...prev,
                [lastIdx]: activeThoughts
            }));
        }
    }, [activeThoughts, messages.length]);

    const stopGeneration = () => {
        if (abortControllerRef.current) {
            abortControllerRef.current.abort();
            abortControllerRef.current = null;
            setIsLoading(false);
            toast.info("Generation stopped by user");
        }
    };

    const handleConfirm = async () => {
        if (!confirmationReq) return;
        setIsConfirming(true);
        try {
            const apiHost = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
            const res = await fetch(`http://${apiHost}:8088/api/chat/confirm`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    tool: confirmationReq.tool,
                    arguments: confirmationReq.arguments,
                    session_id: localSessionId
                })
            });

            if (!res.ok) throw new Error("Confirmation failed");
            const data = await res.json();

            setMessages(prev => [
                ...prev,
                { role: "user", content: `Verified action: ${confirmationReq.tool}` },
                { role: "assistant", content: data.output }
            ]);

            setConfirmationReq(null);
        } catch (e: any) {
            toast.error("Confirmation failed: " + e.message);
        } finally {
            setIsConfirming(false);
        }
    };

    const handleSubmit = async (overrideInput?: string) => {
        const textToSend = overrideInput || input;
        if (!textToSend.trim() || isLoading) return;

        let currentSessionId = localSessionId;
        if (!currentSessionId) {
            try {
                const newSession = await createSession(textToSend.slice(0, 30) + "...");
                if (newSession?.id) {
                    currentSessionId = newSession.id;
                    justCreatedSessionRef.current = true; // Mark as just created
                    setLocalSessionId(newSession.id);
                    window.history.pushState({}, "", `/?session=${newSession.id}`);
                    window.dispatchEvent(new Event("session-created"));
                }
            } catch (err) {
                console.error("Session creation error:", err);
                toast.error("Failed to create session");
                return;
            }
        }

        const userMsg: ChatMessage = { role: "user", content: textToSend };
        setMessages(prev => [...prev, userMsg]);
        setInput("");
        setIsLoading(true);
        setActiveThoughts([]);

        abortControllerRef.current = new AbortController();

        let queryToSend = textToSend;
        let mode = "auto";
        if (mcpContext === "chat") mode = "chat";
        else if (mcpContext === "k8s_remote") queryToSend += " (in remote k8s cluster)";
        else if (mcpContext === "k8s_local") queryToSend += " (in local k8s cluster)";
        else if (mcpContext === "docker") queryToSend += " (using docker only)";

        try {
            const apiHost = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
            const response = await fetch(`http://${apiHost}:8088/api/chat/stream`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    query: queryToSend,
                    session_id: currentSessionId,
                    mode: mode
                }),
                signal: abortControllerRef.current.signal,
            });

            if (!response.ok) throw new Error("Network error");
            if (!response.body) throw new Error("No response body");

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            let assistantMsg: ChatMessage = { role: "assistant", content: "" };

            setMessages(prev => [...prev, assistantMsg]);

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                const chunk = decoder.decode(value);
                buffer += chunk;
                const lines = buffer.split("\n\n");
                buffer = lines.pop() || "";

                for (const line of lines) {
                    if (line.startsWith("event:")) {
                        const match = line.match(/event: (.*)[\r\n]+data: (.*)/s);
                        if (match) {
                            const [_, eventType, dataStr] = match;
                            const type = eventType.trim();
                            const data = dataStr.trim();

                            if (type === "token") {
                                try {
                                    const json = JSON.parse(data);
                                    assistantMsg.content += json.token;
                                    setMessages(prev => {
                                        const next = [...prev];
                                        next[next.length - 1] = { ...assistantMsg };
                                        return next;
                                    });
                                } catch (e) {
                                    console.warn("Failed to parse token:", data);
                                }
                            } else if (["thought", "status", "tool_call", "error", "result"].includes(type)) {
                                // Only add if data is non-empty to avoid showing spurious entries
                                if (data && data.length > 0) {
                                    setActiveThoughts(prev => [...prev, { type: type as any, content: data }]);
                                }
                            } else if (type === "confirmation_request") {
                                const req = JSON.parse(data);
                                setConfirmationReq(req);
                                setIsLoading(false);
                            } else if (type === "done") {
                                setIsLoading(false);
                            }
                        }
                    }
                }
            }
        } catch (error: any) {
            if (error.name !== "AbortError") {
                toast.error(error.message);
                setMessages(prev => [...prev, { role: "assistant", content: "**Error:** " + error.message }]);
            }
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div className={styles.chatContainer}>
            <div className={styles.messagesArea} ref={scrollContainerRef}>
                {historyLoading ? (
                    <div className={styles.loadingOverlay}>
                        <div className={styles.spinner}></div>
                        <span>Restoring session...</span>
                    </div>
                ) : messages.length === 0 ? (
                    <EmptyState />
                ) : (
                    <div className={styles.messagesInner}>
                        {messages.map((m, i) => (
                            <MessageBubble
                                key={i}
                                role={m.role}
                                content={m.content}
                                thoughts={m.role === 'assistant' ? (i === messages.length - 1 ? activeThoughts : messageThoughts[i]) : undefined}
                                isStreaming={isLoading && i === messages.length - 1}
                            />
                        ))}
                        <div ref={messagesEndRef} style={{ height: '4px' }} />
                    </div>
                )}
            </div>

            <div className={styles.inputWrapper}>
                <ChatInput
                    input={input}
                    setInput={setInput}
                    onSubmit={() => handleSubmit()}
                    isLoading={isLoading}
                    onStop={stopGeneration}
                    mcpContext={mcpContext}
                    setMcpContext={setMcpContext}
                    disabled={!!confirmationReq}
                />
            </div>

            <AnimatePresence>
                {confirmationReq && (
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className={styles.overlay}
                    >
                        <motion.div
                            initial={{ scale: 0.95, y: 10 }}
                            animate={{ scale: 1, y: 0 }}
                            exit={{ scale: 0.95, y: 10 }}
                            className={styles.modal}
                        >
                            <div className={styles.modalHeader}>
                                <div className={styles.warningIcon}>
                                    <AlertTriangle size={20} />
                                </div>
                                <div>
                                    <h3 className={styles.modalTitle}>Security Check</h3>
                                    <p className={styles.modalSubtitle}>Please review before execution</p>
                                </div>
                            </div>

                            <div className={styles.modalContent}>
                                <div>
                                    <label className={styles.modalLabel}>Reasoning</label>
                                    <p className={styles.modalText}>{confirmationReq.risk?.reason}</p>
                                    {confirmationReq.risk?.impact_analysis && (
                                        <ul className={styles.impactList}>
                                            {confirmationReq.risk.impact_analysis.map((impact: string, idx: number) => (
                                                <li key={idx} className={styles.impactItem}>{impact}</li>
                                            ))}
                                        </ul>
                                    )}
                                </div>
                                <div>
                                    <label className={styles.modalLabel}>System Command</label>
                                    <div className={styles.codeBlock}>
                                        {confirmationReq.tool} <br />
                                        <span style={{ color: 'var(--fg-muted)', fontSize: '0.7rem' }}>
                                            {JSON.stringify(confirmationReq.arguments)}
                                        </span>
                                    </div>
                                </div>
                            </div>

                            <div className={styles.modalFooter}>
                                <button onClick={() => setConfirmationReq(null)} className={styles.cancelBtn}>
                                    Ignore
                                </button>
                                <button
                                    onClick={handleConfirm}
                                    disabled={isConfirming}
                                    className={styles.approveBtn}
                                >
                                    {isConfirming ? <div className={styles.spinner} style={{ width: 14, height: 14 }}></div> : (
                                        <>
                                            <CheckCircle2 size={16} />
                                            Execute Action
                                        </>
                                    )}
                                </button>
                            </div>
                        </motion.div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
}
