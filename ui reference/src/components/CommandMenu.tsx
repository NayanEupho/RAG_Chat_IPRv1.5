"use client";

import { useEffect, useState } from "react";
import { Command } from "cmdk";
import { Search, Plus, Settings, Server, Trash, MessageSquare } from "lucide-react";
import { useRouter } from "next/navigation";
import styles from "./CommandMenu.module.css";

export default function CommandMenu() {
    const [open, setOpen] = useState(false);
    const router = useRouter();

    useEffect(() => {
        const down = (e: KeyboardEvent) => {
            if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                setOpen((open) => !open);
            }
        };

        document.addEventListener("keydown", down);
        return () => document.removeEventListener("keydown", down);
    }, []);

    return (
        <Command.Dialog
            open={open}
            onOpenChange={setOpen}
            label="Global Command Menu"
            className={styles.dialog}
        >
            <div className={styles.wrapper}>
                <div className={styles.header}>
                    <Search size={16} className={styles.searchIcon} />
                    <Command.Input placeholder="Type a command or search..." className={styles.input} />
                </div>

                <Command.List className={styles.list}>
                    <Command.Empty className={styles.empty}>No results found.</Command.Empty>

                    <Command.Group heading="Actions" className={styles.group}>
                        <Command.Item className={styles.item} onSelect={() => { setOpen(false); /* Trigger new chat via URL or context? Need access. For now just navigate home */ router.push("/"); }}>
                            <Plus size={14} /> New Chat
                        </Command.Item>
                        <Command.Item className={styles.item} onSelect={() => { setOpen(false); window.dispatchEvent(new Event("open-settings")); }}>
                            <Settings size={14} /> Open Settings
                        </Command.Item>
                    </Command.Group>

                    <Command.Group heading="Navigation" className={styles.group}>
                        <Command.Item className={styles.item} onSelect={() => { setOpen(false); router.push("/"); }}>
                            <MessageSquare size={14} /> Home
                        </Command.Item>
                    </Command.Group>
                </Command.List>
            </div>
        </Command.Dialog>
    );
}
