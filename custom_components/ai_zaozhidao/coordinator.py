"""Coordinator for AI早知道播客."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AiZaoZhiDaoError, Episode, async_fetch_episodes
from .const import DEFAULT_SCAN_INTERVAL_MINUTES, DOMAIN

_LOGGER = logging.getLogger(__name__)

# 写进实体属性的节目条数上限（属性会被序列化进每一次 state_changed）
MAX_EPISODES_IN_ATTRS = 5


class AiZaoZhiDaoCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """轮询播客列表页，算出「最新一期」与「今天那一期」。"""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        session,
        podcast_id: str,
        title_prefix: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=DEFAULT_SCAN_INTERVAL_MINUTES),
        )
        self.entry = entry
        self.session = session
        self.podcast_id = podcast_id
        self.title_prefix = title_prefix
        # 最近一次成功解析出的节目（供 service 立即使用，无需等下一轮）
        self.episodes: list[Episode] = []

    @property
    def today_key(self) -> str:
        """当天应匹配的标题，如 AI早知道-26-09-20。"""
        return f"{self.title_prefix}-{dt_util.now().strftime('%y-%m-%d')}"

    def find_episode(self, title: str | None = None) -> Episode | None:
        """按精确标题查节目；title 为空时用当天标题。"""
        target = title or self.today_key
        if not target:
            return None
        for ep in self.episodes:
            if ep.title == target:
                return ep
        return None

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            episodes = await async_fetch_episodes(self.session, self.podcast_id)
        except AiZaoZhiDaoError as err:
            raise UpdateFailed(str(err)) from err

        self.episodes = episodes
        today_key = self.today_key
        today_ep = self.find_episode(today_key)
        latest = episodes[0] if episodes else None
        return {
            "latest": latest,
            "latest_title": latest.title if latest else None,
            "latest_date": latest.date_key if latest else None,
            "latest_url": latest.url if latest else None,
            "today_key": today_key,
            "today_available": today_ep is not None,
            "today_title": today_ep.title if today_ep else None,
            "today_url": today_ep.url if today_ep else None,
            "episode_count": len(episodes),
            "fetched_at": dt_util.now().isoformat(),
            "recent_titles": [e.title for e in episodes[:MAX_EPISODES_IN_ATTRS]],
        }
