import { NextRequest } from "next/server";
import proxyConfig from "../../../../../proxy.config.js";

const REQUEST_TIMEOUT_MS = 1800;
const BACKEND_BASE = `${String(process.env.ADMIN_BACKEND_UPSTREAM || proxyConfig.backendUpstream || "http://127.0.0.1:8000").replace(/\/$/, "")}/api/v1`;

function backendUrl(base: string, request: NextRequest, path: string[]): string {
  const suffix = path.map((part) => encodeURIComponent(part)).join("/");
  const query = request.nextUrl.search || "";
  return `${base}/${suffix}${query}`;
}

function proxyHeaders(request: NextRequest): Headers {
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  const accept = request.headers.get("accept");
  if (contentType) headers.set("content-type", contentType);
  if (accept) headers.set("accept", accept);
  return headers;
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const method = request.method.toUpperCase();
  const body = method === "GET" || method === "HEAD" ? undefined : await request.arrayBuffer();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(backendUrl(BACKEND_BASE, request, path), {
      method,
      headers: proxyHeaders(request),
      body,
      cache: "no-store",
      signal: controller.signal,
    });
    clearTimeout(timeout);
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: response.headers,
    });
  } catch (caught) {
    clearTimeout(timeout);
    const message = caught instanceof Error ? caught.message : String(caught);
    return Response.json(
      {
        data: null,
        error: "Admin backend proxy failed",
        detail: `Unable to reach backend from the Next dashboard server at ${BACKEND_BASE}. ${message}`,
      },
      { status: 502 },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
