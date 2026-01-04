"use client";

import { useState, useEffect } from "react";
import styles from "./NewChatModal.module.css";
import { MessageSquarePlus } from "lucide-react";

export default function NewChatModal({ isOpen, onClose, onCreate }: { isOpen: boolean; onClose: () => void; onCreate: (title: string) => void }) {
    const [title, setTitle] = useState("");

    useEffect(() => {
        if (isOpen) {
            const date = new Date();
            setTitle(`Session - ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`);
        }
    }, [isOpen]);

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === "Enter") {
            onCreate(title);
        } else if (e.key === "Escape") {
            onClose();
        }
    };

    if (!isOpen) return null;

    return (
        <div className={styles.overlay} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
            <div className={styles.modal}>
                <div className={styles.header}>
                    <div className="flex items-center" style={{ display: 'flex', alignItems: 'center' }}>
                        <MessageSquarePlus size={20} style={{ marginRight: '8px', color: '#6366f1' }} />
                        <h2>Start New Chat</h2>
                    </div>
                    <button className={styles.closeBtn} onClick={onClose}>×</button>
                </div>

                <div className={styles.content}>
                    <div className={styles.section}>
                        <label>Give your session a name</label>
                        <input
                            type="text"
                            className={styles.input}
                            value={title}
                            onChange={(e) => setTitle(e.target.value)}
                            placeholder="e.g. Debugging Production Pods..."
                            autoFocus
                            onKeyDown={handleKeyDown}
                        />
                    </div>
                </div>

                <div className={styles.footer}>
                    <button className={styles.cancelBtn} onClick={onClose}>Cancel</button>
                    <button className={styles.saveBtn} onClick={() => onCreate(title)}>Create Session</button>
                </div>
            </div>
        </div>
    );
}
