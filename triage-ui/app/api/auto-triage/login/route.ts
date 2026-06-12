import { NextRequest, NextResponse } from "next/server";

import { parseBaseUrl, relayJson } from "@/lib/api-proxy";

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

  const response = await fetch(new URL("/auth/login", baseUrl), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      email: body.email,
      password: body.password,
      display_name: body.displayName,
    }),
  });
  return relayJson(response);
}
