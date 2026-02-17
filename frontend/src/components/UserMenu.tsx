'use client';

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
    LogOut,
    ChevronDown
} from 'lucide-react';
import { useAuth } from '@/hooks/useAuth';
import styles from './UserMenu.module.css';

const UserMenu: React.FC = () => {
    const { user, logout } = useAuth();
    const [isDropdownOpen, setIsDropdownOpen] = useState(false);

    if (!user) return null;

    const initials = user.display_name
        ? user.display_name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2)
        : user.user_id.slice(0, 2).toUpperCase();

    const firstName = user.display_name?.split(' ')[0] || user.user_id.slice(0, 8);

    return (
        <div className={styles.container}>
            {/* User Pill Trigger */}
            <motion.button
                layout
                onClick={() => setIsDropdownOpen(!isDropdownOpen)}
                className={styles.trigger}
            >
                <div className={styles.avatar}>
                    {initials}
                </div>
                <span className={styles.username}>
                    {firstName}
                </span>
                <ChevronDown className={`${styles.chevron} ${isDropdownOpen ? 'rotate-180 opacity-100 !translate-x-0' : ''}`} />
            </motion.button>

            {/* Dropdown Menu */}
            <AnimatePresence>
                {isDropdownOpen && (
                    <>
                        <motion.div
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            exit={{ opacity: 0 }}
                            className="fixed inset-0 z-[-1]"
                            onClick={() => setIsDropdownOpen(false)}
                        />
                        <motion.div
                            initial={{ opacity: 0, scale: 0.98, y: 10 }}
                            animate={{ opacity: 1, scale: 1, y: 0 }}
                            exit={{ opacity: 0, scale: 0.98, y: 10 }}
                            transition={{ duration: 0.18, ease: "easeOut" }}
                            className={styles.dropdown}
                        >
                            {/* User Info Header */}
                            <div className={styles.profileHeader}>
                                <div className={`${styles.avatar} ${styles.largeAvatar}`}>
                                    {initials}
                                </div>
                                <h3 className={styles.displayName}>{user.display_name || user.user_id}</h3>
                                <span className={styles.signedInAs}>Signed in as</span>
                                <p className={styles.email}>{user.email || 'No email associated'}</p>
                            </div>

                            {/* Menu Items */}
                            <div className={styles.menuContent}>
                                <button
                                    onClick={() => {
                                        logout();
                                        setIsDropdownOpen(false);
                                    }}
                                    className={`${styles.menuItem} ${styles.logoutBtn}`}
                                >
                                    <LogOut className="w-4 h-4" />
                                    <span className="font-semibold">Sign Out</span>
                                </button>
                            </div>
                        </motion.div>
                    </>
                )}
            </AnimatePresence>
        </div>
    );
};

export default UserMenu;
