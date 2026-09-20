"""Button: 手动播放当天那一期。"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import async_play
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PlayTodayButton(data, entry)])


class PlayTodayButton(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, data: dict, entry: ConfigEntry) -> None:
        self._data = data
        self._entry = entry
        self._attr_translation_key = "play_today"
        self._attr_unique_id = f"{entry.entry_id}_play_today"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "AI早知道播客",
            "manufacturer": "小宇宙",
            "model": "播客播放器",
        }

    async def async_press(self) -> None:
        await async_play(self.hass, self._data)
