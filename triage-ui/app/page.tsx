import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { SetupWorkspace } from "@/components/setup-workspace";
import {
  githubAuthTokenCookieName,
  readGithubAuthSession,
} from "@/server/github-auth";

export default async function Page() {
  const cookieStore = await cookies();
  const session = await readGithubAuthSession(
    cookieStore.get(githubAuthTokenCookieName)?.value,
  );
  if (!session) {
    redirect("/login");
  }

  return <SetupWorkspace initialSession={session} />;
}
