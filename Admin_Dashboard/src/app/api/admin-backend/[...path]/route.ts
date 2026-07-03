import { NextRequest } from "next/server";
import proxyConfig from "../../../../../proxy.config.js";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const REQUEST_TIMEOUT_MS = 15000;
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

function responseHeaders(response: Response, path: string[]): Headers {
  const headers = new Headers(response.headers);
  if (path.join("/") === "events") {
    headers.set("cache-control", "no-cache, no-transform");
    headers.set("x-accel-buffering", "no");
  }
  return headers;
}

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const method = request.method.toUpperCase();
  const body = method === "GET" || method === "HEAD" ? undefined : await request.arrayBuffer();
  const isEventStream = path.join("/") === "events";
  const controller = isEventStream ? null : new AbortController();
  const timeout = controller ? setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS) : null;
  try {
    const response = await fetch(backendUrl(BACKEND_BASE, request, path), {
      method,
      headers: proxyHeaders(request),
      body,
      cache: "no-store",
      signal: controller?.signal,
    });
    if (timeout) clearTimeout(timeout);
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: responseHeaders(response, path),
    });
  } catch (caught) {
    if (timeout) clearTimeout(timeout);
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
