"""Config flow for AI早知道播客."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AiZaoZhiDaoError, async_fetch_episodes, extract_podcast_id
from .const import (
    CONF_MEDIA_PLAYER,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_TARGET,
    CONF_PODCAST,
    CONF_TITLE_PREFIX,
    CONF_VOLUME,
    DEFAULT_PODCAST,
    DEFAULT_TITLE_PREFIX,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _schema(defaults: dict | None = None, media_player_required: bool = True) -> vol.Schema:
    d = defaults or {}
    media_player = selector.EntitySelector(
        selector.EntitySelectorConfig(domain="media_player")
    )
    podcast_field = (
        vol.Required(CONF_PODCAST, default=d.get(CONF_PODCAST, DEFAULT_PODCAST))
        if media_player_required
        else vol.Optional(CONF_PODCAST, default=d.get(CONF_PODCAST, DEFAULT_PODCAST))
    )
    return vol.Schema(
        {
            podcast_field: selector.TextSelector(),
            vol.Required(
                CONF_TITLE_PREFIX, default=d.get(CONF_TITLE_PREFIX, DEFAULT_TITLE_PREFIX)
            ): selector.TextSelector(),
            vol.Required(CONF_MEDIA_PLAYER, default=d.get(CONF_MEDIA_PLAYER, vol.UNDEFINED)): media_player,
            vol.Optional(
                CONF_NOTIFY_SERVICE, default=d.get(CONF_NOTIFY_SERVICE, "")
            ): selector.TextSelector(),
            vol.Optional(
                CONF_NOTIFY_TARGET, default=d.get(CONF_NOTIFY_TARGET, "")
            ): selector.TextSelector(),
            vol.Optional(
                CONF_VOLUME, default=d.get(CONF_VOLUME, 0)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=1, step=0.01, mode=selector.NumberSelectorMode.BOX
                )
            ),
        }
    )


async def _validate(hass, user_input: dict) -> str | None:
    """抓一次页面确认可达；返回错误 key 或 None。"""
    podcast_id = extract_podcast_id(str(user_input.get(CONF_PODCAST, "")))
    if not podcast_id:
        return "invalid_podcast"
    try:
        episodes = await async_fetch_episodes(async_get_clientsession(hass), podcast_id)
    except AiZaoZhiDaoError as err:
        _LOGGER.warning("配置校验失败: %s", err)
        return "cannot_connect"
    except Exception as err:  # noqa: BLE001
        _LOGGER.exception("配置校验异常: %s", err)
        return "unknown"
    if not episodes:
        return "cannot_connect"
    return None


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        errors: dict[str, str] = {}
        if user_input is not None:
            error = await _validate(self.hass, user_input)
            if error:
                errors["base"] = error
            else:
                podcast_id = extract_podcast_id(str(user_input[CONF_PODCAST]))
                await self.async_set_unique_id(f"{DOMAIN}_{podcast_id}")
                self._abort_if_unique_id_configured()
                data = dict(user_input)
                data[CONF_PODCAST] = podcast_id
                return self.async_create_entry(title="AI早知道播客", data=data)

        return self.async_show_form(
            step_id="user", data_schema=_schema(user_input), errors=errors
        )

    async def async_step_reconfigure(self, user_input: dict | None = None) -> FlowResult:
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="unknown")
        defaults = {**entry.data, **(entry.options or {})}

        errors: dict[str, str] = {}
        if user_input is not None:
            error = await _validate(self.hass, user_input)
            if error:
                errors["base"] = error
            else:
                data = dict(user_input)
                data[CONF_PODCAST] = extract_podcast_id(str(user_input[CONF_PODCAST]))
                self.hass.config_entries.async_update_entry(entry, data=data)
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure", data_schema=_schema(user_input or defaults), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return OptionsFlow()


class OptionsFlow(config_entries.OptionsFlow):
    """可选项：目标音箱、提醒服务、音量等。"""

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="unknown")
        defaults = {**entry.data, **(entry.options or {})}

        errors: dict[str, str] = {}
        if user_input is not None:
            error = await _validate(self.hass, user_input)
            if error:
                errors["base"] = error
            else:
                merged = {**entry.data, **user_input}
                if user_input.get(CONF_PODCAST):
                    merged[CONF_PODCAST] = extract_podcast_id(str(user_input[CONF_PODCAST]))
                return self.async_create_entry(title="", data=merged)

        return self.async_show_form(
            step_id="init", data_schema=_schema(user_input or defaults), errors=errors
        )
