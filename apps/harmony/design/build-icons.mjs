// 由矢量源生成各尺寸应用图标。
//
// 用法：node apps/harmony/design/build-icons.mjs
//
// 为什么要脚本而不是直接放 PNG：图标必须可改。只留一张位图，下次要调色或调比例
// 就得重画；有矢量源 + 一条命令的构建脚本，改一行 SVG 即可全量重出。
//
// 依赖 sharp 栅格化 SVG。sharp 是仓库内已有依赖（`.pnpm/sharp@*`），
// 这里按候选路径解析，避免要求本仓把 sharp 提为直接依赖。
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { readdirSync, existsSync } from "node:fs";

const HERE = dirname(fileURLToPath(import.meta.url));
const HARMONY = join(HERE, "..");
const REPO_ROOT = join(HARMONY, "..", "..");
const require = createRequire(import.meta.url);

/** 解析 sharp：直接依赖优先，否则在 pnpm 虚拟store 里找已安装的版本。 */
function loadSharp() {
  try {
    return require("sharp");
  } catch {
    const store = join(REPO_ROOT, "node_modules", ".pnpm");
    if (!existsSync(store)) throw new Error("找不到 node_modules/.pnpm，请先安装依赖");
    const candidates = readdirSync(store)
      .filter((name) => name.startsWith("sharp@"))
      .sort()
      .reverse();
    for (const name of candidates) {
      const entry = join(store, name, "node_modules", "sharp");
      if (existsSync(entry)) return require(entry);
    }
    throw new Error("在 .pnpm 里找不到 sharp");
  }
}

const sharp = loadSharp();
const svg = readFileSync(join(HERE, "app-icon.svg"));

/** 输出目标：应用图标（AppScope）与启动图标（entry）需同源，避免两处不一致。 */
const TARGETS = [
  { file: join(HARMONY, "AppScope/resources/base/media/app_icon.png"), size: 216 },
  { file: join(HARMONY, "entry/src/main/resources/base/media/startIcon.png"), size: 216 },
  // 应用市场/落地页用的大图
  { file: join(HERE, "app-icon-512.png"), size: 512 },
];

for (const target of TARGETS) {
  const png = await sharp(svg, { density: 384 })
    .resize(target.size, target.size, { fit: "fill" })
    .png({ compressionLevel: 9 })
    .toBuffer();
  writeFileSync(target.file, png);
  console.log(`✓ ${target.size}×${target.size} → ${target.file.replace(REPO_ROOT, ".")} (${png.length} B)`);
}
console.log("图标生成完成");
