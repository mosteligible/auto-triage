"use client";

import {
  Check,
  Clipboard,
  Database,
  GitFork,
  KeyRound,
  RadioTower,
  RefreshCw,
  Save,
  Send,
  ServerCog,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  AlertMode,
  AlertTrigger,
  AiProvider,
  SetupConfig,
  autoTriageWebhookUrl,
  buildEnv,
  buildLogfireQuery,
  buildSmokeTest,
  defaultSetupConfig,
  logfireBaseUrl,
  logfireRegionFromBaseUrl,
  setupProgress,
} from "@/lib/setup";
import {
  fetchPersistedSetup,
  saveEnvironmentSettings,
  type PersistedEnvironmentSettings,
  type PersistedSetup,
} from "@/lib/setup-persistence";

const storageKey = "auto-triage.setup.v1";

type HealthState =
  | { kind: "idle"; label: "Not checked" }
  | { kind: "checking"; label: "Checking" }
  | { kind: "ok"; label: string }
  | { kind: "error"; label: string };

type ActionState = { kind: "idle" | "working" | "ok" | "error"; label: string };

export function SetupWorkspace() {
  const [config, setConfig] = useState<SetupConfig>(defaultSetupConfig);
  const [health, setHealth] = useState<HealthState>({ kind: "idle", label: "Not checked" });
  const [loginState, setLoginState] = useState<ActionState>({ kind: "idle", label: "Signed out" });
  const [saveState, setSaveState] = useState<ActionState>({ kind: "idle", label: "Not saved" });
  const [alertState, setAlertState] = useState<ActionState>({ kind: "idle", label: "Not sent" });
  const [syncState, setSyncState] = useState<ActionState>({ kind: "idle", label: "Not loaded" });
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const didLoadDraft = useRef(false);
  const lastLoadedToken = useRef<string | null>(null);

  useEffect(() => {
    const saved = window.localStorage.getItem(storageKey);
    const frame = window.requestAnimationFrame(() => {
      if (!saved) {
        didLoadDraft.current = true;
        return;
      }
      try {
        setConfig({ ...defaultSetupConfig, ...JSON.parse(saved) });
      } catch {
        window.localStorage.removeItem(storageKey);
      } finally {
        didLoadDraft.current = true;
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    if (!didLoadDraft.current) {
      return;
    }
    window.localStorage.setItem(storageKey, JSON.stringify(config));
  }, [config]);

  const generatedEnv = useMemo(() => buildEnv(config), [config]);
  const logfireQuery = useMemo(() => buildLogfireQuery(config), [config]);
  const smokeTest = useMemo(() => buildSmokeTest(config), [config]);
  const webhookUrl = useMemo(() => autoTriageWebhookUrl(config), [config]);
  const progress = useMemo(() => setupProgress(config), [config]);

  function update<Key extends keyof SetupConfig>(key: Key, value: SetupConfig[Key]) {
    setConfig((current) => ({ ...current, [key]: value }));
  }

  async function checkHealth() {
    setHealth({ kind: "checking", label: "Checking" });
    try {
      const response = await fetch(
        `/api/auto-triage/health?baseUrl=${encodeURIComponent(config.apiBaseUrl)}`,
      );
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        setHealth({ kind: "error", label: payload.error ?? `HTTP ${payload.status}` });
        return;
      }
      const environment = payload.payload?.environment ?? "unknown";
      setHealth({ kind: "ok", label: `Healthy (${environment})` });
    } catch (error) {
      setHealth({
        kind: "error",
        label: error instanceof Error ? error.message : "Connection failed",
      });
    }
  }

  async function login() {
    setLoginState({ kind: "working", label: "Signing in" });
    try {
      const response = await fetch("/api/auto-triage/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          baseUrl: config.apiBaseUrl,
          email: config.userEmail,
          password: config.userPassword,
          displayName: config.userDisplayName,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        setLoginState({ kind: "error", label: payload.detail ?? "Login failed" });
        return;
      }
      setConfig((current) => ({
        ...current,
        authToken: payload.auth_token,
        userId: payload.user_id,
        organizationId: payload.organization_id,
        userEmail: payload.email,
        userDisplayName: payload.display_name ?? current.userDisplayName,
      }));
      setLoginState({ kind: "ok", label: `Signed in as ${payload.email}` });
    } catch (error) {
      setLoginState({
        kind: "error",
        label: error instanceof Error ? error.message : "Login failed",
      });
    }
  }

  async function loadPersistedSetup(authToken: string) {
    setSyncState({ kind: "working", label: "Loading" });
    try {
      const persisted = await fetchPersistedSetup(authToken);
      setConfig((current) => mergePersistedSetup(current, persisted));
      setSyncState({ kind: "ok", label: "Loaded" });
    } catch (error) {
      setSyncState({
        kind: "error",
        label: error instanceof Error ? error.message : "Load failed",
      });
    }
  }

  useEffect(() => {
    if (!didLoadDraft.current || !config.authToken || lastLoadedToken.current === config.authToken) {
      return;
    }
    lastLoadedToken.current = config.authToken;
    void loadPersistedSetup(config.authToken);
  }, [config.authToken]);

  async function saveSetup() {
    setSaveState({ kind: "working", label: "Saving" });
    const [owner, repoName] = splitRepo(config.githubRepo);
    if (!owner || !repoName) {
      setSaveState({ kind: "error", label: "Repo must use owner/repo" });
      return;
    }
    if (!config.authToken) {
      setSaveState({ kind: "error", label: "Login required" });
      return;
    }

    try {
      const response = await fetch("/api/auto-triage/setup", {
        method: "PUT",
        headers: {
          "content-type": "application/json",
          Authorization: `Bearer ${config.authToken}`,
        },
        body: JSON.stringify({
          baseUrl: config.apiBaseUrl,
          config: {
            github_owner: owner,
            github_repo_name: repoName,
            github_token: config.githubToken,
            github_default_branch: config.githubDefaultBranch,
            target_repo_url: config.targetRepoUrl,
            logfire_base_url: logfireBaseUrl(config.logfireRegion),
            logfire_read_token: config.logfireReadToken || null,
            logfire_project_url: config.logfireProjectUrl || null,
            logfire_service_name: config.logfireServiceName || null,
            logfire_route: config.logfireRoute || null,
            alert_trigger: config.alertTrigger,
            alert_mode: config.alertMode,
            ai_provider: config.aiProvider,
          },
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        setSaveState({ kind: "error", label: payload.detail ?? "Save failed" });
        return;
      }

      const nextConfig: SetupConfig = {
        ...config,
        organizationId: payload.organization_id ?? config.organizationId,
        webhookId: payload.webhook_id,
        webhookPath: payload.webhook_path,
        githubRepo: payload.github_repo,
        githubDefaultBranch: payload.github_default_branch,
        targetRepoUrl: payload.target_repo_url ?? config.targetRepoUrl,
        logfireServiceName: payload.logfire_service_name ?? config.logfireServiceName,
        logfireRoute: payload.logfire_route ?? config.logfireRoute,
        aiProvider: payload.ai_provider,
      };
      const environmentSettings = await saveEnvironmentSettings(config.authToken, nextConfig);
      setConfig(applyEnvironmentSettings(nextConfig, environmentSettings));
      setSaveState({ kind: "ok", label: `Saved ${payload.github_repo}` });
    } catch (error) {
      setSaveState({
        kind: "error",
        label: error instanceof Error ? error.message : "Save failed",
      });
    }
  }

  async function sendTestAlert() {
    setAlertState({ kind: "working", label: "Sending" });
    if (!config.authToken) {
      setAlertState({ kind: "error", label: "Login required" });
      return;
    }
    try {
      const response = await fetch("/api/auto-triage/alert-test", {
        method: "POST",
        headers: {
          "content-type": "application/json",
          Authorization: `Bearer ${config.authToken}`,
        },
        body: JSON.stringify({
          baseUrl: config.apiBaseUrl,
          alert: {
            service_name: config.logfireServiceName,
            route: config.logfireRoute,
            status_code: 500,
          },
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        setAlertState({ kind: "error", label: payload.detail ?? "Alert failed" });
        return;
      }
      setAlertState({ kind: "ok", label: `Queued ${payload.incident_id}` });
    } catch (error) {
      setAlertState({
        kind: "error",
        label: error instanceof Error ? error.message : "Alert failed",
      });
    }
  }

  async function copy(value: string, key: string) {
    await navigator.clipboard.writeText(value);
    setCopiedKey(key);
    window.setTimeout(() => setCopiedKey(null), 1400);
  }

  function resetDraft() {
    window.localStorage.removeItem(storageKey);
    lastLoadedToken.current = null;
    setConfig(defaultSetupConfig);
    setHealth({ kind: "idle", label: "Not checked" });
    setSyncState({ kind: "idle", label: "Not loaded" });
  }

  return (
    <main className="appShell">
      <aside className="sidebar">
        <div className="brandBlock">
          <div className="brandMark">AT</div>
          <div>
            <h1>Auto Triage</h1>
            <p>Setup Console</p>
          </div>
        </div>

        <div className="progressBlock">
          <div className="progressHeader">
            <span>Setup</span>
            <strong>{progress}%</strong>
          </div>
          <div className="progressTrack" aria-hidden="true">
            <div className="progressValue" style={{ width: `${progress}%` }} />
          </div>
        </div>

        <nav className="stepNav" aria-label="Setup sections">
          <StepLink icon={<KeyRound size={18} />} href="#login" label="Login" />
          <StepLink icon={<ServerCog size={18} />} href="#service" label="Service" />
          <StepLink icon={<GitFork size={18} />} href="#repository" label="Repository" />
          <StepLink icon={<RadioTower size={18} />} href="#alerting" label="Alerting" />
          <StepLink icon={<Sparkles size={18} />} href="#models" label="Models" />
          <StepLink icon={<Database size={18} />} href="#runtime" label="Runtime" />
          <StepLink icon={<ShieldCheck size={18} />} href="#outputs" label="Outputs" />
        </nav>
      </aside>

      <section className="workspace" aria-label="Auto-triage setup form">
        <header className="topbar">
          <div>
            <p className="eyebrow">Repository triage setup</p>
            <h2>Configure an auto-triage deployment</h2>
          </div>
          <div className={`healthPill ${health.kind}`}>
            <span />
            {health.label}
          </div>
        </header>

        <div className="contentGrid">
          <form className="setupForm">
            <FormSection
              id="login"
              title="Login"
              icon={<KeyRound size={18} />}
              action={
                <button className="secondaryButton" type="button" onClick={login}>
                  <KeyRound size={16} />
                  Sign in
                </button>
              }
            >
              <div className="threeColumn">
                <Field
                  label="Email"
                  value={config.userEmail}
                  onChange={(value) => update("userEmail", value)}
                  placeholder="operator@example.com"
                />
                <Field
                  label="Login password"
                  type="password"
                  value={config.userPassword}
                  onChange={(value) => update("userPassword", value)}
                  placeholder="at least 8 characters"
                />
                <Field
                  label="Display name"
                  value={config.userDisplayName}
                  onChange={(value) => update("userDisplayName", value)}
                  placeholder="Operator"
                />
              </div>
              <StatusLine state={loginState} />
            </FormSection>

            <FormSection
              id="service"
              title="Service"
              icon={<ServerCog size={18} />}
              action={
                <button className="secondaryButton" type="button" onClick={checkHealth}>
                  <RefreshCw size={16} />
                  Check
                </button>
              }
            >
              <Field
                label="Auto-triage API URL"
                value={config.apiBaseUrl}
                onChange={(value) => update("apiBaseUrl", value)}
                placeholder="http://127.0.0.1:8001"
              />
              <Field
                label="Public webhook base URL"
                value={config.publicWebhookBaseUrl}
                onChange={(value) => update("publicWebhookBaseUrl", value)}
                placeholder="https://example-tunnel.trycloudflare.com"
              />
            </FormSection>

            <FormSection id="repository" title="Repository" icon={<GitFork size={18} />}>
              <div className="twoColumn">
                <Field
                  label="GitHub repo"
                  value={config.githubRepo}
                  onChange={(value) => update("githubRepo", value)}
                  placeholder="owner/repo"
                />
                <Field
                  label="Default branch"
                  value={config.githubDefaultBranch}
                  onChange={(value) => update("githubDefaultBranch", value)}
                  placeholder="main"
                />
              </div>
              <Field
                label="Target repo URL"
                value={config.targetRepoUrl}
                onChange={(value) => update("targetRepoUrl", value)}
                placeholder="https://github.com/owner/repo.git"
              />
              <Field
                label="GitHub token"
                type="password"
                value={config.githubToken}
                onChange={(value) => update("githubToken", value)}
                placeholder="fine-grained PAT"
              />
            </FormSection>

            <FormSection id="alerting" title="Alerting" icon={<RadioTower size={18} />}>
              <SegmentedControl<AlertTrigger>
                label="Alert trigger"
                value={config.alertTrigger}
                options={[
                  ["http_5xx", "HTTP 5xx"],
                  ["exception", "Exception"],
                  ["error_rate", "Error rate"],
                ]}
                onChange={(value) => update("alertTrigger", value)}
              />
              <SegmentedControl<AlertMode>
                label="Alert mode"
                value={config.alertMode}
                options={[
                  ["starts_having_results", "Starts"],
                  ["has_results", "Any results"],
                  ["results_change", "Changes"],
                ]}
                onChange={(value) => update("alertMode", value)}
              />
              <div className="threeColumn">
                <SelectField
                  label="Logfire region"
                  value={config.logfireRegion}
                  options={[
                    ["us", "US"],
                    ["eu", "EU"],
                  ]}
                  onChange={(value) => update("logfireRegion", value as "us" | "eu")}
                />
                <Field
                  label="Service name"
                  value={config.logfireServiceName}
                  onChange={(value) => update("logfireServiceName", value)}
                  placeholder="api"
                />
                <Field
                  label="Route"
                  value={config.logfireRoute}
                  onChange={(value) => update("logfireRoute", value)}
                  placeholder="/checkout"
                />
              </div>
              <div className="twoColumn">
                <Field
                  label="Read token"
                  type="password"
                  value={config.logfireReadToken}
                  onChange={(value) => update("logfireReadToken", value)}
                  placeholder="pylf_v2_..."
                />
                <Field
                  label="Project URL"
                  value={config.logfireProjectUrl}
                  onChange={(value) => update("logfireProjectUrl", value)}
                  placeholder="https://logfire.pydantic.dev/..."
                />
              </div>
              <Field
                label="Window minutes"
                type="number"
                value={config.alertWindowMinutes}
                onChange={(value) => update("alertWindowMinutes", value)}
                placeholder="10"
              />
            </FormSection>

            <FormSection id="models" title="Models" icon={<Sparkles size={18} />}>
              <SegmentedControl<AiProvider>
                label="Default provider"
                value={config.aiProvider}
                options={[
                  ["azure", "Azure OpenAI"],
                  ["openai", "OpenAI"],
                ]}
                onChange={(value) => update("aiProvider", value)}
              />
              <div className="twoColumn">
                <Field
                  label="Azure endpoint"
                  value={config.azureEndpoint}
                  onChange={(value) => update("azureEndpoint", value)}
                  placeholder="https://resource.openai.azure.com/openai/v1"
                />
                <Field
                  label="Azure deployment"
                  value={config.azureDeployment}
                  onChange={(value) => update("azureDeployment", value)}
                  placeholder="gpt-4.1-mini"
                />
              </div>
              <div className="twoColumn">
                <Field
                  label="Azure API version"
                  value={config.azureApiVersion}
                  onChange={(value) => update("azureApiVersion", value)}
                  placeholder="optional for /openai/v1"
                />
                <Field
                  label="Azure API key"
                  type="password"
                  value={config.azureApiKey}
                  onChange={(value) => update("azureApiKey", value)}
                  placeholder="key"
                />
              </div>
              <div className="twoColumn">
                <Field
                  label="OpenAI model"
                  value={config.openaiModel}
                  onChange={(value) => update("openaiModel", value)}
                  placeholder="openai:gpt-4.1-mini"
                />
                <Field
                  label="OpenAI API key"
                  type="password"
                  value={config.openaiApiKey}
                  onChange={(value) => update("openaiApiKey", value)}
                  placeholder="sk-..."
                />
              </div>
            </FormSection>

            <FormSection id="runtime" title="Runtime" icon={<Database size={18} />}>
              <div className="threeColumn">
                <Field
                  label="Postgres host"
                  value={config.postgresHost}
                  onChange={(value) => update("postgresHost", value)}
                  placeholder="postgres"
                />
                <Field
                  label="Postgres port"
                  value={config.postgresPort}
                  onChange={(value) => update("postgresPort", value)}
                  placeholder="5432"
                />
                <Field
                  label="Database"
                  value={config.postgresDb}
                  onChange={(value) => update("postgresDb", value)}
                  placeholder="auto_triage"
                />
              </div>
              <div className="twoColumn">
                <Field
                  label="Postgres user"
                  value={config.postgresUser}
                  onChange={(value) => update("postgresUser", value)}
                  placeholder="auto_triage"
                />
                <Field
                  label="Postgres password"
                  type="password"
                  value={config.postgresPassword}
                  onChange={(value) => update("postgresPassword", value)}
                  placeholder="password"
                />
              </div>
              <label className="toggleRow">
                <input
                  checked={config.redisEnabled}
                  type="checkbox"
                  onChange={(event) => update("redisEnabled", event.target.checked)}
                />
                <span>Redis cache</span>
              </label>
              <div className="threeColumn">
                <Field
                  label="Redis host"
                  value={config.redisHost}
                  onChange={(value) => update("redisHost", value)}
                  placeholder="redis"
                />
                <Field
                  label="Redis port"
                  value={config.redisPort}
                  onChange={(value) => update("redisPort", value)}
                  placeholder="6379"
                />
                <Field
                  label="Cache TTL"
                  value={config.redisTtlSeconds}
                  onChange={(value) => update("redisTtlSeconds", value)}
                  placeholder="300"
                />
              </div>
              <div className="twoColumn">
                <Field
                  label="Redis user"
                  value={config.redisUsername}
                  onChange={(value) => update("redisUsername", value)}
                  placeholder="auto_triage"
                />
                <Field
                  label="Redis password"
                  type="password"
                  value={config.redisPassword}
                  onChange={(value) => update("redisPassword", value)}
                  placeholder="password"
                />
              </div>
            </FormSection>

            <div className="formActions">
              <button className="secondaryButton" type="button" onClick={sendTestAlert}>
                <Send size={16} />
                Test alert
              </button>
              <button className="secondaryButton" type="button" onClick={saveSetup}>
                <Save size={16} />
                Save setup
              </button>
              <button className="secondaryButton" type="button" onClick={resetDraft}>
                Reset
              </button>
            </div>
            <div className="statusGrid">
              <StatusLine state={saveState} label="Setup" />
              <StatusLine state={alertState} label="Alert" />
              <StatusLine state={syncState} label="Database" />
            </div>
          </form>

          <aside className="outputRail" id="outputs" aria-label="Generated setup outputs">
            <OutputBlock
              title="Webhook URL"
              value={webhookUrl}
              copied={copiedKey === "webhook"}
              onCopy={() => copy(webhookUrl, "webhook")}
            />
            <OutputBlock
              title=".env"
              value={generatedEnv}
              copied={copiedKey === "env"}
              onCopy={() => copy(generatedEnv, "env")}
              tall
            />
            <OutputBlock
              title="Logfire query"
              value={logfireQuery}
              copied={copiedKey === "query"}
              onCopy={() => copy(logfireQuery, "query")}
              tall
            />
            <OutputBlock
              title="Smoke test"
              value={smokeTest}
              copied={copiedKey === "smoke"}
              onCopy={() => copy(smokeTest, "smoke")}
              tall
            />
          </aside>
        </div>
      </section>
    </main>
  );
}

function mergePersistedSetup(current: SetupConfig, persisted: PersistedSetup): SetupConfig {
  let next: SetupConfig = {
    ...current,
    userId: persisted.user.userId,
    organizationId: persisted.user.organizationId,
    userEmail: persisted.user.email,
    userDisplayName: persisted.user.displayName ?? current.userDisplayName,
  };

  if (persisted.repositoryConfig) {
    const repository = persisted.repositoryConfig;
    next = {
      ...next,
      organizationId: repository.organizationId,
      webhookId: repository.webhookId,
      webhookPath: repository.webhookPath,
      githubRepo: repository.githubRepo,
      githubDefaultBranch: repository.githubDefaultBranch,
      targetRepoUrl: repository.targetRepoUrl ?? "",
      githubToken: repository.githubToken,
      logfireRegion: logfireRegionFromBaseUrl(repository.logfireBaseUrl),
      logfireReadToken: repository.logfireReadToken ?? "",
      logfireProjectUrl: repository.logfireProjectUrl ?? "",
      logfireServiceName: repository.logfireServiceName ?? "",
      logfireRoute: repository.logfireRoute ?? "",
      alertTrigger: asAlertTrigger(repository.alertTrigger, next.alertTrigger),
      alertMode: asAlertMode(repository.alertMode, next.alertMode),
      aiProvider: repository.aiProvider,
    };
  }

  return applyEnvironmentSettings(next, persisted.environmentSettings);
}

function applyEnvironmentSettings(
  current: SetupConfig,
  settings: PersistedEnvironmentSettings | null,
): SetupConfig {
  if (!settings) {
    return current;
  }
  return {
    ...current,
    organizationId: settings.organizationId,
    apiBaseUrl: settings.apiBaseUrl,
    publicWebhookBaseUrl: settings.publicWebhookBaseUrl ?? "",
    logfireRegion: settings.logfireRegion,
    alertWindowMinutes: String(settings.alertWindowMinutes),
    openaiModel: settings.openaiModel,
    openaiApiKey: settings.openaiApiKey ?? "",
    azureEndpoint: settings.azureEndpoint ?? "",
    azureDeployment: settings.azureDeployment ?? "",
    azureApiVersion: settings.azureApiVersion ?? "",
    azureApiKey: settings.azureApiKey ?? "",
    postgresHost: settings.postgresHost ?? "",
    postgresPort: String(settings.postgresPort),
    postgresUser: settings.postgresUser ?? "",
    postgresPassword: settings.postgresPassword ?? "",
    postgresDb: settings.postgresDb ?? "",
    redisEnabled: settings.redisEnabled,
    redisHost: settings.redisHost ?? "",
    redisPort: String(settings.redisPort),
    redisUsername: settings.redisUsername ?? "",
    redisPassword: settings.redisPassword ?? "",
    redisTtlSeconds: String(settings.redisTtlSeconds),
  };
}

function asAlertTrigger(value: string, fallback: AlertTrigger): AlertTrigger {
  if (value === "exception" || value === "http_5xx" || value === "error_rate") {
    return value;
  }
  return fallback;
}

function asAlertMode(value: string, fallback: AlertMode): AlertMode {
  if (value === "has_results" || value === "starts_having_results" || value === "results_change") {
    return value;
  }
  return fallback;
}

function StepLink({
  href,
  icon,
  label,
}: {
  href: string;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <a href={href}>
      {icon}
      <span>{label}</span>
    </a>
  );
}

function FormSection({
  id,
  title,
  icon,
  action,
  children,
}: {
  id: string;
  title: string;
  icon: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="formSection" id={id}>
      <div className="sectionHeader">
        <div>
          {icon}
          <h3>{title}</h3>
        </div>
        {action}
      </div>
      <div className="sectionBody">{children}</div>
    </section>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: "text" | "password" | "number";
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function SelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: [string, string][];
  onChange: (value: string) => void;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue}>
            {optionLabel}
          </option>
        ))}
      </select>
    </label>
  );
}

function SegmentedControl<Value extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: Value;
  options: [Value, string][];
  onChange: (value: Value) => void;
}) {
  return (
    <fieldset className="segmentedField">
      <legend>{label}</legend>
      <div className="segmentedControl">
        {options.map(([optionValue, optionLabel]) => (
          <button
            key={optionValue}
            type="button"
            className={value === optionValue ? "selected" : ""}
            onClick={() => onChange(optionValue)}
          >
            {optionLabel}
          </button>
        ))}
      </div>
    </fieldset>
  );
}

function OutputBlock({
  title,
  value,
  copied,
  onCopy,
  tall = false,
}: {
  title: string;
  value: string;
  copied: boolean;
  onCopy: () => void;
  tall?: boolean;
}) {
  return (
    <section className="outputBlock">
      <div className="outputHeader">
        <h3>{title}</h3>
        <button className="iconTextButton" type="button" onClick={onCopy}>
          {copied ? <Check size={15} /> : <Clipboard size={15} />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className={tall ? "tall" : ""}>
        <code>{value}</code>
      </pre>
    </section>
  );
}

function StatusLine({
  state,
  label,
}: {
  state: ActionState;
  label?: string;
}) {
  return (
    <div className={`statusLine ${state.kind}`}>
      <span />
      {label ? `${label}: ` : ""}
      {state.label}
    </div>
  );
}

function splitRepo(repo: string): [string, string] {
  const [owner, repoName] = repo.split("/", 2).map((part) => part.trim());
  return [owner ?? "", repoName ?? ""];
}
