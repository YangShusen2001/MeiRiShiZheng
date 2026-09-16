import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const gatePath = fileURLToPath(new URL("./release-gate.mjs", import.meta.url));
const realRegistryPath = fileURLToPath(new URL("../docs/release-readiness.json", import.meta.url));

function runGate(blockers) {
  const directory = mkdtempSync(join(tmpdir(), "kaogong-release-gate-"));
  const registryPath = join(directory, "release-readiness.json");
  writeFileSync(registryPath, JSON.stringify({ version: 1, blockers }));
  return spawnSync(process.execPath, [gatePath, registryPath], {
    encoding: "utf8",
  });
}

test("blocks release when a high-risk blocker is open", () => {
  const result = runGate([
    {
      id: "REL-TEST-OPEN",
      title: "Provider unavailable",
      severity: "high",
      status: "open",
      closeEvidence: null,
    },
  ]);

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /REL-TEST-OPEN/);
});

test("blocks release when a high-risk blocker is closed without evidence", () => {
  const result = runGate([
    {
      id: "REL-TEST-NO-EVIDENCE",
      title: "Provider unavailable",
      severity: "critical",
      status: "closed",
      closeEvidence: null,
    },
  ]);

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /close evidence/i);
});

test("allows release when every high-risk blocker has explicit close evidence", () => {
  const result = runGate([
    {
      id: "REL-TEST-CLOSED",
      title: "Provider verified",
      severity: "high",
      status: "closed",
      closeEvidence: {
        verifiedAt: "2026-08-15T00:00:00Z",
        verifiedBy: "release-owner",
        evidence: "https://github.com/example/repository/actions/runs/1",
      },
    },
  ]);

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /release gate passed/i);
});

test("blocks each open high-risk blocker independently", () => {
  const newsletterOnly = runGate([
    {
      id: "REL-TEST-NEWSLETTER",
      title: "Newsletter provider evidence missing",
      severity: "high",
      status: "open",
      closeEvidence: null,
    },
    {
      id: "REL-TEST-DEPLOYMENT",
      title: "Deployment evidence present",
      severity: "high",
      status: "closed",
      closeEvidence: {
        verifiedAt: "2026-08-15T00:00:00Z",
        verifiedBy: "release-owner",
        evidence: "https://github.com/example/repository/actions/runs/deployment",
      },
    },
  ]);
  const deploymentOnly = runGate([
    {
      id: "REL-TEST-NEWSLETTER",
      title: "Newsletter provider evidence present",
      severity: "high",
      status: "closed",
      closeEvidence: {
        verifiedAt: "2026-08-15T00:00:00Z",
        verifiedBy: "release-owner",
        evidence: "https://github.com/example/repository/actions/runs/newsletter",
      },
    },
    {
      id: "REL-TEST-DEPLOYMENT",
      title: "Deployment evidence missing",
      severity: "high",
      status: "open",
      closeEvidence: null,
    },
  ]);

  assert.notEqual(newsletterOnly.status, 0);
  assert.match(newsletterOnly.stderr, /REL-TEST-NEWSLETTER/);
  assert.doesNotMatch(newsletterOnly.stderr, /REL-TEST-DEPLOYMENT/);
  assert.notEqual(deploymentOnly.status, 0);
  assert.match(deploymentOnly.stderr, /REL-TEST-DEPLOYMENT/);
  assert.doesNotMatch(deploymentOnly.stderr, /REL-TEST-NEWSLETTER/);
});

test("passes on the real registry after the 2026-09-16 triage", () => {
  const result = spawnSync(process.execPath, [gatePath, realRegistryPath], {
    encoding: "utf8",
  });

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /release gate passed/i);
});

test("keeps the downgraded newsletter blocker honest: medium + open + no fabricated evidence", () => {
  // 降级是为了不阻塞主干，不是「已解决」。这三条断言防止有人靠改 status
  // 或补假 evidence 让它彻底消失 —— 账必须还是欠着的。
  const registry = JSON.parse(readFileSync(realRegistryPath, "utf8"));
  const newsletter = registry.blockers.find((blocker) => blocker.id === "REL-NEWSLETTER-PROVIDER");

  assert.ok(newsletter, "REL-NEWSLETTER-PROVIDER must stay in the registry");
  assert.equal(newsletter.severity, "medium");
  assert.equal(newsletter.status, "open");
  assert.equal(newsletter.closeEvidence, null);
  assert.equal(typeof newsletter.severityChangeReason, "string");
  assert.ok(newsletter.severityChangeReason.length > 0);
});
