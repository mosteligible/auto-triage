import { createHash, createHmac, randomBytes } from "node:crypto";
import type { PoolClient } from "pg";
import { NextRequest, NextResponse } from "next/server";

import { pool } from "@/server/db";
import { newUuid7Hex } from "@/server/ids";

export const githubStateCookieName = "auto_triage.github_oauth_state";
export const githubSessionCookieName = "auto_triage.github_auth";
export const githubAuthTokenCookieName = "auto_triage.auth_token";

const githubAuthorizeUrl = "https://github.com/login/oauth/authorize";
const githubAccessTokenUrl = "https://github.com/login/oauth/access_token";
const githubUserUrl = "https://api.github.com/user";
const githubUserEmailsUrl = "https://api.github.com/user/emails";
const stateMaxAgeSeconds = 10 * 60;
const sessionMaxAgeSeconds = 2 * 60;
const authTokenMaxAgeSeconds = 7 * 24 * 60 * 60;

export type GithubAuthMode = "login" | "register";

export type GithubAuthPayload = {
  auth_token: string;
  user_id: string;
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  role: "admin" | "write" | "read";
  platform_role: "admin" | "user";
  email: string;
  display_name: string | null;
  github_login: string;
};

type GithubOAuthConfig = {
  authKind: "github_app" | "oauth_app";
  clientId: string;
  clientSecret: string;
  redirectUri: string;
  stateSecret: string;
};

type GithubStatePayload = {
  nonce: string;
  mode: GithubAuthMode;
  organizationName: string | null;
  returnTo: string;
  createdAt: number;
};

type GithubUserResponse = {
  id: number;
  login: string;
  name?: string | null;
  email?: string | null;
  avatar_url?: string | null;
};

type GithubEmailResponse = {
  email: string;
  primary: boolean;
  verified: boolean;
}[];

type GithubProfile = {
  id: string;
  login: string;
  name: string | null;
  email: string;
  avatarUrl: string | null;
};

type UserRow = {
  id: string;
  email: string;
  display_name: string | null;
  github_id: string | null;
  platform_role: "admin" | "user";
};

type MembershipRow = {
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  role: "admin" | "write" | "read";
};

type AuthSessionRow = {
  user_id: string;
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  role: "admin" | "write" | "read";
  platform_role: "admin" | "user";
  email: string;
  display_name: string | null;
  github_login: string | null;
};

export function githubOAuthConfig(request: NextRequest): GithubOAuthConfig {
  const authKind = githubAuthKind();
  const clientId = githubClientId(authKind);
  const clientSecret = githubClientSecret(authKind);
  warnIfGithubAppUsesLegacyAliases();

  if (!clientId || !clientSecret) {
    throw new Error(
      authKind === "github_app"
        ? "GitHub App login is not configured"
        : "GitHub OAuth App login is not configured",
    );
  }

  return {
    authKind,
    clientId,
    clientSecret,
    redirectUri: githubRedirectUri(request, configuredGithubRedirectUri(authKind)),
    stateSecret:
      githubStateSecret(authKind) ?? clientSecret,
  };
}

function githubRedirectUri(request: NextRequest, configuredRedirect: string | null): string {
  if (!configuredRedirect) {
    return new URL("/api/auth/callback/github", githubPublicOrigin(request)).toString();
  }

  const parsedRedirect = parseUrl(configuredRedirect);
  if (!parsedRedirect) {
    return new URL("/api/auth/callback/github", githubPublicOrigin(request)).toString();
  }

  const explicitOrigin = configuredPublicOrigin();
  if (!explicitOrigin) {
    if (isLocalOrBindHost(parsedRedirect.host)) {
      return new URL(
        `${parsedRedirect.pathname}${parsedRedirect.search}${parsedRedirect.hash}`,
        githubPublicOrigin(request),
      ).toString();
    }
    return parsedRedirect.toString();
  }

  return new URL(
    `${parsedRedirect.pathname}${parsedRedirect.search}${parsedRedirect.hash}`,
    explicitOrigin,
  ).toString();
}

export function githubPublicOrigin(request: NextRequest): string {
  const parsedExplicitOrigin = configuredPublicOrigin();
  if (parsedExplicitOrigin) {
    return parsedExplicitOrigin;
  }

  const forwardedHost = firstHeaderValue(request.headers.get("x-forwarded-host"));
  if (forwardedHost && !isBindHost(forwardedHost)) {
    const forwardedProto =
      firstHeaderValue(request.headers.get("x-forwarded-proto")) ??
      request.nextUrl.protocol.replace(":", "") ??
      "http";
    return `${forwardedProto}://${forwardedHost}`;
  }

  const host = firstHeaderValue(request.headers.get("host"));
  if (host && !isBindHost(host)) {
    return `${request.nextUrl.protocol}//${host}`;
  }

  const configuredRedirect = configuredGithubRedirectUri(githubAuthKind());
  const configuredOrigin = configuredRedirect ? parseOrigin(configuredRedirect) : null;
  if (configuredOrigin) {
    return configuredOrigin;
  }

  return request.nextUrl.origin;
}

export function createGithubStateCookie(
  config: GithubOAuthConfig,
  input: {
    mode: GithubAuthMode;
    organizationName?: string | null;
    returnTo?: string | null;
  },
): { state: string; cookieValue: string } {
  const payload: GithubStatePayload = {
    nonce: randomBytes(24).toString("base64url"),
    mode: input.mode,
    organizationName: blankToNull(input.organizationName),
    returnTo: safeReturnTo(input.returnTo),
    createdAt: Date.now(),
  };
  return {
    state: payload.nonce,
    cookieValue: signPayload(config.stateSecret, payload),
  };
}

export function readGithubStateCookie(
  config: GithubOAuthConfig,
  cookieValue: string | undefined,
  state: string | null,
): GithubStatePayload {
  if (!cookieValue || !state) {
    throw new Error("Missing GitHub login state");
  }

  const payload = verifyPayload<GithubStatePayload>(config.stateSecret, cookieValue);
  if (payload.nonce !== state) {
    throw new Error("GitHub login state mismatch");
  }
  if (Date.now() - payload.createdAt > stateMaxAgeSeconds * 1000) {
    throw new Error("GitHub login state expired");
  }
  return payload;
}

export function buildGithubAuthorizeUrl(config: GithubOAuthConfig, state: string): URL {
  const url = new URL(githubAuthorizeUrl);
  url.searchParams.set("client_id", config.clientId);
  url.searchParams.set("redirect_uri", config.redirectUri);
  if (config.authKind === "oauth_app") {
    url.searchParams.set("scope", "read:user user:email");
  }
  url.searchParams.set("state", state);
  return url;
}

export async function exchangeGithubCode(
  config: GithubOAuthConfig,
  code: string,
): Promise<string> {
  const body = new URLSearchParams({
    client_id: config.clientId,
    client_secret: config.clientSecret,
    code,
    redirect_uri: config.redirectUri,
  });
  const response = await fetch(githubAccessTokenUrl, {
    method: "POST",
    headers: {
      accept: "application/json",
      "content-type": "application/x-www-form-urlencoded",
    },
    body,
  });
  const payload = (await response.json()) as {
    access_token?: string;
    error?: string;
    error_description?: string;
  };

  if (!response.ok || !payload.access_token) {
    throw new Error(payload.error_description ?? payload.error ?? "GitHub token exchange failed");
  }
  return payload.access_token;
}

export async function fetchGithubProfile(accessToken: string): Promise<GithubProfile> {
  const headers = {
    accept: "application/vnd.github+json",
    authorization: `Bearer ${accessToken}`,
    "x-github-api-version": "2022-11-28",
  };
  const [userResponse, emailResponse] = await Promise.all([
    fetch(githubUserUrl, { headers }),
    fetch(githubUserEmailsUrl, { headers }),
  ]);

  if (!userResponse.ok) {
    throw new Error("GitHub user lookup failed");
  }
  if (!emailResponse.ok) {
    throw new Error("GitHub email lookup failed");
  }

  const user = (await userResponse.json()) as GithubUserResponse;
  const emails = (await emailResponse.json()) as GithubEmailResponse;
  const verifiedEmail =
    emails.find((item) => item.primary && item.verified)?.email ??
    emails.find((item) => item.verified)?.email ??
    null;

  if (!verifiedEmail) {
    throw new Error("GitHub account needs a verified email address");
  }

  return {
    id: String(user.id),
    login: user.login,
    name: blankToNull(user.name),
    email: verifiedEmail.toLowerCase(),
    avatarUrl: blankToNull(user.avatar_url),
  };
}

export async function completeGithubLogin(profile: GithubProfile): Promise<GithubAuthPayload> {
  const client = await pool.connect();
  try {
    await client.query("BEGIN");

    const token = randomBytes(32).toString("base64url");
    const authTokenHash = tokenHash(token);
    const user = await upsertGithubUser(client, profile, authTokenHash);
    let membership = await readPrimaryMembership(client, user.id);

    if (!membership) {
      membership = await createGithubOrganization(client, user.id, profile);
    }

    await client.query("COMMIT");
    return {
      auth_token: token,
      user_id: user.id,
      organization_id: membership.organization_id,
      organization_name: membership.organization_name,
      organization_slug: membership.organization_slug,
      role: membership.role,
      platform_role: user.platform_role,
      email: profile.email,
      display_name: githubDisplayName(profile),
      github_login: profile.login,
    };
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}

export function encodeSessionCookie(payload: GithubAuthPayload): string {
  return Buffer.from(JSON.stringify(payload), "utf8").toString("base64url");
}

export async function readGithubAuthSession(
  authToken: string | undefined,
): Promise<GithubAuthPayload | null> {
  if (!authToken) {
    return null;
  }

  const result = await pool.query<AuthSessionRow>(
    `
      SELECT
        users.id AS user_id,
        memberships.organization_id,
        organizations.name AS organization_name,
        organizations.slug AS organization_slug,
        memberships.role,
        users.platform_role,
        users.email,
        users.display_name,
        users.github_login
      FROM triage_users AS users
      INNER JOIN organization_memberships AS memberships
        ON memberships.user_id = users.id
      INNER JOIN organizations
        ON organizations.id = memberships.organization_id
      WHERE users.auth_token_hash = $1
      ORDER BY memberships.created_at ASC
      LIMIT 1
    `,
    [tokenHash(authToken)],
  );
  const row = result.rows[0];
  if (!row?.github_login) {
    return null;
  }

  return {
    auth_token: authToken,
    user_id: row.user_id,
    organization_id: row.organization_id,
    organization_name: row.organization_name,
    organization_slug: row.organization_slug,
    role: row.role,
    platform_role: row.platform_role,
    email: row.email,
    display_name: row.display_name,
    github_login: row.github_login,
  };
}

export function githubAuthTokenCookieOptions(request: NextRequest) {
  return {
    httpOnly: true,
    maxAge: authTokenMaxAgeSeconds,
    path: "/",
    sameSite: "lax" as const,
    secure: request.nextUrl.protocol === "https:",
  };
}

export function githubSessionCookieOptions(request: NextRequest) {
  return {
    httpOnly: false,
    maxAge: sessionMaxAgeSeconds,
    path: "/",
    sameSite: "lax" as const,
    secure: request.nextUrl.protocol === "https:",
  };
}

export function githubStateCookieOptions(request: NextRequest) {
  return {
    httpOnly: true,
    maxAge: stateMaxAgeSeconds,
    path: "/",
    sameSite: "lax" as const,
    secure: request.nextUrl.protocol === "https:",
  };
}

export function redirectWithGithubError(
  request: NextRequest,
  message: string,
  returnTo?: string | null,
): NextResponse {
  const redirectUrl = new URL(safeReturnTo(returnTo), githubPublicOrigin(request));
  redirectUrl.searchParams.set("github_error", message);
  return NextResponse.redirect(redirectUrl);
}

async function upsertGithubUser(
  client: PoolClient,
  profile: GithubProfile,
  authTokenHash: string,
): Promise<UserRow> {
  const existing = await client.query<UserRow>(
    `
      SELECT id, email, display_name, github_id, platform_role
      FROM triage_users
      WHERE github_id = $1
         OR email = $2
      ORDER BY CASE WHEN github_id = $1 THEN 0 ELSE 1 END
      LIMIT 1
    `,
    [profile.id, profile.email],
  );
  const row = existing.rows[0];
  const displayName = githubDisplayName(profile);
  const platformRole = platformRoleForGithubProfile(profile, row?.platform_role);

  if (row) {
    if (row.github_id && row.github_id !== profile.id) {
      throw new Error("Email is already linked to a different GitHub account");
    }
    const updated = await client.query<UserRow>(
      `
        UPDATE triage_users
        SET
          email = $2,
          display_name = $3,
          github_id = $4,
          github_login = $5,
          github_avatar_url = $6,
          auth_token_hash = $7,
          platform_role = $8,
          updated_at = now()
        WHERE id = $1
        RETURNING id, email, display_name, github_id, platform_role
      `,
      [
        row.id,
        profile.email,
        displayName,
        profile.id,
        profile.login,
        profile.avatarUrl,
        authTokenHash,
        platformRole,
      ],
    );
    return updated.rows[0];
  }

  const inserted = await client.query<UserRow>(
    `
      INSERT INTO triage_users (
        id,
        email,
        display_name,
        github_id,
        github_login,
        github_avatar_url,
        platform_role,
        password_hash,
        auth_token_hash
      )
      VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
      RETURNING id, email, display_name, github_id, platform_role
    `,
    [
      newUuid7Hex(),
      profile.email,
      displayName,
      profile.id,
      profile.login,
      profile.avatarUrl,
      platformRole,
      placeholderPasswordHash(profile.id),
      authTokenHash,
    ],
  );
  return inserted.rows[0];
}

async function readPrimaryMembership(
  client: PoolClient,
  userId: string,
): Promise<MembershipRow | null> {
  const membership = await client.query<MembershipRow>(
    `
      SELECT
        memberships.organization_id,
        organizations.name AS organization_name,
        organizations.slug AS organization_slug,
        memberships.role
      FROM organization_memberships AS memberships
      INNER JOIN organizations
        ON organizations.id = memberships.organization_id
      WHERE memberships.user_id = $1
      ORDER BY memberships.created_at ASC
      LIMIT 1
    `,
    [userId],
  );
  return membership.rows[0] ?? null;
}

async function createGithubOrganization(
  client: PoolClient,
  userId: string,
  profile: GithubProfile,
): Promise<MembershipRow> {
  const organizationId = newUuid7Hex();
  const organizationName = organizationNameFromGithub(profile);
  const organizationSlug = `${slugBase(profile.login || profile.email)}-${organizationId.slice(
    0,
    8,
  )}`;
  await client.query(
    `
      INSERT INTO organizations (id, name, slug)
      VALUES ($1, $2, $3)
    `,
    [organizationId, organizationName, organizationSlug],
  );
  await client.query(
    `
      INSERT INTO organization_memberships (id, organization_id, user_id, role)
      VALUES ($1, $2, $3, 'admin')
    `,
    [newUuid7Hex(), organizationId, userId],
  );
  return {
    organization_id: organizationId,
    organization_name: organizationName,
    organization_slug: organizationSlug,
    role: "admin",
  };
}

function signPayload(secret: string, payload: GithubStatePayload): string {
  const body = Buffer.from(JSON.stringify(payload), "utf8").toString("base64url");
  const signature = createHmac("sha256", secret).update(body).digest("base64url");
  return `${body}.${signature}`;
}

function verifyPayload<Payload>(secret: string, value: string): Payload {
  const [body, signature] = value.split(".", 2);
  if (!body || !signature) {
    throw new Error("Invalid GitHub login state");
  }
  const expected = createHmac("sha256", secret).update(body).digest("base64url");
  if (signature !== expected) {
    throw new Error("Invalid GitHub login state signature");
  }
  return JSON.parse(Buffer.from(body, "base64url").toString("utf8")) as Payload;
}

function tokenHash(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

function placeholderPasswordHash(githubId: string): string {
  return `github_oauth$${githubId}$${randomBytes(16).toString("hex")}`;
}

function githubDisplayName(profile: GithubProfile): string {
  return profile.login || profile.name || profile.email;
}

function organizationNameFromGithub(profile: GithubProfile): string {
  const owner = profile.login || profile.email.split("@", 1)[0] || "GitHub";
  return `${owner} Organization`;
}

function githubAuthKind(): GithubOAuthConfig["authKind"] {
  if (process.env.GITHUB_AUTH_KIND === "oauth_app") {
    return "oauth_app";
  }
  return "github_app";
}

function githubClientId(authKind: GithubOAuthConfig["authKind"]): string | null {
  return authKind === "github_app"
    ? blankToNull(process.env.GITHUB_APP_CLIENT_ID) ??
        blankToNull(process.env.GITHUB_OAUTH_CLIENT_ID)
    : blankToNull(process.env.GITHUB_OAUTH_CLIENT_ID);
}

function githubClientSecret(authKind: GithubOAuthConfig["authKind"]): string | null {
  return authKind === "github_app"
    ? blankToNull(process.env.GITHUB_APP_CLIENT_SECRET) ??
        blankToNull(process.env.GITHUB_OAUTH_CLIENT_SECRET)
    : blankToNull(process.env.GITHUB_OAUTH_CLIENT_SECRET);
}

function configuredGithubRedirectUri(authKind: GithubOAuthConfig["authKind"]): string | null {
  return authKind === "github_app"
    ? blankToNull(process.env.GITHUB_APP_REDIRECT_URI) ??
        blankToNull(process.env.GITHUB_OAUTH_REDIRECT_URI)
    : blankToNull(process.env.GITHUB_OAUTH_REDIRECT_URI);
}

function githubStateSecret(authKind: GithubOAuthConfig["authKind"]): string | null {
  return authKind === "github_app"
    ? blankToNull(process.env.GITHUB_APP_STATE_SECRET) ??
        blankToNull(process.env.GITHUB_OAUTH_STATE_SECRET)
    : blankToNull(process.env.GITHUB_OAUTH_STATE_SECRET);
}

function warnIfGithubAppUsesLegacyAliases() {
  if (githubAuthKind() !== "github_app") {
    return;
  }

  const usesLegacyClientId =
    !blankToNull(process.env.GITHUB_APP_CLIENT_ID) &&
    Boolean(blankToNull(process.env.GITHUB_OAUTH_CLIENT_ID));
  const usesLegacyClientSecret =
    !blankToNull(process.env.GITHUB_APP_CLIENT_SECRET) &&
    Boolean(blankToNull(process.env.GITHUB_OAUTH_CLIENT_SECRET));
  const usesLegacyRedirectUri =
    !blankToNull(process.env.GITHUB_APP_REDIRECT_URI) &&
    Boolean(blankToNull(process.env.GITHUB_OAUTH_REDIRECT_URI));

  if (usesLegacyClientId || usesLegacyClientSecret || usesLegacyRedirectUri) {
    console.warn("github_app_login_uses_legacy_oauth_env_aliases", {
      clientId: usesLegacyClientId,
      clientSecret: usesLegacyClientSecret,
      redirectUri: usesLegacyRedirectUri,
    });
  }
}

function platformRoleForGithubProfile(
  profile: GithubProfile,
  existingRole: "admin" | "user" | undefined,
): "admin" | "user" {
  if (existingRole === "admin") {
    return "admin";
  }

  const adminEmails = csvEnv("TRIAGE_UI_PLATFORM_ADMIN_EMAILS");
  const adminLogins = csvEnv("TRIAGE_UI_PLATFORM_ADMIN_GITHUB_LOGINS");
  if (adminEmails.has(profile.email.toLowerCase()) || adminLogins.has(profile.login.toLowerCase())) {
    return "admin";
  }

  return "user";
}

function csvEnv(name: string): Set<string> {
  return new Set(
    (process.env[name] ?? "")
      .split(",")
      .map((value) => value.trim().toLowerCase())
      .filter(Boolean),
  );
}

function blankToNull(value: string | null | undefined): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function safeReturnTo(value: string | null | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) {
    return "/";
  }
  return value;
}

function parseOrigin(value: string): string | null {
  const parsedUrl = parseUrl(value);
  return parsedUrl?.origin ?? null;
}

function parseUrl(value: string): URL | null {
  const normalized = value.includes("://") ? value : `http://${value}`;
  try {
    return new URL(normalized);
  } catch {
    return null;
  }
}

function configuredPublicOrigin(): string | null {
  const explicitOrigin =
    blankToNull(process.env.TRIAGE_UI_PUBLIC_ORIGIN) ??
    blankToNull(process.env.NEXT_PUBLIC_TRIAGE_UI_PUBLIC_ORIGIN);
  return explicitOrigin ? parseOrigin(explicitOrigin) : null;
}

function firstHeaderValue(value: string | null): string | null {
  return blankToNull(value?.split(",", 1)[0]);
}

function isBindHost(host: string): boolean {
  const normalized = host.toLowerCase();
  return (
    normalized === "0.0.0.0" ||
    normalized.startsWith("0.0.0.0:") ||
    normalized === "[::]" ||
    normalized.startsWith("[::]:")
  );
}

function isLocalOrBindHost(host: string): boolean {
  const normalized = host.toLowerCase();
  return (
    isBindHost(normalized) ||
    normalized === "localhost" ||
    normalized.startsWith("localhost:") ||
    normalized === "127.0.0.1" ||
    normalized.startsWith("127.0.0.1:") ||
    normalized === "[::1]" ||
    normalized.startsWith("[::1]:")
  );
}

function slugBase(value: string): string {
  const slug = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug || "github-user";
}
