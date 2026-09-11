# -*- coding: utf-8 -*-
"""选材漏斗：粗筛 / 评级与主线 / 槽位 / 下限补剧。"""
import datetime as dt
import json

from kaogong.curation import assign_grades, assign_slots, authority_rank, build_picks, coarse_filter

TARGET = dt.date(2026, 8, 22)
LINES = [{"id": "fifteen-five-plan", "name": "十五五规划建议", "status": "active"},
         {"id": "govt-work-report-2026", "name": "2026 年政府工作报告", "status": "active"}]


def _article(aid, title, source="新华网", date="2026-08-22", ann_count=3, pub="2026-08-22"):
    return {
        "id": aid, "title": title, "source": source, "date": date, "pubDate": pub,
        "aiStatus": "ok", "paragraphs": ["正文内容。" * 3], "keySentences": [],
        "aiAnnotations": [{"id": f"ai-{aid}-{i}", "paragraphIndex": 0, "start": 0, "end": 4,
                           "text": "正文内容", "type": "viewpoint"} for i in range(ann_count)],
    }


def _payload(items):
    return json.dumps({"items": items}, ensure_ascii=False)


def _call(items):
    def _stub(*_a, **_kw):
        return _payload(items)
    return _stub


def test_authority_rank():
    assert authority_rank("人民网") == 1.0
    assert authority_rank("广东省人民政府网") == 0.7
    assert authority_rank("sichuan.scol.com.cn") == 0.4


def test_coarse_filter_drops_old_dupe_and_failed():
    pool = [
        _article("a1", "全国铁路投资创新高", pub="2026-08-22"),
        _article("a2", "全国铁路投资创新高！", pub="2026-08-22"),          # 标题签名重复 → 丢
        _article("a3", "三天前的旧闻", pub="2026-08-19"),                  # 超 1 天 → 丢
        _article("a4", "AI 失败文章", pub="2026-08-22"),                   # aiStatus 覆盖
    ]
    pool[3]["aiStatus"] = "error"
    kept = coarse_filter(pool, TARGET)
    assert [a["id"] for a in kept] == ["a1"]


def test_assign_grades_uses_model_and_validates_line():
    articles = [_article("a1", "学习时报评论：敬畏历史", source="学习时报"),
                _article("a2", "全国统一大市场建设方案", source="中国政府网")]
    graded = assign_grades(articles, LINES, {"deepseek_api_key": "k"}, call=_call([
        {"index": 0, "grade": "S", "policyLine": "fifteen-five-plan", "reason": "权威源"},
        {"index": 1, "grade": "A", "policyLine": "不存在的线", "reason": "文件类"},
    ]))
    assert graded[0]["grade"] == "S" and graded[0]["policyLine"] == "fifteen-five-plan"
    assert graded[1]["policyLine"] is None  # 非法主线 id 归 None


def test_assign_grades_falls_back_without_key():
    graded = assign_grades([_article("a1", "某文章")], [], {})
    assert graded[0]["grade"] in ("A", "B")


def test_assign_slots_structure():
    articles = [
        _article("h", "某头版要闻", source="人民网", ann_count=6),                       # 头版候选
        _article("e1", "学习时报评论：敬畏历史", source="学习时报"),                        # essay
        _article("e2", "南方网评：把饭碗端牢", source="南方网"),                            # essay
        _article("x", "国务院关于《特殊教育发展提升十五五行动计划》的批复", source="中国政府网"),  # file
        _article("n", "普通社会新闻", source="news.cn", ann_count=1),
    ]
    graded = assign_grades(articles, LINES, {"deepseek_api_key": "k"}, call=_call([
        {"index": 0, "grade": "S", "policyLine": None, "reason": "头版"},
        {"index": 1, "grade": "A", "policyLine": "fifteen-five-plan", "reason": "评论"},
        {"index": 2, "grade": "B", "policyLine": "fifteen-five-plan", "reason": "评论"},
        {"index": 3, "grade": "A", "policyLine": "fifteen-five-plan", "reason": "文件"},
        {"index": 4, "grade": "C", "policyLine": None, "reason": "普通"},
    ]))
    slots = assign_slots(graded)
    assert slots["headline"] == "h"            # 头版可无主线
    assert set(slots["essay"]) == {"e1", "e2"}
    assert slots["exam"] == "x"
    assert slots["extra"] is None              # 无剩余绑主线且不同主线者
    assert len(slots["picked"]) == 4


def test_build_picks_supplements_from_history():
    articles = [_article("a1", "普通文章", source="news.cn", ann_count=1)]  # 粗筛后仅 1 篇
    history = [_article("old1", "历史好文", source="人民网", date="2026-08-20", pub="2026-08-20", ann_count=8)]
    picks = build_picks(articles, LINES, {"deepseek_api_key": "k"}, target=TARGET,
                        call=_call([{"index": 0, "grade": "B", "policyLine": None, "reason": "普通"}]),
                        history=history)
    assert "a1" in picks["picked"] and "old1" in picks["picked"]  # 下限 2：历史补剧


def test_curate_content_end_to_end(tmp_path):
    """集成：picks 写出、文章回写 aiCards/aiRelations/policyLine、每日配额生效。"""
    import json

    from kaogong.curation import curate_content

    day = TARGET.isoformat()
    (tmp_path / day).mkdir(parents=True)
    (tmp_path / "policy-lines.json").write_text(json.dumps({"lines": LINES}), encoding="utf-8")
    article = _article("a1", "全民医保十五五规划来了", source="中国政府网")
    article["paragraphs"] = ["8月19日，国家医保局印发《全民医疗保障十五五规划》。"]
    article["aiAnnotations"] = [
        {"id": "ai-0-0-12-viewpoint", "paragraphIndex": 0, "start": 0, "end": 12, "text": "8月19日，国家医保局印发《全民医疗保障十五五规划》。", "type": "viewpoint"},
    ]
    (tmp_path / day / "article-a1.json").write_text(json.dumps(article), encoding="utf-8")

    def _stub(messages, _cfg, **_kw):
        system = messages[0]["content"]
        if "必记考点卡片" in system:
            return json.dumps({"cards": [{
                "question": "规划提出的多层次医疗保障体系特征是什么？",
                "answer": "覆盖全民、统筹城乡、公平统一、安全规范、可持续。",
                "tags": ["定位"],
                "anchor": {"paragraphIndex": 0, "sentence": "国家医保局印发《全民医疗保障十五五规划》。"},
            }]}, ensure_ascii=False)
        if "关系标注" in system:
            return json.dumps({"relations": [{
                "paragraphIndex": 0, "anchor": "ai-0-0-12-viewpoint",
                "points": [{"annotationId": "ai-0-0-12-viewpoint", "kind": "support"}], "kind": "support",
            }]}, ensure_ascii=False)
        return json.dumps({"items": [{"index": 0, "grade": "A", "policyLine": "fifteen-five-plan", "reason": "测试"}]}, ensure_ascii=False)

    report = curate_content(TARGET, tmp_path, {"deepseek_api_key": "k"}, call=_stub)
    picks = json.loads((tmp_path / day / "picks.json").read_text(encoding="utf-8"))
    assert picks["picked"] == ["a1"]
    saved = json.loads((tmp_path / day / "article-a1.json").read_text(encoding="utf-8"))
    assert saved["policyLine"] == "fifteen-five-plan"
    assert saved["aiCards"] and saved["aiCards"][0]["question"]
    assert report["curation"]["cardsProduced"] == 1
    assert (tmp_path / day / "article-a1.json").exists()


def test_card_budget_is_distributed_not_first_come():
    """回归防护：每日卡片配额必须按篇数分配，不能让第一篇吃掉全部。

    原实现 `budget = 每日上限 - 已用`（先到先得）下，2 篇被选中时第二篇预算为 0
    —— 等于"选了它却不给它产出"。实测在 2026-08-21 上真的发生了：
    跑出 5 张卡却只落在第 1 篇文章上，第 2 篇一张没有。
    """
    from kaogong.curation import card_budget_for

    # 两篇被选中：5 张按 3 + 2 分配（靠前的槽位略多）
    quota = 5
    picked = 2
    granted = []
    for index in range(picked):
        got = card_budget_for(quota, picked - index)
        granted.append(got)
        quota -= got
    assert granted == [3, 2]
    assert all(b >= 1 for b in granted), f"每篇都应分到额度，实际 {granted}"
    assert sum(granted) <= 5, f"总产出不应超过每日上限，实际 {granted}"

    # 单篇：拿满
    assert card_budget_for(5, 1) == 5
    # 额度刚好够每篇一张
    assert card_budget_for(2, 2) == 1
    assert card_budget_for(1, 3) == 1
    # 额度耗尽：不再产出（而不是负数）
    assert card_budget_for(0, 3) == 0
    # 篇数为 0：不会除零
    assert card_budget_for(5, 0) == 5


def test_curate_content_degrades_without_key(tmp_path):
    """无 key：仍产出 picks.json，卡片/关系标记 error，不抛异常（与管道降级哲学一致）。"""
    import json

    from kaogong.curation import curate_content

    day = TARGET.isoformat()
    (tmp_path / day).mkdir(parents=True)
    article = _article("a1", "某文章", source="新华网")
    (tmp_path / day / "article-a1.json").write_text(json.dumps(article), encoding="utf-8")
    report = curate_content(TARGET, tmp_path, {})
    assert (tmp_path / day / "picks.json").exists()
    assert report["curation"]["cardErrors"] >= 0


def test_load_lines_only_active(tmp_path):
    import json

    from kaogong.curation import _load_lines

    (tmp_path / "policy-lines.json").write_text(json.dumps({
        "lines": [
            {"id": "a", "name": "A", "status": "active"},
            {"id": "b", "name": "B", "status": "archived"},
        ]
    }), encoding="utf-8")
    lines = _load_lines(tmp_path)
    assert [p["id"] for p in lines] == ["a"]
