import { createHash } from "node:crypto";

import { query } from "@/server/db";

export type CurrentUser = {
  userId: string;
  email: string;
  displayName: string | null;
  organizationId: string;
  organizationName: string;
  organizationSlug: string;
  role: string;
};

type UserRow = {
  user_id: string;
  email: string;
  display_name: string | null;
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  role: string;
};

export type TrpcContext = {
  user: CurrentUser | null;
};

export async function createTRPCContext(request: Request): Promise<TrpcContext> {
  const token = bearerToken(request.headers.get("authorization"));
  if (!token) {
    return { user: null };
  }

  const rows = await query<UserRow>(
    `
      SELECT
        users.id AS user_id,
        users.email,
        users.display_name,
        memberships.organization_id,
        organizations.name AS organization_name,
        organizations.slug AS organization_slug,
        memberships.role
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
    return { user: null };
  }

  return {
    user: {
      userId: row.user_id,
      email: row.email,
      displayName: row.display_name,
      organizationId: row.organization_id,
      organizationName: row.organization_name,
      organizationSlug: row.organization_slug,
      role: row.role,
    },
  };
}

function bearerToken(value: string | null): string | null {
  if (!value?.toLowerCase().startsWith("bearer ")) {
    return null;
  }
  return value.slice("bearer ".length).trim() || null;
}

function tokenHash(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}
