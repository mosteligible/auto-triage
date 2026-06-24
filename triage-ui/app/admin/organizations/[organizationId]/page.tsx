import { ArrowLeft, Building2, UserPlus, Users } from "lucide-react";
import Link from "next/link";
import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";

import {
  githubAuthTokenCookieName,
  readGithubAuthSession,
} from "@/server/github-auth";
import { appRouter } from "@/server/trpc/router";
import {
  addOrganizationUserAction,
  deleteOrganizationAction,
  removeOrganizationUserAction,
  updateOrganizationAction,
  updateOrganizationUserAction,
} from "@/app/admin/actions";

export const metadata = {
  title: "Organization Users | Auto Triage",
};

export default async function AdminOrganizationPage({
  params,
  searchParams,
}: {
  params: Promise<{ organizationId: string }>;
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { organizationId } = await params;
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
  if (!canManagePlatform && organizationId !== session.organization_id) {
    redirect("/admin");
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

  let organization: Awaited<ReturnType<typeof caller.admin.organization>>;
  try {
    organization = await caller.admin.organization({ organizationId });
  } catch {
    notFound();
  }
  const feedback = await readFeedback(searchParams);

  return (
    <main className="environmentPage adminPage">
      <header className="environmentHeader">
        <div className="environmentTitle">
          <div className="environmentTitleIcon" aria-hidden="true">
            <Building2 size={20} />
          </div>
          <div>
            <p className="eyebrow">Administration</p>
            <h1>{organization.name}</h1>
            <p>
              {organization.slug} · {organization.users.length} user
              {organization.users.length === 1 ? "" : "s"}
            </p>
          </div>
        </div>
        <div className="environmentHeaderActions">
          <span>{session.email}</span>
          <Link className="secondaryButton" href="/admin">
            <ArrowLeft size={16} />
            Back to organizations
          </Link>
        </div>
      </header>

      {feedback ? (
        <div className={`adminFeedback ${feedback.status}`} role="status">
          {feedback.message}
        </div>
      ) : null}

      <section className="adminContent" aria-label={`${organization.name} users`}>
        <article className="adminManagementPanel">
          <header className="adminPanelHeader">
            <div>
              <h2>Organization</h2>
            <p>
              {canManagePlatform
                ? "Update the organization record or remove the organization."
                : "Update your organization record."}
            </p>
            </div>
          </header>
          <div className="adminInlineManagement detail">
            <form action={updateOrganizationAction} className="adminInlineForm">
              <input name="organizationId" type="hidden" value={organization.id} />
              <input
                name="returnTo"
                type="hidden"
                value={`/admin/organizations/${organization.id}`}
              />
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
                  Save organization
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
                  Remove organization
                </button>
              </form>
            ) : null}
          </div>
        </article>

        <article className="adminManagementPanel">
          <header className="adminPanelHeader">
            <div>
              <h2>Add user</h2>
              <p>Add an existing user by email or create a GitHub-claimable user record.</p>
            </div>
          </header>
          <form action={addOrganizationUserAction} className="adminFormGrid users">
            <input name="organizationId" type="hidden" value={organization.id} />
            <label className="adminField">
              <span>Email</span>
              <input name="email" placeholder="person@example.com" required type="email" />
            </label>
            <label className="adminField">
              <span>Display name</span>
              <input name="displayName" placeholder="Jane Doe" />
            </label>
            <label className="adminField">
              <span>GitHub login</span>
              <input name="githubLogin" placeholder="janedoe" />
            </label>
            <label className="adminField">
              <span>Role</span>
              <select name="role" defaultValue="read">
                <option value="admin">Admin</option>
                <option value="write">Write</option>
                <option value="read">Read</option>
              </select>
            </label>
            {canManagePlatform ? (
              <label className="adminField">
                <span>Platform role</span>
                <select name="platformRole" defaultValue="user">
                  <option value="user">User</option>
                  <option value="admin">Platform admin</option>
                </select>
              </label>
            ) : null}
            <div className="adminFormActions">
              <button className="secondaryButton primaryAction" type="submit">
                <UserPlus size={16} />
                Add user
              </button>
            </div>
          </form>
        </article>

        <article className="adminOrganization">
          <header className="adminOrganizationHeader">
            <div>
              <h2>Users</h2>
              <p>{formatDate(organization.createdAt)}</p>
            </div>
          </header>

          {organization.users.length ? (
            <div className="adminUserManagementList">
              {organization.users.map((user) => (
                <article className="adminUserManageRow" key={user.membershipId}>
                  <form action={updateOrganizationUserAction} className="adminUserManageForm">
                    <input name="organizationId" type="hidden" value={organization.id} />
                    <input name="membershipId" type="hidden" value={user.membershipId} />
                    <input name="userId" type="hidden" value={user.userId} />
                    <label className="adminField">
                      <span>Email</span>
                      <input name="email" defaultValue={user.email} required type="email" />
                    </label>
                    <label className="adminField">
                      <span>Display name</span>
                      <input name="displayName" defaultValue={user.displayName ?? ""} />
                    </label>
                    <label className="adminField">
                      <span>GitHub</span>
                      <input name="githubLogin" defaultValue={user.githubLogin ?? ""} />
                    </label>
                    <label className="adminField">
                      <span>Role</span>
                      <select name="role" defaultValue={user.role}>
                        <option value="admin">Admin</option>
                        <option value="write">Write</option>
                        <option value="read">Read</option>
                      </select>
                    </label>
                    {canManagePlatform ? (
                      <label className="adminField">
                        <span>Platform role</span>
                        <select name="platformRole" defaultValue={user.platformRole}>
                          <option value="user">User</option>
                          <option value="admin">Platform admin</option>
                        </select>
                      </label>
                    ) : null}
                    <div className="adminUserMeta">
                      <span>Joined {formatDate(user.membershipCreatedAt)}</span>
                      {user.platformRole === "admin" ? (
                        <span className="platformBadge">Platform admin</span>
                      ) : null}
                      <span className={`roleBadge ${user.role}`}>{user.role}</span>
                    </div>
                    <div className="adminFormActions">
                      <button className="secondaryButton" type="submit">
                        Save user
                      </button>
                    </div>
                  </form>
                  <form action={removeOrganizationUserAction} className="adminRemoveUserForm">
                    <input name="organizationId" type="hidden" value={organization.id} />
                    <input name="membershipId" type="hidden" value={user.membershipId} />
                    <button className="secondaryButton dangerButton" type="submit">
                      Remove user
                    </button>
                  </form>
                </article>
              ))}
            </div>
          ) : (
            <div className="emptyState adminEmptyState">
              <Users size={18} />
              <div>
                <strong>No users</strong>
                <span>This organization has no memberships.</span>
              </div>
            </div>
          )}
        </article>
      </section>
    </main>
  );
}

async function readFeedback(
  searchParams: Promise<Record<string, string | string[] | undefined>> | undefined,
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
