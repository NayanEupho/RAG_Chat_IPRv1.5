"use client";

import { useEffect, useState, Suspense } from "react";
import Link from "next/link";
import { useSearchParams, useRouter } from "next/navigation";
import { Settings, Play, RefreshCw, Server, Bot, Trash2, BrainCircuit, Plus } from "lucide-react";
import { getSessions, Session, createSession, getSystemStatus, startMCPServers, deleteSession } from "../lib/api";
import styles from "./Sidebar.module.css";
import ConfigModal from "./ConfigModal";
import NewChatModal from "./NewChatModal";
import MCPManager from "./MCPManager";

// Helper for hydration-safe date
function ClientDate({ date }: { date: string }) {
    const [mounted, setMounted] = useState(false);
    useEffect(() => setMounted(true), []);
    if (!mounted) return <span style={{ opacity: 0 }}>...</span>;
    try {
        return <span>{new Date(date).toLocaleDateString()}</span>;
    } catch {
        return <span>--</span>;
    }
}

// Inner component that uses useSearchParams
function SidebarContent() {
    const [sessions, setSessions] = useState<Session[]>([]);
    const [isConfigOpen, setIsConfigOpen] = useState(false);
    const [isNewChatOpen, setIsNewChatOpen] = useState(false);

    const [status, setStatus] = useState<any>(null);
    const [pulseStatus, setPulseStatus] = useState<any>(null);
    const [statusLoading, setStatusLoading] = useState(false);
    const [error, setError] = useState(false);

    // Selective MCP Startup
    const [selectedServers, setSelectedServers] = useState<Set<string>>(new Set(["docker", "k8s_local", "k8s_remote"]));

    const searchParams = useSearchParams();
    const router = useRouter();
    const currentSessionId = searchParams.get("session");

    useEffect(() => {
        loadSessions();
        checkStatus();
        checkPulse();

        const interval = setInterval(() => {
            checkStatus();
            checkPulse();
        }, 10000);

        // Listen for global command menu events
        const handleOpenSettings = () => setIsConfigOpen(true);
        const handleRefresh = () => loadSessions();

        window.addEventListener("open-settings", handleOpenSettings);
        window.dispatchEvent(new Event("session-created")); // actually triggers refresh? NO, we listen to it.
        window.addEventListener("session-created", handleRefresh);

        return () => {
            clearInterval(interval);
            window.removeEventListener("open-settings", handleOpenSettings);
            window.removeEventListener("session-created", handleRefresh);
        };
    }, []);

    async function loadSessions() {
        const data = await getSessions();
        setSessions(data);
    }

    async function checkStatus() {
        const s = await getSystemStatus();
        if (s) {
            setStatus(s);
            setError(false);
        } else {
            setError(true);
        }
    }

    async function checkPulse() {
        const { getPulseStatus } = await import("../lib/api");
        const p = await getPulseStatus();
        if (p) setPulseStatus(p);
    }

    function toggleServerSelection(server: string) {
        const newSet = new Set(selectedServers);
        if (newSet.has(server)) newSet.delete(server);
        else newSet.add(server);
        setSelectedServers(newSet);
    }

    async function handleStartServers() {
        if (selectedServers.size === 0) return; // Nothing to start

        setStatusLoading(true);
        await startMCPServers(Array.from(selectedServers));
        setTimeout(checkStatus, 4000);
        setTimeout(() => setStatusLoading(false), 5000);
    }

    async function handleCreateSession(title: string) {
        setIsNewChatOpen(false);
        const session = await createSession(title);
        if (session) {
            await loadSessions();
            router.push(`/?session=${session.id}`);
        }
    }

    async function handleDeleteSession(e: React.MouseEvent, id: string) {
        e.preventDefault();
        e.stopPropagation();

        if (!confirm("Are you sure you want to delete this session permanently?")) return;

        await deleteSession(id);

        // Optimistic UI update
        setSessions(prev => prev.filter(s => s.id !== id));

        if (currentSessionId === id) {
            router.push("/");
        }
    }

    return (
        <aside className={styles.sidebar}>
            <div className={styles.header}>
                <div className={styles.logoContainer}>
                    <div className={styles.logoIcon}>
                        <BrainCircuit size={20} />
                    </div>
                    <div>
                        <div className={styles.logoText}>DevOps Agent</div>
                        <div className={styles.logoVersion}>v2.0 PREVIEW</div>
                    </div>
                </div>
                <button onClick={() => setIsNewChatOpen(true)} className={styles.newButton}>
                    <Plus size={16} /> New Session
                </button>
            </div>

            <div className={styles.list}>
                {sessions.map((s) => (
                    <div key={s.id} className={styles.itemWrapper}>
                        <Link
                            href={`/?session=${s.id}`}
                            className={`${styles.item} ${s.id === currentSessionId ? styles.active : ""}`}
                            suppressHydrationWarning
                        >
                            <div className={styles.itemTitle}>{s.title || "Untitled Session"}</div>
                            <div className={styles.itemMeta}>
                                <ClientDate date={s.last_activity} />
                            </div>
                        </Link>
                        <button
                            className={styles.deleteBtn}
                            onClick={(e) => handleDeleteSession(e, s.id)}
                            title="Delete Session"
                        >
                            <Trash2 size={14} />
                        </button>
                    </div>
                ))}
            </div>

            <div className={styles.footer}>
                {status?.agents ? (
                    <div className={styles.statusGroup}>
                        <div className={styles.sectionTitle}><Bot size={12} /> Agents</div>
                        <div className={styles.statusRow}>
                            <div className={`${styles.statusIndicator} ${status.agents.fast.active ? styles.dotGreen : styles.dotRed}`} />
                            <div>
                                <div className={styles.label}>Fast · <span className={styles.subModel}>{status.agents.fast.model}</span></div>
                            </div>
                        </div>
                        <div className={styles.statusRow}>
                            <div className={`${styles.statusIndicator} ${status.agents.smart.active ? styles.dotGreen : styles.dotRed}`} />
                            <div>
                                <div className={styles.label}>Smart · <span className={styles.subModel}>{status.agents.smart.model}</span></div>
                            </div>
                        </div>
                        {status.agents.embedding && (
                            <div className={styles.statusRow}>
                                <div className={`${styles.statusIndicator} ${status.agents.embedding.active ? styles.dotGreen : styles.dotRed}`} />
                                <div>
                                    <div className={styles.label}>Embedding · <span className={styles.subModel}>{status.agents.embedding.model}</span></div>
                                </div>
                            </div>
                        )}

                        <div className={styles.sectionTitle} style={{ marginTop: "4px" }}><Server size={12} /> Live MCPs</div>
                        <MCPManager status={status} pulseStatus={pulseStatus} refreshStatus={checkStatus} />
                    </div>
                ) : (
                    <div className={styles.status} style={{ color: error ? 'var(--accent-error)' : 'var(--fg-muted)', fontSize: '0.8rem' }}>
                        {error ? "🔴 Connection Failed" : "🟡 Connecting..."}
                    </div>
                )}

                <button className={styles.settingsBtn} onClick={() => setIsConfigOpen(true)}>
                    <Settings size={14} /> Settings
                </button>
            </div>

            <ConfigModal isOpen={isConfigOpen} onClose={() => setIsConfigOpen(false)} />
            <NewChatModal isOpen={isNewChatOpen} onClose={() => setIsNewChatOpen(false)} onCreate={handleCreateSession} />
        </aside>
    );
}

// Outer wrapper with Suspense boundary for useSearchParams
export default function Sidebar() {
    return (
        <Suspense fallback={<aside className={styles.sidebar}><div className={styles.header}>Loading...</div></aside>}>
            <SidebarContent />
        </Suspense>
    );
}
