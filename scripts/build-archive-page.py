# -*- coding: utf-8 -*-
"""生成月度政策档案查看页（单文件 HTML）。

输入：content/archive/<YYYY-MM>/archive.json（curate-archive.py 产出）
输出：_review/archive-policy.html
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "content" / "archive"
DST = ROOT / "_review" / "archive-policy.html"

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>月度政策档案</title>
<style>
  :root{--bg:#F5F1E8;--ink:#2B2B28;--sub:#6B6B63;--line:#DFD8C8;--green:#4C795B;--red:#A8543F;--card:#FFFDF8;--amber:#8A6D3B}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.75 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
  header{position:sticky;top:0;z-index:10;background:var(--bg);border-bottom:1px solid var(--line);padding:16px 20px}
  h1{font-size:17px;margin:0 0 4px;font-weight:600}
  .sub{font-size:13px;color:var(--sub)}
  main{max-width:920px;margin:0 auto;padding:22px 20px 80px}
  .month{margin:30px 0 0}
  .mhead{display:flex;align-items:baseline;gap:12px;border-bottom:2px solid var(--line);padding-bottom:8px;margin-bottom:16px}
  .mhead h2{font-size:20px;margin:0;font-weight:600}
  .pill{font-size:12px;border:1px solid var(--line);background:var(--card);border-radius:20px;padding:2px 10px;color:var(--sub)}
  .pill.high{color:#fff;background:var(--green);border-color:var(--green)}
  .item{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 18px;margin-bottom:11px;border-left:4px solid var(--line)}
  .item.high{border-left-color:var(--green)}
  .item.medium{border-left-color:var(--amber)}
  .item.low{border-left-color:#C9C4B6;opacity:.85}
  .row{display:flex;gap:9px;align-items:center;font-size:12px;color:var(--sub);margin-bottom:6px;flex-wrap:wrap}
  .tag{background:var(--bg);border:1px solid var(--line);border-radius:5px;padding:1px 7px}
  .tag.topic{color:var(--amber)}
  .tag.imp-high{color:#fff;background:var(--green);border-color:var(--green)}
  h3{font-size:15.5px;margin:0 0 7px;line-height:1.5;font-weight:600}
  .gist{font-size:14px;color:#43433D;margin:0}
  a{color:var(--green);font-size:12.5px}
  details{margin-top:14px}
  summary{cursor:pointer;font-size:13.5px;color:var(--sub)}
  .legend{font-size:13px;color:var(--sub);background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin-bottom:8px}
</style>
</head>
<body>
<header>
  <h1>月度政策档案 · 2026</h1>
  <div class="sub" id="topline"></div>
</header>
<main>
  <div class="legend">
    <b>这是什么</b>：从中国政府网政策文件库（国务院文件 + 部门文件）按月回溯抓取的权威政策清单，
    经 AI 判断考公价值后分层。<b>绿色左边框 = 核心考点</b>（五年规划、重要法规、中央战略部署），
    琥珀 = 了解即可，灰 = 技术细则。
  </div>
  <div id="body"></div>
</main>
<script>
const DATA = __DATA__;
function esc(s){return String(s||"").replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function render(){
  const months = Object.keys(DATA).sort();
  let totalHigh = 0, total = 0;
  months.forEach(m => { totalHigh += DATA[m].high; total += DATA[m].count; });
  document.getElementById("topline").textContent =
    months.length + " 个月 · 共 " + total + " 份政策文件 · 核心考点 " + totalHigh + " 份";

  const body = document.getElementById("body");
  months.forEach(m => {
    const d = DATA[m];
    const wrap = document.createElement("div");
    wrap.className = "month";
    const [y, mo] = m.split("-");
    wrap.innerHTML = '<div class="mhead"><h2>' + y + ' 年 ' + parseInt(mo, 10) + ' 月</h2>' +
      '<span class="pill high">核心 ' + d.high + '</span>' +
      '<span class="pill">了解 ' + d.medium + '</span>' +
      '<span class="pill">细则 ' + d.low + '</span>' +
      '<span class="pill">共 ' + d.count + ' 份</span></div>';

    const groups = [["高","核心考点"],["中","了解即可"],["低","技术细则"]];
    groups.forEach(([imp, label]) => {
      const rows = d.items.filter(x => x.importance === imp);
      if (!rows.length) return;
      if (imp !== "高") {
        const det = document.createElement("details");
        det.innerHTML = '<summary>' + label + '（' + rows.length + '）</summary>';
        const box = document.createElement("div");
        rows.forEach(x => box.appendChild(card(x, imp)));
        det.appendChild(box);
        wrap.appendChild(det);
      } else {
        rows.forEach(x => wrap.appendChild(card(x, imp)));
      }
    });
    body.appendChild(wrap);
  });
}
function card(x, imp) {
  const el = document.createElement("div");
  el.className = "item " + (imp === "高" ? "high" : imp === "中" ? "medium" : "low");
  el.innerHTML =
    '<div class="row">' +
      '<span class="tag">' + esc(x.date.slice(5)) + '</span>' +
      '<span class="tag imp-' + (imp === "高" ? "high" : "") + '">' + esc(x.lib) + '</span>' +
      '<span class="tag topic">' + esc(x.topic) + '</span>' +
      (x.url ? '<a href="' + esc(x.url) + '" target="_blank" rel="noopener">原文 ↗</a>' : '') +
    '</div>' +
    '<h3>' + esc(x.title) + '</h3>' +
    '<p class="gist">' + esc(x.gist || "（未生成要点）") + '</p>';
  return el;
}
render();
</script>
</body>
</html>
"""


def main() -> int:
    data = {}
    for day in sorted(ARCHIVE.glob("????-??")):
        f = day / "archive.json"
        if f.exists():
            data[day.name] = json.loads(f.read_text(encoding="utf-8"))
    if not data:
        print("没有 archive.json，先跑 curate-archive.py")
        return 2
    html = HTML.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    DST.write_text(html, encoding="utf-8")
    for m, d in data.items():
        print(f"{m}: {d['count']} 份（核心 {d['high']}）")
    print(f"档案页: {DST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
