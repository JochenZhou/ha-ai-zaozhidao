"""Binary sensor: 今天那期是否已发布。"""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
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
    async_add_entities([TodayAvailableBinarySensor(data["coordinator"], entry)])


class TodayAvailableBinarySensor(
    CoordinatorEntity[AiZaoZhiDaoCoordinator], BinarySensorEntity
):
    _attr_has_entity_name = True

    def __init__(self, coordinator: AiZaoZhiDaoCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_translation_key = "today_available"
        self._attr_unique_id = f"{entry.entry_id}_today_available"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "AI早知道播客",
            "manufacturer": "小宇宙",
            "model": "播客播放器",
        }

    @property
    def is_on(self) -> bool:
        return bool((self.coordinator.data or {}).get("today_available"))

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {"today_key": data.get("today_key"), "today_title": data.get("today_title")}
