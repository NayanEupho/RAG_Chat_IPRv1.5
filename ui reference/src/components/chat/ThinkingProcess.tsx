"use client";

import { useState, useEffect } from "react";
import { ChevronDown, ChevronRight, Cpu, Terminal, AlertCircle, CheckCircle2, BrainCircuit } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

interface ThoughtItem {
    type: "thought" | "tool_call" | "error" | "status" | "result";
    content: string;
}

interface ThinkingProcessProps {
    thoughts: ThoughtItem[];
    isFinished?: boolean;
}

import styles from "./ThinkingProcess.module.css";

interface ThoughtItem {
    type: "thought" | "tool_call" | "error" | "status" | "result";
    content: string;
}

interface ThinkingProcessProps {
    thoughts: ThoughtItem[];
    isFinished?: boolean;
}

export default function ThinkingProcess({ thoughts, isFinished = false }: ThinkingProcessProps) {
    const [isExpanded, setIsExpanded] = useState(!isFinished);
    const [elapsed, setElapsed] = useState(0);

    useEffect(() => {
        if (isFinished) {
            // Collapse by default when finished histories are loaded
            // But if it just finished streaming, we might want to let user see it for a bit
            const t = setTimeout(() => setIsExpanded(false), 800);
            return () => clearTimeout(t);
        } else {
            setIsExpanded(true);
        }
    }, [isFinished]);

    useEffect(() => {
        if (isFinished) return;
        const interval = setInterval(() => setElapsed(s => s + 1), 1000);
        return () => clearInterval(interval);
    }, [isFinished]);

    if (thoughts.length === 0) return null;

    const getIcon = (type: string) => {
        switch (type) {
            case "tool_call": return <Terminal size={14} className={styles.type_tool_call} />;
            case "error": return <AlertCircle size={14} className={styles.type_error} />;
            case "result": return <CheckCircle2 size={14} className={styles.type_result} />;
            case "thought": return <Cpu size={14} className={styles.type_thought} />;
            default: return <Cpu size={14} className={styles.type_status} />;
        }
    };

    return (
        <div className={styles.container}>
            <button
                onClick={() => setIsExpanded(!isExpanded)}
                className={`${styles.header} ${isExpanded ? styles.headerExpanded : ""}`}
            >
                <div className={styles.icon}>
                    {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </div>

                <div className={`${styles.icon} ${!isFinished ? styles.iconThinking : ""}`}>
                    <BrainCircuit size={16} />
                </div>

                <span className={styles.label}>
                    {isFinished ? "Thought Process" : "Thinking..."}
                </span>

                <div className={styles.meta}>
                    <span>{thoughts.length} steps</span>
                    {!isFinished && <span>{elapsed}s</span>}
                </div>
            </button>

            <AnimatePresence initial={false}>
                {isExpanded && (
                    <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: "auto", opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
                        className={styles.logsContainer}
                    >
                        {thoughts.map((t, idx) => (
                            <div key={idx} className={styles.logRow}>
                                <div className={styles.logIcon}>
                                    {getIcon(t.type)}
                                </div>
                                <div className={`${styles.logContent} ${styles[`type_${t.type}`]}`}>
                                    {t.content}
                                </div>
                            </div>
                        ))}

                        {!isFinished && (
                            <div className={styles.thinkingRow}>
                                <div className={styles.thinkingDot} />
                                Processing next step...
                            </div>
                        )}
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
}
