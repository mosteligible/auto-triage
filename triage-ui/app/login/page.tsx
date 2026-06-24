import { GitFork } from "lucide-react";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import {
  githubAuthTokenCookieName,
  readGithubAuthSession,
} from "@/server/github-auth";

type LoginPageProps = {
  searchParams: Promise<{
    github_error?: string | string[];
  }>;
};

export const metadata = {
  title: "Sign in | Auto Triage",
};

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const cookieStore = await cookies();
  const session = await readGithubAuthSession(
    cookieStore.get(githubAuthTokenCookieName)?.value,
  );
  if (session) {
    redirect("/");
  }

  const params = await searchParams;
  const errorValue = Array.isArray(params.github_error)
    ? params.github_error[0]
    : params.github_error;

  return (
    <main className="loginPage">
      <section className="loginPanel" aria-labelledby="login-title">
        <div className="loginBrand" aria-hidden="true">AT</div>
        <div className="loginHeading">
          <h1 id="login-title">Sign in to Auto Triage</h1>
          <p>Continue with your GitHub account.</p>
        </div>
        {errorValue ? (
          <div className="loginError" role="alert">
            {errorValue}
          </div>
        ) : null}
        <a
          className="githubLoginButton"
          href="/api/auth/github/start?mode=login&returnTo=%2F"
        >
          <GitFork size={18} />
          Continue with GitHub
        </a>
      </section>
    </main>
  );
}
