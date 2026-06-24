import { NextRequest, NextResponse } from "next/server";

import {
  completeGithubLogin,
  encodeSessionCookie,
  exchangeGithubCode,
  fetchGithubProfile,
  githubAuthTokenCookieName,
  githubAuthTokenCookieOptions,
  githubOAuthConfig,
  githubPublicOrigin,
  githubSessionCookieName,
  githubSessionCookieOptions,
  githubStateCookieName,
  githubStateCookieOptions,
  readGithubStateCookie,
  redirectWithGithubError,
} from "@/server/github-auth";

export async function GET(request: NextRequest) {
  console.info("github_login_callback_received", {
    requestHost: request.nextUrl.host,
    path: request.nextUrl.pathname,
    hasCode: request.nextUrl.searchParams.has("code"),
    hasState: request.nextUrl.searchParams.has("state"),
    hasStateCookie: Boolean(request.cookies.get(githubStateCookieName)?.value),
  });
  const error = request.nextUrl.searchParams.get("error_description")
    ?? request.nextUrl.searchParams.get("error");
  if (error) {
    console.warn("github_login_callback_provider_error", { error });
    return redirectWithGithubError(request, error, "/login");
  }

  let config: ReturnType<typeof githubOAuthConfig>;
  try {
    config = githubOAuthConfig(request);
  } catch (configError) {
    console.warn("github_login_callback_config_error", {
      error: configError instanceof Error ? configError.message : "GitHub login is not configured",
    });
    return redirectWithGithubError(
      request,
      configError instanceof Error ? configError.message : "GitHub login is not configured",
      "/login",
    );
  }

  let statePayload;
  try {
    statePayload = readGithubStateCookie(
      config,
      request.cookies.get(githubStateCookieName)?.value,
      request.nextUrl.searchParams.get("state"),
    );
  } catch (stateError) {
    console.warn("github_login_callback_state_error", {
      error: stateError instanceof Error ? stateError.message : "GitHub login failed",
    });
    return redirectWithGithubError(
      request,
      stateError instanceof Error ? stateError.message : "GitHub login failed",
      "/login",
    );
  }

  try {
    const code = request.nextUrl.searchParams.get("code");
    if (!code) {
      throw new Error("Missing GitHub authorization code");
    }

    const accessToken = await exchangeGithubCode(config, code);
    const profile = await fetchGithubProfile(accessToken);
    const authPayload = await completeGithubLogin(profile);
    console.info("github_login_callback_complete", {
      requestHost: request.nextUrl.host,
      organizationId: authPayload.organization_id,
      role: authPayload.role,
      githubLogin: authPayload.github_login,
    });
    const redirectUrl = new URL(statePayload.returnTo, githubPublicOrigin(request));
    const response = NextResponse.redirect(redirectUrl);
    response.cookies.set(githubStateCookieName, "", {
      ...githubStateCookieOptions(request),
      maxAge: 0,
    });
    response.cookies.set(
      githubSessionCookieName,
      encodeSessionCookie(authPayload),
      githubSessionCookieOptions(request),
    );
    response.cookies.set(
      githubAuthTokenCookieName,
      authPayload.auth_token,
      githubAuthTokenCookieOptions(request),
    );
    return response;
  } catch (callbackError) {
    console.warn("github_login_callback_error", {
      error: callbackError instanceof Error ? callbackError.message : "GitHub login failed",
    });
    const response = redirectWithGithubError(
      request,
      callbackError instanceof Error ? callbackError.message : "GitHub login failed",
      "/login",
    );
    response.cookies.set(githubStateCookieName, "", {
      ...githubStateCookieOptions(request),
      maxAge: 0,
    });
    return response;
  }
}
