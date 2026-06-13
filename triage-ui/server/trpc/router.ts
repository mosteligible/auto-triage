import { TRPCError, initTRPC } from "@trpc/server";
import { z } from "zod";

import { query } from "@/server/db";
import { newUuid7Hex } from "@/server/ids";
import type { CurrentUser, TrpcContext } from "@/server/trpc/context";

const t = initTRPC.context<TrpcContext>().create();

const environmentSettingsInput = z.object({
  apiBaseUrl: z.string().min(1).max(1024),
  publicWebhookBaseUrl: z.string().max(1024).optional().nullable(),
  logfireRegion: z.enum(["us", "eu"]),
  alertWindowMinutes: z.coerce.number().int().min(1).max(1440),
  openaiModel: z.string().min(1).max(256),
  openaiApiKey: z.string().optional().nullable(),
  azureEndpoint: z.string().max(1024).optional().nullable(),
  azureDeployment: z.string().max(256).optional().nullable(),
  azureApiVersion: z.string().max(128).optional().nullable(),
  azureApiKey: z.string().optional().nullable(),
  postgresHost: z.string().max(256).optional().nullable(),
  postgresPort: z.coerce.number().int().min(1).max(65535),
  postgresUser: z.string().max(256).optional().nullable(),
  postgresPassword: z.string().optional().nullable(),
  postgresDb: z.string().max(256).optional().nullable(),
  redisEnabled: z.boolean(),
  redisHost: z.string().max(256).optional().nullable(),
  redisPort: z.coerce.number().int().min(1).max(65535),
  redisUsername: z.string().max(256).optional().nullable(),
  redisPassword: z.string().optional().nullable(),
  redisTtlSeconds: z.coerce.number().int().min(0).max(86_400),
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
  user_id: string;
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

const protectedProcedure = t.procedure.use(({ ctx, next }) => {
  if (!ctx.user) {
    throw new TRPCError({ code: "UNAUTHORIZED" });
  }
  return next({ ctx: { ...ctx, user: ctx.user } });
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

    saveEnvironment: protectedProcedure
      .input(environmentSettingsInput)
      .mutation(async ({ ctx, input }) => {
        return upsertEnvironmentSettings(ctx.user, input);
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
    githubToken: row.github_token,
    githubDefaultBranch: row.github_default_branch,
    targetRepoUrl: row.target_repo_url,
    logfireBaseUrl: row.logfire_base_url,
    logfireReadToken: row.logfire_read_token,
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
      FROM user_environment_settings
      WHERE user_id = $1
        AND organization_id = $2
      LIMIT 1
    `,
    [user.userId, user.organizationId],
  );
  return rows[0] ? mapEnvironmentSettings(rows[0]) : null;
}

async function upsertEnvironmentSettings(user: CurrentUser, input: EnvironmentSettingsInput) {
  const rows = await query<EnvironmentSettingsRow>(
    `
      INSERT INTO user_environment_settings (
        id,
        organization_id,
        user_id,
        api_base_url,
        public_webhook_base_url,
        logfire_region,
        alert_window_minutes,
        openai_model,
        openai_api_key,
        azure_openai_endpoint,
        azure_openai_deployment,
        azure_openai_api_version,
        azure_openai_api_key,
        postgres_host,
        postgres_port,
        postgres_user,
        postgres_password,
        postgres_db,
        redis_enabled,
        redis_host,
        redis_port,
        redis_username,
        redis_password,
        redis_ttl_seconds
      )
      VALUES (
        $1, $2, $3, $4, $5, $6, $7, $8,
        $9, $10, $11, $12, $13, $14, $15, $16,
        $17, $18, $19, $20, $21, $22, $23, $24
      )
      ON CONFLICT (organization_id, user_id)
      DO UPDATE SET
        api_base_url = EXCLUDED.api_base_url,
        public_webhook_base_url = EXCLUDED.public_webhook_base_url,
        logfire_region = EXCLUDED.logfire_region,
        alert_window_minutes = EXCLUDED.alert_window_minutes,
        openai_model = EXCLUDED.openai_model,
        openai_api_key = EXCLUDED.openai_api_key,
        azure_openai_endpoint = EXCLUDED.azure_openai_endpoint,
        azure_openai_deployment = EXCLUDED.azure_openai_deployment,
        azure_openai_api_version = EXCLUDED.azure_openai_api_version,
        azure_openai_api_key = EXCLUDED.azure_openai_api_key,
        postgres_host = EXCLUDED.postgres_host,
        postgres_port = EXCLUDED.postgres_port,
        postgres_user = EXCLUDED.postgres_user,
        postgres_password = EXCLUDED.postgres_password,
        postgres_db = EXCLUDED.postgres_db,
        redis_enabled = EXCLUDED.redis_enabled,
        redis_host = EXCLUDED.redis_host,
        redis_port = EXCLUDED.redis_port,
        redis_username = EXCLUDED.redis_username,
        redis_password = EXCLUDED.redis_password,
        redis_ttl_seconds = EXCLUDED.redis_ttl_seconds,
        updated_at = now()
      RETURNING *
    `,
    [
      newUuid7Hex(),
      user.organizationId,
      user.userId,
      input.apiBaseUrl,
      blankToNull(input.publicWebhookBaseUrl),
      input.logfireRegion,
      input.alertWindowMinutes,
      input.openaiModel,
      blankToNull(input.openaiApiKey),
      blankToNull(input.azureEndpoint),
      blankToNull(input.azureDeployment),
      blankToNull(input.azureApiVersion),
      blankToNull(input.azureApiKey),
      blankToNull(input.postgresHost),
      input.postgresPort,
      blankToNull(input.postgresUser),
      blankToNull(input.postgresPassword),
      blankToNull(input.postgresDb),
      input.redisEnabled,
      blankToNull(input.redisHost),
      input.redisPort,
      blankToNull(input.redisUsername),
      blankToNull(input.redisPassword),
      input.redisTtlSeconds,
    ],
  );

  return mapEnvironmentSettings(rows[0]);
}

function mapEnvironmentSettings(row: EnvironmentSettingsRow) {
  return {
    id: row.id,
    organizationId: row.organization_id,
    userId: row.user_id,
    apiBaseUrl: row.api_base_url,
    publicWebhookBaseUrl: row.public_webhook_base_url,
    logfireRegion: row.logfire_region,
    alertWindowMinutes: row.alert_window_minutes,
    openaiModel: row.openai_model,
    openaiApiKey: row.openai_api_key,
    azureEndpoint: row.azure_openai_endpoint,
    azureDeployment: row.azure_openai_deployment,
    azureApiVersion: row.azure_openai_api_version,
    azureApiKey: row.azure_openai_api_key,
    postgresHost: row.postgres_host,
    postgresPort: row.postgres_port,
    postgresUser: row.postgres_user,
    postgresPassword: row.postgres_password,
    postgresDb: row.postgres_db,
    redisEnabled: row.redis_enabled,
    redisHost: row.redis_host,
    redisPort: row.redis_port,
    redisUsername: row.redis_username,
    redisPassword: row.redis_password,
    redisTtlSeconds: row.redis_ttl_seconds,
    createdAt: asIso(row.created_at),
    updatedAt: asIso(row.updated_at),
  };
}

function blankToNull(value: string | null | undefined): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function asIso(value: Date | string | null): string | null {
  if (value instanceof Date) {
    return value.toISOString();
  }
  return value;
}
