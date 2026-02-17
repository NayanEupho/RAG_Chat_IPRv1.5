'use client';

import React, { useEffect, useState, ReactNode, useCallback } from 'react';
import { AuthContext } from '@/hooks/useAuth';

interface User {
    user_id: string;
    email?: string;
    display_name?: string;
    attributes?: Record<string, unknown>;
}

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<User | null>(null);
    const [loading, setLoading] = useState(true);

    const getApiBase = () => {
        if (typeof window === 'undefined') return '';
        return `${window.location.protocol}//${window.location.host}`;
    };

    const login = () => {
        window.location.href = `${getApiBase()}/saml/login`;
    };

    const logout = () => {
        // Use full page redirect to ensure browser processes the Set-Cookie header correctly.
        // We redirect to /logged-out to avoid the auto-re-login loop.
        const logoutUrl = `${getApiBase()}/saml/logout?next=/logged-out`;
        console.log("Initiating logout using URL:", logoutUrl);
        window.location.href = logoutUrl;
    };

    const checkAuth = useCallback(async () => {
        try {
            const res = await fetch(`${getApiBase()}/saml/check`, {
                credentials: 'include', // Important: send cookies
            });
            const data = await res.json();
            if (data.authenticated && data.user) {
                setUser({
                    user_id: data.user.user_id,
                    email: data.user.email,
                    display_name: data.user.display_name,
                    attributes: data.user.attributes,
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
    }, []);

    useEffect(() => {
        checkAuth();
    }, [checkAuth]);

    return (
        <AuthContext.Provider value={{ user, loading, login, logout, checkAuth }}>
            {children}
        </AuthContext.Provider>
    );
}
