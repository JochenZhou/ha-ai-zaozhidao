"""Sensor entities for AI早知道播客."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AiZaoZhiDaoCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: AiZaoZhiDaoCoordinator = data["coordinator"]
    async_add_entities(
        [
            LatestTitleSensor(coordinator, entry),
            LatestDateSensor(coordinator, entry),
        ]
    )


class _Base(CoordinatorEntity[AiZaoZhiDaoCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: AiZaoZhiDaoCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "AI早知道播客",
            "manufacturer": "小宇宙",
            "model": "播客播放器",
        }


class LatestTitleSensor(_Base):
    """最新一期标题。"""

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "latest_title")

    @property
    def native_value(self) -> str | None:
        return (self.coordinator.data or {}).get("latest_title")

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        cfg = {**self._entry.data, **(self._entry.options or {})}
        return {
            "latest_date": data.get("latest_date"),
            "latest_url": data.get("latest_url"),
            "today_key": data.get("today_key"),
            "today_available": data.get("today_available"),
            "today_url": data.get("today_url"),
            "episode_count": data.get("episode_count"),
            "recent_titles": data.get("recent_titles"),
            "fetched_at": data.get("fetched_at"),
            "target_media_player": cfg.get("media_player"),
        }


class LatestDateSensor(_Base):
    """最新一期日期。"""

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "latest_date")

    @property
    def native_value(self) -> str | None:
        return (self.coordinator.data or {}).get("latest_date")
