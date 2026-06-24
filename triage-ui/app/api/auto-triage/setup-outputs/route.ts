import { NextRequest, NextResponse } from "next/server";

import { authHeaders, parseBaseUrl, relayJson } from "@/lib/api-proxy";

export async function GET(request: NextRequest) {
  let baseUrl: URL;
  try {
    baseUrl = parseBaseUrl(request.nextUrl.searchParams.get("baseUrl"));
  } catch (error) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "Invalid baseUrl" },
      { status: 400 },
    );
  }

  const response = await fetch(new URL("/users/me/setup-outputs", baseUrl), {
    headers: authHeaders(request.headers.get("authorization")?.replace(/^Bearer\s+/i, "") ?? null),
  });
  return relayJson(response);
}

export async function PUT(request: NextRequest) {
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

  const response = await fetch(new URL("/users/me/setup-outputs", baseUrl), {
    method: "PUT",
    headers: {
      "content-type": "application/json",
      ...authHeaders(request.headers.get("authorization")?.replace(/^Bearer\s+/i, "") ?? null),
    },
    body: JSON.stringify(body.outputs),
  });
  return relayJson(response);
}
