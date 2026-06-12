export type AiProvider = "azure" | "openai";
export type AlertTrigger = "exception" | "http_5xx" | "error_rate";
export type AlertMode = "has_results" | "starts_having_results" | "results_change";

export type SetupConfig = {
  apiBaseUrl: string;
  userEmail: string;
  userPassword: string;
  userDisplayName: string;
  authToken: string;
  userId: string;
  webhookPath: string;
  webhookId: string;
  publicWebhookBaseUrl: string;
  githubRepo: string;
  githubDefaultBranch: string;
  targetRepoUrl: string;
  githubToken: string;
  logfireRegion: "us" | "eu";
  logfireReadToken: string;
  logfireProjectUrl: string;
  logfireServiceName: string;
  logfireRoute: string;
  alertTrigger: AlertTrigger;
  alertMode: AlertMode;
  alertWindowMinutes: string;
  aiProvider: AiProvider;
  openaiModel: string;
  openaiApiKey: string;
  azureEndpoint: string;
  azureDeployment: string;
  azureApiVersion: string;
  azureApiKey: string;
  postgresHost: string;
  postgresPort: string;
  postgresUser: string;
  postgresPassword: string;
  postgresDb: string;
  redisEnabled: boolean;
  redisHost: string;
  redisPort: string;
  redisUsername: string;
  redisPassword: string;
  redisTtlSeconds: string;
};

export const defaultSetupConfig: SetupConfig = {
  apiBaseUrl: process.env.NEXT_PUBLIC_AUTO_TRIAGE_API_URL ?? "http://127.0.0.1:8001",
  userEmail: "operator@example.com",
  userPassword: "change-me-now",
  userDisplayName: "Operator",
  authToken: "",
  userId: "",
  webhookPath: "",
  webhookId: "",
  publicWebhookBaseUrl: "",
  githubRepo: "owner/repo",
  githubDefaultBranch: "main",
  targetRepoUrl: "https://github.com/owner/repo.git",
  githubToken: "",
  logfireRegion: "us",
  logfireReadToken: "",
  logfireProjectUrl: "",
  logfireServiceName: "test-app-failure-generator",
  logfireRoute: "/lean",
  alertTrigger: "http_5xx",
  alertMode: "starts_having_results",
  alertWindowMinutes: "10",
  aiProvider: "azure",
  openaiModel: "openai:gpt-4.1-mini",
  openaiApiKey: "",
  azureEndpoint: "",
  azureDeployment: "",
  azureApiVersion: "",
  azureApiKey: "",
  postgresHost: "postgres",
  postgresPort: "5432",
  postgresUser: "auto_triage",
  postgresPassword: "auto_triage_password",
  postgresDb: "auto_triage",
  redisEnabled: true,
  redisHost: "redis",
  redisPort: "6379",
  redisUsername: "auto_triage",
  redisPassword: "auto_triage_redis_password",
  redisTtlSeconds: "300",
};

export function autoTriageWebhookUrl(config: SetupConfig): string {
  const base = normalizeUrl(config.publicWebhookBaseUrl || config.apiBaseUrl);
  const path = config.webhookPath || "/webhooks/logfire";
  const separator = path.includes("?") ? "&" : "?";
  return `${base}${path}${separator}ai_provider=${config.aiProvider}`;
}

export function logfireBaseUrl(region: SetupConfig["logfireRegion"]): string {
  return region === "eu" ? "https://logfire-eu.pydantic.dev" : "https://logfire-us.pydantic.dev";
}

export function buildEnv(config: SetupConfig): string {
  return [
    "ENVIRONMENT=production",
    "RUN_WORKER=true",
    "",
    `POSTGRES_HOST=${config.postgresHost}`,
    `POSTGRES_PORT=${config.postgresPort}`,
    `POSTGRES_USER=${config.postgresUser}`,
    `POSTGRES_PASSWORD=${config.postgresPassword}`,
    `POSTGRES_DB=${config.postgresDb}`,
    "DATABASE_URL=",
    "",
    `REDIS_CACHE_ENABLED=${String(config.redisEnabled)}`,
    `REDIS_HOST=${config.redisHost}`,
    `REDIS_PORT=${config.redisPort}`,
    "REDIS_DB=0",
    `REDIS_USERNAME=${config.redisUsername}`,
    `REDIS_PASSWORD=${config.redisPassword}`,
    `REDIS_CACHE_TTL_SECONDS=${config.redisTtlSeconds}`,
    "",
    `LOGFIRE_BASE_URL=${logfireBaseUrl(config.logfireRegion)}`,
    `LOGFIRE_READ_TOKEN=${config.logfireReadToken}`,
    `LOGFIRE_PROJECT_URL=${config.logfireProjectUrl}`,
    "LOGFIRE_LOOKBACK_HOURS=2",
    "",
    `OPENAI_API_KEY=${config.openaiApiKey}`,
    `TRIAGE_MODEL=${config.openaiModel}`,
    "OPENAI_TRIAGE_MODEL=",
    "",
    `AZURE_OPENAI_ENDPOINT=${config.azureEndpoint}`,
    `AZURE_OPENAI_API_KEY=${config.azureApiKey}`,
    `AZURE_OPENAI_API_VERSION=${config.azureApiVersion}`,
    `AZURE_OPENAI_DEPLOYMENT=${config.azureDeployment}`,
    "",
    `GITHUB_TOKEN=${config.githubToken}`,
    `GITHUB_REPO=${config.githubRepo}`,
    `GITHUB_DEFAULT_BRANCH=${config.githubDefaultBranch}`,
    `TARGET_REPO_URL=${config.targetRepoUrl}`,
    "",
    "WORKSPACE_DIR=.auto-triage-work",
    "CLEANUP_REPO_AFTER_TRIAGE=true",
  ].join("\n");
}

export function buildLogfireQuery(config: SetupConfig): string {
  if (config.alertTrigger === "exception") {
    return [
      "SELECT",
      "  trace_id,",
      "  service_name,",
      "  span_name,",
      "  attributes->>'http.route' AS route,",
      "  http_response_status_code,",
      "  message,",
      "  exception_type,",
      "  exception_message",
      "FROM records",
      "WHERE is_exception",
      "  AND level >= 'error'",
      config.logfireServiceName
        ? `  AND service_name = '${escapeSql(config.logfireServiceName)}'`
        : "",
      "ORDER BY start_timestamp DESC",
      "LIMIT 25",
    ]
      .filter(Boolean)
      .join("\n");
  }

  if (config.alertTrigger === "error_rate") {
    return [
      "SELECT",
      "  service_name,",
      "  attributes->>'http.route' AS route,",
      "  count(*) FILTER (WHERE http_response_status_code >= 500) AS errors,",
      "  count(*) AS total,",
      "  count(*) FILTER (WHERE http_response_status_code >= 500)::float / count(*) AS error_rate",
      "FROM records",
      `WHERE start_timestamp > now() - interval '${Number(config.alertWindowMinutes) || 10} minutes'`,
      config.logfireServiceName
        ? `  AND service_name = '${escapeSql(config.logfireServiceName)}'`
        : "",
      config.logfireRoute ? `  AND attributes->>'http.route' = '${escapeSql(config.logfireRoute)}'` : "",
      "GROUP BY service_name, attributes->>'http.route'",
      "HAVING count(*) >= 10",
      "   AND count(*) FILTER (WHERE http_response_status_code >= 500)::float / count(*) >= 0.2",
      "ORDER BY error_rate DESC",
    ]
      .filter(Boolean)
      .join("\n");
  }

  return [
    "SELECT",
    "  trace_id,",
    "  service_name,",
    "  span_name,",
    "  attributes->>'http.route' AS route,",
    "  http_response_status_code,",
    "  message",
    "FROM records",
    "WHERE http_response_status_code >= 500",
    config.logfireServiceName ? `  AND service_name = '${escapeSql(config.logfireServiceName)}'` : "",
    config.logfireRoute ? `  AND attributes->>'http.route' = '${escapeSql(config.logfireRoute)}'` : "",
    "ORDER BY start_timestamp DESC",
    "LIMIT 25",
  ]
    .filter(Boolean)
    .join("\n");
}

export function buildSmokeTest(config: SetupConfig): string {
  return [
    `curl -X POST '${autoTriageWebhookUrl(config)}' \\`,
    "  -H 'content-type: application/json' \\",
    "  -d '{",
    '    "columns": [',
    '      {"name": "trace_id"},',
    '      {"name": "service_name"},',
    '      {"name": "span_name"},',
    '      {"name": "route"},',
    '      {"name": "http_response_status_code"},',
    '      {"name": "exception_type"},',
    '      {"name": "exception_message"}',
    "    ],",
    '    "data": [[',
    '      "0123456789abcdef0123456789abcdef",',
    `      "${jsonEscape(config.logfireServiceName)}",`,
    `      "GET ${jsonEscape(config.logfireRoute || "/")}",`,
    `      "${jsonEscape(config.logfireRoute || "/")}",`,
    "      500,",
    '      "RuntimeError",',
    '      "Intentional setup smoke test"',
    "    ]]",
    "  }'",
  ].join("\n");
}

export function setupProgress(config: SetupConfig): number {
  const checks = [
    config.apiBaseUrl,
    config.authToken,
    config.webhookPath,
    config.githubRepo,
    config.githubDefaultBranch,
    config.targetRepoUrl,
    config.logfireServiceName,
    config.logfireRoute,
    config.aiProvider === "azure" ? config.azureEndpoint : config.openaiModel,
    config.aiProvider === "azure" ? config.azureDeployment : config.openaiApiKey,
    config.postgresHost,
    config.postgresUser,
    config.redisEnabled ? config.redisHost : "redis-disabled",
  ];
  const done = checks.filter(Boolean).length;
  return Math.round((done / checks.length) * 100);
}

function normalizeUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

function escapeSql(value: string): string {
  return value.replaceAll("'", "''");
}

function jsonEscape(value: string): string {
  return value.replaceAll("\\", "\\\\").replaceAll('"', '\\"');
}
