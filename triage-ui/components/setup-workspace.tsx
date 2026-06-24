"use client";

import {
  Braces,
  ChevronDown,
  Check,
  CircleAlert,
  Clipboard,
  Database,
  Eye,
  EyeOff,
  GitFork,
  KeyRound,
  LoaderCircle,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  RadioTower,
  RefreshCw,
  Save,
  Send,
  ServerCog,
  ShieldCheck,
  Sparkles,
  UserPlus,
  UserCircle,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  AlertMode,
  AlertTrigger,
  AiProvider,
  OrganizationRole,
  PlatformRole,
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
  fetchSetupOutputs,
  fetchPersistedSetup,
  saveEnvironmentSettings,
  saveSetupOutputs,
  type PersistedEnvironmentSettings,
  type PersistedSetup,
  type PersistedSetupOutputs,
  type SetupOutputsInput,
} from "@/lib/setup-persistence";

const storageKey = "auto-triage.setup.v1";
const outputStorageKey = "auto-triage.setup.outputs.v1";
const githubSessionCookieName = "auto_triage.github_auth";
const githubAuthAttemptKey = "auto-triage.github-auth-attempt.v1";

type HealthState =
  | { kind: "idle"; label: "Not checked" }
  | { kind: "checking"; label: "Checking" }
  | { kind: "ok"; label: string }
  | { kind: "error"; label: string };

type ActionState = { kind: "idle" | "working" | "ok" | "error"; label: string };
type ToastState = {
  id: number;
  kind: "ok" | "error";
  title: string;
  message: string;
};
type EditableOutputKey = "webhook" | "env" | "logfireQuery";
type EditableOutputDraft = {
  value: string;
  source: string;
  dirty: boolean;
};
type EditableOutputDrafts = Record<EditableOutputKey, EditableOutputDraft>;
type GithubAuthSession = {
  auth_token: string;
  user_id: string;
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  role: OrganizationRole;
  platform_role: PlatformRole;
  email: string;
  display_name: string | null;
  github_login: string;
};
type OrganizationMember = {
  membership_id: string;
  user_id: string;
  organization_id: string;
  email: string;
  display_name: string | null;
  role: OrganizationRole;
};

export function SetupWorkspace({ initialSession }: { initialSession: GithubAuthSession }) {
  const [config, setConfig] = useState<SetupConfig>(() =>
    applyGithubAuthSession(defaultSetupConfig, initialSession),
  );
  const [health, setHealth] = useState<HealthState>({ kind: "idle", label: "Not checked" });
  const [registerState, setRegisterState] = useState<ActionState>({
    kind: "ok",
    label: `Using ${initialSession.organization_name}`,
  });
  const [loginState, setLoginState] = useState<ActionState>({
    kind: "ok",
    label: `Signed in as ${initialSession.email}`,
  });
  const [memberState, setMemberState] = useState<ActionState>({
    kind: "idle",
    label: "Not loaded",
  });
  const [saveState, setSaveState] = useState<ActionState>({ kind: "idle", label: "Not saved" });
  const [alertState, setAlertState] = useState<ActionState>({ kind: "idle", label: "Not sent" });
  const [syncState, setSyncState] = useState<ActionState>({ kind: "idle", label: "Not loaded" });
  const [toast, setToast] = useState<ToastState | null>(null);
  const [members, setMembers] = useState<OrganizationMember[]>([]);
  const [editableOutputs, setEditableOutputs] = useState<EditableOutputDrafts>(() =>
    createEditableOutputDrafts(defaultSetupConfig),
  );
  const [editingOutputs, setEditingOutputs] = useState<Record<EditableOutputKey, boolean>>({
    webhook: false,
    env: false,
    logfireQuery: false,
  });
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const didLoadDraft = useRef(false);
  const lastLoadedToken = useRef<string | null>(null);
  const toastTimer = useRef<number | null>(null);

  useEffect(() => {
    const saved = window.localStorage.getItem(storageKey);
    const frame = window.requestAnimationFrame(() => {
      let nextConfig = defaultSetupConfig;
      try {
        if (saved) {
          nextConfig = withoutSensitiveDraftValues({
            ...defaultSetupConfig,
            ...JSON.parse(saved),
          });
        }
      } catch {
        window.localStorage.removeItem(storageKey);
      }

      const githubSession = readGithubAuthSession() ?? initialSession;
      if (githubSession) {
        nextConfig = applyGithubAuthSession(nextConfig, githubSession);
        deleteCookie(githubSessionCookieName);
        window.sessionStorage.removeItem(githubAuthAttemptKey);
        lastLoadedToken.current = null;
        setLoginState({
          kind: "ok",
          label: `GitHub sign-in complete for ${githubSession.email}`,
        });
        setRegisterState({
          kind: "ok",
          label: `Using ${githubSession.organization_name}`,
        });
      }

      const githubError = readGithubError();
      if (githubError) {
        window.sessionStorage.removeItem(githubAuthAttemptKey);
        setLoginState({ kind: "error", label: `GitHub sign-in failed: ${githubError}` });
        setRegisterState({ kind: "error", label: `GitHub sign-in failed` });
      } else if (!githubSession && readGithubAuthAttempt()) {
        setLoginState({ kind: "error", label: "GitHub sign-in did not complete" });
      } else if (!githubSession && nextConfig.authToken) {
        setLoginState({ kind: "ok", label: `Signed in as ${nextConfig.userEmail}` });
      }

      setEditableOutputs(readEditableOutputDrafts(nextConfig));
      setConfig(nextConfig);
      didLoadDraft.current = true;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [initialSession]);

  useEffect(() => {
    if (!didLoadDraft.current) {
      return;
    }
    window.localStorage.setItem(
      storageKey,
      JSON.stringify(withoutSensitiveDraftValues(config)),
    );
  }, [config]);

  useEffect(() => {
    if (!didLoadDraft.current) {
      return;
    }
    window.localStorage.setItem(
      outputStorageKey,
      JSON.stringify({
        ...editableOutputs,
        env: { value: "", source: "", dirty: false },
      }),
    );
  }, [editableOutputs]);

  useEffect(() => {
    return () => {
      if (toastTimer.current) {
        window.clearTimeout(toastTimer.current);
      }
    };
  }, []);

  const generatedEnv = useMemo(() => buildEnv(config), [config]);
  const logfireQuery = useMemo(() => buildLogfireQuery(config), [config]);
  const smokeTest = useMemo(() => buildSmokeTest(config), [config]);
  const webhookUrl = useMemo(() => autoTriageWebhookUrl(config), [config]);
  const outputSources = useMemo<Record<EditableOutputKey, string>>(
    () => ({
      webhook: webhookUrl,
      env: generatedEnv,
      logfireQuery,
    }),
    [generatedEnv, logfireQuery, webhookUrl],
  );
  const webhookOutput = editableOutputs.webhook.dirty
    ? editableOutputs.webhook.value
    : outputSources.webhook;
  const envOutput = editableOutputs.env.dirty ? editableOutputs.env.value : outputSources.env;
  const logfireQueryOutput = editableOutputs.logfireQuery.dirty
    ? editableOutputs.logfireQuery.value
    : outputSources.logfireQuery;
  const progress = useMemo(() => setupProgress(config), [config]);
  const canWrite = config.organizationRole === "admin" || config.organizationRole === "write";
  const canAdmin = config.platformRole === "admin" || config.organizationRole === "admin";
  const signedIn = Boolean(config.authToken);

  function update<Key extends keyof SetupConfig>(key: Key, value: SetupConfig[Key]) {
    setConfig((current) => ({ ...current, [key]: value }));
  }

  function updateEditableOutput(key: EditableOutputKey, value: string) {
    setEditableOutputs((current) => {
      const source = outputSources[key];
      return {
        ...current,
        [key]: {
          value,
          source,
          dirty: value !== source,
        },
      };
    });
  }

  function toggleEditableOutput(key: EditableOutputKey) {
    setEditingOutputs((current) => ({ ...current, [key]: !current[key] }));
  }

  function resetEditableOutput(key: EditableOutputKey) {
    const source = outputSources[key];
    setEditableOutputs((current) => ({
      ...current,
      [key]: {
        value: source,
        source,
        dirty: false,
      },
    }));
    setEditingOutputs((current) => ({ ...current, [key]: false }));
  }

  function showToast(kind: ToastState["kind"], title: string, message: string) {
    if (toastTimer.current) {
      window.clearTimeout(toastTimer.current);
    }
    setToast({ id: Date.now(), kind, title, message });
    toastTimer.current = window.setTimeout(() => setToast(null), 4200);
  }

  function dismissToast() {
    if (toastTimer.current) {
      window.clearTimeout(toastTimer.current);
      toastTimer.current = null;
    }
    setToast(null);
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

  const loadMembers = useCallback(async function loadMembers(
    authToken = config.authToken,
    organizationName = config.organizationName,
    apiBaseUrl = config.apiBaseUrl,
  ) {
    if (!authToken) {
      return;
    }
    setMemberState({ kind: "working", label: "Loading" });
    try {
      const response = await fetch(
        `/api/auto-triage/members?baseUrl=${encodeURIComponent(apiBaseUrl)}`,
        {
          headers: { Authorization: `Bearer ${authToken}` },
        },
      );
      const payload = await response.json();
      if (!response.ok) {
        setMemberState({ kind: "error", label: payload.detail ?? "Member load failed" });
        return;
      }
      setMembers(payload);
      setMemberState({ kind: "ok", label: `${payload.length} in ${organizationName}` });
    } catch (error) {
      setMemberState({
        kind: "error",
        label: error instanceof Error ? error.message : "Member load failed",
      });
    }
  }, [config.apiBaseUrl, config.authToken, config.organizationName]);

  function startGithubAuth(mode: "login" | "register") {
    const label = mode === "register" ? "Creating with GitHub" : "Signing in with GitHub";
    setLoginState({ kind: "working", label });
    setRegisterState({ kind: "working", label });
    writeGithubAuthAttempt(mode);
    const params = new URLSearchParams({
      mode,
      organizationName: config.organizationName,
      returnTo: `${window.location.pathname}${window.location.search}`,
    });
    window.location.assign(`/api/auth/github/start?${params.toString()}`);
  }

  useEffect(() => {
    if (!didLoadDraft.current || !config.authToken || lastLoadedToken.current === config.authToken) {
      return;
    }
    const authToken = config.authToken;
    const apiBaseUrl = config.apiBaseUrl;
    lastLoadedToken.current = authToken;

    async function loadPersistedSetupForToken() {
      setSyncState({ kind: "working", label: "Loading" });
      try {
        const persisted = await fetchPersistedSetup(authToken);
        const mergedConfig = mergePersistedSetup(config, persisted);
        setConfig(mergedConfig);
        setSyncState({ kind: "ok", label: "Loaded" });
        void loadMembers(
          authToken,
          persisted.user.organizationName,
          persisted.environmentSettings?.apiBaseUrl ?? apiBaseUrl,
        );
        const persistedOutputs = await fetchSetupOutputs(authToken, mergedConfig.apiBaseUrl);
        if (persistedOutputs) {
          setEditableOutputs(outputDraftsFromPersisted(mergedConfig, persistedOutputs));
        }
      } catch (error) {
        setSyncState({
          kind: "error",
          label: error instanceof Error ? error.message : "Load failed",
        });
      }
    }

    void loadPersistedSetupForToken();
  }, [config, loadMembers]);

  async function saveSetup() {
    setSaveState({ kind: "working", label: "Saving" });
    const [owner, repoName] = splitRepo(config.githubRepo);
    if (!owner || !repoName) {
      setSaveState({ kind: "error", label: "Repo must use owner/repo" });
      showToast("error", "Save unsuccessful", "Repo must use owner/repo");
      return;
    }
    if (!config.authToken) {
      setSaveState({ kind: "error", label: "Login required" });
      showToast("error", "Save unsuccessful", "Login required");
      return;
    }
    if (!canWrite) {
      setSaveState({ kind: "error", label: "Write role required" });
      showToast("error", "Save unsuccessful", "Write role required");
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
            github_token_unchanged:
              config.githubTokenConfigured && !config.githubToken,
            github_default_branch: config.githubDefaultBranch,
            target_repo_url: config.targetRepoUrl,
            logfire_base_url: logfireBaseUrl(config.logfireRegion),
            logfire_read_token: config.logfireReadToken || null,
            logfire_read_token_unchanged:
              config.logfireReadTokenConfigured && !config.logfireReadToken,
            logfire_project_url: config.logfireProjectUrl || null,
            logfire_service_name: config.logfireServiceName || null,
            logfire_route: config.logfireRoute || null,
            alert_trigger: config.alertTrigger,
            alert_mode: config.alertMode,
            ai_provider: config.aiProvider,
          },
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const message = responseDetail(payload) ?? `HTTP ${response.status}`;
        setSaveState({ kind: "error", label: message });
        showToast("error", "Save unsuccessful", message);
        return;
      }

      const nextConfig: SetupConfig = {
        ...config,
        organizationId: payload.organization_id ?? config.organizationId,
        webhookId: payload.webhook_id,
        webhookPath: payload.webhook_path,
        githubRepo: payload.github_repo,
        githubToken: "",
        githubTokenConfigured: payload.github_token_configured,
        githubDefaultBranch: payload.github_default_branch,
        targetRepoUrl: payload.target_repo_url ?? config.targetRepoUrl,
        logfireServiceName: payload.logfire_service_name ?? config.logfireServiceName,
        logfireReadToken: "",
        logfireReadTokenConfigured: payload.logfire_read_token_configured,
        logfireRoute: payload.logfire_route ?? config.logfireRoute,
        aiProvider: payload.ai_provider,
      };
      const environmentSettings = await saveEnvironmentSettings(config.authToken, nextConfig);
      const appliedConfig = applyEnvironmentSettings(nextConfig, environmentSettings);
      const savedOutputs = await saveSetupOutputs(
        config.authToken,
        appliedConfig.apiBaseUrl,
        resolvedOutputPayload(editableOutputs, generatedOutputValues(appliedConfig)),
      );
      setConfig(appliedConfig);
      setEditableOutputs(outputDraftsFromPersisted(appliedConfig, savedOutputs));
      setEditingOutputs({ webhook: false, env: false, logfireQuery: false });
      setSaveState({ kind: "ok", label: `Saved ${payload.github_repo}` });
      showToast("ok", "Save successful", `Saved ${payload.github_repo}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Save failed";
      setSaveState({
        kind: "error",
        label: message,
      });
      showToast("error", "Save unsuccessful", message);
    }
  }

  async function sendTestAlert() {
    if (alertState.kind === "working") {
      return;
    }
    setAlertState({ kind: "working", label: "Sending" });
    if (!config.authToken) {
      setAlertState({ kind: "error", label: "Login required" });
      showToast("error", "Test unsuccessful", "Login required");
      return;
    }
    if (!canWrite) {
      setAlertState({ kind: "error", label: "Write role required" });
      showToast("error", "Test unsuccessful", "Write role required");
      return;
    }
    try {
      const [response] = await Promise.all([
        fetch("/api/auto-triage/alert-test", {
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
        }),
        minimumDelay(250),
      ]);
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const message = responseDetail(payload) ?? `HTTP ${response.status}`;
        setAlertState({ kind: "error", label: message });
        showToast("error", "Test unsuccessful", message);
        return;
      }
      setAlertState({ kind: "ok", label: `Queued ${payload.incident_id}` });
      showToast("ok", "Test successful", `Queued ${payload.incident_id}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Alert failed";
      setAlertState({
        kind: "error",
        label: message,
      });
      showToast("error", "Test unsuccessful", message);
    }
  }

  async function copy(value: string, key: string) {
    await navigator.clipboard.writeText(value);
    setCopiedKey(key);
    window.setTimeout(() => setCopiedKey(null), 1400);
  }

  function resetDraft() {
    window.localStorage.removeItem(storageKey);
    window.localStorage.removeItem(outputStorageKey);
    window.sessionStorage.removeItem(githubAuthAttemptKey);
    deleteCookie(githubSessionCookieName);
    lastLoadedToken.current = null;
    setUserMenuOpen(false);
    setConfig(defaultSetupConfig);
    setEditableOutputs(createEditableOutputDrafts(defaultSetupConfig));
    setEditingOutputs({ webhook: false, env: false, logfireQuery: false });
    setHealth({ kind: "idle", label: "Not checked" });
    setRegisterState({ kind: "idle", label: "Not registered" });
    setLoginState({ kind: "idle", label: "Signed out" });
    setMemberState({ kind: "idle", label: "Not loaded" });
    setMembers([]);
    setSyncState({ kind: "idle", label: "Not loaded" });
  }

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    window.sessionStorage.removeItem(githubAuthAttemptKey);
    deleteCookie(githubSessionCookieName);
    lastLoadedToken.current = null;
    setUserMenuOpen(false);
    setMembers([]);
    setLoginState({ kind: "idle", label: "Signed out" });
    setRegisterState({ kind: "idle", label: "Not registered" });
    setMemberState({ kind: "idle", label: "Not loaded" });
    setSyncState({ kind: "idle", label: "Not loaded" });
    const signedOutConfig: SetupConfig = {
      ...config,
      authToken: "",
      userId: "",
      organizationId: "",
      organizationSlug: "",
      organizationRole: "read",
      platformRole: "user",
      githubLogin: "",
    };
    window.localStorage.setItem(
      storageKey,
      JSON.stringify(withoutSensitiveDraftValues(signedOutConfig)),
    );
    setConfig(signedOutConfig);
    window.location.assign("/login");
  }

  return (
    <main className={`appShell ${sidebarCollapsed ? "sidebarCollapsed" : ""}`}>
      {toast ? <Toast state={toast} onDismiss={dismissToast} /> : null}
      <aside className="sidebar">
        <div className="sidebarTop">
          <div className="brandBlock">
            <div className="brandMark">AT</div>
            <div>
              <h1>Auto Triage</h1>
              <p>Setup Console</p>
            </div>
          </div>
          <button
            className="iconButton sidebarToggle"
            type="button"
            aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-expanded={!sidebarCollapsed}
            onClick={() => setSidebarCollapsed((current) => !current)}
          >
            {sidebarCollapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
          </button>
        </div>

        {signedIn ? (
          <div className="progressBlock">
            <div className="progressHeader">
              <span>Setup</span>
              <strong>{progress}%</strong>
            </div>
            <div className="progressTrack" aria-hidden="true">
              <div className="progressValue" style={{ width: `${progress}%` }} />
            </div>
          </div>
        ) : null}

        <SidebarAuthPanel
          config={config}
          loginState={loginState}
          registerState={registerState}
          onStartGithubAuth={startGithubAuth}
        />

        {signedIn ? (
          <nav className="stepNav" aria-label="Setup sections">
            <StepLink icon={<Users size={18} />} href="#organization" label="Organization" />
            <StepLink icon={<UserPlus size={18} />} href="#members" label="Members" />
            <StepLink icon={<ServerCog size={18} />} href="#service" label="Service" />
            <StepLink icon={<GitFork size={18} />} href="#repository" label="Repository" />
            <StepLink icon={<RadioTower size={18} />} href="#alerting" label="Alerting" />
            <StepLink icon={<Sparkles size={18} />} href="#models" label="Models" />
            <StepLink icon={<Database size={18} />} href="#runtime" label="Runtime" />
            <StepLink icon={<ShieldCheck size={18} />} href="#outputs" label="Outputs" />
            <StepLink icon={<Braces size={18} />} href="/environment" label="Environment" />
          </nav>
        ) : null}
      </aside>

      <section className="workspace" aria-label="Auto-triage setup form">
        <header className="topbar">
          <div>
            <p className="eyebrow">Repository triage setup</p>
            <h2>Configure an auto-triage deployment</h2>
          </div>
          <div className="topbarControls">
            {signedIn ? (
              <div className="quickActions" aria-label="Primary setup actions">
                {canAdmin ? (
                  <Link className="secondaryButton" href="/admin">
                    <ShieldCheck size={16} />
                    Admin
                  </Link>
                ) : null}
                <button
                  className="secondaryButton"
                  type="button"
                  onClick={sendTestAlert}
                  disabled={!canWrite || alertState.kind === "working"}
                  aria-busy={alertState.kind === "working"}
                  title={canWrite ? "Send test alert" : "Write role required"}
                >
                  {alertState.kind === "working" ? (
                    <LoaderCircle className="loadingSpinner" size={16} />
                  ) : (
                    <Send size={16} />
                  )}
                  {alertState.kind === "working" ? "Testing" : "Test"}
                </button>
                <button
                  className="secondaryButton primaryAction"
                  type="button"
                  onClick={saveSetup}
                  disabled={!canWrite}
                  title={canWrite ? "Save setup" : "Write role required"}
                >
                  <Save size={16} />
                  Save
                </button>
              </div>
            ) : null}
            <div className={`healthPill ${health.kind}`}>
              <span />
              {health.label}
            </div>
            <UserMenu
              config={config}
              open={userMenuOpen}
              onLogout={logout}
              onToggle={() => setUserMenuOpen((current) => !current)}
            />
          </div>
        </header>

        {signedIn ? (
          <div className="contentGrid">
            <form className="setupForm">
            <FormSection
              id="organization"
              title="Organization"
              icon={<Users size={18} />}
            >
              <div className="twoColumn">
                <ReadOnlyField label="Organization name" value={config.organizationName} />
                <ReadOnlyField label="Current role" value={config.organizationRole} />
              </div>
              <div className="twoColumn">
                <ReadOnlyField label="User email" value={config.authToken ? config.userEmail : ""} />
                <ReadOnlyField label="GitHub login" value={config.githubLogin} />
              </div>
              <ReadOnlyField label="Platform role" value={config.platformRole} />
            </FormSection>

            <FormSection
              id="members"
              title="Members"
              icon={<UserPlus size={18} />}
              action={
                <button className="secondaryButton" type="button" onClick={() => void loadMembers()}>
                  <RefreshCw size={16} />
                  Refresh
                </button>
              }
            >
              <div className="memberList">
                {members.length ? (
                  members.map((member) => (
                    <div className="memberRow" key={member.membership_id}>
                      <div>
                        <strong>{member.email}</strong>
                        <span>{member.display_name || "No display name"}</span>
                      </div>
                      <span className={`roleBadge ${member.role}`}>{member.role}</span>
                    </div>
                  ))
                ) : (
                  <div className="emptyState">
                    <Users size={18} />
                    <div>
                      <strong>No members loaded</strong>
                      <span>{memberState.kind === "working" ? "Loading members" : "Refresh to load members"}</span>
                    </div>
                  </div>
                )}
              </div>
              <StatusLine state={memberState} label="Members" />
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
              <button
                className="secondaryButton"
                type="button"
                onClick={sendTestAlert}
                disabled={!canWrite || alertState.kind === "working"}
                aria-busy={alertState.kind === "working"}
                title={canWrite ? "Send test alert" : "Write role required"}
              >
                {alertState.kind === "working" ? (
                  <LoaderCircle className="loadingSpinner" size={16} />
                ) : (
                  <Send size={16} />
                )}
                {alertState.kind === "working" ? "Testing alert" : "Test alert"}
              </button>
              <button
                className="secondaryButton"
                type="button"
                onClick={saveSetup}
                disabled={!canWrite}
                title={canWrite ? "Save setup" : "Write role required"}
              >
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
              value={webhookOutput}
              copied={copiedKey === "webhook"}
              dirty={editableOutputs.webhook.dirty}
              editing={editingOutputs.webhook}
              onChange={(value) => updateEditableOutput("webhook", value)}
              onCopy={() => copy(webhookOutput, "webhook")}
              onEditToggle={() => toggleEditableOutput("webhook")}
              onReset={() => resetEditableOutput("webhook")}
              editable
            />
            <OutputBlock
              title=".env"
              value={envOutput}
              copied={copiedKey === "env"}
              dirty={editableOutputs.env.dirty}
              editing={editingOutputs.env}
              onChange={(value) => updateEditableOutput("env", value)}
              onCopy={() => copy(envOutput, "env")}
              onEditToggle={() => toggleEditableOutput("env")}
              onReset={() => resetEditableOutput("env")}
              editable
              tall
            />
            <OutputBlock
              title="Logfire query"
              value={logfireQueryOutput}
              copied={copiedKey === "query"}
              dirty={editableOutputs.logfireQuery.dirty}
              editing={editingOutputs.logfireQuery}
              onChange={(value) => updateEditableOutput("logfireQuery", value)}
              onCopy={() => copy(logfireQueryOutput, "query")}
              onEditToggle={() => toggleEditableOutput("logfireQuery")}
              onReset={() => resetEditableOutput("logfireQuery")}
              editable
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
        ) : (
          <div className="signedOutWorkspace">
            <AccountStatus config={config} state={loginState} />
          </div>
        )}
      </section>
    </main>
  );
}

function mergePersistedSetup(current: SetupConfig, persisted: PersistedSetup): SetupConfig {
  let next: SetupConfig = {
    ...current,
    userId: persisted.user.userId,
    organizationId: persisted.user.organizationId,
    organizationName: persisted.user.organizationName,
    organizationSlug: persisted.user.organizationSlug,
    organizationRole: persisted.user.role,
    platformRole: persisted.user.platformRole,
    userEmail: persisted.user.email,
    userDisplayName: persisted.user.displayName ?? current.userDisplayName,
    githubLogin: persisted.user.githubLogin ?? current.githubLogin,
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
      githubTokenConfigured: repository.githubTokenConfigured,
      logfireRegion: logfireRegionFromBaseUrl(repository.logfireBaseUrl),
      logfireReadToken: repository.logfireReadToken ?? "",
      logfireReadTokenConfigured: repository.logfireReadTokenConfigured,
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

function generatedOutputValues(config: SetupConfig): Record<EditableOutputKey, string> {
  return {
    webhook: autoTriageWebhookUrl(config),
    env: buildEnv(config),
    logfireQuery: buildLogfireQuery(config),
  };
}

function createEditableOutputDrafts(config: SetupConfig): EditableOutputDrafts {
  const generated = generatedOutputValues(config);
  return {
    webhook: { value: generated.webhook, source: generated.webhook, dirty: false },
    env: { value: generated.env, source: generated.env, dirty: false },
    logfireQuery: {
      value: generated.logfireQuery,
      source: generated.logfireQuery,
      dirty: false,
    },
  };
}

function outputDraftsFromPersisted(
  config: SetupConfig,
  outputs: PersistedSetupOutputs,
): EditableOutputDrafts {
  const generated = generatedOutputValues(config);
  return {
    webhook: editableOutputDraftFromValue(outputs.webhookUrl, generated.webhook),
    env: editableOutputDraftFromValue(outputs.envFile, generated.env),
    logfireQuery: editableOutputDraftFromValue(outputs.logfireQuery, generated.logfireQuery),
  };
}

function resolvedOutputPayload(
  drafts: EditableOutputDrafts,
  generated: Record<EditableOutputKey, string>,
): SetupOutputsInput {
  return {
    webhookUrl: drafts.webhook.dirty ? drafts.webhook.value : generated.webhook,
    envFile: drafts.env.dirty ? drafts.env.value : generated.env,
    logfireQuery: drafts.logfireQuery.dirty
      ? drafts.logfireQuery.value
      : generated.logfireQuery,
  };
}

function readEditableOutputDrafts(config: SetupConfig): EditableOutputDrafts {
  const generated = generatedOutputValues(config);
  const fallback = createEditableOutputDrafts(config);
  const saved = window.localStorage.getItem(outputStorageKey);
  if (!saved) {
    return fallback;
  }

  try {
    const parsed = JSON.parse(saved) as Partial<Record<EditableOutputKey, Partial<EditableOutputDraft>>>;
    return {
      webhook: restoreEditableOutputDraft(parsed.webhook, generated.webhook),
      env: fallback.env,
      logfireQuery: restoreEditableOutputDraft(parsed.logfireQuery, generated.logfireQuery),
    };
  } catch {
    window.localStorage.removeItem(outputStorageKey);
    return fallback;
  }
}

function withoutSensitiveDraftValues(config: SetupConfig): SetupConfig {
  return {
    ...config,
    githubToken: "",
    logfireReadToken: "",
    openaiApiKey: "",
    azureApiKey: "",
    postgresPassword: "",
    redisPassword: "",
  };
}

function restoreEditableOutputDraft(
  saved: Partial<EditableOutputDraft> | undefined,
  generated: string,
): EditableOutputDraft {
  if (!saved?.dirty || typeof saved.value !== "string") {
    return { value: generated, source: generated, dirty: false };
  }

  return editableOutputDraftFromValue(saved.value, generated);
}

function editableOutputDraftFromValue(value: string, generated: string): EditableOutputDraft {
  return {
    value,
    source: generated,
    dirty: value !== generated,
  };
}

function applyGithubAuthSession(current: SetupConfig, session: GithubAuthSession): SetupConfig {
  return {
    ...current,
    authToken: session.auth_token,
    userId: session.user_id,
    organizationId: session.organization_id,
    organizationName: session.organization_name,
    organizationSlug: session.organization_slug,
    organizationRole: session.role,
    platformRole: session.platform_role ?? "user",
    userEmail: session.email,
    userDisplayName: session.display_name ?? session.github_login,
    githubLogin: session.github_login,
  };
}

function readGithubAuthSession(): GithubAuthSession | null {
  const cookieValue = readCookie(githubSessionCookieName);
  if (!cookieValue) {
    return null;
  }

  try {
    return decodeBase64UrlJson<GithubAuthSession>(cookieValue);
  } catch {
    deleteCookie(githubSessionCookieName);
    return null;
  }
}

function readGithubAuthAttempt(): boolean {
  const value = window.sessionStorage.getItem(githubAuthAttemptKey);
  if (!value) {
    return false;
  }

  try {
    const payload = JSON.parse(value) as { startedAt?: number };
    window.sessionStorage.removeItem(githubAuthAttemptKey);
    return Boolean(payload.startedAt && Date.now() - payload.startedAt <= 15 * 60 * 1000);
  } catch {
    window.sessionStorage.removeItem(githubAuthAttemptKey);
    return false;
  }
}

function writeGithubAuthAttempt(mode: "login" | "register") {
  window.sessionStorage.setItem(
    githubAuthAttemptKey,
    JSON.stringify({
      mode,
      startedAt: Date.now(),
    }),
  );
}

function readGithubError(): string | null {
  const url = new URL(window.location.href);
  const error = url.searchParams.get("github_error");
  if (!error) {
    return null;
  }

  url.searchParams.delete("github_error");
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  return error;
}

function readCookie(name: string): string | null {
  const prefix = `${encodeURIComponent(name)}=`;
  const cookie = document.cookie
    .split("; ")
    .find((item) => item.startsWith(prefix));
  if (!cookie) {
    return null;
  }
  return decodeURIComponent(cookie.slice(prefix.length));
}

function deleteCookie(name: string) {
  document.cookie = `${encodeURIComponent(name)}=; Max-Age=0; path=/; SameSite=Lax`;
}

function decodeBase64UrlJson<Value>(value: string): Value {
  const base64 = value.replaceAll("-", "+").replaceAll("_", "/");
  const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, "=");
  const bytes = Uint8Array.from(window.atob(padded), (char) => char.charCodeAt(0));
  return JSON.parse(new TextDecoder().decode(bytes)) as Value;
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
    openaiApiKeyConfigured: settings.openaiApiKeyConfigured,
    azureEndpoint: settings.azureEndpoint ?? "",
    azureDeployment: settings.azureDeployment ?? "",
    azureApiVersion: settings.azureApiVersion ?? "",
    azureApiKey: settings.azureApiKey ?? "",
    azureApiKeyConfigured: settings.azureApiKeyConfigured,
    postgresHost: settings.postgresHost ?? "",
    postgresPort: String(settings.postgresPort),
    postgresUser: settings.postgresUser ?? "",
    postgresPassword: settings.postgresPassword ?? "",
    postgresPasswordConfigured: settings.postgresPasswordConfigured,
    postgresDb: settings.postgresDb ?? "",
    redisEnabled: settings.redisEnabled,
    redisHost: settings.redisHost ?? "",
    redisPort: String(settings.redisPort),
    redisUsername: settings.redisUsername ?? "",
    redisPassword: settings.redisPassword ?? "",
    redisPasswordConfigured: settings.redisPasswordConfigured,
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

function SidebarAuthPanel({
  config,
  loginState,
  registerState,
  onStartGithubAuth,
}: {
  config: SetupConfig;
  loginState: ActionState;
  registerState: ActionState;
  onStartGithubAuth: (mode: "login" | "register") => void;
}) {
  const signedIn = Boolean(config.authToken);

  return (
    <section className="sidebarAuthPanel" aria-label="Login">
      <AccountStatus config={config} state={loginState} compact />
      {!signedIn ? (
        <>
          <div className="sidebarAuthActions">
            <button
              className="secondaryButton"
              type="button"
              onClick={() => onStartGithubAuth("login")}
            >
              <GitFork size={16} />
              GitHub sign in
            </button>
            <button
              className="secondaryButton"
              type="button"
              onClick={() => onStartGithubAuth("register")}
            >
              <GitFork size={16} />
              GitHub create
            </button>
          </div>
          <div className="sidebarStatusStack">
            <StatusLine state={loginState} />
            <StatusLine state={registerState} label="Registration" />
          </div>
        </>
      ) : null}
    </section>
  );
}

function UserMenu({
  config,
  open,
  onToggle,
  onLogout,
}: {
  config: SetupConfig;
  open: boolean;
  onToggle: () => void;
  onLogout: () => void;
}) {
  const signedIn = Boolean(config.authToken);
  const label = signedIn ? config.userEmail : "Signed out";

  return (
    <div className="userMenu">
      <button
        className="userMenuButton"
        type="button"
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={onToggle}
      >
        <UserCircle size={17} />
        <span>{label}</span>
        <ChevronDown size={15} />
      </button>
      {open ? (
        <div className="userMenuDropdown" role="menu">
          <div className="userMenuIdentity">
            <strong>{label}</strong>
            <span>{signedIn ? config.organizationName : "No active session"}</span>
            {config.githubLogin ? <span>@{config.githubLogin}</span> : null}
          </div>
          <button
            className="userMenuLogout"
            type="button"
            role="menuitem"
            onClick={onLogout}
            disabled={!signedIn}
          >
            <LogOut size={15} />
            Logout
          </button>
        </div>
      ) : null}
    </div>
  );
}

function AccountStatus({
  config,
  state,
  compact = false,
}: {
  config: SetupConfig;
  state: ActionState;
  compact?: boolean;
}) {
  const signedIn = Boolean(config.authToken);
  const statusKind = signedIn
    ? "ok"
    : state.kind === "working"
      ? "working"
      : state.kind === "error"
        ? "error"
        : "idle";
  const title = signedIn
    ? config.githubLogin
      ? "GitHub login active"
      : "Signed in"
    : state.kind === "working"
      ? state.label
      : state.kind === "error"
        ? "Login failed"
        : "Signed out";
  const email = signedIn ? config.userEmail : "No user email";
  const organization = signedIn ? config.organizationName : "No organization";

  return (
    <section className={`accountStatus ${statusKind} ${compact ? "compact" : ""}`}>
      <div className="accountStatusIcon" aria-hidden="true">
        {config.githubLogin ? <GitFork size={18} /> : <KeyRound size={18} />}
      </div>
      <div className="accountStatusBody">
        <div className="accountStatusHeader">
          <strong>{title}</strong>
          <span>{signedIn ? config.organizationRole : state.kind}</span>
        </div>
        <div className="accountIdentity">
          <span>{email}</span>
          <span>{organization}</span>
          {config.githubLogin ? <span>@{config.githubLogin}</span> : null}
        </div>
        {!signedIn && state.kind === "error" ? (
          <p className="accountStatusMessage">{state.label}</p>
        ) : null}
      </div>
    </section>
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
  const [showSecret, setShowSecret] = useState(false);
  const isSecret = type === "password";
  const inputType = isSecret && showSecret ? "text" : type;

  return (
    <label className="field">
      <span>{label}</span>
      <div className={`fieldControl ${isSecret ? "hasFieldAction" : ""}`}>
        <input
          type={inputType}
          value={value}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
        />
        {isSecret ? (
          <button
            aria-label={showSecret ? `Hide ${label}` : `Show ${label}`}
            className="fieldIconButton"
            type="button"
            onClick={() => setShowSecret((current) => !current)}
          >
            {showSecret ? <EyeOff size={15} /> : <Eye size={15} />}
          </button>
        ) : null}
      </div>
    </label>
  );
}

function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return (
    <div className="field readOnlyField">
      <span>{label}</span>
      <div>{value || "Not assigned"}</div>
    </div>
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
  dirty = false,
  editing = false,
  editable = false,
  onChange,
  onCopy,
  onEditToggle,
  onReset,
  tall = false,
}: {
  title: string;
  value: string;
  copied: boolean;
  dirty?: boolean;
  editing?: boolean;
  editable?: boolean;
  onChange?: (value: string) => void;
  onCopy: () => void;
  onEditToggle?: () => void;
  onReset?: () => void;
  tall?: boolean;
}) {
  return (
    <section className="outputBlock">
      <div className="outputHeader">
        <div className="outputTitle">
          <h3>{title}</h3>
          {dirty ? <span className="outputBadge">Modified</span> : null}
        </div>
        <div className="outputActions">
          {dirty ? (
            <button className="iconTextButton" type="button" onClick={onReset}>
              <RefreshCw size={15} />
              Reset
            </button>
          ) : null}
          {editable ? (
            <button className="iconTextButton" type="button" onClick={onEditToggle}>
              <Pencil size={15} />
              {editing ? "Done" : "Edit"}
            </button>
          ) : null}
          <button className="iconTextButton" type="button" onClick={onCopy}>
            {copied ? <Check size={15} /> : <Clipboard size={15} />}
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </div>
      {editable && editing ? (
        <textarea
          aria-label={title}
          className={`outputEditor ${tall ? "tall" : ""}`}
          spellCheck={false}
          value={value}
          onChange={(event) => onChange?.(event.target.value)}
        />
      ) : (
        <pre className={tall ? "tall" : ""}>
          <code>{value}</code>
        </pre>
      )}
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

function Toast({
  state,
  onDismiss,
}: {
  state: ToastState;
  onDismiss: () => void;
}) {
  return (
    <div className="toastViewport" aria-live="polite" aria-atomic="true">
      <div className={`toast ${state.kind}`}>
        <div className="toastIcon" aria-hidden="true">
          {state.kind === "ok" ? <Check size={18} /> : <CircleAlert size={18} />}
        </div>
        <div className="toastBody">
          <strong>{state.title}</strong>
          <span>{state.message}</span>
        </div>
        <button
          className="toastDismiss"
          type="button"
          aria-label="Dismiss notification"
          onClick={onDismiss}
        >
          <X size={16} />
        </button>
      </div>
    </div>
  );
}

function splitRepo(repo: string): [string, string] {
  const [owner, repoName] = repo.split("/", 2).map((part) => part.trim());
  return [owner ?? "", repoName ?? ""];
}

function minimumDelay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function responseDetail(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const detail = (payload as { detail?: unknown; error?: unknown }).detail;
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  const error = (payload as { error?: unknown }).error;
  if (typeof error === "string" && error.trim()) {
    return error;
  }
  return null;
}
