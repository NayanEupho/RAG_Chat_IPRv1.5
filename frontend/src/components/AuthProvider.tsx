'use client';

import React, { useEffect, useState, ReactNode } from 'react';
import { AuthContext } from '@/hooks/useAuth';

interface User {
    user_id: string;
    email?: string;
    display_name?: string;
}

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<User | null>(null);
    const [loading, setLoading] = useState(true);

    const getApiBase = () => {
        const hostname = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
        return `https://${hostname}:443`;
    };

    const login = () => {
        window.location.href = `${getApiBase()}/saml/login`;
    };

    const logout = async () => {
        try {
            // Call backend logout to clear cookie
            await fetch(`${getApiBase()}/saml/logout`);
            setUser(null);
            // Optional: Redirect to login or home
            window.location.href = '/';
        } catch (e) {
            console.error("Logout failed", e);
        }
    };

    const checkAuth = async () => {
        try {
            const res = await fetch(`${getApiBase()}/saml/check`, {
                credentials: 'include', // Important: send cookies
            });
            const data = await res.json();
            if (data.authenticated) {
                setUser({
                    user_id: data.user_id,
                    email: data.email,
                    display_name: data.display_name,
                });
            } else {
                setUser(null);
            }
        } catch (error) {
            console.error('Auth check failed:', error);
            setUser(null);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        checkAuth();
    }, []);

    return (
        <AuthContext.Provider value={{ user, loading, login, logout, checkAuth }}>
            {children}
        </AuthContext.Provider>
    );
}
