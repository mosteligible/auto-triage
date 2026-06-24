import { ArrowLeft, ArrowRight, Building2, ShieldCheck, Users } from "lucide-react";
import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import {
  githubAuthTokenCookieName,
  readGithubAuthSession,
} from "@/server/github-auth";
import { appRouter } from "@/server/trpc/router";
import {
  createOrganizationAction,
  deleteOrganizationAction,
  updateOrganizationAction,
} from "./actions";

export const metadata = {
  title: "Admin | Auto Triage",
};

type AdminPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function AdminPage({ searchParams }: AdminPageProps) {
  const cookieStore = await cookies();
  const session = await readGithubAuthSession(
    cookieStore.get(githubAuthTokenCookieName)?.value,
  );
  if (!session) {
    redirect("/login");
  }
  const canManagePlatform = session.platform_role === "admin";
  if (!canManagePlatform && session.role !== "admin") {
    redirect("/");
  }

  const caller = appRouter.createCaller({
    authToken: session.auth_token,
    user: {
      userId: session.user_id,
      email: session.email,
      displayName: session.display_name,
      githubLogin: session.github_login,
      organizationId: session.organization_id,
      organizationName: session.organization_name,
      organizationSlug: session.organization_slug,
      role: session.role,
      platformRole: session.platform_role,
    },
  });
  const adminData = await caller.admin.organizations();
  const organizationCount = adminData.organizations.length;
  const userCount = adminData.organizations.reduce(
    (count, organization) => count + organization.userCount,
    0,
  );
  const feedback = await readFeedback(searchParams);

  return (
    <main className="environmentPage adminPage">
      <header className="environmentHeader">
        <div className="environmentTitle">
          <div className="environmentTitleIcon" aria-hidden="true">
            <ShieldCheck size={20} />
          </div>
          <div>
            <p className="eyebrow">Administration</p>
            <h1>{canManagePlatform ? "Organizations" : "Your organization"}</h1>
            <p>
              {organizationCount} organization{organizationCount === 1 ? "" : "s"} ·{" "}
              {userCount} user{userCount === 1 ? "" : "s"}
            </p>
          </div>
        </div>
        <div className="environmentHeaderActions">
          <span>{session.email}</span>
          <Link className="secondaryButton" href="/">
            <ArrowLeft size={16} />
            Back to setup
          </Link>
        </div>
      </header>

      {feedback ? (
        <div className={`adminFeedback ${feedback.status}`} role="status">
          {feedback.message}
        </div>
      ) : null}

      <section className="adminContent" aria-label="Organizations">
        {canManagePlatform ? (
          <article className="adminManagementPanel">
            <header className="adminPanelHeader">
              <div>
                <h2>Add organization</h2>
                <p>Create an organization record before assigning users.</p>
              </div>
            </header>
            <form action={createOrganizationAction} className="adminFormGrid">
              <label className="adminField">
                <span>Name</span>
                <input name="name" placeholder="Acme Engineering" required />
              </label>
              <label className="adminField">
                <span>Slug</span>
                <input name="slug" placeholder="acme-engineering" />
              </label>
              <div className="adminFormActions">
                <button className="secondaryButton primaryAction" type="submit">
                  Add organization
                </button>
              </div>
            </form>
          </article>
        ) : null}

        {adminData.organizations.length ? (
          adminData.organizations.map((organization) => (
            <article className="adminOrganization adminOrganizationManaged" key={organization.id}>
              <Link
                className="adminOrganizationLink"
                href={`/admin/organizations/${organization.id}`}
              >
                <div className="adminOrganizationSummary">
                <div className="adminOrganizationIcon" aria-hidden="true">
                  <Building2 size={19} />
                </div>
                <div className="adminOrganizationSummaryBody">
                  <h2>{organization.name}</h2>
                  <p>{organization.slug}</p>
                </div>
                <div className="adminOrganizationMeta">
                  <span>{organization.userCount} users</span>
                  <span>{formatDate(organization.createdAt)}</span>
                  <ArrowRight size={16} />
                </div>
                </div>
              </Link>

              <div className="adminInlineManagement">
                <form action={updateOrganizationAction} className="adminInlineForm">
                  <input name="organizationId" type="hidden" value={organization.id} />
                  <input name="returnTo" type="hidden" value="/admin" />
                  <label className="adminField">
                    <span>Name</span>
                    <input name="name" defaultValue={organization.name} required />
                  </label>
                  <label className="adminField">
                    <span>Slug</span>
                    <input name="slug" defaultValue={organization.slug} required />
                  </label>
                  <div className="adminFormActions">
                    <button className="secondaryButton" type="submit">
                      Save
                    </button>
                  </div>
                </form>
                {canManagePlatform ? (
                  <form action={deleteOrganizationAction} className="adminDeleteForm">
                    <input name="organizationId" type="hidden" value={organization.id} />
                    <input name="slug" type="hidden" value={organization.slug} />
                    <label className="adminField">
                      <span>Type slug to remove</span>
                      <input name="confirmSlug" placeholder={organization.slug} required />
                    </label>
                    <button className="secondaryButton dangerButton" type="submit">
                      Remove
                    </button>
                  </form>
                ) : null}
              </div>
            </article>
          ))
        ) : (
          <div className="emptyState adminEmptyState">
            <Users size={18} />
            <div>
              <strong>No organizations</strong>
              <span>No organization records were found.</span>
            </div>
          </div>
        )}
      </section>
    </main>
  );
}

async function readFeedback(
  searchParams: AdminPageProps["searchParams"],
): Promise<{ status: "ok" | "error"; message: string } | null> {
  const params = await searchParams;
  const status = firstParam(params?.admin_status);
  const message = firstParam(params?.admin_message);
  if ((status === "ok" || status === "error") && message) {
    return { status, message };
  }
  return null;
}

function firstParam(value: string | string[] | undefined): string | null {
  if (Array.isArray(value)) {
    return value[0] ?? null;
  }
  return value ?? null;
}

function formatDate(value: string | null): string {
  if (!value) {
    return "Unknown";
  }
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}
