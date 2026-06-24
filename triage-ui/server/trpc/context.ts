import { createHash } from "node:crypto";

import { query } from "@/server/db";

export type OrganizationRole = "admin" | "write" | "read";
export type PlatformRole = "admin" | "user";

export type CurrentUser = {
  userId: string;
  email: string;
  displayName: string | null;
  githubLogin: string | null;
  organizationId: string;
  organizationName: string;
  organizationSlug: string;
  role: OrganizationRole;
  platformRole: PlatformRole;
};

type UserRow = {
  user_id: string;
  email: string;
  display_name: string | null;
  github_login: string | null;
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  role: string;
  platform_role: string;
};

export type TrpcContext = {
  authToken: string | null;
  user: CurrentUser | null;
};

export async function createTRPCContext(request: Request): Promise<TrpcContext> {
  const token =
    bearerToken(request.headers.get("authorization")) ??
    cookieValue(request.headers.get("cookie"), "auto_triage.auth_token");
  if (!token) {
    return { authToken: null, user: null };
  }

  const rows = await query<UserRow>(
    `
      SELECT
        users.id AS user_id,
        users.email,
        users.display_name,
        users.github_login,
        memberships.organization_id,
        organizations.name AS organization_name,
        organizations.slug AS organization_slug,
        memberships.role,
        users.platform_role
      FROM triage_users AS users
      INNER JOIN organization_memberships AS memberships
        ON memberships.user_id = users.id
      INNER JOIN organizations
        ON organizations.id = memberships.organization_id
      WHERE users.auth_token_hash = $1
      ORDER BY memberships.created_at ASC
      LIMIT 1
    `,
    [tokenHash(token)],
  );
  const row = rows[0];
  if (!row) {
    return { authToken: null, user: null };
  }

  return {
    authToken: token,
    user: {
      userId: row.user_id,
      email: row.email,
      displayName: row.display_name,
      githubLogin: row.github_login,
      organizationId: row.organization_id,
      organizationName: row.organization_name,
      organizationSlug: row.organization_slug,
      role: asOrganizationRole(row.role),
      platformRole: asPlatformRole(row.platform_role),
    },
  };
}

function bearerToken(value: string | null): string | null {
  if (!value?.toLowerCase().startsWith("bearer ")) {
    return null;
  }
  return value.slice("bearer ".length).trim() || null;
}

function cookieValue(header: string | null, name: string): string | null {
  if (!header) {
    return null;
  }
  const prefix = `${encodeURIComponent(name)}=`;
  const item = header.split(";").map((value) => value.trim()).find((value) => value.startsWith(prefix));
  return item ? decodeURIComponent(item.slice(prefix.length)) : null;
}

function tokenHash(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

function asOrganizationRole(value: string): OrganizationRole {
  if (value === "admin" || value === "owner") {
    return "admin";
  }
  if (value === "write" || value === "read") {
    return value;
  }
  return "read";
}

function asPlatformRole(value: string): PlatformRole {
  return value === "admin" ? "admin" : "user";
}
