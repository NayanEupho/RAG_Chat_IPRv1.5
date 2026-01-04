"use client";

import { useState } from "react";
import { ChevronDown, Server, Box, Layers, Globe, MessageSquare } from "lucide-react";
import styles from "./MCPSelector.module.css";

const options = [
    { id: "auto", label: "Auto (Smart)", icon: <Globe size={14} />, color: "#3b82f6" },     // Blue
    { id: "chat", label: "Chat Only", icon: <MessageSquare size={14} />, color: "#10b981" }, // Green
    { id: "docker", label: "Docker Only", icon: <Box size={14} />, color: "#06b6d4" },       // Cyan
    { id: "k8s_local", label: "Local K8s", icon: <Layers size={14} />, color: "#8b5cf6" },   // Violet
    { id: "k8s_remote", label: "Remote K8s", icon: <Server size={14} />, color: "#f59e0b" }, // Amber
];

interface MCPSelectorProps {
    value: string;
    onChange: (val: string) => void;
    disabled?: boolean;
}

export default function MCPSelector({ value, onChange, disabled }: MCPSelectorProps) {
    const [isOpen, setIsOpen] = useState(false);

    const selected = options.find(o => o.id === value) || options[0];

    return (
        <div className={styles.container}>
            <button
                className={styles.trigger}
                onClick={() => !disabled && setIsOpen(!isOpen)}
                disabled={disabled}
                style={{ borderColor: isOpen ? selected.color : undefined }}
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
                                className={`${styles.item} ${value === opt.id ? styles.selected : ''}`}
                                onClick={() => {
                                    onChange(opt.id);
                                    setIsOpen(false);
                                }}
                            >
                                <span style={{ color: value === opt.id ? 'white' : opt.color, display: 'flex', alignItems: 'center' }}>
                                    {opt.icon}
                                </span>
                                {opt.label}
                            </button>
                        ))}
                    </div>
                </>
            )}
        </div>
    );
}
