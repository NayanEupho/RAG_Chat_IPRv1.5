"use client";

import { Send, StopCircle, Sparkles, PlusCircle } from "lucide-react";
import { useRef, useEffect } from "react";
import MCPSelector from "../MCPSelector";
import { motion, AnimatePresence } from "framer-motion";

interface ChatInputProps {
    input: string;
    setInput: (val: string) => void;
    onSubmit: () => void;
    isLoading: boolean;
    onStop: () => void;
    mcpContext: string;
    setMcpContext: (val: string) => void;
    placeholder?: string;
    disabled?: boolean;
}

import styles from "./ChatInput.module.css";

interface ChatInputProps {
    input: string;
    setInput: (val: string) => void;
    onSubmit: () => void;
    isLoading: boolean;
    onStop: () => void;
    mcpContext: string;
    setMcpContext: (val: string) => void;
    placeholder?: string;
    disabled?: boolean;
}

export default function ChatInput({
    input,
    setInput,
    onSubmit,
    isLoading,
    onStop,
    mcpContext,
    setMcpContext,
    placeholder = "Message DevOps Agent...",
    disabled = false
}: ChatInputProps) {
    const textareaRef = useRef<HTMLTextAreaElement>(null);

    useEffect(() => {
        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto';
            textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 200) + 'px';
        }
    }, [input]);

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            onSubmit();
        }
    };

    return (
        <div className={styles.container}>
            <div className={styles.inputBar}>


                {/* Text Area */}
                <textarea
                    ref={textareaRef}
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder={placeholder}
                    className={styles.textarea}
                    disabled={disabled}
                    rows={1}
                />

                {/* Right Side Actions */}
                <div className={styles.rightActions}>
                    <div className={styles.selectorWrapper}>
                        <MCPSelector
                            value={mcpContext}
                            onChange={setMcpContext}
                            disabled={isLoading || disabled}
                        />
                    </div>

                    {isLoading ? (
                        <button onClick={onStop} className={styles.stopBtn} title="Stop Generation">
                            <StopCircle size={18} fill="currentColor" />
                        </button>
                    ) : (
                        <button
                            onClick={onSubmit}
                            disabled={!input.trim() || disabled}
                            className={styles.submitBtn}
                            title="Send Message"
                        >
                            <Send size={18} fill={input.trim() ? "currentColor" : "none"} />
                        </button>
                    )}
                </div>
            </div>

            {/* Footer Info */}
            <div className={styles.footerInfo}>
                <span className={styles.footerLabel}>Secure Context</span>
                <div className={styles.footerDot} />
                <span className={styles.footerLabel}>v2.0 PREVIEW</span>
            </div>
        </div>
    );
}
