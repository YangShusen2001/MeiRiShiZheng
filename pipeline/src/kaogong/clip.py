# -*- coding: utf-8 -*-
"""剪藏原文：抓文章页 → 提取正文 → 产出 ClippedArticle（移植自原 clip_articles.py）。

核心价值是 extract_paragraphs：用「容器标记 + 最长连续段落块 + 噪声/页脚过滤」从中文新闻页
精准抠出正文（不把导航/推荐流混进来）。本移植去掉了 emphasis（加粗区间）——阅读页暂不用。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html as ihtml
import re
import time
import urllib.parse

import httpx

from .http import fetch

CONTAINER_MARKERS = [
    'id="rwb_zw"', 'id="rwb-zw"', 'id="zoom"', 'class="zoom"',
    'id="contentArea"', 'id="content_area"', 'class="article-content"', 'class="article_con"',
    'class="article-con"', 'id="article"', 'class="article"', 'id="content"', 'class="content"',
    'id="TRS_Editor"', 'class="detail-content"', 'class="detail_con"', 'id="detail"',
    'class="article-content-box"', 'class="main-content"',
]

NOISE = re.compile(
    r"(责任编辑|版权声明|扫码|分享到|免责声明|相关新闻|延伸阅读|进入专题|点击进入|"
    r"举报电话|服务邮箱|网站声明|网站律师|信息保护|招聘英才|广告服务|关于人民网|"
    r"人民日报社概况|粤公网安备|ICP备|网站标识码|主办：|承办：|联系我们|版权与免责声明|"
    r"版权所有|互联网新闻信息服务许可证|增值电信业务经营许可证|网络文化经营许可证|"
    r"信息网络传播视听节目许可证|网络出版服务许可证|京ICP备)"
)

FOOTER_START = re.compile(
    r"(人民日报社概况|关于人民网|报社招聘|广告服务|版权服务|数据服务|网站声明|网站律师|"
    r"信息保护|联系我们|举报电话|服务邮箱|许可证|ICP备|版权所有|粤公网安备|网站标识码|"
    r"主办：|承办：|版权与免责声明|Copyright|违法和不良信息举报)"
)


def source_of(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower()
    for frag, name in [
        ("people.com.cn", "人民网"),
        ("gd.gov.cn", "广东省人民政府网"),
        ("banyuetan.org", "半月谈"),
        ("southcn.com", "南方网"),
        ("gov.cn", "中国政府网"),
    ]:
        if frag in host:
            return name
    return host.replace("www.", "")


def url_date(url: str) -> str:
    m = re.search(r"/(20\d{2})/(\d{4})/", url)
    if m:
        return "%s-%s-%s" % (m.group(1), m.group(2)[:2], m.group(2)[2:])
    m = re.search(r"/(20\d{2})/(\d{2})(\d{2})/", url)
    if m:
        return "%s-%s-%s" % (m.group(1), m.group(2), m.group(3))
    return ""


def _find_container(text: str, markers: list[str]) -> tuple[int, int] | None:
    for marker in markers:
        idx = text.find(marker)
        if idx < 0:
            continue
        start = text.rfind("<", 0, idx)
        while start >= 0 and text.find(">", start, idx) != -1:
            start = text.rfind("<", 0, start)
        if start < 0:
            continue
        end = text.find(">", idx)
        if end < 0:
            continue
        tag_m = re.search(r"<\s*([a-zA-Z0-9]+)", text[start:end + 1])
        if not tag_m:
            continue
        tag = tag_m.group(1)
        depth = 0
        pat = re.compile(r"</?%s[\s>]" % re.escape(tag), re.I)
        for m in pat.finditer(text, end + 1):
            if m.group(0).startswith("</"):
                depth -= 1
                if depth < 0:
                    gt = text.find(">", m.start())
                    return start, (gt + 1 if gt != -1 else m.end())
            else:
                depth += 1
    return None


def _extract_from(body: str) -> tuple[list[str], str]:
    paras = [(m.start(), _clean(m.group(1))) for m in re.finditer(r"<p[^>]*>(.*?)</p>", body, re.S)]
    paras = [(pos, p) for pos, p in paras if len(p) >= 25]
    runs: list[list[tuple[int, str]]] = []
    cur: list[tuple[int, str]] = []
    for pos, p in paras:
        if cur and pos - cur[-1][0] > 2000:
            runs.append(cur)
            cur = []
        cur.append((pos, p))
    if cur:
        runs.append(cur)
    best = max(runs, key=lambda r: sum(len(p) for _, p in r)) if runs else []
    out: list[str] = []
    for _, p in best:
        p = p.strip()
        if len(p) < 25:
            continue
        if NOISE.search(p) and len(p) < 60:
            continue
        if p in out:
            continue
        out.append(p)
    for i, p in enumerate(out):
        if FOOTER_START.search(p):
            out = out[:i]
            break
    return out, "longest-run3"


def _clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s or "")
    s = ihtml.unescape(s)
    s = re.sub(r"\s+", " ", s).replace("\u3000", " ").strip()
    return s


def extract_paragraphs(text: str) -> tuple[list[str], str]:
    t = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
    t = re.sub(r"<style[\s\S]*?</style>", " ", t, flags=re.I)
    t = re.sub(r"<!--[\s\S]*?-->", " ", t)
    container = _find_container(t, CONTAINER_MARKERS)
    if container:
        start, end = container
        paras, method = _extract_from(t[start:end])
        if len(paras) >= 2:
            return paras, "container-markers"
    return _extract_from(t)


def extract_title(text: str, fallback: str) -> str:
    m = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.S)
    if m:
        t = _clean(m.group(1))
        t = re.sub(r"\s*(广东省人民政府门户网站|人民网|南方网|半月谈|中国政府网)\s*$", "", t).strip()
        if t:
            return t
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.S)
    if m:
        t = _clean(m.group(1))
        t = re.sub(r"[_\-|]\s*(人民网|广东省人民政府门户网站|南方网|半月谈|中国政府网).*$", "", t).strip()
        if t:
            return t
    return fallback


def _fetch_retry(url: str, client: httpx.Client | None, tries: int = 3) -> str:
    last: Exception | None = None
    for i in range(tries):
        try:
            return fetch(url, client=client)
        except Exception as e:
            last = e
            if i < tries - 1:
                time.sleep(2 * (i + 1))
    if last is not None:
        raise last
    raise RuntimeError("fetch failed")


def clip_article(url: str, title: str, date: str, *, client: httpx.Client | None = None, allow_single: bool = False) -> dict:
    """抓取并剪藏一篇原文，返回 ClippedArticle 形状的 dict。

    allow_single=True（强制收录，0018）：正文只有 1 段也收录（用于 gd 短讯等边界情况）。
    失败分类（0018）：error 以类别前缀开头——fetch_failed / video_no_text / too_short / parse_error。
    """
    cid = hashlib.md5(url.encode("utf-8")).hexdigest()[:10]
    clip: dict = {
        "id": cid,
        "date": date,
        "title": title,
        "source": source_of(url),
        "url": url,
        "pubDate": url_date(url),
        "fetchedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "status": "error",
        "paragraphs": [],
        "keySentences": [],
    }
    try:
        try:
            text = _fetch_retry(url, client)
        except Exception as exc:
            clip["error"] = f"fetch_failed:{type(exc).__name__}:{str(exc)[:100]}"
            return clip
        paras, method = extract_paragraphs(text)
        if len(paras) == 0:
            clip["error"] = "video_no_text:页面无可提取正文（可能为视频/图集稿）"
            return clip
        if len(paras) < 2 and not allow_single:
            clip["error"] = "too_short:正文提取过短（%d 段）" % len(paras)
            return clip
        clip["title"] = extract_title(text, title)
        clip["status"] = "ok"
        clip["paragraphs"] = paras
    except Exception as e:
        clip["error"] = f"parse_error:{str(e)[:200]}"
    return clip
