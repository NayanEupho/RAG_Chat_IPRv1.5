'use client';
/**
 * Sidebar Component
 * -----------------
 * Manages the conversation list, session creation/deletion, 
 * and displays system health/model configuration status.
 */
import { Plus, MessageSquare, Menu, Settings, Calendar, Trash2, BrainCircuit } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import NewChatModal from './NewChatModal';

interface Session {
    session_id: string;
    title: string;
    updated_at: string;
}

export default function Sidebar({
    currentSessionId,
    onSelectSession,
    onNewChat
}: {
    currentSessionId: string,
    onSelectSession: (id: string) => void,
    onNewChat?: () => void
}) {
    const [sessions, setSessions] = useState<Session[]>([]);
    const [config, setConfig] = useState<any>(null);
    const [systemHealth, setSystemHealth] = useState<boolean>(false);
    const [mainModelHealthy, setMainModelHealthy] = useState<boolean>(false);
    const [embedModelHealthy, setEmbedModelHealthy] = useState<boolean>(false);
    const [isOpen, setIsOpen] = useState(true);
    const [mounted, setMounted] = useState(false);
    const [isNewChatModalOpen, setIsNewChatModalOpen] = useState(false);
    const router = useRouter();

    // Dynamic API Base Detection
    const getApiBase = () => {
        if (typeof window !== 'undefined') {
            const hostname = window.location.hostname;
            return `http://${hostname}:8000/api`;
        }
        return 'http://localhost:8000/api';
    };

    // Fetch sessions
    const fetchSessions = async () => {
        try {
            const res = await fetch(`${getApiBase()}/sessions`);
            const data = await res.json();
            if (data && data.sessions) {
                setSessions(data.sessions);
            } else {
                setSessions([]);
            }
        } catch (err) {
            console.error("Failed to load sessions", err);
        }
    };


    // Check System Health (consolidated health & name check)
    const checkHealth = async () => {
        try {
            const res = await fetch(`${getApiBase()}/status`);
            if (res.ok) {
                const data = await res.json();
                setMainModelHealthy(data.main_model_healthy === true);
                setEmbedModelHealthy(data.embed_model_healthy === true);
                setSystemHealth(data.status === 'ok');
                setConfig(data); // Store full status as config for names
            } else {
                setMainModelHealthy(false);
                setEmbedModelHealthy(false);
                setSystemHealth(false);
                setConfig(null);
            }
        } catch (err) {
            setMainModelHealthy(false);
            setEmbedModelHealthy(false);
            setSystemHealth(false);
            setConfig(null);
        }
    }

    const handleCreateSession = async (title: string) => {
        try {
            const res = await fetch(`${getApiBase()}/sessions`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: title || 'New Conversation' })
            });
            const data = await res.json();
            if (data && data.session_id) {
                await fetchSessions(); // Refresh list immediately
                setIsNewChatModalOpen(false); // Close Modal

                // Use the callback if provided, otherwise update URL
                onSelectSession(data.session_id);
            }
        } catch (err) {
            console.error("Failed to create session", err);
        }
    };

    const handleDeleteSession = async (e: React.MouseEvent, id: string) => {
        e.stopPropagation();
        if (!confirm("Delete this session?")) return;

        try {
            await fetch(`${getApiBase()}/sessions/${id}`, { method: 'DELETE' });
            setSessions(prev => prev.filter(s => s.session_id !== id));
            if (currentSessionId === id) {
                // If deleted active session, go to root
                window.history.pushState({}, "", "/");
                window.dispatchEvent(new Event("session-deleted")); // Notify ChatInterface
            }
        } catch (err) {
            console.error("Failed to delete session", err);
        }
    }

    useEffect(() => {
        setMounted(true);
        // Initial Fetch
        fetchSessions();
        checkHealth();

        // Polling (Every 5s)
        const interval = setInterval(() => {
            fetchSessions();
            checkHealth();
        }, 5000);

        return () => clearInterval(interval);
    }, []);

    if (!mounted) return null;

    const toggleSidebar = () => setIsOpen(!isOpen);

    const formatDate = (dateStr: string) => {
        try {
            const date = new Date(dateStr);
            return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
        } catch {
            return '--';
        }
    };

    return (
        <>
            {/* Mobile Toggle */}
            <button
                className="new-chat-btn"
                style={{ position: 'fixed', top: '10px', left: '10px', zIndex: 50, width: 'auto', display: isOpen ? 'none' : 'flex' }}
                onClick={toggleSidebar}
            >
                <Menu size={20} />
            </button>

            <div className="sidebar" style={{ transform: isOpen ? 'translateX(0)' : 'translateX(-100%)', position: isOpen ? 'relative' : 'absolute' }}>

                {/* Header with Boxed Logo */}
                <div className="sidebar-header">
                    <div className="logo-container">
                        <div className="logo-icon">
                            <BrainCircuit size={20} />
                        </div>
                        <div>
                            <div className="logo-text">RAG Chat IPR</div>
                            <div className="logo-version">v2.0 PREVIEW</div>
                        </div>
                    </div>

                    <button onClick={() => setIsNewChatModalOpen(true)} className="new-chat-btn">
                        <Plus size={16} /> New Session
                    </button>
                </div>

                {/* Session List */}
                <div className="sidebar-content custom-scrollbar">
                    <div style={{ padding: '0 8px' }}>
                        {sessions.map(s => (
                            <div key={s.session_id} className="session-item-wrapper">
                                <button
                                    onClick={() => onSelectSession(s.session_id)}
                                    className={`session-btn ${currentSessionId === s.session_id ? 'active' : ''}`}
                                >
                                    <div className="session-title">{s.title}</div>
                                    <div className="session-date">{formatDate(s.updated_at)}</div>
                                </button>
                                <button
                                    className="delete-btn"
                                    onClick={(e) => handleDeleteSession(e, s.session_id)}
                                >
                                    <Trash2 size={14} />
                                </button>
                            </div>
                        ))}
                    </div>

                    {sessions.length === 0 && (
                        <div style={{ padding: '2rem 1rem', textAlign: 'center', fontSize: '0.8rem', color: 'var(--fg-muted)' }}>
                            No active sessions
                        </div>
                    )}
                </div>

                {/* Footer */}
                <div className="sidebar-footer" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: '12px' }}>

                    {/* AI Model Config Section */}
                    <div style={{ width: '100%' }}>
                        <div style={{ fontSize: '0.7rem', fontWeight: 600, color: 'var(--fg-muted)', textTransform: 'uppercase', marginBottom: '8px', letterSpacing: '0.05em' }}>
                            AI Model Config
                        </div>

                        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                            {/* Main Model */}
                            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '0.8rem', color: 'var(--fg-secondary)' }}>
                                <div style={{
                                    width: '8px', height: '8px', borderRadius: '50%',
                                    backgroundColor: mainModelHealthy ? 'var(--accent-secondary)' : 'var(--accent-error)',
                                    boxShadow: mainModelHealthy ? '0 0 5px var(--accent-secondary)' : 'none',
                                    transition: 'background-color 0.3s'
                                }}></div>
                                <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.2 }}>
                                    <span style={{ fontSize: '0.7rem', color: 'var(--fg-muted)' }}>Main Model</span>
                                    <span style={{ fontWeight: 500 }}>{config?.main_model_name || 'Disconnected'}</span>
                                </div>
                            </div>

                            {/* Embedding Model */}
                            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '0.8rem', color: 'var(--fg-secondary)' }}>
                                <div style={{
                                    width: '8px', height: '8px', borderRadius: '50%',
                                    backgroundColor: embedModelHealthy ? 'var(--accent-secondary)' : 'var(--accent-error)',
                                    boxShadow: embedModelHealthy ? '0 0 5px var(--accent-secondary)' : 'none',
                                    transition: 'background-color 0.3s'
                                }}></div>
                                <div style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.2 }}>
                                    <span style={{ fontSize: '0.7rem', color: 'var(--fg-muted)' }}>Embedding Model</span>
                                    <span style={{ fontWeight: 500 }}>{config?.embed_model_name || 'Disconnected'}</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', fontSize: '0.75rem', color: 'var(--fg-secondary)', marginTop: '8px', paddingTop: '8px', borderTop: '1px solid var(--border-subtle)', width: '100%' }}>
                        <div style={{
                            width: '8px', height: '8px', borderRadius: '50%',
                            backgroundColor: systemHealth ? 'var(--accent-primary)' : 'var(--accent-error)', // Blue for good, Red for bad (matches reference somewhat, user asked for blue)
                            boxShadow: systemHealth ? '0 0 5px var(--accent-primary)' : 'none',
                            transition: 'background-color 0.3s'
                        }}></div>
                        <span>{systemHealth ? 'System Operational' : 'System Offline'}</span>
                    </div>
                </div>
            </div>

            <NewChatModal
                isOpen={isNewChatModalOpen}
                onClose={() => setIsNewChatModalOpen(false)}
                onCreate={handleCreateSession}
            />
        </>
    );
}
