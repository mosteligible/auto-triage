import { createTRPCProxyClient, httpBatchLink } from "@trpc/client";
import type { inferRouterOutputs } from "@trpc/server";

import type { SetupConfig } from "@/lib/setup";
import type { AppRouter } from "@/server/trpc/router";

type RouterOutputs = inferRouterOutputs<AppRouter>;

export type PersistedSetup = RouterOutputs["setup"]["get"];
export type PersistedEnvironmentSettings = RouterOutputs["setup"]["saveEnvironment"];
export type PersistedSetupOutputs = {
  id: string;
  organizationId: string;
  webhookUrl: string;
  envFile: string;
  logfireQuery: string;
  createdAt: string | null;
  updatedAt: string | null;
};
export type SetupOutputsInput = {
  webhookUrl: string;
  envFile: string;
  logfireQuery: string;
};

export function setupClient(authToken?: string) {
  return createTRPCProxyClient<AppRouter>({
    links: [
      httpBatchLink({
        url: "/api/trpc",
        headers: () =>
          authToken
            ? {
                Authorization: `Bearer ${authToken}`,
              }
            : {},
      }),
    ],
  });
}

export async function fetchPersistedSetup(authToken: string): Promise<PersistedSetup> {
  return setupClient(authToken).setup.get.query();
}

export async function saveEnvironmentSettings(
  authToken: string,
  config: SetupConfig,
): Promise<PersistedEnvironmentSettings> {
  return setupClient(authToken).setup.saveEnvironment.mutate({
    apiBaseUrl: config.apiBaseUrl,
    publicWebhookBaseUrl: config.publicWebhookBaseUrl,
    logfireRegion: config.logfireRegion,
    alertWindowMinutes: numberOrDefault(config.alertWindowMinutes, 10),
    openaiModel: config.openaiModel,
    openaiApiKey: config.openaiApiKey,
    openaiApiKeyUnchanged:
      config.openaiApiKeyConfigured && !config.openaiApiKey,
    azureEndpoint: config.azureEndpoint,
    azureDeployment: config.azureDeployment,
    azureApiVersion: config.azureApiVersion,
    azureApiKey: config.azureApiKey,
    azureApiKeyUnchanged:
      config.azureApiKeyConfigured && !config.azureApiKey,
    postgresHost: config.postgresHost,
    postgresPort: numberOrDefault(config.postgresPort, 5432),
    postgresUser: config.postgresUser,
    postgresPassword: config.postgresPassword,
    postgresPasswordUnchanged:
      config.postgresPasswordConfigured && !config.postgresPassword,
    postgresDb: config.postgresDb,
    redisEnabled: config.redisEnabled,
    redisHost: config.redisHost,
    redisPort: numberOrDefault(config.redisPort, 6379),
    redisUsername: config.redisUsername,
    redisPassword: config.redisPassword,
    redisPasswordUnchanged:
      config.redisPasswordConfigured && !config.redisPassword,
    redisTtlSeconds: numberOrDefault(config.redisTtlSeconds, 300),
  });
}

export async function fetchSetupOutputs(
  authToken: string,
  apiBaseUrl: string,
): Promise<PersistedSetupOutputs | null> {
  const response = await fetch(
    `/api/auto-triage/setup-outputs?baseUrl=${encodeURIComponent(apiBaseUrl)}`,
    {
      headers: { Authorization: `Bearer ${authToken}` },
    },
  );
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail ?? "Output load failed");
  }
  return payload ? mapSetupOutputs(payload) : null;
}

export async function saveSetupOutputs(
  authToken: string,
  apiBaseUrl: string,
  outputs: SetupOutputsInput,
): Promise<PersistedSetupOutputs> {
  const response = await fetch("/api/auto-triage/setup-outputs", {
    method: "PUT",
    headers: {
      "content-type": "application/json",
      Authorization: `Bearer ${authToken}`,
    },
    body: JSON.stringify({
      baseUrl: apiBaseUrl,
      outputs: {
        webhook_url: outputs.webhookUrl,
        env_file: redactSensitiveEnvironmentValues(outputs.envFile),
        logfire_query: outputs.logfireQuery,
      },
    }),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail ?? "Output save failed");
  }
  return mapSetupOutputs(payload);
}

function redactSensitiveEnvironmentValues(value: string): string {
  const names = [
    "GITHUB_TOKEN",
    "LOGFIRE_READ_TOKEN",
    "OPENAI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
  ];
  const sensitive = new Set(names);
  return value
    .split("\n")
    .map((line) => {
      const separator = line.indexOf("=");
      if (separator < 0 || !sensitive.has(line.slice(0, separator).trim())) {
        return line;
      }
      return `${line.slice(0, separator + 1)}<stored-in-openbao>`;
    })
    .join("\n");
}

function numberOrDefault(value: string, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function mapSetupOutputs(payload: {
  id: string;
  organization_id: string;
  webhook_url: string;
  env_file: string;
  logfire_query: string;
  created_at: string | null;
  updated_at: string | null;
}): PersistedSetupOutputs {
  return {
    id: payload.id,
    organizationId: payload.organization_id,
    webhookUrl: payload.webhook_url,
    envFile: payload.env_file,
    logfireQuery: payload.logfire_query,
    createdAt: payload.created_at,
    updatedAt: payload.updated_at,
  };
}
