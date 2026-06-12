import { NextRequest, NextResponse } from "next/server";

import { authHeaders, parseBaseUrl, relayJson } from "@/lib/api-proxy";

export async function POST(request: NextRequest) {
  const body = await request.json();
  let baseUrl: URL;
  try {
    baseUrl = parseBaseUrl(body.baseUrl);
  } catch (error) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "Invalid baseUrl" },
      { status: 400 },
    );
  }

  const response = await fetch(new URL("/users/me/alerts/test", baseUrl), {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...authHeaders(request.headers.get("authorization")?.replace(/^Bearer\s+/i, "") ?? null),
    },
    body: JSON.stringify(body.alert ?? {}),
  });
  return relayJson(response);
}
