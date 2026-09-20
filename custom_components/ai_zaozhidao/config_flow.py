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


def _settings(entry: ConfigEntry) -> dict:
    """生效中的设置：options 覆盖 data（options 是用户改过的那一份）。"""
    return {**entry.data, **(entry.options or {})}


def _normalize(user_input: dict) -> dict:
    """把播客输入统一收敛成 24 位 ID。"""
    values = dict(user_input)
    podcast_id = extract_podcast_id(str(values.get(CONF_PODCAST, "")))
    if podcast_id:
        values[CONF_PODCAST] = podcast_id
    values[CONF_NOTIFY_SERVICE] = (values.get(CONF_NOTIFY_SERVICE) or "").strip()
    values[CONF_NOTIFY_TARGET] = (values.get(CONF_NOTIFY_TARGET) or "").strip()
    return values


def _schema(defaults: dict | None = None) -> vol.Schema:
    d = defaults or {}
    media_player = selector.EntitySelector(
        selector.EntitySelectorConfig(domain="media_player")
    )
    fields: dict = {
        vol.Required(CONF_PODCAST, default=d.get(CONF_PODCAST, DEFAULT_PODCAST)): selector.TextSelector(),
        vol.Required(
            CONF_TITLE_PREFIX, default=d.get(CONF_TITLE_PREFIX, DEFAULT_TITLE_PREFIX)
        ): selector.TextSelector(),
    }
    if d.get(CONF_MEDIA_PLAYER):
        fields[vol.Required(CONF_MEDIA_PLAYER, default=d[CONF_MEDIA_PLAYER])] = media_player
    else:
        fields[vol.Required(CONF_MEDIA_PLAYER)] = media_player
    fields.update(
        {
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
    return vol.Schema(fields)


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
                values = _normalize(user_input)
                await self.async_set_unique_id(f"{DOMAIN}_{values[CONF_PODCAST]}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="AI早知道播客", data=values)

        return self.async_show_form(
            step_id="user", data_schema=_schema(user_input), errors=errors
        )

    async def async_step_reconfigure(self, user_input: dict | None = None) -> FlowResult:
        # 用官方取值器：OptionsFlow 没有 context["entry_id"]，reconfigure 才有
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await _validate(self.hass, user_input)
            if error:
                errors["base"] = error
            else:
                # options 是唯一生效来源，与 data 合并写入，避免两处互相覆盖
                self.hass.config_entries.async_update_entry(
                    entry, options={**(entry.options or {}), **_normalize(user_input)}
                )
                # 不额外 reload：entry 的 update listener 已负责重载
                return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(user_input or _settings(entry)),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "OptionsFlow":
        return OptionsFlow()


class OptionsFlow(config_entries.OptionsFlow):
    """可选项：目标音箱、提醒服务、音量等。"""

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        # 关键：OptionsFlow 的 entry 从 self.config_entry 取，
        # self.context 里没有 entry_id（取它会 KeyError → 前端 500）
        entry = self.config_entry
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await _validate(self.hass, user_input)
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(title="", data=_normalize(user_input))

        return self.async_show_form(
            step_id="init",
            data_schema=_schema(user_input or _settings(entry)),
            errors=errors,
        )
