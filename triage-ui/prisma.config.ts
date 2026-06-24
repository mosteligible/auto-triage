import { defineConfig } from "prisma/config";

export default defineConfig({
  schema: "prisma/schema.prisma",
  datasource: {
    url:
      process.env.DATABASE_URL ??
      "postgresql://auto_triage:auto_triage_password@127.0.0.1:5432/auto_triage",
  },
});
