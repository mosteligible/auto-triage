import { NextRequest, NextResponse } from "next/server";

import {
  githubAuthTokenCookieName,
  githubAuthTokenCookieOptions,
  githubSessionCookieName,
  githubSessionCookieOptions,
  githubStateCookieName,
  githubStateCookieOptions,
} from "@/server/github-auth";

export async function POST(request: NextRequest) {
  const response = NextResponse.json({ status: "ok" });
  response.cookies.set(githubAuthTokenCookieName, "", {
    ...githubAuthTokenCookieOptions(request),
    maxAge: 0,
  });
  response.cookies.set(githubSessionCookieName, "", {
    ...githubSessionCookieOptions(request),
    maxAge: 0,
  });
  response.cookies.set(githubStateCookieName, "", {
    ...githubStateCookieOptions(request),
    maxAge: 0,
  });
  return response;
}
