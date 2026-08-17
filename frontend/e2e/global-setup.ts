import { execSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

export default async function globalSetup() {
  execSync("python scripts/seed_e2e_fixtures.py", {
    cwd: root,
    stdio: "inherit",
    env: process.env,
  });
}
