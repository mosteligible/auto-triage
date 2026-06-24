import { PrismaPg } from "@prisma/adapter-pg";
import { PrismaClient } from "@prisma/client";

declare global {
  var autoTriagePrisma: PrismaClient | undefined;
}

function databaseUrl(): string {
  const value =
    process.env.DATABASE_URL ??
    "postgresql://auto_triage:auto_triage_password@127.0.0.1:5432/auto_triage";
  return value
    .replace(/^postgresql\+asyncpg:\/\//, "postgresql://")
    .replace(/^postgres\+asyncpg:\/\//, "postgres://");
}

const adapter = new PrismaPg({ connectionString: databaseUrl() });

export const prisma =
  globalThis.autoTriagePrisma ??
  new PrismaClient({
    adapter,
  });

if (process.env.NODE_ENV !== "production") {
  globalThis.autoTriagePrisma = prisma;
}
