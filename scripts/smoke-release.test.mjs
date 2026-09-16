import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createServer } from "node:http";
import test from "node:test";
import { fileURLToPath } from "node:url";

const smokePath = fileURLToPath(new URL("./smoke-release.mjs", import.meta.url));

/**
 * 起一个本地假站点跑冒烟脚本，返回退出码、输出与请求序列。
 * handler 只负责「站点长什么样」，请求记录由这里统一收集。
 */
async function runSmoke(handler) {
  const requests = [];
  const server = createServer((request, response) => {
    requests.push({ method: request.method, url: request.url });
    handler(request, response);
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const address = server.address();
  assert.notEqual(address, null);
  assert.equal(typeof address, "object");
  const baseUrl = `http://127.0.0.1:${address.port}`;

  const child = spawn(process.execPath, [smokePath], {
    env: { ...process.env, PUBLIC_SITE_URL: baseUrl, PUBLIC_API_BASE: baseUrl },
  });
  let stdout = "";
  let stderr = "";
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", (chunk) => {
    stdout += chunk;
  });
  child.stderr.on("data", (chunk) => {
    stderr += chunk;
  });
  const [status] = await once(child, "close");
  server.close();

  return { status, stdout, stderr, requests };
}

test("checks deployed public surfaces without mutation", async () => {
  const { status, stderr, requests } = await runSmoke((request, response) => {
    if (request.url === "/") {
      response.writeHead(200, { "content-type": "text/html" });
      response.end('<a href="/read/article-1">reader</a>');
      return;
    }
    if (request.url === "/read/article-1" || request.url === "/api/ping") {
      response.writeHead(200);
      response.end("ok");
      return;
    }
    if (request.url === "/api/auth/session" || request.url === "/api/subscription") {
      response.writeHead(401);
      response.end("unauthorized");
      return;
    }
    response.writeHead(404);
    response.end("missing");
  });

  assert.equal(status, 0, stderr);
  assert.deepEqual(requests, [
    { method: "GET", url: "/" },
    { method: "GET", url: "/read/article-1" },
    { method: "GET", url: "/api/ping" },
    { method: "GET", url: "/api/auth/session" },
    { method: "GET", url: "/api/subscription" },
  ]);
});

test("falls back to the latest daily page when the home page has no reader link", async () => {
  // 零选日：管道按设计不写 picks.json ⇒ 首页没有 /read/ 链接。这是正确行为，
  // 冒烟应退回日报页取 reader 链接，而不是判站点失败。
  const { status, stdout, stderr, requests } = await runSmoke((request, response) => {
    if (request.url === "/") {
      response.writeHead(200, { "content-type": "text/html" });
      response.end('<a href="/daily/2026-09-15/">今日速览</a>');
      return;
    }
    if (request.url === "/daily/2026-09-15/") {
      response.writeHead(200, { "content-type": "text/html" });
      response.end('<a href="/read/article-9">reader</a>');
      return;
    }
    if (request.url === "/read/article-9" || request.url === "/api/ping") {
      response.writeHead(200);
      response.end("ok");
      return;
    }
    if (request.url === "/api/auth/session" || request.url === "/api/subscription") {
      response.writeHead(401);
      response.end("unauthorized");
      return;
    }
    response.writeHead(404);
    response.end("missing");
  });

  assert.equal(status, 0, stderr);
  assert.match(stdout, /reader \(via daily \/daily\/2026-09-15\/\)/);
  assert.deepEqual(requests, [
    { method: "GET", url: "/" },
    { method: "GET", url: "/daily/2026-09-15/" },
    { method: "GET", url: "/read/article-9" },
    { method: "GET", url: "/api/ping" },
    { method: "GET", url: "/api/auth/session" },
    { method: "GET", url: "/api/subscription" },
  ]);
});

test("fails when neither the home page nor a daily page exposes any reader link", async () => {
  // 判据不能放松：站点真的没有任何可读内容时，冒烟必须仍然红。
  const { status, stderr } = await runSmoke((request, response) => {
    if (request.url === "/") {
      response.writeHead(200, { "content-type": "text/html" });
      response.end('<a href="/about/">关于</a>');
      return;
    }
    if (request.url === "/api/ping") {
      response.writeHead(200);
      response.end("ok");
      return;
    }
    response.writeHead(401);
    response.end("unauthorized");
  });

  assert.notEqual(status, 0);
  assert.match(stderr, /no reader link and no daily link/);
});
