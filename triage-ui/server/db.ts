import { Pool, type PoolConfig, type QueryResultRow } from "pg";

declare global {
  var autoTriagePgPool: Pool | undefined;
}

function poolConfig(): PoolConfig {
  if (process.env.DATABASE_URL) {
    return { connectionString: normalizeDatabaseUrl(process.env.DATABASE_URL) };
  }

  return {
    host: process.env.POSTGRES_HOST ?? "127.0.0.1",
    port: Number(process.env.POSTGRES_PORT ?? 5432),
    user: process.env.POSTGRES_USER ?? "auto_triage",
    password: process.env.POSTGRES_PASSWORD ?? "auto_triage_password",
    database: process.env.POSTGRES_DB ?? "auto_triage",
  };
}

function normalizeDatabaseUrl(value: string): string {
  return value
    .replace(/^postgresql\+asyncpg:\/\//, "postgresql://")
    .replace(/^postgres\+asyncpg:\/\//, "postgres://");
}

export const pool = globalThis.autoTriagePgPool ?? new Pool(poolConfig());

if (process.env.NODE_ENV !== "production") {
  globalThis.autoTriagePgPool = pool;
}

export async function query<Row extends QueryResultRow>(
  text: string,
  values: unknown[] = [],
): Promise<Row[]> {
  const result = await pool.query<Row>(text, values);
  return result.rows;
}
