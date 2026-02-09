"use client";
/**
 * Mode Selector Component
 * ------------------------
 * Allows users to manually toggle between 'Auto' (Smart Routing),
 * 'RAG' (Knowledge Base Only), and 'Chat' (Direct LLM) modes.
 */

import React, { useState } from "react";
import { ChevronDown, Globe, MessageSquare, Database } from "lucide-react";
import styles from "./ModeSelector.module.css";

export type InteractionMode = "auto" | "rag" | "chat";

const options = [
    { id: "auto", label: "Auto", icon: <Globe size={13} />, color: "#3b82f6", desc: "Smart Routing" },
    { id: "rag", label: "RAG", icon: <Database size={13} />, color: "#8b5cf6", desc: "Knowledge Base Only" },
    { id: "chat", label: "Chat", icon: <MessageSquare size={13} />, color: "#10b981", desc: "Direct LLM Only" },
];

interface ModeSelectorProps {
    value: InteractionMode;
    onChange: (val: InteractionMode) => void;
    disabled?: boolean;
}

export default function ModeSelector({ value, onChange, disabled }: ModeSelectorProps) {
    const [isOpen, setIsOpen] = useState(false);

    const selected = options.find(o => o.id === value) || options[0];

    return (
        <div className={styles.container}>
            <button
                className={styles.trigger}
                onClick={() => !disabled && setIsOpen(!isOpen)}
                disabled={disabled}
                title={`Mode: ${selected.label} (${selected.desc})`}
            >
                <span className={styles.icon} style={{ color: selected.color }}>{selected.icon}</span>
                <span className={styles.label}>{selected.label}</span>
                <ChevronDown size={12} className={styles.chevron} />
            </button>

            {isOpen && (
                <>
                    <div className={styles.overlay} onClick={() => setIsOpen(false)} />
                    <div className={styles.dropdown}>
                        {options.map((opt) => (
                            <button
                                key={opt.id}
                                className={`${styles.item} ${value === opt.id ? styles.selected : ""}`}
                                onClick={() => {
                                    onChange(opt.id as InteractionMode);
                                    setIsOpen(false);
                                }}
                            >
                                <span className={styles.icon} style={{ color: value === opt.id ? "#3b82f6" : opt.color }}>
                                    {opt.icon}
                                </span>
                                <div style={{ display: "flex", flexDirection: "column" }}>
                                    <span>{opt.label}</span>
                                </div>
                            </button>
                        ))}
                    </div>
                </>
            )}
        </div>
    );
}
