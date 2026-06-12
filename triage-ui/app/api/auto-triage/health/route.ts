import { NextRequest, NextResponse } from "next/server";

export async function GET(request: NextRequest) {
  const baseUrl = request.nextUrl.searchParams.get("baseUrl");
  if (!baseUrl) {
    return NextResponse.json({ error: "baseUrl is required" }, { status: 400 });
  }

  let parsed: URL;
  try {
    parsed = new URL(baseUrl);
  } catch {
    return NextResponse.json({ error: "baseUrl must be a valid URL" }, { status: 400 });
  }

  try {
    const response = await fetch(new URL("/health", parsed), {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    const payload = await response.json().catch(() => ({}));
    return NextResponse.json(
      {
        ok: response.ok,
        status: response.status,
        payload,
      },
      { status: response.ok ? 200 : 502 },
    );
  } catch (error) {
    return NextResponse.json(
      {
        ok: false,
        error: error instanceof Error ? error.message : "Connection failed",
      },
      { status: 502 },
    );
  }
}
