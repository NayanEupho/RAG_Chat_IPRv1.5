"use client";

export interface AdminSession {
  email: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}

const ADMIN_AUTH_KEY = "rag-admin-local-auth";

export function readAdminSession(): AdminSession {
  if (typeof window === "undefined") {
    return { email: null, isAuthenticated: false, isLoading: true };
  }
  try {
    const parsed = JSON.parse(window.localStorage.getItem(ADMIN_AUTH_KEY) || "null") as { email?: string } | null;
    const email = parsed?.email || null;
    return { email, isAuthenticated: Boolean(email), isLoading: false };
  } catch {
    return { email: null, isAuthenticated: false, isLoading: false };
  }
}

export function saveAdminSession(email: string): AdminSession {
  const normalized = email.trim().toLowerCase();
  window.localStorage.setItem(ADMIN_AUTH_KEY, JSON.stringify({ email: normalized, authenticatedAt: new Date().toISOString() }));
  return { email: normalized, isAuthenticated: true, isLoading: false };
}

export function clearAdminSession(): AdminSession {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(ADMIN_AUTH_KEY);
  }
  return { email: null, isAuthenticated: false, isLoading: false };
}

export function getAdminCsrfHeaders(): HeadersInit {
  return {};
}

export async function getAdminSession(): Promise<AdminSession> {
  return readAdminSession();
}
