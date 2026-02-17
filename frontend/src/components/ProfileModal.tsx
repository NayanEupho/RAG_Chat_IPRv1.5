'use client';

import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Mail, Shield, Fingerprint, Database, CheckCircle2 } from 'lucide-react';
import { useAuth } from '@/hooks/useAuth';

interface ProfileModalProps {
    isOpen: boolean;
    onClose: () => void;
}

const ProfileModal: React.FC<ProfileModalProps> = ({ isOpen, onClose }) => {
    const { user } = useAuth();

    if (!user) return null;

    const initials = user.display_name
        ? user.display_name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2)
        : user.user_id.slice(0, 2).toUpperCase();

    return (
        <AnimatePresence>
            {isOpen && (
                <>
                    {/* Backdrop */}
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        onClick={onClose}
                        className="fixed inset-0 bg-black/60 backdrop-blur-md z-[1000]"
                    />

                    {/* Modal */}
                    <motion.div
                        initial={{ opacity: 0, scale: 0.9, y: 20 }}
                        animate={{ opacity: 1, scale: 1, y: 0 }}
                        exit={{ opacity: 0, scale: 0.9, y: 20 }}
                        transition={{ type: 'spring', damping: 25, stiffness: 300 }}
                        className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-lg 
                                   bg-[#121212]/90 backdrop-blur-2xl rounded-[24px] shadow-[0_32px_80px_rgba(0,0,0,0.8)] 
                                   border border-white/10 z-[1001] overflow-hidden"
                    >
                        {/* Header with Gradient */}
                        <div className="relative px-8 py-10 border-b border-white/5 bg-gradient-to-br from-blue-500/10 to-transparent">
                            <button
                                onClick={onClose}
                                className="absolute right-6 top-6 p-2 rounded-full hover:bg-white/10 transition-colors"
                            >
                                <X className="w-5 h-5 text-white/40 hover:text-white" />
                            </button>

                            <div className="flex items-center gap-6">
                                <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center text-white text-2xl font-bold shadow-2xl shadow-blue-500/20">
                                    {initials}
                                </div>
                                <div className="overflow-hidden">
                                    <h2 className="text-2xl font-bold text-white tracking-tight truncate">
                                        {user.display_name || 'User Profile'}
                                    </h2>
                                    <p className="text-white/50 flex items-center gap-2 mt-1.5 text-sm">
                                        <Mail className="w-4 h-4" />
                                        {user.email || 'No email provided'}
                                    </p>
                                </div>
                            </div>
                        </div>

                        {/* Content Scroll Area */}
                        <div className="p-8 space-y-8 max-h-[60vh] overflow-y-auto custom-scrollbar">
                            {/* Security Section */}
                            <section>
                                <div className="flex items-center gap-2 mb-4">
                                    <Shield className="w-4 h-4 text-blue-400" />
                                    <h3 className="text-xs font-bold text-white/30 uppercase tracking-[0.2em]">
                                        Account Security
                                    </h3>
                                </div>

                                <div className="grid grid-cols-1 gap-3">
                                    <div className="flex items-center justify-between p-4 rounded-2xl bg-white/5 border border-white/5">
                                        <div className="flex items-center gap-4">
                                            <div className="p-2.5 rounded-xl bg-blue-500/10 text-blue-400">
                                                <Fingerprint className="w-5 h-5" />
                                            </div>
                                            <div>
                                                <p className="text-[10px] uppercase font-bold text-white/30 tracking-wider">User ID</p>
                                                <p className="text-sm text-white/80 font-mono tracking-tight">{user.user_id}</p>
                                            </div>
                                        </div>
                                    </div>

                                    <div className="flex items-center justify-between p-4 rounded-2xl bg-white/5 border border-white/5">
                                        <div className="flex items-center gap-4">
                                            <div className="p-2.5 rounded-xl bg-emerald-500/10 text-emerald-400">
                                                <CheckCircle2 className="w-5 h-5" />
                                            </div>
                                            <div>
                                                <p className="text-[10px] uppercase font-bold text-white/30 tracking-wider">Auth Status</p>
                                                <p className="text-sm text-white/80">SAML SSO Verified</p>
                                            </div>
                                        </div>
                                        <div className="w-2 h-2 rounded-full bg-emerald-500 shadow-[0_0_8px_#10b981]"></div>
                                    </div>
                                </div>
                            </section>

                            {/* SAML Attributes Section */}
                            {user.attributes && Object.keys(user.attributes).length > 0 && (
                                <section>
                                    <div className="flex items-center gap-2 mb-4">
                                        <Database className="w-4 h-4 text-blue-400" />
                                        <h3 className="text-xs font-bold text-white/30 uppercase tracking-[0.2em]">
                                            SAML Directory
                                        </h3>
                                    </div>
                                    <div className="rounded-2xl border border-white/5 overflow-hidden divide-y divide-white/5 bg-white/[0.02]">
                                        {Object.entries(user.attributes || {}).map(([key, value]) => (
                                            <div key={key} className="p-4 flex flex-col gap-1 hover:bg-white/[0.03] transition-colors">
                                                <p className="text-[10px] font-bold text-white/20 uppercase tracking-tighter">
                                                    {key.split('/').pop()}
                                                </p>
                                                <p className="text-sm text-white/60 font-medium break-all leading-snug">
                                                    {Array.isArray(value) ? value.join(', ') : String(value)}
                                                </p>
                                            </div>
                                        ))}
                                    </div>
                                </section>
                            )}
                        </div>

                        {/* Footer */}
                        <div className="p-6 bg-white/[0.03] border-t border-white/5 flex justify-end">
                            <button
                                onClick={onClose}
                                className="px-8 py-2.5 rounded-xl bg-white text-black text-sm font-bold 
                                           hover:bg-white/90 transition-all active:scale-95"
                            >
                                Close
                            </button>
                        </div>
                    </motion.div>
                </>
            )}
        </AnimatePresence>
    );
};

export default ProfileModal;
