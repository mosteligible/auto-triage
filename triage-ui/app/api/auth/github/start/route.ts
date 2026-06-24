import { NextRequest, NextResponse } from "next/server";

import {
  buildGithubAuthorizeUrl,
  createGithubStateCookie,
  githubOAuthConfig,
  githubStateCookieName,
  githubStateCookieOptions,
  redirectWithGithubError,
  type GithubAuthMode,
} from "@/server/github-auth";

export async function GET(request: NextRequest) {
  let config: ReturnType<typeof githubOAuthConfig>;
  try {
    config = githubOAuthConfig(request);
  } catch (error) {
    return redirectWithGithubError(
      request,
      error instanceof Error ? error.message : "GitHub login is not configured",
      "/login",
    );
  }

  const mode = githubMode(request.nextUrl.searchParams.get("mode"));
  const { state, cookieValue } = createGithubStateCookie(config, {
    mode,
    organizationName: request.nextUrl.searchParams.get("organizationName"),
    returnTo: request.nextUrl.searchParams.get("returnTo"),
  });
  const authorizeUrl = buildGithubAuthorizeUrl(config, state);
  const redirectUri = new URL(authorizeUrl.searchParams.get("redirect_uri") ?? config.redirectUri);
  console.info("github_login_start", {
    mode,
    requestHost: request.nextUrl.host,
    redirectHost: redirectUri.host,
    redirectPath: redirectUri.pathname,
    authKind: config.authKind,
  });
  const response = NextResponse.redirect(authorizeUrl);
  response.cookies.set(githubStateCookieName, cookieValue, githubStateCookieOptions(request));
  return response;
}

function githubMode(value: string | null): GithubAuthMode {
  return value === "register" ? "register" : "login";
}
