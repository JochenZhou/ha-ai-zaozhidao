"""HTTP client for 小宇宙 podcast pages.

只做纯 HTTP + 解析，不 import homeassistant。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import aiohttp

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120 Safari/537.36"
)

PODCAST_URL = "https://www.xiaoyuzhoufm.com/podcast/{pid}"

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)
_DATE_RE = re.compile(r"(\d{2}-\d{2}-\d{2})")
_PID_RE = re.compile(r"([0-9a-fA-F]{24})")

TIMEOUT = aiohttp.ClientTimeout(total=30)


class AiZaoZhiDaoError(Exception):
    """所有本集成错误的基类 —— 具体异常必须继承它，否则调用点会静默漏掉。"""


class CannotConnect(AiZaoZhiDaoError):
    """网络层失败。"""


class InvalidResponse(AiZaoZhiDaoError):
    """页面结构变化 / 解析失败。"""


@dataclass(slots=True)
class Episode:
    """一期节目。"""

    eid: str
    title: str
    url: str
    duration: int = 0
    pub_date: str = ""

    @property
    def date_key(self) -> str | None:
        """标题里的 YY-MM-DD 日期段。"""
        m = _DATE_RE.search(self.title or "")
        return m.group(1) if m else None


def extract_podcast_id(value: str) -> str | None:
    """从完整 URL 或裸 ID 里取出播客 ID。"""
    if not value:
        return None
    m = _PID_RE.search(value)
    return m.group(1) if m else None


def _iter_episode_dicts(obj):
    if isinstance(obj, dict):
        if "eid" in obj and "title" in obj:
            yield obj
        for value in obj.values():
            yield from _iter_episode_dicts(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _iter_episode_dicts(value)


def _episode_url(raw: dict) -> str | None:
    enclosure = raw.get("enclosure")
    if isinstance(enclosure, dict):
        url = enclosure.get("url")
        if url:
            return str(url)
    media = raw.get("media")
    if isinstance(media, dict):
        source = media.get("source")
        if isinstance(source, dict) and source.get("url"):
            return str(source["url"])
        if media.get("url"):
            return str(media["url"])
    return None


def parse_episodes(html: str) -> list[Episode]:
    """从播客列表页 HTML 解析出全部节目（页面按发布时间倒序）。"""
    match = _NEXT_DATA_RE.search(html or "")
    if not match:
        raise InvalidResponse("页面结构变化：未找到 __NEXT_DATA__")
    try:
        data = json.loads(match.group(1))
    except ValueError as err:
        raise InvalidResponse(f"__NEXT_DATA__ JSON 解析失败: {err}") from err

    episodes: list[Episode] = []
    seen: set[str] = set()
    for raw in _iter_episode_dicts(data):
        eid = raw.get("eid")
        title = raw.get("title")
        if not eid or not title or eid in seen:
            continue
        url = _episode_url(raw)
        if not url:
            continue
        seen.add(eid)
        try:
            duration = int(raw.get("duration") or 0)
        except (TypeError, ValueError):
            duration = 0
        episodes.append(
            Episode(
                eid=str(eid),
                title=str(title),
                url=url,
                duration=duration,
                pub_date=str(raw.get("pubDate") or ""),
            )
        )
    if not episodes:
        raise InvalidResponse("页面结构变化：未解析到任何节目")
    return episodes


async def async_fetch_episodes(session: aiohttp.ClientSession, podcast_id: str) -> list[Episode]:
    """抓取播客列表页并解析。"""
    url = PODCAST_URL.format(pid=podcast_id)
    try:
        async with session.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT) as resp:
            if resp.status != 200:
                raise CannotConnect(f"HTTP {resp.status}")
            html = await resp.text()
    except aiohttp.ClientError as err:
        raise CannotConnect(str(err)) from err
    except TimeoutError as err:
        raise CannotConnect(f"请求超时: {err}") from err
    return parse_episodes(html)
