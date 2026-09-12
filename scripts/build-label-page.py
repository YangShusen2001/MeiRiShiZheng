# -*- coding: utf-8 -*-
"""生成黄金样本标注页：把 sample-40.json 内嵌进单文件 HTML。

用户打开 HTML → 逐篇点「进池 / 不进池」→ 结果存 localStorage 并可导出 JSON。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = ROOT / "_review" / "sample-40.json"
dst = ROOT / "_review" / "label.html"
items = json.loads(src.read_text(encoding="utf-8"))

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>黄金样本标注 · 2026-09-11</title>
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
  main{max-width:860px;margin:0 auto;padding:22px 20px 120px}
  .guide{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 20px;margin-bottom:22px;font-size:14px}
  .guide h2{font-size:14px;margin:0 0 10px;color:var(--green)}
  .guide ul{margin:6px 0;padding-left:20px}
  .guide li{margin:3px 0}
  .guide .no{color:var(--red)}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 20px;margin-bottom:14px;transition:border-color .2s,opacity .2s}
  .card.done{opacity:.55}
  .card.in{border-color:var(--green);border-width:2px}
  .card.out{border-color:var(--red);border-width:2px}
  .meta{display:flex;gap:10px;align-items:center;font-size:12px;color:var(--sub);margin-bottom:8px;flex-wrap:wrap}
  .tag{background:var(--bg);border:1px solid var(--line);border-radius:5px;padding:1px 7px}
  .tag.host{color:var(--green)}
  h3{font-size:16px;margin:0 0 10px;line-height:1.5;font-weight:600}
  .prev{font-size:13.5px;color:var(--sub);white-space:pre-wrap;max-height:120px;overflow:hidden;position:relative;margin-bottom:12px}
  .prev.noclip{font-style:italic;color:#9A9A90}
  .prev::after{content:"";position:absolute;bottom:0;left:0;right:0;height:32px;background:linear-gradient(transparent,var(--card))}
  .acts{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  .acts button{min-height:44px;min-width:104px;font-weight:500}
  .acts button[data-v="in"].on{background:var(--green);color:#fff;border-color:var(--green)}
  .acts button[data-v="out"].on{background:var(--red);color:#fff;border-color:var(--red)}
  .reason{width:100%;margin-top:10px;border:1px dashed var(--line);border-radius:8px;background:transparent;padding:8px 12px;font:inherit;font-size:13.5px;color:var(--ink);resize:vertical;min-height:38px}
  .reason:focus{border-color:var(--green);outline:none;border-style:solid;background:var(--card)}
  .reason::-webkit-textarea-placeholder{color:#B0AFA5}
  a{color:var(--green);font-size:13px}
  .float{position:fixed;bottom:0;left:0;right:0;background:rgba(245,241,232,.96);backdrop-filter:blur(6px);border-top:1px solid var(--line);padding:12px 20px;display:flex;gap:12px;align-items:center;justify-content:center;flex-wrap:wrap}
  .stat{font-size:13px;color:var(--sub);font-variant-numeric:tabular-nums}
  .stat b{color:var(--green)}.stat i{color:var(--red);font-style:normal}
  kbd{background:var(--bg);border:1px solid var(--line);border-bottom-width:2px;border-radius:4px;padding:0 5px;font-size:11px;font-family:inherit}
  @media(max-width:600px){.prev{max-height:88px}}
</style>
</head>
<body>
<header>
  <div class="bar">
    <h1>黄金样本标注</h1>
    <span class="prog" id="prog">0 / __N__</span>
    <div class="track"><div class="fill" id="fill"></div></div>
    <button onclick="exportJSON()">导出结果</button>
    <button onclick="resetAll()">清空</button>
  </div>
</header>
<main>
  <div class="guide">
    <h2>判据：这篇能不能进「精品阅读池」？</h2>
    <div><b>进池（✅）——面向公务员考试，具备以下任一：</b></div>
    <ul>
      <li><b>观点式表述</b>：可背诵、可用于申论写作的规范表述（如"以正确政绩观推进…"）</li>
      <li><b>政策落点</b>：中央级政策文件、重大部署、领导人重要活动</li>
      <li><b>结构式论证</b>：有清晰分论点（如"五个发力"式的动宾结构）</li>
      <li><b>可复用案例</b>：能浓缩成十几字的典型案例素材</li>
      <li><b>重点领域动态</b>：AI、知识产权、生态、教育科技人才等高频考点领域</li>
    </ul>
    <div class="no"><b>不进池（❌）：</b></div>
    <ul>
      <li>地方工作动态、地方通稿（无论哪个省）</li>
      <li>人事任免、气象天气、票务服务、民生事务细节</li>
      <li>展会节庆、文化活动、体育赛事</li>
      <li>个案执法、社会新闻</li>
      <li>纯信息通报，无可背诵表述、无结构、无案例价值</li>
    </ul>
    <div style="margin-top:10px;color:#6B6B63;font-size:13px">
      快捷键：<kbd>1</kbd> 进池 · <kbd>2</kbd> 不进池 · <kbd>←</kbd><kbd>→</kbd> 上下 · <kbd>Esc</kbd> 退出理由框 · 进池后光标自动跳进理由框 · 进度自动保存在本机
    </div>
  </div>
  <div id="list"></div>
</main>
<div class="float">
  <span class="stat">已标 <b id="sIn">0</b> 进池 · <i id="sOut">0</i> 不进池 · 已写理由 <span id="sReason">0</span> · 余 <span id="sLeft">__N__</span></span>
  <span class="stat" style="margin-left:12px">进池标题：</span>
  <span class="stat" id="inList" style="max-width:520px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></span>
</div>
<script>
const DATA = __DATA__;
const KEY = "kaogong-gold-2026-09-11";
const RKEY = "kaogong-gold-2026-09-11-reasons";
let labels = JSON.parse(localStorage.getItem(KEY) || "{}");
let reasons = JSON.parse(localStorage.getItem(RKEY) || "{}");
let focusIdx = 0;

function render(){
  const list = document.getElementById("list");
  list.innerHTML = "";
  DATA.forEach((it, i) => {
    const v = labels[it.id];
    const el = document.createElement("div");
    el.className = "card" + (v ? " done " + (v === "in" ? "in" : "out") : "");
    el.id = "c" + i;
    const prevCls = it.hasClip ? "prev" : "prev noclip";
    const prevTxt = it.hasClip ? esc(it.preview || "(正文为空)") : "⚠️ 剪藏失败，无正文预览（请按标题判断）";
    const rv = reasons[it.id] || "";
    const ph = v === "in"
      ? "为什么进池？（必填：它是什么类型的素材——观点表述 / 政策落点 / 论证结构 / 案例 / 重点领域？）"
      : v === "out" ? "为什么不进？（可选，一句话）" : "先标注进 / 不进，再写理由";
    el.innerHTML = `
      <div class="meta">
        <span class="tag">${esc(it.section)}</span>
        <span class="tag host">${esc(it.host)}</span>
        <span>#${i + 1}</span>
      </div>
      <h3>${esc(it.title)}</h3>
      <div class="${prevCls}">${prevTxt}</div>
      <div class="acts">
        <button data-v="in" class="${v === "in" ? "on" : ""}" onclick="mark(${i},'in')">✅ 进池</button>
        <button data-v="out" class="${v === "out" ? "on" : ""}" onclick="mark(${i},'out')">❌ 不进池</button>
        <a href="${esc(it.url)}" target="_blank" rel="noopener">查看原文 ↗</a>
      </div>
      <textarea class="reason" rows="2" placeholder="${ph}"
        oninput="saveReason(${i}, this.value)">${esc(rv)}</textarea>`;
    list.appendChild(el);
  });
  updateStats();
}
function esc(s){return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function saveReason(i, v){
  reasons[DATA[i].id] = v;
  localStorage.setItem(RKEY, JSON.stringify(reasons));
  updateStats();
}
function mark(i, v){
  const id = DATA[i].id;
  if (labels[id] === v) delete labels[id]; else labels[id] = v;
  localStorage.setItem(KEY, JSON.stringify(labels));
  render();
  if (v === "in" || v === "out") {
    const ta = document.querySelector("#c" + i + " .reason");
    if (ta) { ta.focus(); }
  }
}
function updateStats(){
  const vals = Object.values(labels);
  const nin = vals.filter(v => v === "in").length;
  const nout = vals.filter(v => v === "out").length;
  const done = nin + nout;
  const nReason = Object.values(reasons).filter(r => r && r.trim()).length;
  document.getElementById("prog").textContent = done + " / " + DATA.length;
  document.getElementById("fill").style.width = (done / DATA.length * 100) + "%";
  document.getElementById("sIn").textContent = nin;
  document.getElementById("sOut").textContent = nout;
  document.getElementById("sLeft").textContent = DATA.length - done;
  document.getElementById("sReason").textContent = nReason;
  const ins = DATA.filter(it => labels[it.id] === "in").map(it => it.title).join(" / ");
  document.getElementById("inList").textContent = ins || "（还没标）";
}
function exportJSON(){
  const rows = DATA.map(it => ({id: it.id, verdict: labels[it.id] || null, reason: (reasons[it.id] || "").trim() || null, section: it.section, host: it.host, title: it.title, url: it.url}));
  const missing = rows.filter(r => r.verdict === "in" && !r.reason);
  const msg = missing.length
    ? "还有 " + missing.length + " 篇进池的没写理由：\\n" + missing.map(r => "· " + r.title.slice(0, 24)).join("\\n") + "\\n\\n仍要导出吗？（理由可以之后再补）"
    : null;
  const go = () => {
    const blob = new Blob([JSON.stringify({date: "2026-09-11", labels: rows}, null, 2)], {type: "application/json"});
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "gold-labels-2026-09-11.json";
    a.click();
    navigator.clipboard && navigator.clipboard.writeText(JSON.stringify(rows.filter(r => r.verdict)));
  };
  if (msg && !confirm(msg)) return; else go();
}
function resetAll(){ if(confirm("清空全部标注与理由？")){ labels = {}; reasons = {}; localStorage.removeItem(KEY); localStorage.removeItem(RKEY); render(); } }
document.addEventListener("keydown", e => {
  const t = e.target;
  const typing = t && (t.tagName === "TEXTAREA" || t.tagName === "INPUT");
  if (e.key === "Escape" && typing) { t.blur(); return; }
  if (typing) return;  // 打理由时不触发快捷键（1/2/方向键都是正文输入）
  if (e.key === "1" || e.key === "2") { mark(focusIdx, e.key === "1" ? "in" : "out"); }
  else if (e.key === "ArrowRight") { focusIdx = Math.min(focusIdx + 1, DATA.length - 1); scrollTo(); }
  else if (e.key === "ArrowLeft") { focusIdx = Math.max(focusIdx - 1, 0); scrollTo(); }
});
function scrollTo(){
  const el = document.getElementById("c" + focusIdx);
  if (el) el.scrollIntoView({block: "center", behavior: "smooth"});
}
render();
</script>
</body>
</html>
"""

html = HTML.replace("__DATA__", json.dumps(items, ensure_ascii=False)).replace("__N__", str(len(items)))
dst.write_text(html, encoding="utf-8")
print(f"生成 {dst}  ({len(html)} 字节, {len(items)} 条)")
