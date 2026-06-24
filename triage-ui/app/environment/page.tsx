import { ArrowLeft, Braces } from "lucide-react";
import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { EnvironmentVariableTable } from "@/components/environment-variable-table";
import {
  githubAuthTokenCookieName,
  readGithubAuthSession,
} from "@/server/github-auth";
import { appRouter } from "@/server/trpc/router";

export const metadata = {
  title: "Environment | Auto Triage",
};

export default async function EnvironmentPage() {
  const cookieStore = await cookies();
  const session = await readGithubAuthSession(
    cookieStore.get(githubAuthTokenCookieName)?.value,
  );
  if (!session) {
    redirect("/login");
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
  const environment = await caller.setup.environmentVariables();

  return (
    <main className="environmentPage">
      <header className="environmentHeader">
        <div className="environmentTitle">
          <div className="environmentTitleIcon" aria-hidden="true">
            <Braces size={20} />
          </div>
          <div>
            <p className="eyebrow">Organization configuration</p>
            <h1>Environment variables</h1>
            <p>{environment.organizationName}</p>
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

      <section className="environmentContent" aria-labelledby="environment-table-title">
        <EnvironmentVariableTable
          variables={environment.variables}
          updatedAt={environment.updatedAt}
          canEdit={session.role === "admin" || session.role === "write"}
        />
      </section>
    </main>
  );
}
