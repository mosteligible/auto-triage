import { NextResponse } from "next/server";

export function parseBaseUrl(value: unknown): URL {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error("baseUrl is required");
  }
  return new URL(value);
}

export function authHeaders(token: string | null): HeadersInit {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function relayJson(response: Response) {
  const payload = await response.json().catch(() => ({}));
  return NextResponse.json(payload, { status: response.status });
}
