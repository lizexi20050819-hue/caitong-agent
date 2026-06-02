"""Dimension 17 · A-share 舆情 — 东方财富新闻 + 社交热榜."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import requests

from backend.app.services.fetchers.utils import (
    normalize_code,
    safe_fetch,
    try_ak,
    _HEADERS,
    _TIMEOUT,
)

logger = logging.getLogger(__name__)

_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", ".cache")
os.makedirs(_CACHE_DIR, exist_ok=True)


def fetch_sentiment(ticker: str, stock_name: str = "") -> dict[str, Any]:
    code = normalize_code(ticker)
    return safe_fetch(lambda: _fetch(code, stock_name), default={})


def _fetch(code: str, stock_name: str) -> dict:
    out: dict[str, Any] = {}
    import akshare as ak

    # 1. News
    df_news = try_ak(ak.stock_news_em, symbol=code)
    news = []
    if df_news is not None:
        for _, r in df_news.head(30).iterrows():
            title = str(r.get("标题", r.get("title", "")))
            news.append({
                "title": title[:120],
                "time": str(r.get("发布时间", r.get("pub_time", ""))),
                "sentiment": _simple_sentiment(title),
            })
    out["news"] = news

    # 2. Announcements
    df_ann = try_ak(ak.stock_notice_report, symbol=code)
    announcements = []
    if df_ann is not None and "标题" in df_ann.columns:
        for _, r in df_ann.head(10).iterrows():
            announcements.append({
                "title": str(r["标题"])[:120],
                "date": str(r.get("日期", r.get("公告日期", ""))),
                "type": str(r.get("类型", r.get("公告类型", ""))),
            })
    out["announcements"] = announcements

    # 3. Hot trends
    out["hot_trends"] = _fetch_hot_trends(stock_name)

    # 4. Sentiment score
    pos = sum(1 for n in news if n["sentiment"] == "positive")
    neg = sum(1 for n in news if n["sentiment"] == "negative")
    score = round(pos / (pos + neg) * 100, 1) if (pos + neg) > 0 else 50.0
    out["sentiment_score"] = score
    out["sentiment_verdict"] = "偏乐观" if score >= 60 else "偏悲观" if score <= 40 else "中性"
    out["_status"] = "ok"
    return out


def _simple_sentiment(text: str) -> str:
    pos_words = ["增长", "盈利", "突破", "利好", "增持", "分红", "回购", "中标", "超预期", "创新高", "扭亏"]
    neg_words = ["下跌", "亏损", "减持", "爆雷", "退市", "违规", "处罚", "下滑", "暴跌", "跌停", "风险", "诉讼"]
    p = sum(1 for w in pos_words if w in text)
    n = sum(1 for w in neg_words if w in text)
    return "positive" if p > n else "negative" if n > p else "neutral"


def _fetch_hot_trends(stock_name: str) -> dict:
    if not stock_name:
        return {"hits": 0, "mentions": [], "verdict": "未提供股票名称"}
    mentions = []
    for platform, fetcher in [("weibo", _weibo_hot), ("zhihu", _zhihu_hot),
                               ("baidu", _baidu_hot), ("bilibili", _bilibili_hot)]:
        try:
            for item in fetcher():
                if _match_name(stock_name, item.get("title", "")):
                    mentions.append({"platform": platform, "rank": item.get("rank"),
                                     "title": item["title"][:100]})
        except Exception:
            continue
    return {
        "hits": len(mentions),
        "platforms_checked": 4,
        "mentions": mentions,
        "verdict": "多平台热搜" if len(mentions) >= 3 else "部分平台关注" if mentions else "无热搜提及",
    }


def _match_name(name: str, title: str) -> bool:
    if not name or len(name) < 2:
        return False
    if name in title:
        return True
    if len(name) >= 4 and name[-2:] in title:
        return True
    return False


# ── Hot trend fetchers (5-min file cache) ────────────────────────────────────

def _cached(key: str, fetcher, ttl=300):
    f = os.path.join(_CACHE_DIR, f"hot_{key}.json")
    try:
        if os.path.exists(f) and time.time() - os.stat(f).st_mtime < ttl:
            with open(f, encoding="utf-8") as fh:
                return json.load(fh)
    except Exception:
        pass
    try:
        data = fetcher()
        with open(f, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        return data
    except Exception:
        return []


def _weibo_hot_raw():
    r = requests.get("https://weibo.com/ajax/side/hotSearch", headers=_HEADERS, timeout=_TIMEOUT)
    return [{"rank": i + 1, "title": d.get("word", "")}
            for i, d in enumerate(r.json().get("data", {}).get("realtime", [])[:30])]

def _zhihu_hot_raw():
    r = requests.get("https://www.zhihu.com/api/v3/feed/topstory/hot-list-web?limit=30",
                     headers=_HEADERS, timeout=_TIMEOUT)
    return [{"rank": i + 1, "title": d.get("target", {}).get("title", "")}
            for i, d in enumerate(r.json().get("data", []))]

def _baidu_hot_raw():
    r = requests.get("https://top.baidu.com/board?tab=realtime", headers=_HEADERS, timeout=_TIMEOUT)
    return [{"rank": d.get("index"), "title": d.get("word", "")}
            for d in r.json().get("data", {}).get("cards", [{}])[0].get("content", [])[:30]
            if d.get("word")]

def _bilibili_hot_raw():
    r = requests.get("https://s.search.bilibili.com/main/hotword", headers=_HEADERS, timeout=_TIMEOUT)
    return [{"rank": i + 1, "title": d.get("keyword", "")}
            for i, d in enumerate(r.json().get("list", [])[:30])]


def _weibo_hot():
    return _cached("weibo", _weibo_hot_raw)

def _zhihu_hot():
    return _cached("zhihu", _zhihu_hot_raw)

def _baidu_hot():
    return _cached("baidu", _baidu_hot_raw)

def _bilibili_hot():
    return _cached("bilibili", _bilibili_hot_raw)
