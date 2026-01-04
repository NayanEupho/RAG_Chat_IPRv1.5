"use client";

import { Cpu, Terminal, Zap, Server, BrainCircuit, ShieldCheck, Activity, ArrowRight, Sparkles } from "lucide-react";
import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";

import styles from "./EmptyState.module.css";

export default function EmptyState() {
    const examples = [
        "show me all running containers in docker",
        "List all deployments",
        "show nodes & pods in my k8s",
        "explain error 403 and a fix for it",
        "Why is my pod crashing?"
    ];

    return (
        <div className={styles.container}>
            <div className={styles.backdrop} />

            <div className={styles.spacer} />

            <motion.div
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
                className={styles.content}
            >
                {/* Premium Icon */}
                <div className={styles.logoWrapper}>
                    <div className={styles.logo}>
                        <BrainCircuit size={32} />
                    </div>
                </div>

                <h1 className={styles.title}>
                    DevOps Agent
                </h1>

                <p className={styles.subtitle}>
                    Agentic solution for automating and monitoring you Docker and Kubernaties with safe, high-fidelity AI agents. & MCPs
                </p>

                {/* Example Pills */}
                <div className={styles.suggestionsGrid}>
                    {examples.slice(0, 4).map((ex, i) => (
                        <SuggestionCard
                            key={i}
                            icon={i === 0 ? <Box size={16} /> : i === 1 ? <Zap size={16} /> : i === 2 ? <Activity size={16} /> : <Terminal size={16} />}
                            text={ex}
                            delay={0.1 * i}
                        />
                    ))}
                </div>
            </motion.div>

            <div className={styles.spacer} />

            {/* Subtle Capability List */}
            <div className={styles.capabilities}>
                <Capability icon={<ShieldCheck size={14} />} text="Zero-Trust Safety" />
                <Capability icon={<Server size={14} />} text="Multi-Cluster Aware" />
                <Capability icon={<Sparkles size={14} />} text="High-Fidelity Reasoner" />
            </div>
        </div>
    );
}

function Box({ size }: { size: number }) { return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z" /><path d="M3.27 6.96 12 12.01l8.73-5.05" /><path d="M12 22.08V12" /></svg>; }

function Capability({ icon, text }: { icon: any, text: string }) {
    return (
        <div className={styles.capability}>
            {icon}
            {text}
        </div>
    );
}

function SuggestionCard({ icon, text, delay }: { icon: any, text: string, delay: number }) {
    return (
        <motion.button
            initial={{ opacity: 0, scale: 0.98 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay, duration: 0.5 }}
            className={styles.suggestionCard}
        >
            <div className={styles.suggestionIcon}>
                {icon}
            </div>
            <div className={styles.suggestionText}>
                {text}
            </div>
            <ArrowRight size={14} className={styles.arrow} />
        </motion.button>
    );
}
