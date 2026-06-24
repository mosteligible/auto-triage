import { randomBytes } from "node:crypto";

import { TRPCError, initTRPC } from "@trpc/server";
import type { PoolClient } from "pg";
import { z } from "zod";

import { pool, query } from "@/server/db";
import { newUuid7Hex } from "@/server/ids";
import type {
  CurrentUser,
  OrganizationRole,
  PlatformRole,
  TrpcContext,
} from "@/server/trpc/context";

const t = initTRPC.context<TrpcContext>().create();

const environmentSettingsInput = z.object({
  apiBaseUrl: z.string().min(1).max(1024),
  publicWebhookBaseUrl: z.string().max(1024).optional().nullable(),
  logfireRegion: z.enum(["us", "eu"]),
  alertWindowMinutes: z.coerce.number().int().min(1).max(1440),
  openaiModel: z.string().min(1).max(256),
  openaiApiKey: z.string().optional().nullable(),
  openaiApiKeyUnchanged: z.boolean().default(false),
  azureEndpoint: z.string().max(1024).optional().nullable(),
  azureDeployment: z.string().max(256).optional().nullable(),
  azureApiVersion: z.string().max(128).optional().nullable(),
  azureApiKey: z.string().optional().nullable(),
  azureApiKeyUnchanged: z.boolean().default(false),
  postgresHost: z.string().max(256).optional().nullable(),
  postgresPort: z.coerce.number().int().min(1).max(65535),
  postgresUser: z.string().max(256).optional().nullable(),
  postgresPassword: z.string().optional().nullable(),
  postgresPasswordUnchanged: z.boolean().default(false),
  postgresDb: z.string().max(256).optional().nullable(),
  redisEnabled: z.boolean(),
  redisHost: z.string().max(256).optional().nullable(),
  redisPort: z.coerce.number().int().min(1).max(65535),
  redisUsername: z.string().max(256).optional().nullable(),
  redisPassword: z.string().optional().nullable(),
  redisPasswordUnchanged: z.boolean().default(false),
  redisTtlSeconds: z.coerce.number().int().min(0).max(86_400),
});

const environmentVariableInput = z.object({
  id: z.string().length(32).optional().nullable(),
  name: z
    .string()
    .trim()
    .min(1)
    .max(256)
    .regex(/^[A-Za-z_][A-Za-z0-9_]*$/, "Use a valid environment variable name"),
  value: z.string().max(262_144),
  sensitive: z.boolean(),
  retainExisting: z.boolean().default(false),
});

const environmentVariablesInput = z.object({
  variables: z.array(environmentVariableInput).max(200),
});

const organizationInput = z.object({
  name: z.string().trim().min(1).max(256),
  slug: z.string().trim().max(256).optional().nullable(),
});

const organizationIdInput = z.object({
  organizationId: z.string().length(32),
});

const organizationRoleInput = z.enum(["admin", "write", "read"]);
const platformRoleInput = z.enum(["admin", "user"]);

const organizationUserInput = z.object({
  organizationId: z.string().length(32),
  email: z.string().trim().email().max(320).transform((value) => value.toLowerCase()),
  displayName: z.string().trim().max(256).optional().nullable(),
  githubLogin: z.string().trim().max(256).optional().nullable(),
  role: organizationRoleInput,
  platformRole: platformRoleInput.optional(),
});

const organizationUserUpdateInput = organizationUserInput.extend({
  membershipId: z.string().length(32),
  userId: z.string().length(32),
});

const organizationMembershipInput = z.object({
  organizationId: z.string().length(32),
  membershipId: z.string().length(32),
});

type EnvironmentSettingsInput = z.infer<typeof environmentSettingsInput>;

type RepositoryConfigRow = {
  id: string;
  organization_id: string;
  webhook_id: string;
  github_owner: string;
  github_repo_name: string;
  github_token: string;
  github_default_branch: string;
  target_repo_url: string | null;
  logfire_base_url: string;
  logfire_read_token: string | null;
  logfire_project_url: string | null;
  logfire_service_name: string | null;
  logfire_route: string | null;
  alert_trigger: string;
  alert_mode: string;
  ai_provider: "azure" | "openai";
  created_at: Date | string | null;
  updated_at: Date | string | null;
};

type EnvironmentSettingsRow = {
  id: string;
  organization_id: string;
  api_base_url: string;
  public_webhook_base_url: string | null;
  logfire_region: "us" | "eu";
  alert_window_minutes: number;
  openai_model: string;
  openai_api_key: string | null;
  azure_openai_endpoint: string | null;
  azure_openai_deployment: string | null;
  azure_openai_api_version: string | null;
  azure_openai_api_key: string | null;
  postgres_host: string | null;
  postgres_port: number;
  postgres_user: string | null;
  postgres_password: string | null;
  postgres_db: string | null;
  redis_enabled: boolean;
  redis_host: string | null;
  redis_port: number;
  redis_username: string | null;
  redis_password: string | null;
  redis_ttl_seconds: number;
  created_at: Date | string | null;
  updated_at: Date | string | null;
};

type AdminOrganizationRow = {
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  organization_created_at: Date | string | null;
  user_count: string | number;
};

type AdminOrganizationMemberRow = {
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  organization_created_at: Date | string | null;
  membership_id: string | null;
  role: string | null;
  membership_created_at: Date | string | null;
  user_id: string | null;
  email: string | null;
  display_name: string | null;
  github_login: string | null;
  github_avatar_url: string | null;
  platform_role: string | null;
  user_created_at: Date | string | null;
};

type MembershipForUpdateRow = {
  id: string;
  organization_id: string;
  user_id: string;
  role: OrganizationRole;
};

type EnvironmentVariablesApiResponse = {
  organization_id: string;
  organization_name: string;
  variables: Array<{
    id: string;
    name: string;
    value: string;
    sensitive: boolean;
    configured: boolean;
    position: number;
    updated_at: string | null;
  }>;
  updated_at: string | null;
};

type EnvironmentSettingsApiResponse = {
  id: string;
  organization_id: string;
  api_base_url: string;
  public_webhook_base_url: string | null;
  logfire_region: "us" | "eu";
  alert_window_minutes: number;
  openai_model: string;
  openai_api_key_configured: boolean;
  azure_openai_endpoint: string | null;
  azure_openai_deployment: string | null;
  azure_openai_api_version: string | null;
  azure_openai_api_key_configured: boolean;
  postgres_host: string | null;
  postgres_port: number;
  postgres_user: string | null;
  postgres_password_configured: boolean;
  postgres_db: string | null;
  redis_enabled: boolean;
  redis_host: string | null;
  redis_port: number;
  redis_username: string | null;
  redis_password_configured: boolean;
  redis_ttl_seconds: number;
  created_at: string | null;
  updated_at: string | null;
};

const protectedProcedure = t.procedure.use(({ ctx, next }) => {
  if (!ctx.user) {
    throw new TRPCError({ code: "UNAUTHORIZED" });
  }
  return next({ ctx: { ...ctx, user: ctx.user } });
});

const writeProcedure = protectedProcedure.use(({ ctx, next }) => {
  if (ctx.user.role !== "admin" && ctx.user.role !== "write") {
    throw new TRPCError({ code: "FORBIDDEN", message: "Organization write role is required" });
  }
  return next({ ctx });
});

const adminProcedure = protectedProcedure.use(({ ctx, next }) => {
  if (!isPlatformAdmin(ctx.user) && ctx.user.role !== "admin") {
    throw new TRPCError({ code: "FORBIDDEN", message: "Admin role is required" });
  }
  return next({ ctx });
});

const platformAdminProcedure = protectedProcedure.use(({ ctx, next }) => {
  if (!isPlatformAdmin(ctx.user)) {
    throw new TRPCError({ code: "FORBIDDEN", message: "Platform admin role is required" });
  }
  return next({ ctx });
});

export const appRouter = t.router({
  setup: t.router({
    get: protectedProcedure.query(async ({ ctx }) => {
      const [repositoryConfig, environmentSettings] = await Promise.all([
        readRepositoryConfig(ctx.user),
        readEnvironmentSettings(ctx.user),
      ]);

      return {
        user: ctx.user,
        repositoryConfig,
        environmentSettings,
      };
    }),

    saveEnvironment: writeProcedure
      .input(environmentSettingsInput)
      .mutation(async ({ ctx, input }) => {
        const settings = await saveEnvironmentSettingsViaApi(ctx.authToken, input);
        await invalidateOrganizationSettingsCache(ctx.authToken, input.apiBaseUrl);
        return settings;
      }),

    environmentVariables: protectedProcedure.query(async ({ ctx }) => {
      return readEnvironmentVariablesViaApi(ctx.authToken);
    }),

    saveEnvironmentVariables: writeProcedure
      .input(environmentVariablesInput)
      .mutation(async ({ ctx, input }) => {
        const names = input.variables.map((variable) => variable.name);
        if (new Set(names).size !== names.length) {
          throw new TRPCError({
            code: "BAD_REQUEST",
            message: "Environment variable names must be unique",
          });
        }

        return saveEnvironmentVariablesViaApi(ctx.authToken, input);
      }),
  }),
  admin: t.router({
    organizations: adminProcedure.query(async ({ ctx }) => {
      const rows = await query<AdminOrganizationRow>(
        `
          SELECT
            organizations.id AS organization_id,
            organizations.name AS organization_name,
            organizations.slug AS organization_slug,
            organizations.created_at AS organization_created_at,
            count(memberships.id) AS user_count
          FROM organizations
          LEFT JOIN organization_memberships AS memberships
            ON memberships.organization_id = organizations.id
          WHERE ($1::text IS NULL OR organizations.id = $1)
          GROUP BY organizations.id, organizations.name, organizations.slug, organizations.created_at
          ORDER BY organizations.name ASC
        `,
        [isPlatformAdmin(ctx.user) ? null : ctx.user.organizationId],
      );

      return {
        organizations: rows.map((row) => ({
          id: row.organization_id,
          name: row.organization_name,
          slug: row.organization_slug,
          createdAt: asIso(row.organization_created_at),
          userCount: Number(row.user_count),
        })),
      };
    }),

    createOrganization: platformAdminProcedure
      .input(organizationInput)
      .mutation(async ({ input }) => {
        const client = await pool.connect();
        try {
          await client.query("BEGIN");
          const organizationId = newUuid7Hex();
          const slug = await uniqueOrganizationSlug(client, input.slug || input.name);
          const rows = await client.query<AdminOrganizationRow>(
            `
              INSERT INTO organizations (id, name, slug)
              VALUES ($1, $2, $3)
              RETURNING
                id AS organization_id,
                name AS organization_name,
                slug AS organization_slug,
                created_at AS organization_created_at,
                0 AS user_count
            `,
            [organizationId, input.name, slug],
          );
          await client.query("COMMIT");
          const row = rows.rows[0];
          return {
            id: row.organization_id,
            name: row.organization_name,
            slug: row.organization_slug,
            createdAt: asIso(row.organization_created_at),
            userCount: Number(row.user_count),
          };
        } catch (error) {
          await client.query("ROLLBACK");
          throw adminMutationError(error, "Organization could not be created");
        } finally {
          client.release();
        }
      }),

    updateOrganization: adminProcedure
      .input(organizationIdInput.merge(organizationInput))
      .mutation(async ({ ctx, input }) => {
        assertCanManageOrganization(ctx.user, input.organizationId);
        const client = await pool.connect();
        try {
          await client.query("BEGIN");
          const slug = await uniqueOrganizationSlug(
            client,
            input.slug || input.name,
            input.organizationId,
          );
          const rows = await client.query<AdminOrganizationRow>(
            `
              UPDATE organizations
              SET name = $2, slug = $3, updated_at = now()
              WHERE id = $1
              RETURNING
                id AS organization_id,
                name AS organization_name,
                slug AS organization_slug,
                created_at AS organization_created_at,
                (
                  SELECT count(*)
                  FROM organization_memberships
                  WHERE organization_id = organizations.id
                ) AS user_count
            `,
            [input.organizationId, input.name, slug],
          );
          const row = rows.rows[0];
          if (!row) {
            throw new TRPCError({ code: "NOT_FOUND", message: "Organization not found" });
          }
          await client.query("COMMIT");
          return {
            id: row.organization_id,
            name: row.organization_name,
            slug: row.organization_slug,
            createdAt: asIso(row.organization_created_at),
            userCount: Number(row.user_count),
          };
        } catch (error) {
          await client.query("ROLLBACK");
          throw adminMutationError(error, "Organization could not be updated");
        } finally {
          client.release();
        }
      }),

    deleteOrganization: platformAdminProcedure
      .input(organizationIdInput)
      .mutation(async ({ ctx, input }) => {
        if (input.organizationId === ctx.user.organizationId) {
          throw new TRPCError({
            code: "BAD_REQUEST",
            message: "You cannot delete the organization for your current admin session",
          });
        }

        const client = await pool.connect();
        try {
          await client.query("BEGIN");
          const existing = await client.query<{ id: string }>(
            "SELECT id FROM organizations WHERE id = $1",
            [input.organizationId],
          );
          if (!existing.rows[0]) {
            throw new TRPCError({ code: "NOT_FOUND", message: "Organization not found" });
          }

          await client.query(
            `
              DELETE FROM github_pull_request_links
              WHERE incident_id IN (
                SELECT id FROM incidents WHERE organization_id = $1
              )
            `,
            [input.organizationId],
          );
          await client.query(
            `
              DELETE FROM github_issue_links
              WHERE incident_id IN (
                SELECT id FROM incidents WHERE organization_id = $1
              )
            `,
            [input.organizationId],
          );
          await client.query(
            `
              DELETE FROM evidence_bundles
              WHERE incident_id IN (
                SELECT id FROM incidents WHERE organization_id = $1
              )
            `,
            [input.organizationId],
          );
          await client.query(
            `
              DELETE FROM triage_jobs
              WHERE incident_id IN (
                SELECT id FROM incidents WHERE organization_id = $1
              )
            `,
            [input.organizationId],
          );
          await client.query("DELETE FROM incidents WHERE organization_id = $1", [
            input.organizationId,
          ]);
          await client.query("DELETE FROM user_repository_configs WHERE organization_id = $1", [
            input.organizationId,
          ]);
          await client.query(
            "DELETE FROM organization_environment_variables WHERE organization_id = $1",
            [input.organizationId],
          );
          await client.query(
            "DELETE FROM organization_setup_outputs WHERE organization_id = $1",
            [input.organizationId],
          );
          await client.query(
            "DELETE FROM organization_environment_settings WHERE organization_id = $1",
            [input.organizationId],
          );
          await client.query("DELETE FROM organization_memberships WHERE organization_id = $1", [
            input.organizationId,
          ]);
          await client.query("DELETE FROM organizations WHERE id = $1", [input.organizationId]);
          await client.query("COMMIT");
          return { deleted: true };
        } catch (error) {
          await client.query("ROLLBACK");
          throw adminMutationError(error, "Organization could not be deleted");
        } finally {
          client.release();
        }
      }),

    organization: adminProcedure
      .input(z.object({ organizationId: z.string().length(32) }))
      .query(async ({ ctx, input }) => {
        assertCanManageOrganization(ctx.user, input.organizationId);
        const rows = await query<AdminOrganizationMemberRow>(
          `
            SELECT
              organizations.id AS organization_id,
              organizations.name AS organization_name,
              organizations.slug AS organization_slug,
              organizations.created_at AS organization_created_at,
              memberships.id AS membership_id,
              memberships.role,
              memberships.created_at AS membership_created_at,
              users.id AS user_id,
              users.email,
              users.display_name,
              users.github_login,
              users.github_avatar_url,
              users.platform_role,
              users.created_at AS user_created_at
            FROM organizations
            LEFT JOIN organization_memberships AS memberships
              ON memberships.organization_id = organizations.id
            LEFT JOIN triage_users AS users
              ON users.id = memberships.user_id
            WHERE organizations.id = $1
            ORDER BY memberships.created_at ASC
          `,
          [input.organizationId],
        );
        const first = rows[0];
        if (!first) {
          throw new TRPCError({ code: "NOT_FOUND", message: "Organization not found" });
        }

        return {
          id: first.organization_id,
          name: first.organization_name,
          slug: first.organization_slug,
          createdAt: asIso(first.organization_created_at),
          users: rows.flatMap((row) =>
            row.membership_id && row.user_id && row.email && row.role
              ? [
                  {
                    membershipId: row.membership_id,
                    userId: row.user_id,
                    email: row.email,
                    displayName: row.display_name,
                    githubLogin: row.github_login,
                    githubAvatarUrl: row.github_avatar_url,
                    platformRole: asPlatformRole(row.platform_role),
                    role: asOrganizationRole(row.role),
                    membershipCreatedAt: asIso(row.membership_created_at),
                    userCreatedAt: asIso(row.user_created_at),
                  },
                ]
              : [],
          ),
        };
      }),

    addOrganizationUser: adminProcedure
      .input(organizationUserInput)
      .mutation(async ({ ctx, input }) => {
        assertCanManageOrganization(ctx.user, input.organizationId);
        assertCanSetPlatformRole(ctx.user, input.platformRole);
        const client = await pool.connect();
        try {
          await client.query("BEGIN");
          await ensureOrganizationExists(client, input.organizationId);

          const userId = await upsertAdminManagedUser(client, {
            ...input,
            platformRole: isPlatformAdmin(ctx.user) ? input.platformRole : undefined,
          });
          await client.query(
            `
              INSERT INTO organization_memberships (id, organization_id, user_id, role)
              VALUES ($1, $2, $3, $4)
              ON CONFLICT ON CONSTRAINT uq_org_membership_org_user
              DO UPDATE SET role = EXCLUDED.role, updated_at = now()
            `,
            [newUuid7Hex(), input.organizationId, userId, input.role],
          );

          await client.query("COMMIT");
          return { saved: true };
        } catch (error) {
          await client.query("ROLLBACK");
          throw adminMutationError(error, "User could not be added");
        } finally {
          client.release();
        }
      }),

    updateOrganizationUser: adminProcedure
      .input(organizationUserUpdateInput)
      .mutation(async ({ ctx, input }) => {
        assertCanManageOrganization(ctx.user, input.organizationId);
        assertCanSetPlatformRole(ctx.user, input.platformRole);
        const client = await pool.connect();
        try {
          await client.query("BEGIN");
          const membership = await readMembershipForUpdate(client, input.membershipId);
          if (
            !membership ||
            membership.organization_id !== input.organizationId ||
            membership.user_id !== input.userId
          ) {
            throw new TRPCError({ code: "NOT_FOUND", message: "Membership not found" });
          }
          if (input.userId === ctx.user.userId && input.role !== "admin") {
            throw new TRPCError({
              code: "BAD_REQUEST",
              message: "You cannot remove your own admin role",
            });
          }
          if (
            input.userId === ctx.user.userId &&
            input.platformRole &&
            input.platformRole !== "admin"
          ) {
            throw new TRPCError({
              code: "BAD_REQUEST",
              message: "You cannot remove your own platform admin role",
            });
          }
          if (membership.role === "admin" && input.role !== "admin") {
            await ensureAnotherOrganizationAdmin(client, input.organizationId, input.userId);
          }

          await client.query(
            `
              UPDATE triage_users
              SET
                email = $2,
                display_name = $3,
                github_login = $4,
                platform_role = COALESCE($5, platform_role),
                updated_at = now()
              WHERE id = $1
            `,
            [
              input.userId,
              input.email,
              blankToNull(input.displayName),
              blankToNull(input.githubLogin),
              isPlatformAdmin(ctx.user) ? input.platformRole ?? null : null,
            ],
          );
          await client.query(
            `
              UPDATE organization_memberships
              SET role = $2, updated_at = now()
              WHERE id = $1
            `,
            [input.membershipId, input.role],
          );

          await client.query("COMMIT");
          return { saved: true };
        } catch (error) {
          await client.query("ROLLBACK");
          throw adminMutationError(error, "User could not be updated");
        } finally {
          client.release();
        }
      }),

    removeOrganizationUser: adminProcedure
      .input(organizationMembershipInput)
      .mutation(async ({ ctx, input }) => {
        assertCanManageOrganization(ctx.user, input.organizationId);
        const client = await pool.connect();
        try {
          await client.query("BEGIN");
          const membership = await readMembershipForUpdate(client, input.membershipId);
          if (!membership || membership.organization_id !== input.organizationId) {
            throw new TRPCError({ code: "NOT_FOUND", message: "Membership not found" });
          }
          if (membership.user_id === ctx.user.userId) {
            throw new TRPCError({
              code: "BAD_REQUEST",
              message: "You cannot remove your own admin membership",
            });
          }
          if (membership.role === "admin") {
            await ensureAnotherOrganizationAdmin(
              client,
              input.organizationId,
              membership.user_id,
            );
          }

          await reassignEnvironmentVariableUpdates(client, input.organizationId, membership.user_id);
          await client.query(
            `
              UPDATE incidents
              SET user_config_id = NULL, updated_at = now()
              WHERE user_config_id IN (
                SELECT id
                FROM user_repository_configs
                WHERE organization_id = $1 AND user_id = $2
              )
            `,
            [input.organizationId, membership.user_id],
          );
          await client.query(
            "DELETE FROM user_repository_configs WHERE organization_id = $1 AND user_id = $2",
            [input.organizationId, membership.user_id],
          );
          await client.query("DELETE FROM organization_memberships WHERE id = $1", [
            input.membershipId,
          ]);

          await client.query("COMMIT");
          return { removed: true };
        } catch (error) {
          await client.query("ROLLBACK");
          throw adminMutationError(error, "User could not be removed");
        } finally {
          client.release();
        }
      }),
  }),
});

export type AppRouter = typeof appRouter;
export type PersistedSetup = Awaited<ReturnType<typeof readPersistedSetup>>;
export type PersistedEnvironmentSettings = ReturnType<typeof mapEnvironmentSettings>;

async function readPersistedSetup(user: CurrentUser) {
  const [repositoryConfig, environmentSettings] = await Promise.all([
    readRepositoryConfig(user),
    readEnvironmentSettings(user),
  ]);
  return { user, repositoryConfig, environmentSettings };
}

async function readRepositoryConfig(user: CurrentUser) {
  const rows = await query<RepositoryConfigRow>(
    `
      SELECT
        id,
        organization_id,
        webhook_id,
        github_owner,
        github_repo_name,
        github_token,
        github_default_branch,
        target_repo_url,
        logfire_base_url,
        logfire_read_token,
        logfire_project_url,
        logfire_service_name,
        logfire_route,
        alert_trigger,
        alert_mode,
        ai_provider,
        created_at,
        updated_at
      FROM user_repository_configs
      WHERE user_id = $1
        AND organization_id = $2
      LIMIT 1
    `,
    [user.userId, user.organizationId],
  );
  const row = rows[0];
  if (!row) {
    return null;
  }

  return {
    id: row.id,
    organizationId: row.organization_id,
    webhookId: row.webhook_id,
    webhookPath: `/webhooks/users/${row.webhook_id}/logfire`,
    githubOwner: row.github_owner,
    githubRepoName: row.github_repo_name,
    githubRepo: `${row.github_owner}/${row.github_repo_name}`,
    githubToken: "",
    githubTokenConfigured: Boolean(row.github_token),
    githubDefaultBranch: row.github_default_branch,
    targetRepoUrl: row.target_repo_url,
    logfireBaseUrl: row.logfire_base_url,
    logfireReadToken: null,
    logfireReadTokenConfigured: Boolean(row.logfire_read_token),
    logfireProjectUrl: row.logfire_project_url,
    logfireServiceName: row.logfire_service_name,
    logfireRoute: row.logfire_route,
    alertTrigger: row.alert_trigger,
    alertMode: row.alert_mode,
    aiProvider: row.ai_provider,
    createdAt: asIso(row.created_at),
    updatedAt: asIso(row.updated_at),
  };
}

async function readEnvironmentSettings(user: CurrentUser) {
  const rows = await query<EnvironmentSettingsRow>(
    `
      SELECT *
      FROM organization_environment_settings
      WHERE organization_id = $1
      LIMIT 1
    `,
    [user.organizationId],
  );
  return rows[0] ? mapEnvironmentSettings(rows[0]) : null;
}

function mapEnvironmentSettings(row: EnvironmentSettingsRow) {
  return {
    id: row.id,
    organizationId: row.organization_id,
    apiBaseUrl: row.api_base_url,
    publicWebhookBaseUrl: row.public_webhook_base_url,
    logfireRegion: row.logfire_region,
    alertWindowMinutes: row.alert_window_minutes,
    openaiModel: row.openai_model,
    openaiApiKey: null,
    openaiApiKeyConfigured: Boolean(row.openai_api_key),
    azureEndpoint: row.azure_openai_endpoint,
    azureDeployment: row.azure_openai_deployment,
    azureApiVersion: row.azure_openai_api_version,
    azureApiKey: null,
    azureApiKeyConfigured: Boolean(row.azure_openai_api_key),
    postgresHost: row.postgres_host,
    postgresPort: row.postgres_port,
    postgresUser: row.postgres_user,
    postgresPassword: null,
    postgresPasswordConfigured: Boolean(row.postgres_password),
    postgresDb: row.postgres_db,
    redisEnabled: row.redis_enabled,
    redisHost: row.redis_host,
    redisPort: row.redis_port,
    redisUsername: row.redis_username,
    redisPassword: null,
    redisPasswordConfigured: Boolean(row.redis_password),
    redisTtlSeconds: row.redis_ttl_seconds,
    createdAt: asIso(row.created_at),
    updatedAt: asIso(row.updated_at),
  };
}

async function saveEnvironmentSettingsViaApi(
  authToken: string | null,
  input: EnvironmentSettingsInput,
) {
  const payload = await autoTriageRequest<EnvironmentSettingsApiResponse>(
    authToken,
    "/users/me/environment-settings",
    {
      method: "PUT",
      body: JSON.stringify({
        api_base_url: input.apiBaseUrl,
        public_webhook_base_url: input.publicWebhookBaseUrl,
        logfire_region: input.logfireRegion,
        alert_window_minutes: input.alertWindowMinutes,
        openai_model: input.openaiModel,
        openai_api_key: input.openaiApiKey,
        openai_api_key_unchanged: input.openaiApiKeyUnchanged,
        azure_openai_endpoint: input.azureEndpoint,
        azure_openai_deployment: input.azureDeployment,
        azure_openai_api_version: input.azureApiVersion,
        azure_openai_api_key: input.azureApiKey,
        azure_openai_api_key_unchanged: input.azureApiKeyUnchanged,
        postgres_host: input.postgresHost,
        postgres_port: input.postgresPort,
        postgres_user: input.postgresUser,
        postgres_password: input.postgresPassword,
        postgres_password_unchanged: input.postgresPasswordUnchanged,
        postgres_db: input.postgresDb,
        redis_enabled: input.redisEnabled,
        redis_host: input.redisHost,
        redis_port: input.redisPort,
        redis_username: input.redisUsername,
        redis_password: input.redisPassword,
        redis_password_unchanged: input.redisPasswordUnchanged,
        redis_ttl_seconds: input.redisTtlSeconds,
      }),
    },
  );
  return mapEnvironmentSettingsApi(payload);
}

async function readEnvironmentVariablesViaApi(authToken: string | null) {
  const payload = await autoTriageRequest<EnvironmentVariablesApiResponse>(
    authToken,
    "/users/me/environment-variables",
  );
  return mapEnvironmentVariablesApi(payload);
}

async function saveEnvironmentVariablesViaApi(
  authToken: string | null,
  input: z.infer<typeof environmentVariablesInput>,
) {
  const payload = await autoTriageRequest<EnvironmentVariablesApiResponse>(
    authToken,
    "/users/me/environment-variables",
    {
      method: "PUT",
      body: JSON.stringify({
        variables: input.variables.map((variable) => ({
          id: variable.id,
          name: variable.name,
          value: variable.value,
          sensitive: variable.sensitive,
          retain_existing: variable.retainExisting,
        })),
      }),
    },
  );
  return mapEnvironmentVariablesApi(payload);
}

function mapEnvironmentVariablesApi(payload: EnvironmentVariablesApiResponse) {
  return {
    organizationId: payload.organization_id,
    organizationName: payload.organization_name,
    variables: payload.variables.map((variable) => ({
      id: variable.id,
      name: variable.name,
      value: variable.value,
      sensitive: variable.sensitive,
      configured: variable.configured,
      position: variable.position,
      updatedAt: variable.updated_at,
    })),
    updatedAt: payload.updated_at,
  };
}

function mapEnvironmentSettingsApi(payload: EnvironmentSettingsApiResponse) {
  return {
    id: payload.id,
    organizationId: payload.organization_id,
    apiBaseUrl: payload.api_base_url,
    publicWebhookBaseUrl: payload.public_webhook_base_url,
    logfireRegion: payload.logfire_region,
    alertWindowMinutes: payload.alert_window_minutes,
    openaiModel: payload.openai_model,
    openaiApiKey: null,
    openaiApiKeyConfigured: payload.openai_api_key_configured,
    azureEndpoint: payload.azure_openai_endpoint,
    azureDeployment: payload.azure_openai_deployment,
    azureApiVersion: payload.azure_openai_api_version,
    azureApiKey: null,
    azureApiKeyConfigured: payload.azure_openai_api_key_configured,
    postgresHost: payload.postgres_host,
    postgresPort: payload.postgres_port,
    postgresUser: payload.postgres_user,
    postgresPassword: null,
    postgresPasswordConfigured: payload.postgres_password_configured,
    postgresDb: payload.postgres_db,
    redisEnabled: payload.redis_enabled,
    redisHost: payload.redis_host,
    redisPort: payload.redis_port,
    redisUsername: payload.redis_username,
    redisPassword: null,
    redisPasswordConfigured: payload.redis_password_configured,
    redisTtlSeconds: payload.redis_ttl_seconds,
    createdAt: payload.created_at,
    updatedAt: payload.updated_at,
  };
}

async function autoTriageRequest<Response>(
  authToken: string | null,
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  if (!authToken) {
    throw new TRPCError({ code: "UNAUTHORIZED" });
  }
  const baseUrl = normalizeUrl(
    process.env.AUTO_TRIAGE_API_URL ??
      process.env.NEXT_PUBLIC_AUTO_TRIAGE_API_URL ??
      "http://127.0.0.1:8001",
  );
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      "content-type": "application/json",
      Authorization: `Bearer ${authToken}`,
      ...init.headers,
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new TRPCError({
      code:
        response.status === 401
          ? "UNAUTHORIZED"
          : response.status === 403
            ? "FORBIDDEN"
            : response.status === 404
              ? "NOT_FOUND"
              : response.status === 422
                ? "BAD_REQUEST"
                : "INTERNAL_SERVER_ERROR",
      message:
        typeof payload.detail === "string"
          ? payload.detail
          : `Auto-triage API failed with HTTP ${response.status}`,
    });
  }
  return payload as Response;
}

function asIso(value: Date | string | null): string | null {
  if (value instanceof Date) {
    return value.toISOString();
  }
  return value;
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

function asPlatformRole(value: string | null): PlatformRole {
  return value === "admin" ? "admin" : "user";
}

function isPlatformAdmin(user: CurrentUser): boolean {
  return user.platformRole === "admin";
}

function assertCanManageOrganization(user: CurrentUser, organizationId: string): void {
  if (isPlatformAdmin(user)) {
    return;
  }
  if (user.role === "admin" && user.organizationId === organizationId) {
    return;
  }
  throw new TRPCError({
    code: "FORBIDDEN",
    message: "Organization admin role is required for this organization",
  });
}

function assertCanSetPlatformRole(
  user: CurrentUser,
  platformRole: PlatformRole | undefined,
): void {
  if (!platformRole || isPlatformAdmin(user)) {
    return;
  }
  throw new TRPCError({
    code: "FORBIDDEN",
    message: "Platform admin role is required to update platform access",
  });
}

async function uniqueOrganizationSlug(
  client: PoolClient,
  value: string,
  excludeOrganizationId?: string,
): Promise<string> {
  const base = slugBase(value);
  for (let index = 0; index < 100; index += 1) {
    const suffix = index === 0 ? "" : `-${index + 1}`;
    const candidate = `${base.slice(0, 256 - suffix.length)}${suffix}`;
    const existing = await client.query<{ id: string }>(
      `
        SELECT id
        FROM organizations
        WHERE slug = $1
          AND ($2::text IS NULL OR id <> $2)
        LIMIT 1
      `,
      [candidate, excludeOrganizationId ?? null],
    );
    if (!existing.rows[0]) {
      return candidate;
    }
  }
  throw new TRPCError({
    code: "CONFLICT",
    message: "Organization slug could not be made unique",
  });
}

function slugBase(value: string): string {
  const slug = value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 96);
  return slug || "organization";
}

async function ensureOrganizationExists(
  client: PoolClient,
  organizationId: string,
): Promise<void> {
  const existing = await client.query<{ id: string }>(
    "SELECT id FROM organizations WHERE id = $1 LIMIT 1",
    [organizationId],
  );
  if (!existing.rows[0]) {
    throw new TRPCError({ code: "NOT_FOUND", message: "Organization not found" });
  }
}

async function upsertAdminManagedUser(
  client: PoolClient,
  input: z.infer<typeof organizationUserInput>,
): Promise<string> {
  const existing = await client.query<{ id: string }>(
    `
      SELECT id
      FROM triage_users
      WHERE email = $1
      LIMIT 1
    `,
    [input.email],
  );
  const displayName = blankToNull(input.displayName);
  const githubLogin = blankToNull(input.githubLogin);
  const row = existing.rows[0];
  const platformRole = input.platformRole ?? "user";
  if (row) {
    await client.query(
      `
        UPDATE triage_users
        SET
          display_name = COALESCE($2, display_name),
          github_login = COALESCE($3, github_login),
          platform_role = COALESCE($4, platform_role),
          updated_at = now()
        WHERE id = $1
      `,
      [row.id, displayName, githubLogin, input.platformRole ?? null],
    );
    return row.id;
  }

  const userId = newUuid7Hex();
  await client.query(
    `
      INSERT INTO triage_users (
        id,
        email,
        display_name,
        github_login,
        platform_role,
        password_hash,
        auth_token_hash
      )
      VALUES ($1, $2, $3, $4, $5, $6, $7)
    `,
    [
      userId,
      input.email,
      displayName,
      githubLogin,
      platformRole,
      `admin_created$${randomBytes(16).toString("hex")}`,
      randomBytes(32).toString("hex"),
    ],
  );
  return userId;
}

async function readMembershipForUpdate(
  client: PoolClient,
  membershipId: string,
): Promise<MembershipForUpdateRow | null> {
  const result = await client.query<MembershipForUpdateRow>(
    `
      SELECT id, organization_id, user_id, role
      FROM organization_memberships
      WHERE id = $1
      FOR UPDATE
    `,
    [membershipId],
  );
  return result.rows[0] ?? null;
}

async function ensureAnotherOrganizationAdmin(
  client: PoolClient,
  organizationId: string,
  excludedUserId: string,
): Promise<void> {
  const result = await client.query<{ count: string }>(
    `
      SELECT count(*) AS count
      FROM organization_memberships
      WHERE organization_id = $1
        AND user_id <> $2
        AND role = 'admin'
    `,
    [organizationId, excludedUserId],
  );
  if (Number(result.rows[0]?.count ?? 0) < 1) {
    throw new TRPCError({
      code: "BAD_REQUEST",
      message: "An organization must keep at least one admin",
    });
  }
}

async function reassignEnvironmentVariableUpdates(
  client: PoolClient,
  organizationId: string,
  removedUserId: string,
): Promise<void> {
  const dependentRows = await client.query<{ count: string }>(
    `
      SELECT count(*) AS count
      FROM organization_environment_variables
      WHERE organization_id = $1
        AND updated_by_user_id = $2
    `,
    [organizationId, removedUserId],
  );
  if (Number(dependentRows.rows[0]?.count ?? 0) === 0) {
    return;
  }

  const fallback = await client.query<{ user_id: string }>(
    `
      SELECT user_id
      FROM organization_memberships
      WHERE organization_id = $1
        AND user_id <> $2
      ORDER BY
        CASE role
          WHEN 'admin' THEN 0
          WHEN 'write' THEN 1
          ELSE 2
        END,
        created_at ASC
      LIMIT 1
    `,
    [organizationId, removedUserId],
  );
  const fallbackUserId = fallback.rows[0]?.user_id;
  if (!fallbackUserId) {
    throw new TRPCError({
      code: "BAD_REQUEST",
      message: "Cannot remove the only user while organization environment variables reference them",
    });
  }

  await client.query(
    `
      UPDATE organization_environment_variables
      SET updated_by_user_id = $3, updated_at = now()
      WHERE organization_id = $1
        AND updated_by_user_id = $2
    `,
    [organizationId, removedUserId, fallbackUserId],
  );
}

function blankToNull(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

function adminMutationError(error: unknown, fallbackMessage: string): TRPCError {
  if (error instanceof TRPCError) {
    return error;
  }
  if (isUniqueViolation(error)) {
    return new TRPCError({
      code: "CONFLICT",
      message: "A record with that email, slug, or GitHub identity already exists",
    });
  }
  return new TRPCError({
    code: "INTERNAL_SERVER_ERROR",
    message: error instanceof Error ? error.message : fallbackMessage,
  });
}

function isUniqueViolation(error: unknown): boolean {
  return Boolean(
    error &&
      typeof error === "object" &&
      "code" in error &&
      (error as { code?: string }).code === "23505",
  );
}

async function invalidateOrganizationSettingsCache(
  authToken: string | null,
  apiBaseUrl: string,
): Promise<void> {
  if (!authToken || !apiBaseUrl) {
    return;
  }

  const baseUrl = normalizeUrl(
    process.env.AUTO_TRIAGE_API_URL ?? process.env.NEXT_PUBLIC_AUTO_TRIAGE_API_URL ?? apiBaseUrl,
  );
  try {
    const response = await fetch(`${baseUrl}/users/me/cache/organization-settings/invalidate`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${authToken}`,
      },
    });
    if (!response.ok) {
      console.warn("Failed to invalidate organization settings cache", response.status);
    }
  } catch (error) {
    console.warn("Failed to invalidate organization settings cache", error);
  }
}

function normalizeUrl(value: string): string {
  return value.replace(/\/+$/, "");
}
