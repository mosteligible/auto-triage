import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { rmSync } from "node:fs";
import { resolve } from "node:path";

import { expect, test } from "@playwright/test";

const repoRoot = resolve(__dirname, "../..");
const apiPort = 8011;
const apiBaseUrl = `http://127.0.0.1:${apiPort}`;
const databasePath = `/tmp/auto-triage-ui-e2e-${process.pid}.db`;

let apiProcess: ChildProcessWithoutNullStreams;

test.beforeAll(async () => {
  rmSync(databasePath, { force: true });
  apiProcess = spawn(
    "uv",
    ["run", "uvicorn", "auto_triage.app:app", "--host", "127.0.0.1", "--port", String(apiPort)],
    {
      cwd: repoRoot,
      env: {
        ...process.env,
        DATABASE_URL: `sqlite+aiosqlite:///${databasePath}`,
        RUN_WORKER: "false",
        UV_CACHE_DIR: "/tmp/uv-cache",
      },
    },
  );

  const logs: string[] = [];
  apiProcess.stdout.on("data", (chunk) => logs.push(String(chunk)));
  apiProcess.stderr.on("data", (chunk) => logs.push(String(chunk)));

  await waitForApi(logs);
});

test.afterAll(async () => {
  apiProcess?.kill("SIGTERM");
  rmSync(databasePath, { force: true });
});

test("user can login, save repository setup, receive a unique webhook, and trigger an alert", async ({
  page,
  request,
}) => {
  await page.goto("/");

  await page.getByLabel("Auto-triage API URL").fill(apiBaseUrl);
  await page.getByRole("button", { name: "Check" }).click();
  await expect(page.getByText(/Healthy/)).toBeVisible();

  const email = `operator-${Date.now()}@example.com`;
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Login password").fill("change-me-now");
  await page.getByLabel("Display name").fill("Operator");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText(new RegExp(`Signed in as ${escapeRegExp(email)}`))).toBeVisible();

  await page.getByLabel("GitHub repo").fill("mosteligible/auto-triage");
  await page.getByLabel("Default branch").fill("logfire");
  await page.getByLabel("Target repo URL").fill("https://github.com/mosteligible/auto-triage.git");
  await page.getByLabel("GitHub token").fill("github_pat_setup_test");
  await page.getByLabel("Read token").fill("pylf_setup_test");
  await page.getByLabel("Service name").fill("test-app-failure-generator");
  await page.getByLabel("Route").fill("/lean");

  await page.getByRole("button", { name: "Save setup" }).click();
  await expect(page.getByText("Setup: Saved mosteligible/auto-triage")).toBeVisible();
  await expect(page.getByText(/\/webhooks\/users\/[a-f0-9]+\/logfire/).first()).toBeVisible();

  const savedConfig = await page.evaluate(() => {
    const raw = window.localStorage.getItem("auto-triage.setup.v1");
    return raw ? JSON.parse(raw) : null;
  });
  expect(savedConfig?.authToken).toBeTruthy();
  expect(savedConfig?.webhookPath).toMatch(/^\/webhooks\/users\/[a-f0-9]+\/logfire$/);

  const profileResponse = await request.get(`${apiBaseUrl}/users/me`, {
    headers: { Authorization: `Bearer ${savedConfig.authToken}` },
  });
  expect(profileResponse.ok()).toBeTruthy();
  const profile = await profileResponse.json();
  expect(profile.repository_config.github_repo).toBe("mosteligible/auto-triage");
  expect(profile.repository_config.github_token_configured).toBe(true);

  await page.getByRole("button", { name: "Test alert" }).click();
  await expect(page.getByText(/Alert: Queued [a-f0-9]+/)).toBeVisible();
});

async function waitForApi(logs: string[]) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (apiProcess.exitCode !== null) {
      throw new Error(`API exited early:\n${logs.join("")}`);
    }
    try {
      const response = await fetch(`${apiBaseUrl}/health`);
      if (response.ok) {
        return;
      }
    } catch {
      await new Promise((resolveWait) => setTimeout(resolveWait, 250));
    }
  }
  throw new Error(`API did not become healthy:\n${logs.join("")}`);
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
