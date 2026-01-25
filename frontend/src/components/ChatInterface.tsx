'use client';
import { useChat } from '@/hooks/useChat';
import { useRef, useEffect, useState, useCallback } from 'react';
import Sidebar from './Sidebar';
import ThinkingProcess from './ThinkingProcess';
import { toast } from 'sonner';
import {
    Send, Cpu, Database, FileText, ChevronRight, Sparkles,
    Square, X, Copy, Check, User, Bot, Search, Brain, AtSign, ArrowUpRight, Target, Info
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { useRouter, useSearchParams } from 'next/navigation';
import ModeSelector, { InteractionMode } from './ModeSelector';

export default function ChatInterface() {
    const {
        messages, sendMessage, loading, currentStatus,
        sessionId, stopGeneration, fetchDocuments,
        setSessionId, loadHistory
    } = useChat();

    const bottomRef = useRef<HTMLDivElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const [copiedIdx, setCopiedIdx] = useState<number | null>(null);
    const router = useRouter();
    const searchParams = useSearchParams();

    // Handle URL params on mount/update
    useEffect(() => {
        const urlSession = searchParams.get('session');
        if (urlSession && urlSession !== sessionId) {
            setSessionId(urlSession);
            loadHistory(urlSession);
            localStorage.setItem('rag_session_id', urlSession);
        }
    }, [searchParams, sessionId, setSessionId, loadHistory]);

    // Modal State
    const [isModalOpen, setIsModalOpen] = useState(false);
    const [modalTitle, setModalTitle] = useState('');
    const [modalContent, setModalContent] = useState<any>('');
    const [modalType, setModalType] = useState<'source' | 'docs'>('source');

    // @Mentions State
    const [allDocs, setAllDocs] = useState<string[]>([]);
    const [inputValue, setInputValue] = useState('');
    const [showMentions, setShowMentions] = useState(false);
    const [mentionQuery, setMentionQuery] = useState('');
    const [mentionIndex, setMentionIndex] = useState(0);
    const [loadingDocs, setLoadingDocs] = useState(false);
    const [activeMode, setActiveMode] = useState<InteractionMode>('auto');

    // Initial Load
    useEffect(() => {
        const loadDocs = async () => {
            setLoadingDocs(true);
            const docs = await fetchDocuments();
            console.log(`[ChatInterface] Knowledge Base loaded: ${docs.length} files`);
            setAllDocs(docs);
            setLoadingDocs(false);
        };
        loadDocs();
    }, [fetchDocuments]);

    // Auto-scroll to bottom
    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages, currentStatus]);

    // Auto-resize textarea
    const adjustTextareaHeight = useCallback(() => {
        const textarea = textareaRef.current;
        if (textarea) {
            textarea.style.height = 'auto';
            textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
        }
    }, []);

    // Listen for session deletion
    useEffect(() => {
        const handleSessionDeleted = () => {
            localStorage.removeItem('rag_session_id');
            window.location.href = '/';
        };
        window.addEventListener('session-deleted', handleSessionDeleted);
        return () => window.removeEventListener('session-deleted', handleSessionDeleted);
    }, []);

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (showMentions) {
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                setMentionIndex(prev => (prev + 1) % filteredDocs.length);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                setMentionIndex(prev => (prev - 1 + filteredDocs.length) % filteredDocs.length);
            } else if (e.key === 'Enter') {
                e.preventDefault();
                if (filteredDocs[mentionIndex]) {
                    insertMention(filteredDocs[mentionIndex]);
                }
            } else if (e.key === 'Escape') {
                setShowMentions(false);
            }
            // Removed ' ' check to allow multi-word filenames in mentions
            return;
        }

        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            triggerSend();
        }
        if (e.key === 'Escape' && loading) {
            stopGeneration();
        }
    };

    const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
        const value = e.target.value;
        setInputValue(value);
        const cursorPos = e.target.selectionStart;

        adjustTextareaHeight();

        // 1. Find the last word starting with '@' before or at the cursor
        const textBeforeCursor = value.substring(0, cursorPos);

        // Find the last '@' that is either at the start of string or preceded by whitespace/punctuation
        const words = textBeforeCursor.split(/[\s\n]/);
        const lastWord = words[words.length - 1];

        if (lastWord.startsWith('@')) {
            const query = lastWord.substring(1);

            // Proactive refresh if list is empty or first time typing @
            if (allDocs.length === 0 && !loadingDocs) {
                setLoadingDocs(true);
                fetchDocuments().then(docs => {
                    if (docs && docs.length > 0) setAllDocs(docs);
                    setLoadingDocs(false);
                });
            }

            setShowMentions(true);
            setMentionQuery(query);
            setMentionIndex(0);
            return;
        }
        setShowMentions(false);
    };

    const insertMention = (docName: string) => {
        if (!textareaRef.current) return;
        const textarea = textareaRef.current;
        const value = textarea.value;
        const cursorPos = textarea.selectionStart;
        const textBeforeCursor = value.substring(0, cursorPos);
        const textAfterCursor = value.substring(cursorPos);
        const lastAtPos = textBeforeCursor.lastIndexOf('@');

        const newValue = value.substring(0, lastAtPos) + `@${docName} ` + textAfterCursor;

        setInputValue(newValue);
        setShowMentions(false);
        textarea.focus();

        // Move cursor to after the inserted mention
        const newCursorPos = lastAtPos + docName.length + 2; // +1 for @, +1 for space
        textarea.setSelectionRange(newCursorPos, newCursorPos);
        adjustTextareaHeight();
    };

    const triggerSend = () => {
        if (loading) return;
        if (inputValue.trim()) {
            sendMessage(inputValue, activeMode);
            setInputValue('');
            if (textareaRef.current) {
                textareaRef.current.style.height = 'auto';
            }
        }
    };

    const openSourceModal = (sourceName: string, fullContent: string) => {
        setModalTitle(sourceName);
        setModalContent(fullContent);
        setModalType('source');
        setIsModalOpen(true);
    };

    const handleShowDocuments = async () => {
        setModalTitle('Embedded Knowledge Base');
        setModalType('docs');
        setIsModalOpen(true);
        setModalContent('loading');
        const docs = await fetchDocuments();
        setAllDocs(docs); // Sync while we are at it
        setModalContent(docs);
    };

    const copyToClipboard = async (text: string, idx?: number) => {
        try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(text);
            } else {
                // Fallback for environments where navigator.clipboard is not available
                const textArea = document.createElement("textarea");
                textArea.value = text;
                textArea.style.position = "fixed";
                textArea.style.left = "-9999px";
                document.body.appendChild(textArea);
                textArea.focus();
                textArea.select();
                try {
                    document.execCommand('copy');
                } catch (err) {
                    console.error('Fallback: Oops, unable to copy', err);
                    throw new Error("Clipboard API unavailable");
                }
                document.body.removeChild(textArea);
            }

            if (idx !== undefined) {
                setCopiedIdx(idx);
                setTimeout(() => setCopiedIdx(null), 2000);
            }
            toast.success("Copied to clipboard");
        } catch (err) {
            console.error("Failed to copy:", err);
            toast.error("Failed to copy to clipboard");
        }
    };

    // Unified filteredDocs logic for modern tagging
    const filteredDocs = allDocs.filter(doc => {
        const lowerDoc = doc.toLowerCase();
        const lowerQuery = mentionQuery.toLowerCase();

        // 1. Fuzzy match: Check if query is in doc name, or if "clean" versions match
        // Remove common separators for a more forgiving match
        const cleanDoc = lowerDoc.replace(/[\s\-_]/g, '');
        const cleanQuery = lowerQuery.replace(/[\s\-_]/g, '');

        const matches = lowerDoc.includes(lowerQuery) || cleanDoc.includes(cleanQuery);

        // 2. Uniqueness: Check if file is already mentioned in textarea (safely)
        // We look for the exact "@filename " pattern (with space) to consider it truly tagged
        const isAlreadyTagged = inputValue.toLowerCase().includes(`@${lowerDoc} `);

        return matches && !isAlreadyTagged;
    }).slice(0, 10);



    return (
        <div className="app-container">
            <Sidebar
                currentSessionId={sessionId}
                onSelectSession={(id) => {
                    // Client-side navigation
                    setSessionId(id);
                    loadHistory(id);
                    localStorage.setItem('rag_session_id', id);
                    router.push(`/?session=${id}`);
                }}
            />

            <div className="main-chat-area">
                <div style={{ position: 'absolute', inset: 0, zIndex: 0, opacity: 0.4, background: 'radial-gradient(circle at 50% -20%, rgba(59, 130, 246, 0.15), transparent 70%)', pointerEvents: 'none' }}></div>

                <div className="messages-container">
                    <div className="messages-wrapper">
                        {messages.map((msg, idx) => (
                            <div key={idx} className={`message-row ${msg.role === 'user' ? 'user-row' : 'bot-row'} animate-fade-in-up`}>
                                <div className={`message-bubble ${msg.role}`}>
                                    {msg.role === 'bot' && (
                                        <>
                                            <div className="message-meta">
                                                <div className="flex flex-col gap-1">
                                                    {msg.targeted_docs && msg.targeted_docs.length > 0 ? (
                                                        <span className="meta-intent flex items-center gap-1" style={{ color: 'var(--accent-secondary)', fontWeight: 700 }}>
                                                            <Target size={12} className="animate-pulse" /> Targeted Search: {msg.targeted_docs.join(', ')}
                                                        </span>
                                                    ) : msg.intent?.includes('rag') ? (
                                                        <span className="meta-intent" style={{ color: 'var(--accent-secondary)' }}>
                                                            <Database size={12} /> Knowledge Verified
                                                        </span>
                                                    ) : (
                                                        <span className="meta-intent" style={{ color: 'var(--accent-primary)' }}>
                                                            <Cpu size={12} /> RAG Chat IPR
                                                        </span>
                                                    )}
                                                </div>
                                                <button style={{ marginLeft: 'auto', opacity: 0.6 }} onClick={() => copyToClipboard(msg.content, idx)}>
                                                    {copiedIdx === idx ? <Check size={14} /> : <Copy size={14} />}
                                                </button>
                                            </div>

                                            {/* Thinking Process Integration */}
                                            {msg.thoughts && msg.thoughts.length > 0 && (
                                                <ThinkingProcess thoughts={msg.thoughts} isFinished={!loading || idx !== messages.length - 1} />
                                            )}

                                            {/* Premium Source Strip (Top Placement) */}
                                            {msg.sources && msg.sources.length > 0 && (
                                                <div className="source-strip custom-scrollbar">
                                                    {msg.sources.map((src, i) => {
                                                        // Platinum Envelope Parsing
                                                        // Structure: Source: ... \nSection: ... \nVisual: ... \nContent: ...

                                                        const contentParts = src.split('\nContent: ');
                                                        const metadataBlock = contentParts[0];
                                                        const content = contentParts[1] || '';

                                                        // Extract fields
                                                        const sourceMatch = metadataBlock.match(/Source: (.*?)(?:\n|$)/);
                                                        const sectionMatch = metadataBlock.match(/Section: (.*?)(?:\n|$)/);
                                                        const visualMatch = metadataBlock.match(/Visual: (.*?)(?:\n|$)/);

                                                        const sourceName = sourceMatch ? sourceMatch[1].trim() : 'Unknown Source';
                                                        const displayTitle = sourceName.split('/').pop() || sourceName;

                                                        const visualTag = visualMatch ? visualMatch[1] : null;
                                                        const isTargeted = msg.targeted_docs?.some(d => sourceName.includes(d));

                                                        return (
                                                            <button
                                                                key={i}
                                                                className="source-strip-card"
                                                                onClick={() => openSourceModal(sourceName, content)}
                                                                title={`View Source ${i + 1}`}
                                                                style={isTargeted ? { borderColor: 'var(--accent-secondary)', boxShadow: '0 0 8px rgba(59, 130, 246, 0.2)' } : {}}
                                                            >
                                                                <div className="source-badge" style={isTargeted ? { background: 'var(--accent-secondary)' } : {}}>{i + 1}</div>
                                                                <div className="source-card-header">
                                                                    <FileText size={12} />
                                                                    <div className="source-card-title" style={isTargeted ? { fontWeight: 700 } : {}}>
                                                                        {displayTitle}
                                                                        {visualTag && <span style={{ marginLeft: '6px', fontSize: '0.65rem', padding: '1px 4px', borderRadius: '3px', background: 'rgba(255,255,255,0.1)', color: 'var(--accent-secondary)' }}>{visualTag.split(']')[0] + ']'}</span>}
                                                                    </div>
                                                                </div>
                                                                <div className="source-card-preview">
                                                                    {content.substring(0, 100)}...
                                                                </div>
                                                            </button>
                                                        );
                                                    })}
                                                </div>
                                            )}
                                        </>
                                    )}

                                    {/* User Message Header */}
                                    {msg.role === 'user' && (
                                        <div className="message-meta" style={{ borderBottomColor: 'rgba(255,255,255,0.2)' }}>
                                            <span style={{ fontSize: '0.75rem', fontWeight: 500, opacity: 0.9 }}>You</span>
                                            <button
                                                onClick={() => copyToClipboard(msg.content, idx)}
                                                style={{ marginLeft: 'auto', opacity: 0.8, display: 'flex', alignItems: 'center' }}
                                                title="Copy Message"
                                            >
                                                {copiedIdx === idx ? <Check size={14} /> : <Copy size={14} />}
                                            </button>
                                        </div>
                                    )}

                                    <div className="markdown-content">
                                        <ReactMarkdown
                                            remarkPlugins={[remarkGfm]}
                                            components={{
                                                code({ node, className, children, ...props }) {
                                                    const match = /language-(\w+)/.exec(className || '')
                                                    const inline = !className;
                                                    const codeContent = String(children).replace(/\n$/, '');

                                                    return !inline && match ? (
                                                        <div style={{ position: 'relative', marginTop: '1rem', marginBottom: '1rem' }}>
                                                            <div style={{
                                                                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                                                                background: 'rgba(255,255,255,0.05)', padding: '6px 12px',
                                                                borderTopLeftRadius: '6px', borderTopRightRadius: '6px',
                                                                borderBottom: '1px solid var(--border-subtle)',
                                                                fontSize: '0.75rem', color: 'var(--fg-muted)', fontFamily: 'var(--font-mono)'
                                                            }}>
                                                                <span>{match[1]}</span>
                                                                <button
                                                                    onClick={() => copyToClipboard(codeContent)}
                                                                    style={{ display: 'flex', alignItems: 'center', gap: '4px', background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--fg-secondary)' }}
                                                                    title="Copy Code"
                                                                >
                                                                    <Copy size={12} /> Copy
                                                                </button>
                                                            </div>
                                                            <SyntaxHighlighter
                                                                style={vscDarkPlus as any}
                                                                language={match[1]}
                                                                PreTag="div"
                                                                customStyle={{ margin: 0, borderTopLeftRadius: 0, borderTopRightRadius: 0 }}
                                                                {...(props as any)}
                                                            >
                                                                {codeContent}
                                                            </SyntaxHighlighter>
                                                        </div>
                                                    ) : (
                                                        <code className={className} {...props}>
                                                            {children}
                                                        </code>
                                                    )
                                                }
                                            }}
                                        >
                                            {msg.content}
                                        </ReactMarkdown>
                                    </div>


                                </div>
                            </div>
                        ))}
                        <div ref={bottomRef} />
                    </div>
                </div>

                <div className="input-area">
                    <div className="relative w-full" style={{ maxWidth: '800px', margin: '0 auto' }}>
                        {/* Mentions Dropdown */}
                        {showMentions && (
                            <div style={{
                                position: 'absolute', bottom: '100%', left: 0, marginBottom: '10px',
                                background: 'rgba(15, 15, 15, 0.95)', backdropFilter: 'blur(24px)',
                                border: '1px solid rgba(59, 130, 246, 0.3)',
                                borderRadius: '12px', width: '280px', overflow: 'hidden', zIndex: 60,
                                boxShadow: '0 10px 40px rgba(0,0,0,0.6)',
                                animation: 'fadeIn 0.2s ease-out'
                            }}>
                                <div style={{ padding: '10px 14px', fontSize: '0.7rem', color: 'var(--accent-secondary)', borderBottom: '1px solid rgba(255,255,255,0.05)', fontWeight: 700, letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                    <Database size={12} /> KNOWLEDGE BASE ({loadingDocs ? 'LOADING...' : `${allDocs.length} FILES`})
                                </div>
                                {loadingDocs ? (
                                    <div style={{ padding: '24px 14px', textAlign: 'center', color: 'var(--fg-muted)', fontSize: '0.85rem' }}>
                                        <div className="animate-pulse">Fetching documents...</div>
                                    </div>
                                ) : filteredDocs.length > 0 ? (
                                    filteredDocs.map((doc, i) => (
                                        <div
                                            key={doc}
                                            style={{
                                                padding: '12px 14px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '10px',
                                                background: i === mentionIndex ? 'rgba(59, 130, 246, 0.2)' : 'transparent',
                                                transition: 'all 0.1s ease',
                                                borderLeft: i === mentionIndex ? '3px solid var(--accent-secondary)' : '3px solid transparent'
                                            }}
                                            onClick={() => insertMention(doc)}
                                            onMouseEnter={() => setMentionIndex(i)}
                                        >
                                            <div style={{
                                                width: '24px', height: '24px', borderRadius: '6px',
                                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                                background: i === mentionIndex ? 'var(--accent-secondary)' : 'rgba(255,255,255,0.05)',
                                                color: i === mentionIndex ? 'white' : 'var(--fg-muted)'
                                            }}>
                                                <AtSign size={12} />
                                            </div>
                                            <span style={{
                                                fontSize: '0.85rem',
                                                fontWeight: i === mentionIndex ? 600 : 400,
                                                color: i === mentionIndex ? 'white' : 'var(--fg-secondary)',
                                                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'
                                            }}>
                                                {doc}
                                            </span>
                                            {i === mentionIndex && <ChevronRight size={14} style={{ marginLeft: 'auto', opacity: 0.8 }} className="animate-pulse" />}
                                        </div>
                                    ))
                                ) : (
                                    <div style={{ padding: '24px 14px', textAlign: 'center', color: 'var(--fg-muted)', fontSize: '0.85rem', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
                                        <Info size={18} opacity={0.5} />
                                        <span>No documents matched.</span>
                                    </div>
                                )}
                            </div>
                        )}

                        <div className="input-container-glass">
                            <button
                                onClick={handleShowDocuments}
                                style={{ padding: '9px', color: 'var(--fg-muted)', display: 'flex', alignItems: 'center', marginBottom: '1px' }}
                                title="Knowledge Base"
                            >
                                <Database size={20} />
                            </button>
                            <textarea
                                ref={textareaRef}
                                className="chat-textarea custom-scrollbar"
                                placeholder="Ask anything..."
                                onKeyDown={handleKeyDown}
                                onChange={handleTextareaChange}
                                value={inputValue}
                                rows={1}
                                disabled={loading}
                            />
                            <ModeSelector
                                value={activeMode}
                                onChange={setActiveMode}
                                disabled={loading}
                            />
                            {loading ? (
                                <button
                                    onClick={stopGeneration}
                                    className="stop-btn"
                                    title="Stop generating"
                                >
                                    <Square size={20} fill="currentColor" />
                                </button>
                            ) : (
                                <button
                                    onClick={triggerSend}
                                    disabled={!inputValue.trim()}
                                    className="send-btn"
                                    title="Send message"
                                >
                                    <Send size={20} />
                                </button>
                            )}
                        </div>
                        <div style={{ textAlign: 'center', marginTop: '12px', fontSize: '0.7rem', color: 'var(--fg-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
                            IPR Agent v2.0 • AI can make mistakes.
                        </div>
                    </div>
                </div>
            </div>

            {/* Source Modal */}
            {isModalOpen && (
                <div className="modal-overlay" onClick={() => setIsModalOpen(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()}>
                        <div className="modal-header">
                            <div className="flex items-center gap-2">
                                <FileText size={18} color="var(--accent-secondary)" />
                                <h3 style={{ fontSize: '1.1rem', fontWeight: 600 }}>{modalTitle}</h3>
                            </div>
                            <button className="close-btn" onClick={() => setIsModalOpen(false)}>
                                <X size={24} />
                            </button>
                        </div>
                        <div className="modal-body custom-scrollbar">
                            {modalType === 'source' ? (
                                <ReactMarkdown
                                    remarkPlugins={[remarkGfm]}
                                    components={{
                                        code({ node, className, children, ...props }) {
                                            const match = /language-(\w+)/.exec(className || '')
                                            const inline = !className;
                                            return !inline && match ? (
                                                <SyntaxHighlighter
                                                    style={vscDarkPlus as any}
                                                    language={match[1]}
                                                    PreTag="div"
                                                    {...(props as any)}
                                                >
                                                    {String(children).replace(/\n$/, '')}
                                                </SyntaxHighlighter>
                                            ) : (
                                                <code className={className} {...props}>
                                                    {children}
                                                </code>
                                            )
                                        }
                                    }}
                                >
                                    {modalContent}
                                </ReactMarkdown>
                            ) : modalContent === 'loading' ? (
                                <div className="flex flex-col gap-3">
                                    <div style={{ height: '20px', background: 'rgba(255,255,255,0.05)', borderRadius: '4px' }}></div>
                                    <div style={{ height: '20px', background: 'rgba(255,255,255,0.05)', borderRadius: '4px' }}></div>
                                </div>
                            ) : (
                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '12px' }}>
                                    {modalContent && modalContent.length > 0 ? (
                                        modalContent.map((doc: string, i: number) => (
                                            <div key={i} className="animate-fade-in-up" style={{
                                                animationDelay: `${i * 0.05}s`,
                                                padding: '12px', background: 'rgba(255,255,255,0.03)',
                                                border: '1px solid var(--border-subtle)', borderRadius: '10px',
                                                display: 'flex', alignItems: 'center', gap: '8px'
                                            }}>
                                                <FileText size={20} color="var(--accent-primary)" />
                                                <div style={{ fontSize: '0.85rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{doc}</div>
                                            </div>
                                        ))
                                    ) : (
                                        <div style={{ gridColumn: '1 / -1', textAlign: 'center', color: 'var(--fg-muted)', padding: '2rem' }}>
                                            No documents indexed yet.
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
