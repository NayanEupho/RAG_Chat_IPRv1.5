"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { User, Sparkles, Copy, Check } from "lucide-react";
import { useState } from "react";
import { motion } from "framer-motion";
import ThinkingProcess from "./ThinkingProcess";
import styles from "./MessageBubble.module.css";
import { toast } from "sonner";

interface MessageBubbleProps {
    role: string;
    content: string;
    thoughts?: any[];
    isStreaming?: boolean;
}

export default function MessageBubble({ role, content, thoughts, isStreaming }: MessageBubbleProps) {
    const isUser = role === "user";
    const [copied, setCopied] = useState(false);

    const handleCopy = () => {
        navigator.clipboard.writeText(content);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
        toast.success("Message copied to clipboard");
    };

    const markdownComponents = {
        code({ node, inline, className, children, ...props }: any) {
            const match = /language-(\w+)/.exec(className || '')
            return !inline ? (
                <div className={styles.codeBlockContainer}>
                    <div className={styles.codeHeader}>
                        <span className={styles.codeLang}>{match ? match[1] : 'terminal'}</span>
                        <button onClick={() => {
                            const text = String(children).replace(/\n$/, '');
                            navigator.clipboard.writeText(text);
                            toast.success("Code copied");
                        }} className={styles.copyCodeBtn}>
                            Copy
                        </button>
                    </div>
                    <pre className={styles.codePre}>
                        <code className={className} {...props}>
                            {children}
                        </code>
                    </pre>
                </div>
            ) : (
                <code {...props}>
                    {children}
                </code>
            )
        }
    };

    return (
        <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
            className={`${styles.messageRow} ${isUser ? styles.userRow : styles.assistantRow}`}
        >
            <div className={`${styles.messageContent} ${isUser ? styles.userContent : styles.assistantContent}`}>
                {/* Avatar */}
                <div className={`${styles.avatar} ${!isUser ? styles.assistantAvatar : ""}`}>
                    {isUser ? <User size={18} /> : <Sparkles size={18} />}
                </div>

                <div className={`${styles.bubble} ${isUser ? styles.userBubble : styles.assistantBubble}`}>
                    {/* Role Label */}
                    <div className={styles.roleLabel}>
                        {isUser ? "You" : "DevOps Agent"}
                    </div>

                    {/* Thinking Process */}
                    {!isUser && thoughts && thoughts.length > 0 && (
                        <ThinkingProcess thoughts={thoughts} isFinished={!isStreaming} />
                    )}

                    {/* Content Area */}
                    <div className={styles.textContainer}>
                        {/* Diagnosis Card Detection */}
                        {!isUser && content.includes("❌ Operation failed") ? (
                            <div className={styles.diagnosisCard}>
                                <div className="markdown-content">
                                    <ReactMarkdown
                                        remarkPlugins={[remarkGfm]}
                                        components={markdownComponents}
                                    >
                                        {content}
                                    </ReactMarkdown>
                                </div>
                            </div>
                        ) : (
                            <div className="markdown-content">
                                <ReactMarkdown
                                    remarkPlugins={[remarkGfm]}
                                    components={markdownComponents}
                                >
                                    {content}
                                </ReactMarkdown>
                            </div>
                        )}

                        {/* Stream Cursor */}
                        {isStreaming && !isUser && (
                            <motion.span
                                animate={{ opacity: [0, 1, 0] }}
                                transition={{ duration: 0.8, repeat: Infinity }}
                                className={styles.cursor}
                            />
                        )}

                        {/* Action Menu (Visible on hover) */}
                        <div className={`${styles.actions} ${isUser ? styles.userActions : styles.assistantActions}`}>
                            <button
                                onClick={handleCopy}
                                className={styles.actionBtn}
                                title="Copy Message"
                            >
                                {copied ? <Check size={14} /> : <Copy size={14} />}
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </motion.div>
    );
}
