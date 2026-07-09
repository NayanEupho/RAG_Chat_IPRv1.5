import type { NextRequest } from 'next/server';
import proxyConfig from '../../../proxy.config.js';

export function getBackendAdminBaseUrl(): string {
  return `${String(proxyConfig.backendUpstream || 'http://localhost:8000').replace(/\/$/, '')}/api/admin`;
}

export function getBackendAdminUrl(path: string): string {
  const suffix = path.startsWith('/') ? path : `/${path}`;
  return `${getBackendAdminBaseUrl()}${suffix}`;
}

export function buildAdminProxyHeaders(
  request: NextRequest,
  extra: HeadersInit = {},
): Headers {
  const headers = new Headers(extra);
  const cookieHeader = request.headers.get('cookie');
  const origin = request.headers.get('origin');
  const referer = request.headers.get('referer');
  const csrf = request.headers.get('x-admin-csrf-token') || request.headers.get('x-csrf-token');

  if (cookieHeader) headers.set('Cookie', cookieHeader);
  if (origin) headers.set('Origin', origin);
  if (referer) headers.set('Referer', referer);
  if (csrf) headers.set('x-admin-csrf-token', csrf);

  return headers;
}

export async function fetchAdminBackend(
  request: NextRequest,
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = buildAdminProxyHeaders(request, init.headers);
  return fetch(getBackendAdminUrl(path), {
    ...init,
    headers,
  });
}

export function isSecureRequest(request: NextRequest): boolean {
  const forwardedProto = request.headers.get('x-forwarded-proto');
  if (forwardedProto) {
    return forwardedProto.toLowerCase() === 'https';
  }
  return request.nextUrl.protocol === 'https:';
}
