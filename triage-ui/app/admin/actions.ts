"use server";

import { revalidatePath } from "next/cache";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import {
  githubAuthTokenCookieName,
  readGithubAuthSession,
} from "@/server/github-auth";
import { appRouter } from "@/server/trpc/router";

type AdminCaller = ReturnType<typeof appRouter.createCaller>;

export async function createOrganizationAction(formData: FormData) {
  const caller = await adminCaller();
  const name = formValue(formData, "name");
  const slug = optionalFormValue(formData, "slug");
  try {
    await caller.admin.createOrganization({ name, slug });
  } catch (error) {
    redirectWithFeedback("/admin", "error", errorMessage(error, "Organization could not be created"));
  }

  revalidatePath("/admin");
  redirectWithFeedback("/admin", "ok", `Created ${name}`);
}

export async function updateOrganizationAction(formData: FormData) {
  const caller = await adminCaller();
  const organizationId = formValue(formData, "organizationId");
  const name = formValue(formData, "name");
  const slug = optionalFormValue(formData, "slug");
  const returnTo = optionalFormValue(formData, "returnTo") ?? "/admin";
  try {
    await caller.admin.updateOrganization({ organizationId, name, slug });
  } catch (error) {
    redirectWithFeedback(returnTo, "error", errorMessage(error, "Organization could not be updated"));
  }

  revalidatePath("/admin");
  revalidatePath(`/admin/organizations/${organizationId}`);
  redirectWithFeedback(returnTo, "ok", `Updated ${name}`);
}

export async function deleteOrganizationAction(formData: FormData) {
  const caller = await adminCaller();
  const organizationId = formValue(formData, "organizationId");
  const slug = formValue(formData, "slug");
  const confirmSlug = formValue(formData, "confirmSlug");
  if (slug !== confirmSlug) {
    redirectWithFeedback("/admin", "error", "Type the organization slug before removing it");
  }

  try {
    await caller.admin.deleteOrganization({ organizationId });
  } catch (error) {
    redirectWithFeedback("/admin", "error", errorMessage(error, "Organization could not be removed"));
  }

  revalidatePath("/admin");
  redirectWithFeedback("/admin", "ok", `Removed ${slug}`);
}

export async function addOrganizationUserAction(formData: FormData) {
  const caller = await adminCaller();
  const organizationId = formValue(formData, "organizationId");
  const returnTo = organizationPath(organizationId);
  try {
    await caller.admin.addOrganizationUser({
      organizationId,
      email: formValue(formData, "email"),
      displayName: optionalFormValue(formData, "displayName"),
      githubLogin: optionalFormValue(formData, "githubLogin"),
      role: roleValue(formData),
      ...platformRolePatch(formData),
    });
  } catch (error) {
    redirectWithFeedback(returnTo, "error", errorMessage(error, "User could not be added"));
  }

  revalidatePath("/admin");
  revalidatePath(returnTo);
  redirectWithFeedback(returnTo, "ok", "User added");
}

export async function updateOrganizationUserAction(formData: FormData) {
  const caller = await adminCaller();
  const organizationId = formValue(formData, "organizationId");
  const returnTo = organizationPath(organizationId);
  try {
    await caller.admin.updateOrganizationUser({
      organizationId,
      membershipId: formValue(formData, "membershipId"),
      userId: formValue(formData, "userId"),
      email: formValue(formData, "email"),
      displayName: optionalFormValue(formData, "displayName"),
      githubLogin: optionalFormValue(formData, "githubLogin"),
      role: roleValue(formData),
      ...platformRolePatch(formData),
    });
  } catch (error) {
    redirectWithFeedback(returnTo, "error", errorMessage(error, "User could not be updated"));
  }

  revalidatePath("/admin");
  revalidatePath(returnTo);
  redirectWithFeedback(returnTo, "ok", "User updated");
}

export async function removeOrganizationUserAction(formData: FormData) {
  const caller = await adminCaller();
  const organizationId = formValue(formData, "organizationId");
  const returnTo = organizationPath(organizationId);
  try {
    await caller.admin.removeOrganizationUser({
      organizationId,
      membershipId: formValue(formData, "membershipId"),
    });
  } catch (error) {
    redirectWithFeedback(returnTo, "error", errorMessage(error, "User could not be removed"));
  }

  revalidatePath("/admin");
  revalidatePath(returnTo);
  redirectWithFeedback(returnTo, "ok", "User removed");
}

async function adminCaller(): Promise<AdminCaller> {
  const cookieStore = await cookies();
  const session = await readGithubAuthSession(
    cookieStore.get(githubAuthTokenCookieName)?.value,
  );
  if (!session) {
    redirect("/login");
  }
  if (session.platform_role !== "admin" && session.role !== "admin") {
    redirect("/");
  }

  return appRouter.createCaller({
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
}

function formValue(formData: FormData, name: string): string {
  const value = formData.get(name);
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${name} is required`);
  }
  return value.trim();
}

function optionalFormValue(formData: FormData, name: string): string | null {
  const value = formData.get(name);
  if (typeof value !== "string") {
    return null;
  }
  return value.trim() || null;
}

function roleValue(formData: FormData): "admin" | "write" | "read" {
  const value = formValue(formData, "role");
  if (value === "admin" || value === "write" || value === "read") {
    return value;
  }
  throw new Error("role is invalid");
}

function platformRolePatch(formData: FormData): { platformRole?: "admin" | "user" } {
  const value = optionalFormValue(formData, "platformRole");
  if (!value) {
    return {};
  }
  if (value === "admin" || value === "user") {
    return { platformRole: value };
  }
  throw new Error("platformRole is invalid");
}

function organizationPath(organizationId: string): string {
  return `/admin/organizations/${organizationId}`;
}

function redirectWithFeedback(path: string, status: "ok" | "error", message: string): never {
  const params = new URLSearchParams({
    admin_status: status,
    admin_message: message.slice(0, 240),
  });
  redirect(`${path}?${params.toString()}`);
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}
