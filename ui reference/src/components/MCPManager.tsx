"use client";

import { useState, useEffect } from "react";
import { Play, Square, Check, RefreshCw, Box, Server, Globe, Zap, X } from "lucide-react";
import { startMCPServers, stopMCPServers } from "../lib/api";
import { toast } from "sonner";
import { motion, AnimatePresence } from "framer-motion";

interface MCPManagerProps {
    status: any;
    pulseStatus?: any;
    refreshStatus: () => void;
}

type ServerState = 'neutral' | 'selected' | 'connected' | 'disconnecting' | 'error';

import styles from "./MCPManager.module.css";

export default function MCPManager({ status, pulseStatus, refreshStatus }: MCPManagerProps) {
    const [selected, setSelected] = useState<Set<string>>(new Set());
    const [processing, setProcessing] = useState<'connecting' | 'disconnecting' | null>(null);
    const [transientRed, setTransientRed] = useState<Set<string>>(new Set());

    const mcpItems = [
        { id: "docker", label: "Docker", icon: <Box size={14} /> },
        { id: "k8s_local", label: "Local K8s", icon: <Server size={14} /> },
        { id: "k8s_remote", label: "Remote K8s", icon: <Globe size={14} /> }
    ];

    const toggleSelection = (id: string) => {
        const next = new Set(selected);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        setSelected(next);

        if (transientRed.has(id)) {
            const nextRed = new Set(transientRed);
            nextRed.delete(id);
            setTransientRed(nextRed);
        }
    };

    const handleAction = async (action: 'connect' | 'disconnect') => {
        if (selected.size === 0) {
            toast.warning("Please select an MCP agent first");
            return;
        }

        setProcessing(action === 'connect' ? 'connecting' : 'disconnecting');
        const servers = Array.from(selected);

        try {
            if (action === 'connect') {
                await startMCPServers(servers);
                setTimeout(refreshStatus, 1500);
            } else {
                await stopMCPServers(servers);
                const nextRed = new Set(transientRed);
                servers.forEach(s => nextRed.add(s));
                setTransientRed(nextRed);
                setSelected(new Set());
                setTimeout(() => {
                    setTransientRed(prev => {
                        const next = new Set(prev);
                        servers.forEach(s => next.delete(s));
                        return next;
                    });
                }, 2000);
                setTimeout(refreshStatus, 1000);
            }
        } catch (e: any) {
            toast.error(`Control error: ${e.message}`);
        } finally {
            setProcessing(null);
        }
    };

    return (
        <div className={styles.container}>
            <div className={styles.mcpBar}>
                {mcpItems.map(item => {
                    const isConnected = status?.mcp?.[item.id] || false;
                    const isSelected = selected.has(item.id);
                    const isRed = transientRed.has(item.id);

                    // Pulse status mapping
                    const pulseKey = item.id === 'k8s_remote' ? 'remote_k8s' : item.id;
                    const clusterHealth = pulseStatus?.[pulseKey]?.status || 'unknown';
                    const hasPulseIssue = clusterHealth !== 'healthy' && clusterHealth !== 'unknown';

                    const componentClass = [
                        styles.mcpItem,
                        isSelected ? styles.mcpItemSelected : "",
                        isConnected && !isRed ? styles.mcpItemConnected : "",
                        isRed || (isConnected && hasPulseIssue) ? styles.mcpItemError : ""
                    ].join(" ");

                    return (
                        <motion.button
                            key={item.id}
                            whileTap={{ scale: 0.96 }}
                            onClick={() => toggleSelection(item.id)}
                            className={componentClass}
                            title={isConnected ? `Cluster Health: ${clusterHealth}` : "MCP disconnected"}
                        >
                            <div className={styles.iconWrapper}>
                                {item.icon}
                                {isConnected && !isRed && (
                                    <div className={`${styles.statusDot} ${hasPulseIssue ? styles.dotOrange : ""}`} />
                                )}
                            </div>
                            <span className={styles.mcpLabel}>{item.label}</span>
                        </motion.button>
                    );
                })}
            </div>

            <div className={styles.actions}>
                <button
                    onClick={() => handleAction('connect')}
                    disabled={!!processing || selected.size === 0}
                    className={`${styles.actionBtn} ${styles.connectBtn}`}
                >
                    {processing === 'connecting' ? (
                        <RefreshCw size={12} className={styles.spin} />
                    ) : (
                        "Initiate"
                    )}
                </button>

                <button
                    onClick={() => handleAction('disconnect')}
                    disabled={!!processing || selected.size === 0}
                    className={`${styles.actionBtn} ${styles.disconnectBtn}`}
                >
                    {processing === 'disconnecting' ? (
                        <RefreshCw size={12} className={styles.spin} />
                    ) : (
                        "Terminate"
                    )}
                </button>
            </div>

            <AnimatePresence>
                {!processing && selected.size > 0 && (
                    <motion.div
                        initial={{ opacity: 0, y: 4 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0 }}
                        className={styles.successMsg}
                    >
                        Ready to work
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
}
