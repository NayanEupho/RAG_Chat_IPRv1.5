'use client';
/**
 * Main Chat Interface Component
 * ----------------------------
 * The primary view for user interaction. Handles:
 * - Real-time message rendering with Markdown support.
 * - @Mention system for file targeting.
 * - Connection to the RAG backend via useChat hook.
 * - Navigation and session management.
 */
import { useChat } from '@/hooks/useChat';
import React, { useRef, useEffect, useState, useCallback } from 'react';
import Sidebar from './Sidebar';
import UserMenu from './UserMenu';
import ThinkingProcess from './ThinkingProcess';
import { toast } from 'sonner';
import {
    Send, Cpu, Database, FileText, ChevronRight,
    Square, X, Copy, Check, AtSign, Target, Info, ArrowUpRight
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { useRouter, useSearchParams } from 'next/navigation';
import ModeSelector, { InteractionMode } from './ModeSelector';

export default function ChatInterface() {
    const {
        messages, sendMessage, loading,
        sessionId, stopGeneration, fetchDocuments,
        setSessionId, loadHistory, startEmptySession
    } = useChat();

    const bottomRef = useRef<HTMLDivElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const scrollFrameRef = useRef<number | null>(null);
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
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const [modalContent, setModalContent] = useState<any>([]);
    const [modalType, setModalType] = useState<'source' | 'docs'>('source');
    const [expandedSources, setExpandedSources] = useState<Record<number, boolean>>({});

    // @Mentions State
    const [allDocs, setAllDocs] = useState<string[]>([]);
    const [inputValue, setInputValue] = useState('');
    const [kbSearch, setKbSearch] = useState('');
    const [showMentions, setShowMentions] = useState(false);
    const [mentionQuery, setMentionQuery] = useState('');
    const [mentionIndex, setMentionIndex] = useState(0);
    const [mentionPosition, setMentionPosition] = useState<{ left: number; top: number } | null>(null);
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
        if (scrollFrameRef.current !== null) return;

        scrollFrameRef.current = window.requestAnimationFrame(() => {
            scrollFrameRef.current = null;
            bottomRef.current?.scrollIntoView({
                behavior: loading ? 'auto' : 'smooth',
                block: 'end'
            });
        });

        return () => {
            if (scrollFrameRef.current !== null) {
                window.cancelAnimationFrame(scrollFrameRef.current);
                scrollFrameRef.current = null;
            }
        };
    }, [messages, loading]);

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
            setSessionId('');
            startEmptySession('');
            router.push('/');
        };
        window.addEventListener('session-deleted', handleSessionDeleted);
        return () => window.removeEventListener('session-deleted', handleSessionDeleted);
    }, [router, setSessionId, startEmptySession]);

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

    const updateMentionPosition = useCallback((textarea: HTMLTextAreaElement, cursorPos: number) => {
        const styles = window.getComputedStyle(textarea);
        const mirror = document.createElement('div');
        const properties: Array<[string, string]> = [
            ['box-sizing', 'box-sizing'],
            ['width', 'width'],
            ['font-family', 'font-family'],
            ['font-size', 'font-size'],
            ['font-weight', 'font-weight'],
            ['letter-spacing', 'letter-spacing'],
            ['line-height', 'line-height'],
            ['padding-top', 'padding-top'],
            ['padding-right', 'padding-right'],
            ['padding-bottom', 'padding-bottom'],
            ['padding-left', 'padding-left'],
            ['border-top-width', 'border-top-width'],
            ['border-right-width', 'border-right-width'],
            ['border-bottom-width', 'border-bottom-width'],
            ['border-left-width', 'border-left-width']
        ];

        properties.forEach(([target, source]) => {
            mirror.style.setProperty(target, styles.getPropertyValue(source));
        });

        mirror.style.position = 'fixed';
        mirror.style.left = `${textarea.getBoundingClientRect().left}px`;
        mirror.style.top = `${textarea.getBoundingClientRect().top}px`;
        mirror.style.visibility = 'hidden';
        mirror.style.whiteSpace = 'pre-wrap';
        mirror.style.wordBreak = 'break-word';
        mirror.style.overflowWrap = 'break-word';
        mirror.style.maxHeight = styles.maxHeight;
        mirror.style.overflow = 'hidden';

        const beforeCaret = textarea.value.substring(0, cursorPos);
        const marker = document.createElement('span');
        marker.textContent = '\u200b';
        mirror.textContent = beforeCaret;
        mirror.appendChild(marker);
        document.body.appendChild(mirror);

        const markerRect = marker.getBoundingClientRect();
        const left = Math.min(Math.max(12, markerRect.left), window.innerWidth - 332);
        const top = Math.max(16, markerRect.top - textarea.scrollTop);
        setMentionPosition({ left, top });
        document.body.removeChild(mirror);
    }, []);

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
            updateMentionPosition(e.target, cursorPos);
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

    /**
     * Extracts the filename/title from a Platinum Document Envelope string.
     * Preserves the full structural fidelity of the content for the modal.
     */
    const parseEnvelopeTitle = (envelope: string) => {
        // Handle [Source: filename.pdf | Section: ...] or [Q&A | Source: ...]
        const match = envelope.match(/Source:\s*([^|\]\n]+)/);
        if (match && match[1]) {
            const rawTitle = match[1].trim();
            return rawTitle.split('/').pop() || rawTitle;
        }
        return "Document Chunk";
    };

    const parseEnvelopeMeta = (envelope: string) => {
        const title = parseEnvelopeTitle(envelope);
        const section = envelope.match(/Section(?:Path)?:\s*([^\]\n]+)/)?.[1]?.trim();
        const chunkKind = envelope.match(/ChunkKind:\s*([^\]\n]+)/)?.[1]?.trim();
        const chunkIndex = envelope.match(/ChunkIndex:\s*([^\]\n]+)/)?.[1]?.trim();
        const preview = envelope
            .split('\n')
            .filter(line => !line.trim().startsWith('['))
            .join(' ')
            .replace(/\s+/g, ' ')
            .trim();

        return {
            title,
            section,
            chunkKind,
            chunkIndex,
            preview: preview || envelope.replace(/\s+/g, ' ').trim()
        };
    };

    const renderCitationChildren = (children: React.ReactNode, sources?: string[]) => {
        if (!sources || sources.length === 0) return children;

        return React.Children.map(children, child => {
            if (typeof child !== 'string') return child;

            const parts = child.split(/(\[\d+\])/g);
            return parts.map((part, partIdx) => {
                const match = part.match(/^\[(\d+)\]$/);
                if (!match) return part;

                const sourceIndex = Number(match[1]) - 1;
                const source = sources[sourceIndex];
                if (!source) return part;

                const title = parseEnvelopeTitle(source);
                return (
                    <button
                        key={`${part}-${partIdx}`}
                        className="inline-citation"
                        onClick={() => openSourceModal(title, source)}
                        title={`Open source ${match[1]}: ${title}`}
                    >
                        {match[1]}
                    </button>
                );
            });
        });
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

    const getApiBase = () => {
        return "/api";
    };

    const handleOpenFile = (filename: string) => {
        const url = `${getApiBase()}/files/${encodeURIComponent(filename)}`;
        window.open(url, '_blank');
        toast.info(`Opening ${filename}...`);
    };

    const handleShowDocuments = async () => {
        setModalTitle('Embedded Knowledge Base');
        setModalType('docs');
        setIsModalOpen(true);
        setKbSearch('');
        setModalContent(allDocs);
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

    const fuzzyFileMatch = (doc: string, query: string) => {
        const normalizedDoc = doc.toLowerCase();
        const normalizedQuery = query.trim().toLowerCase();
        if (!normalizedQuery) return true;
        if (normalizedDoc.includes(normalizedQuery)) return true;
        let cursor = 0;
        for (const char of normalizedQuery.replace(/[\s._-]+/g, '')) {
            cursor = normalizedDoc.replace(/[\s._-]+/g, '').indexOf(char, cursor);
            if (cursor === -1) return false;
            cursor += 1;
        }
        return true;
    };

    const modalDocs = Array.isArray(modalContent) ? modalContent as string[] : [];
    const filteredModalDocs = modalDocs.filter(doc => fuzzyFileMatch(doc, kbSearch));

    const renderUserMessage = (content: string) => {
        const matches: Array<{ start: number; end: number; doc: string }> = [];
        for (const doc of [...allDocs].sort((a, b) => b.length - a.length)) {
            const needle = `@${doc}`.toLowerCase();
            let cursor = content.toLowerCase().indexOf(needle);
            while (cursor !== -1) {
                matches.push({ start: cursor, end: cursor + doc.length + 1, doc });
                cursor = content.toLowerCase().indexOf(needle, cursor + needle.length);
            }
        }
        matches.sort((a, b) => a.start - b.start);
        const nonOverlapping = matches.filter((match, index, arr) => index === 0 || match.start >= arr[index - 1].end);
        if (nonOverlapping.length === 0) return content;

        const parts: React.ReactNode[] = [];
        let cursor = 0;
        nonOverlapping.forEach((match, idx) => {
            if (match.start > cursor) parts.push(content.slice(cursor, match.start));
            parts.push(
                <span className="user-file-pill" key={`${match.doc}-${idx}`}>
                    <FileText size={13} />
                    {match.doc}
                </span>
            );
            cursor = match.end;
        });
        if (cursor < content.length) parts.push(content.slice(cursor));
        return parts;
    };



    return (
        <div className="app-container">
            <Sidebar
                currentSessionId={sessionId}
                isLoading={loading}
                onSelectSession={(id, options) => {
                    // Client-side navigation
                    setSessionId(id);
                    if (options?.loadHistory === false) {
                        startEmptySession(id);
                    } else {
                        loadHistory(id);
                    }
                    localStorage.setItem('rag_session_id', id);
                    router.push(`/?session=${id}`);
                }}
            />

            <div className="main-chat-area">
                <UserMenu />
                <div style={{ position: 'absolute', inset: 0, zIndex: 0, opacity: 0.4, background: 'radial-gradient(circle at 50% -20%, rgba(59, 130, 246, 0.15), transparent 70%)', pointerEvents: 'none' }}></div>

                <div className="messages-container">
                    <div className="messages-wrapper">
                        {messages.map((msg, idx) => {
                            const sourceList = msg.sources || [];

                            return (
                            <div key={idx} className={`message-row ${msg.role === 'user' ? 'user-row' : 'bot-row'}`}>
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
                                                <ThinkingProcess
                                                    thoughts={msg.thoughts}
                                                    isFinished={!loading || idx !== messages.length - 1}
                                                    ttft={msg.ttft}
                                                    hasStartedAnswer={msg.content.length > 0}
                                                />
                                            )}
                                        </>
                                    )}

                                    <div className="markdown-content">
                                        {msg.role === 'user' ? (
                                            <div className="user-message-content">{renderUserMessage(msg.content)}</div>
                                        ) : (
                                        <ReactMarkdown
                                            remarkPlugins={[remarkGfm]}
                                            components={{
                                                p({ children }) {
                                                    return <p>{renderCitationChildren(children, sourceList)}</p>;
                                                },
                                                li({ children }) {
                                                    return <li>{renderCitationChildren(children, sourceList)}</li>;
                                                },
                                                code({ className, children, ...props }: { className?: string, children?: React.ReactNode }) {
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
                                                                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                                                                style={vscDarkPlus as any}
                                                                language={match[1]}
                                                                PreTag="div"
                                                                customStyle={{ margin: 0, borderTopLeftRadius: 0, borderTopRightRadius: 0 }}
                                                                // eslint-disable-next-line @typescript-eslint/no-explicit-any
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
                                        )}
                                    </div>

                                    {msg.role === 'bot' && sourceList.length > 0 && (
                                        <div className="sources-panel">
                                            <button
                                                className="sources-panel-header"
                                                onClick={() => setExpandedSources(prev => ({ ...prev, [idx]: !prev[idx] }))}
                                                aria-expanded={expandedSources[idx] === true}
                                            >
                                                <div className="sources-panel-title">
                                                    <Database size={14} />
                                                    Sources
                                                </div>
                                                <div className="sources-panel-count">
                                                    {sourceList.length} chunks
                                                    <ChevronRight size={14} className={`sources-chevron ${expandedSources[idx] ? 'open' : ''}`} />
                                                </div>
                                            </button>
                                            {expandedSources[idx] && (
                                                <div className="sources-grid">
                                                    {sourceList.map((src, i) => {
                                                        const meta = parseEnvelopeMeta(src);
                                                        const isTargeted = msg.targeted_docs?.some(d => src.includes(d));

                                                        return (
                                                            <div key={`${meta.title}-${i}`} className={`source-item ${isTargeted ? 'targeted' : ''}`}>
                                                                <button
                                                                    className="source-item-main"
                                                                    onClick={() => openSourceModal(meta.title, src)}
                                                                    title={`Open raw chunk ${i + 1}`}
                                                                >
                                                                    <span className="source-number">{i + 1}</span>
                                                                    <span className="source-item-body">
                                                                        <span className="source-item-title">{meta.title}</span>
                                                                        {(meta.section || meta.chunkKind || meta.chunkIndex) && (
                                                                            <span className="source-item-meta">
                                                                                {[meta.section, meta.chunkKind, meta.chunkIndex ? `chunk ${meta.chunkIndex}` : ''].filter(Boolean).join(' / ')}
                                                                            </span>
                                                                        )}
                                                                        <span className="source-item-preview">{meta.preview}</span>
                                                                    </span>
                                                                </button>
                                                                <button
                                                                    className="source-file-link"
                                                                    onClick={(e) => {
                                                                        e.stopPropagation();
                                                                        handleOpenFile(meta.title);
                                                                    }}
                                                                    title={`Open ${meta.title}`}
                                                                >
                                                                    <ArrowUpRight size={14} />
                                                                </button>
                                                            </div>
                                                        );
                                                    })}
                                                </div>
                                            )}
                                        </div>
                                    )}

                                </div>
                            </div>
                            );
                        })}
                        <div ref={bottomRef} />
                    </div>
                </div>

                <div className="input-area">
                    <div className="relative w-full" style={{ maxWidth: '800px', margin: '0 auto' }}>
                        {/* Mentions Dropdown */}
                        {showMentions && (
                            <div style={{
                                position: 'fixed',
                                left: mentionPosition?.left ?? 24,
                                top: mentionPosition?.top ?? 0,
                                transform: 'translateY(calc(-100% - 10px))',
                                background: 'rgba(15, 15, 15, 0.95)', backdropFilter: 'blur(24px)',
                                border: '1px solid rgba(59, 130, 246, 0.3)',
                                borderRadius: '12px', width: '320px', maxWidth: 'calc(100vw - 24px)', overflow: 'hidden', zIndex: 120,
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
                                onKeyUp={(e) => {
                                    if (showMentions) updateMentionPosition(e.currentTarget, e.currentTarget.selectionStart);
                                }}
                                onClick={(e) => {
                                    if (showMentions) updateMentionPosition(e.currentTarget, e.currentTarget.selectionStart);
                                }}
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
                                <div className="platinum-envelope-container">
                                    {/* 
                                      * Absolute Text Fidelity Rendering:
                                      * We use a pre-formatted div to ensure all whitespace, newlines, 
                                      * and ASCII structures from the main model's context are preserved.
                                      */}
                                    <div className="platinum-envelope-content">
                                        {modalContent}
                                    </div>
                                </div>
                            ) : modalContent === 'loading' ? (
                                <div className="flex flex-col gap-3">
                                    <div style={{ height: '20px', background: 'rgba(255,255,255,0.05)', borderRadius: '4px' }}></div>
                                    <div style={{ height: '20px', background: 'rgba(255,255,255,0.05)', borderRadius: '4px' }}></div>
                                </div>
                            ) : (
                                <div className="kb-modal-content">
                                    <input
                                        className="kb-search-input"
                                        value={kbSearch}
                                        onChange={(e) => setKbSearch(e.target.value)}
                                        placeholder="Search documents..."
                                        autoFocus
                                    />
                                    <div className="kb-doc-grid">
                                    {filteredModalDocs.length > 0 ? (
                                        filteredModalDocs.map((doc: string, i: number) => (
                                            <div
                                                key={i}
                                                className="dashboard-file-card"
                                                style={{
                                                    cursor: 'pointer'
                                                }}
                                                onClick={() => handleOpenFile(doc)}
                                            >
                                                <div className="flex items-center gap-3">
                                                    <div className="file-icon-wrapper">
                                                        <FileText size={20} color="var(--accent-primary)" />
                                                    </div>
                                                    <div className="file-info">
                                                        <div className="file-name" title={doc}>{doc}</div>
                                                        <div className="file-action">Click to open <ArrowUpRight size={10} /></div>
                                                    </div>
                                                </div>
                                            </div>
                                        ))
                                    ) : (
                                        <div style={{ gridColumn: '1 / -1', textAlign: 'center', color: 'var(--fg-muted)', padding: '2rem' }}>
                                            {modalDocs.length > 0 ? 'No documents matched.' : 'No documents indexed yet.'}
                                        </div>
                                    )}
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}


