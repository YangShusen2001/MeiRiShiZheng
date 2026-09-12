# -*- coding: utf-8 -*-
"""生成 8 月规则漏斗审核页（单文件 HTML，零依赖、可离线打开）。

输入：_review/audit-2026-08-rules.json（audit-2026-08-rules.py 产出）
输出：_review/audit-2026-08.html

用户逐条点「留 / 不留」+ 填理由 → 存 localStorage → 可导出 JSON。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "_review" / "audit-2026-08-rules.json"
DST = ROOT / "_review" / "audit-2026-08.html"

REASON_LABEL = {
    "empty": "空正文",
    "shallow_notice": "浅讯稿（领导人短讯/一句话通稿，不足 400 字）",
    "pure_data": "纯数据（数字堆砌、无分析）",
    "caption_style": "图注/诗行体",
    "patchwork": "拼盘（多段拼接、通篇无分析）",
    "cluster_duplicate": "同事件重复（簇去重）",
    "quota_caps": "配额/CAPS 超额",
}

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>8 月规则漏斗审核 · 零 AI</title>
<style>
  :root{--bg:#F5F1E8;--ink:#2B2B28;--sub:#6B6B63;--line:#DFD8C8;--green:#4C795B;--red:#A8543F;--card:#FFFDF8}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.7 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
  header{position:sticky;top:0;z-index:10;background:var(--bg);border-bottom:1px solid var(--line);padding:14px 20px}
  .bar{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
  h1{font-size:16px;margin:0;font-weight:600;letter-spacing:.02em}
  .prog{font-variant-numeric:tabular-nums;color:var(--sub);font-size:13px}
  .track{flex:1;min-width:120px;height:6px;background:var(--line);border-radius:3px;overflow:hidden}
  .fill{height:100%;width:0;background:var(--green);transition:width .2s}
  button{font:inherit;cursor:pointer;border:1px solid var(--line);background:var(--card);border-radius:8px;padding:7px 14px;color:var(--ink)}
  button:hover{border-color:var(--green)}
  button.primary{background:var(--green);color:#fff;border-color:var(--green)}
  main{max-width:900px;margin:0 auto;padding:22px 20px 130px}
  .guide{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 20px;margin-bottom:22px;font-size:14px}
  .guide h2{font-size:14px;margin:0 0 10px;color:var(--green)}
  .guide ul{margin:6px 0;padding-left:20px}
  .guide li{margin:3px 0}
  .guide .no{color:var(--red)}
  .stats{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px}
  .stat{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:4px 10px;font-size:13px;font-variant-numeric:tabular-nums}
  h2.day{font-size:15px;margin:26px 0 12px;padding-bottom:6px;border-bottom:2px solid var(--line);display:flex;justify-content:space-between;align-items:baseline}
  h2.day span{font-size:12.5px;color:var(--sub);font-weight:400}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 18px;margin-bottom:12px;transition:border-color .2s,opacity .2s}
  .card.done{opacity:.5}
  .card.keep{border-color:var(--green);border-width:2px}
  .card.drop{border-color:var(--red);border-width:2px}
  .meta{display:flex;gap:8px;align-items:center;font-size:12px;color:var(--sub);margin-bottom:6px;flex-wrap:wrap}
  .tag{background:var(--bg);border:1px solid var(--line);border-radius:5px;padding:1px 7px}
  .tag.host{color:var(--green)}
  .tag.slot{color:#8A6D3B}
  h3{font-size:15.5px;margin:0 0 8px;line-height:1.5;font-weight:600}
  .acts{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  .acts button{min-height:44px;min-width:100px;font-weight:500}
  .acts button[data-v="keep"].on{background:var(--green);color:#fff;border-color:var(--green)}
  .acts button[data-v="drop"].on{background:var(--red);color:#fff;border-color:var(--red)}
  .reason{width:100%;margin-top:9px;border:1px dashed var(--line);border-radius:8px;background:transparent;padding:8px 12px;font:inherit;font-size:13.5px;color:var(--ink);resize:vertical;min-height:38px}
  .reason:focus{border-color:var(--green);outline:none;border-style:solid;background:var(--card)}
  a{color:var(--green);font-size:13px}
  details.cut{margin:14px 0 0;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 16px}
  details.cut summary{cursor:pointer;font-size:14px;color:var(--sub);font-weight:500}
  details.cut ul{margin:10px 0 4px;padding-left:18px;font-size:13.5px;color:var(--sub)}
  details.cut li{margin:5px 0}
  details.cut .why{color:var(--red);font-size:12.5px}
  .float{position:fixed;bottom:0;left:0;right:0;background:rgba(245,241,232,.96);backdrop-filter:blur(6px);border-top:1px solid var(--line);padding:12px 20px;display:flex;gap:12px;align-items:center;justify-content:center;flex-wrap:wrap}
</style>
</head>
<body>
<header>
  <div class="bar">
    <h1>8 月规则漏斗审核</h1>
    <div class="prog" id="prog">0 / 0</div>
    <div class="track"><div class="fill" id="fill"></div></div>
    <button onclick="exportJSON()">导出结果</button>
    <button onclick="resetAll()">清空</button>
  </div>
</header>
<main>
  <div class="guide">
    <h2>这一页在审什么</h2>
    <p style="margin:0 0 8px">这些是 <b>2026 年 8 月的真实抓取数据</b>，用新管道的<b>纯规则闸门</b>（密度 G1-G4 → 簇去重 → 配额/CAPS）复核过一遍，
    <b>没有调用任何 AI</b>。规则从 195 篇里放行 59 篇、砍掉 136 篇。</p>
    <p style="margin:0 0 6px">你要判断的是两件事：</p>
    <ul>
      <li><b>放行的 59 篇</b>——规则觉得够格，你认可吗？（点「留 / 不留」）</li>
      <li><b>被砍的 136 篇</b>——每条都写了砍的理由，折叠在每天下面，抽查砍得对不对。</li>
    </ul>
    <p style="margin:6px 0 0;font-size:13px" class="no">注：8 月这批没有 AI 摘要与标注（当时额度耗尽），所以规则若能放行不代表终稿合格——AI 判据（7 进 8 出）还没上场。</p>
    <div class="stats" id="stats"></div>
  </div>
  <div id="days"></div>
</main>
<div class="float">
  <span class="prog" id="prog2">0 / 0</span>
  <button class="primary" onclick="exportJSON()">导出结果 JSON</button>
  <button onclick="resetAll()">清空标注</button>
</div>
<script>
const DATA = __DATA__;
const REASON_LABEL = __REASON_LABEL__;
const KEY = "audit-2026-08-labels";
const RKEY = "audit-2026-08-reasons";
let labels = JSON.parse(localStorage.getItem(KEY) || "{}");
let reasons = JSON.parse(localStorage.getItem(RKEY) || "{}");

function save(){ localStorage.setItem(KEY, JSON.stringify(labels)); localStorage.setItem(RKEY, JSON.stringify(reasons)); }

function render(){
  const days = document.getElementById("days");
  days.innerHTML = "";
  let total = 0, done = 0;
  DATA.days.forEach(d => {
    const surv = d.survivors;
    if (!surv.length && !d.cut) return;
    const h = document.createElement("h2");
    h.className = "day";
    h.innerHTML = d.date + ' <span>' + d.counts.total + ' 篇 → 规则放行 ' + d.counts.survived + ' 篇</span>';
    days.appendChild(h);

    surv.forEach(it => {
      total++;
      const key = d.date + "|" + it.id;
      const v = labels[key];
      if (v) done++;
      const card = document.createElement("div");
      card.className = "card" + (v ? " done " + v : "");
      card.innerHTML =
        '<div class="meta">' +
          '<span class="tag host">' + (it.source || "?") + '</span>' +
          '<span class="tag slot">' + (it.slot || "-") + '</span>' +
          '<span class="tag">' + it.chars + ' 字</span>' +
          (it.url ? '<a href="' + it.url + '" target="_blank" rel="noopener">原文 ↗</a>' : '') +
        '</div>' +
        '<h3>' + escapeHtml(it.title || "") + '</h3>';
      const acts = document.createElement("div");
      acts.className = "acts";
      const bk = document.createElement("button");
      bk.dataset.v = "keep"; bk.textContent = "留"; bk.className = v === "keep" ? "on" : "";
      bk.onclick = () => setLabel(d.date, it.id, "keep");
      const bd = document.createElement("button");
      bd.dataset.v = "drop"; bd.textContent = "不留"; bd.className = v === "drop" ? "on" : "";
      bd.onclick = () => setLabel(d.date, it.id, "drop");
      acts.appendChild(bk); acts.appendChild(bd);
      card.appendChild(acts);
      const ta = document.createElement("textarea");
      ta.className = "reason"; ta.placeholder = "理由（可选）";
      ta.value = reasons[key] || "";
      ta.oninput = () => { reasons[key] = ta.value; save(); };
      card.appendChild(ta);
      days.appendChild(card);
    });

    const groups = [
      ["density", "密度门禁砍掉的"],
      ["cluster", "簇去重砍掉的"],
      ["quota", "配额/CAPS 砍掉的"],
    ];
    let cutHtml = "";
    groups.forEach(([g, label]) => {
      const rows = d.cut[g] || [];
      if (!rows.length) return;
      cutHtml += '<details class="cut"><summary>' + label + '（' + rows.length + '）</summary><ul>';
      rows.forEach(r => {
        const why = (r.reason || "").replace("density_low:", "");
        cutHtml += '<li>' + escapeHtml(r.title || "") +
          ' <span class="why">[' + (REASON_LABEL[why] || why) + ']</span>' +
          ' · ' + (r.source || "") + ' · ' + r.chars + ' 字</li>';
      });
      cutHtml += '</ul></details>';
    });
    if (cutHtml) {
      const box = document.createElement("div");
      box.innerHTML = cutHtml;
      days.appendChild(box);
    }
  });
  const pct = total ? Math.round(done * 100 / total) : 0;
  document.getElementById("prog").textContent = done + " / " + total + "（" + pct + "%）";
  document.getElementById("prog2").textContent = done + " / " + total;
  document.getElementById("fill").style.width = pct + "%";

  const st = document.getElementById("stats");
  st.innerHTML = DATA.days.map(d =>
    '<span class="stat">' + d.date.slice(5) + '：' + d.counts.total + '→' + d.counts.survived + '</span>'
  ).join("") +
  '<span class="stat">合计 195 → 59（砍 70%）</span>';
}

function setLabel(date, id, v){
  const key = date + "|" + id;
  labels[key] = labels[key] === v ? null : v;
  if (!labels[key]) delete labels[key];
  save(); render();
}

function escapeHtml(s){
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function exportJSON(){
  const out = { generatedAt: new Date().toISOString(), labels: {} };
  Object.keys(labels).forEach(k => {
    const [date, id] = k.split("|");
    out.labels[k] = { date, id, verdict: labels[k], reason: reasons[k] || "" };
  });
  const blob = new Blob([JSON.stringify(out, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "audit-2026-08-labels.json";
  a.click();
}

function resetAll(){
  if (confirm("清空全部审核结果与理由？")) {
    labels = {}; reasons = {};
    localStorage.removeItem(KEY); localStorage.removeItem(RKEY);
    render();
  }
}

render();
</script>
</body>
</html>
"""


def main() -> int:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    html = (HTML
            .replace("__DATA__", json.dumps(data, ensure_ascii=False))
            .replace("__REASON_LABEL__", json.dumps(REASON_LABEL, ensure_ascii=False)))
    DST.write_text(html, encoding="utf-8")
    total = sum(d["counts"]["total"] for d in data["days"])
    surv = sum(d["counts"]["survived"] for d in data["days"])
    print(f"审核页已生成: {DST}")
    print(f"  {total} 篇 → 放行 {surv} 篇（共 {len(data['days'])} 天）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
