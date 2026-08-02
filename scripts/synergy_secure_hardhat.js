#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");
const dotenv = require("dotenv");

function fail(message) {
  console.error(message);
  process.exit(1);
}

const repo = path.resolve(__dirname, "..");
const envArg = process.argv[2];
const args = process.argv.slice(3);
if (!envArg || args.length === 0) {
  fail("Usage: node scripts/synergy_secure_hardhat.js runtime/synergy_agent/local/polygon-v2.env <hardhat args>");
}
const envPath = path.resolve(repo, envArg);
const localRoot = path.resolve(repo, "runtime/synergy_agent/local") + path.sep;
if (!envPath.startsWith(localRoot)) fail("ENV must be inside runtime/synergy_agent/local/");
if (!fs.existsSync(envPath) || !fs.statSync(envPath).isFile()) fail("ENV file not found");
if (process.platform !== "win32") {
  const mode = fs.statSync(envPath).mode & 0o777;
  if ((mode & 0o077) !== 0) fail(`Unsafe ENV permissions ${mode.toString(8)}; run chmod 600`);
}
const ignored = spawnSync("git", ["check-ignore", "-q", path.relative(repo, envPath)], { cwd: repo });
if (ignored.status !== 0) fail("ENV path is not ignored by git");
const parsed = dotenv.parse(fs.readFileSync(envPath));
if (!parsed.OWNER_PRIVATE_KEY) fail("OWNER_PRIVATE_KEY missing");
if (!/^(0x)?[0-9a-fA-F]{64}$/.test(parsed.OWNER_PRIVATE_KEY)) fail("OWNER_PRIVATE_KEY format invalid");

const child = spawnSync(
  process.platform === "win32" ? "npx.cmd" : "npx",
  ["hardhat", ...args],
  {
    cwd: repo,
    stdio: "inherit",
    env: { ...process.env, ...parsed, SYNERGY_ENV_FILE: envPath },
  }
);
process.exit(child.status === null ? 1 : child.status);
