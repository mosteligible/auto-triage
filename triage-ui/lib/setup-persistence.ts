import { createTRPCProxyClient, httpBatchLink } from "@trpc/client";
import type { inferRouterOutputs } from "@trpc/server";

import type { SetupConfig } from "@/lib/setup";
import type { AppRouter } from "@/server/trpc/router";

type RouterOutputs = inferRouterOutputs<AppRouter>;

export type PersistedSetup = RouterOutputs["setup"]["get"];
export type PersistedEnvironmentSettings = RouterOutputs["setup"]["saveEnvironment"];

export function setupClient(authToken: string) {
  return createTRPCProxyClient<AppRouter>({
    links: [
      httpBatchLink({
        url: "/api/trpc",
        headers: () => ({
          Authorization: `Bearer ${authToken}`,
        }),
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
    azureEndpoint: config.azureEndpoint,
    azureDeployment: config.azureDeployment,
    azureApiVersion: config.azureApiVersion,
    azureApiKey: config.azureApiKey,
    postgresHost: config.postgresHost,
    postgresPort: numberOrDefault(config.postgresPort, 5432),
    postgresUser: config.postgresUser,
    postgresPassword: config.postgresPassword,
    postgresDb: config.postgresDb,
    redisEnabled: config.redisEnabled,
    redisHost: config.redisHost,
    redisPort: numberOrDefault(config.redisPort, 6379),
    redisUsername: config.redisUsername,
    redisPassword: config.redisPassword,
    redisTtlSeconds: numberOrDefault(config.redisTtlSeconds, 300),
  });
}

function numberOrDefault(value: string, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}
