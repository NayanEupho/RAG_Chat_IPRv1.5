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
        return ""; // Relative paths work best for Nginx/Proxy compatibility
    };

    const login = () => {
        if (process.env.NEXT_PUBLIC_USE_SAML_LOGIN === 'true') {
            window.location.href = `${getApiBase()}/saml/login`;
        }
    };

    const logout = () => {
        if (process.env.NEXT_PUBLIC_USE_SAML_LOGIN === 'true') {
            const logoutUrl = `${getApiBase()}/saml/logout?next=/logged-out`;
            console.log("Initiating logout using URL:", logoutUrl);
            window.location.href = logoutUrl;
        } else {
            // Static logout for anonymous
            setUser(null);
            localStorage.removeItem('rag_session_id');
            window.location.href = '/';
        }
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
