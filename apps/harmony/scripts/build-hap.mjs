#!/usr/bin/env node
// 鸿蒙端 CLI 编译验证。
//
// 用法：node apps/harmony/scripts/build-hap.mjs
//
// 背景：此前所有 ArkTS 代码都只能"看着像对"。接上这条链路后，
// 每次改动都能真编译，ArkTS 的硬性限制（类型、@Builder 限制、导出可见性…）
// 会在提交前就暴露出来。
//
// 两个必须知道的约束（均已实测追到底）：
// 1. 必须设 `DEVECO_SDK_HOME`，否则报 `00303217 Invalid value of 'DEVECO_SDK_HOME'`。
// 2. **签名这一步在 CLI 下过不去**（`11014003 Init keystore failed`）。
//    已把机制挖清楚，供以后复查：
//    - `build-profile.json5` 里的 keyPassword / storePassword 是**密文**
//      （形如 `0000001B...`，AES-GCM，密钥由 `~/.ohos/config/material/{fd,ac,ce}`
//       与硬编码分量异或后经 PBKDF2-HMAC-SHA256 迭代 1 万次派生）。
//    - 解密由插件的 `DecipherUtil.decryptPwd(materialDir, encryptedPwd, signConfigSrcPath)`
//      完成；直接把明文写进 build-profile.json5 会被判非法
//      （`00303116 The length ... is less than 32`——该字段必须 ≥32 字符的密文）。
//    - 已排除的猜测：keystore 文件损坏（Java 21 下用 keytool 可正常读取）、
//      JDK 版本不匹配（把 DevEco JBR 提到 PATH 最前仍失败）、常见明文密码。
//    ⇒ 本脚本只负责回答"代码能不能编译过"，**装机在 DevEco 点 Run**。
//
// 退出码：ArkTS 编译错误 → 1；否则 0（即使签名没过）。
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const PROJECT = join(HERE, "..");
const DEVECO = "D:/IDE/DevEco_Studio";
const NODE = `${DEVECO}/tools/node/node.exe`;
const HVIGOR = `${DEVECO}/tools/hvigor/bin/hvigorw.js`;
const SDK_HOME = `${DEVECO}/sdk`;

for (const p of [NODE, HVIGOR, SDK_HOME]) {
  if (!existsSync(p)) {
    console.error(`✗ 找不到 ${p}（DevEco 安装路径变化时需要更新本脚本）`);
    process.exit(1);
  }
}

const args = [
  HVIGOR,
  "--mode", "module",
  "-p", "module=entry@default",
  "-p", "product=default",
  "-p", "requiredDeviceType=phone",
  "assembleHap",
  "--analyze=normal", "--parallel", "--incremental",
];

let log = "";
try {
  log = execFileSync(NODE, args, {
    cwd: PROJECT,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, DEVECO_SDK_HOME: SDK_HOME },
    maxBuffer: 64 * 1024 * 1024,
  });
} catch (err) {
  log = `${err.stdout ?? ""}${err.stderr ?? ""}`;
}

// ArkTS 编译错误：逐条打印，这是本脚本存在的意义
const arkErrors = [...log.matchAll(/Error Message: (.+?) At File: (\S+):(\d+):(\d+)/g)];
const compileFailed = /COMPILE RESULT:FAIL/.test(log);

if (arkErrors.length > 0) {
  console.error(`✗ ArkTS 编译错误 ${arkErrors.length} 处：`);
  for (const [, msg, file, line, col] of arkErrors) {
    console.error(`  ${file.replace(/.*[\\/]ets[\\/]/, "")}:${line}:${col}`);
    console.error(`    ${msg}`);
  }
  process.exit(1);
}

const warnings = [...log.matchAll(/ArkTS:WARN File: (\S+):(\d+):(\d+)/g)];
if (warnings.length > 0) {
  console.log(`⚠ ArkTS 警告 ${warnings.length} 处：`);
  for (const [, file, line, col] of warnings) {
    console.log(`  ${file.replace(/.*[\\/]ets[\\/]/, "")}:${line}:${col}`);
  }
}

if (compileFailed) {
  console.error("✗ 编译失败（未见具体 Error Message，请查看完整日志）");
  process.exit(1);
}

const signFailed = /Init keystore failed/.test(log);
console.log("✓ ArkTS 编译通过，HAP 已打包");
if (signFailed) {
  console.log("  （签名在 CLI 下不可用——密码由 DevEco 加密；装机请在 DevEco 点 Run）");
}
