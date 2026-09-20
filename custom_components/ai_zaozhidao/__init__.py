"""AI早知道播客 —— 抓取当天最新一期并播放到指定 media_player。"""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import extract_podcast_id
from .const import (
    ATTR_ENTRY_ID,
    ATTR_TITLE,
    CONF_MEDIA_PLAYER,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_TARGET,
    CONF_PODCAST,
    CONF_TITLE_PREFIX,
    CONF_VOLUME,
    DEFAULT_PODCAST,
    DEFAULT_TITLE_PREFIX,
    DOMAIN,
    SERVICE_PLAY,
    SERVICE_REFRESH,
)
from .coordinator import AiZaoZhiDaoCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _merged(entry: ConfigEntry) -> dict:
    return {**entry.data, **(entry.options or {})}


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


def _entries(hass: HomeAssistant, entry_id: str | None = None) -> list[dict]:
    store = hass.data.get(DOMAIN, {})
    if entry_id:
        data = store.get(entry_id)
        return [data] if data else []
    return [v for k, v in store.items() if isinstance(v, dict) and k != "services"]


async def _async_notify(hass: HomeAssistant, data: dict, title: str, message: str) -> None:
    """发提醒：始终留一条持久通知，另按配置调 notify 服务。"""
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {"title": title, "message": message, "notification_id": f"{DOMAIN}_notice"},
        blocking=False,
    )
    service = (data.get("notify_service") or "").strip()
    if not service:
        return
    if "." in service:
        domain, name = service.split(".", 1)
    else:
        domain, name = "notify", service
    payload: dict = {"title": title, "message": message}
    target = (data.get("notify_target") or "").strip()
    if target:
        payload["target"] = target
    try:
        if hass.services.has_service(domain, name):
            await hass.services.async_call(domain, name, payload, blocking=False)
        else:
            _LOGGER.warning("通知服务 %s 不存在，已跳过外部提醒", service)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("调用通知服务 %s 失败: %s", service, err)


async def async_play(
    hass: HomeAssistant,
    data: dict,
    title: str | None = None,
    raise_on_missing: bool = False,
) -> str:
    """播放指定（默认当天）一期；返回结果说明。"""
    coordinator: AiZaoZhiDaoCoordinator = data["coordinator"]
    media_player = data.get("media_player")
    if not media_player:
        raise HomeAssistantError("未配置目标媒体播放器，请在集成选项里设置")

    await coordinator.async_request_refresh()
    target = (title or coordinator.today_key or "").strip()
    episode = coordinator.find_episode(target)

    if episode is None:
        message = f"今天还没有《{coordinator.title_prefix}》（{target}）新一期"
        _LOGGER.info("%s", message)
        await _async_notify(hass, data, coordinator.title_prefix, message)
        if raise_on_missing:
            raise HomeAssistantError(message)
        return message

    volume = data.get("volume") or 0
    if volume and float(volume) > 0:
        await hass.services.async_call(
            "media_player",
            "volume_set",
            {"entity_id": media_player, "volume_level": float(volume)},
            blocking=True,
        )

    await hass.services.async_call(
        "media_player",
        "play_media",
        {
            "entity_id": media_player,
            "media_content_id": episode.url,
            "media_content_type": "music",
        },
        blocking=True,
    )
    _LOGGER.info("已播放 %s -> %s", episode.title, media_player)
    return f"已播放 {episode.title}"


async def _handle_play(call: ServiceCall) -> dict:
    hass = call.hass
    entry_id = call.data.get(ATTR_ENTRY_ID)
    title = call.data.get(ATTR_TITLE)
    targets = _entries(hass, entry_id)
    if not targets:
        raise HomeAssistantError("没有已加载的 AI早知道播客 条目")
    results = []
    for data in targets:
        results.append(await async_play(hass, data, title=title))
    return {"result": "; ".join(results)}


async def _handle_refresh(call: ServiceCall) -> None:
    for data in _entries(call.hass, call.data.get(ATTR_ENTRY_ID)):
        await data["coordinator"].async_request_refresh()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    cfg = _merged(entry)
    podcast_id = extract_podcast_id(str(cfg.get(CONF_PODCAST) or DEFAULT_PODCAST))
    if not podcast_id:
        raise HomeAssistantError(f"播客 ID 无效: {cfg.get(CONF_PODCAST)}")

    session = async_get_clientsession(hass)
    coordinator = AiZaoZhiDaoCoordinator(
        hass,
        entry,
        session,
        podcast_id,
        str(cfg.get(CONF_TITLE_PREFIX) or DEFAULT_TITLE_PREFIX),
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "entry": entry,
        "coordinator": coordinator,
        "media_player": cfg.get(CONF_MEDIA_PLAYER),
        "notify_service": cfg.get(CONF_NOTIFY_SERVICE) or "",
        "notify_target": cfg.get(CONF_NOTIFY_TARGET) or "",
        "volume": cfg.get(CONF_VOLUME) or 0,
    }

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.services.has_service(DOMAIN, SERVICE_PLAY):
        hass.services.async_register(
            DOMAIN,
            SERVICE_PLAY,
            _handle_play,
            schema=vol.Schema(
                {
                    vol.Optional(ATTR_TITLE): cv.string,
                    vol.Optional(ATTR_ENTRY_ID): cv.string,
                }
            ),
            supports_response=SupportsResponse.OPTIONAL,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        hass.services.async_register(
            DOMAIN,
            SERVICE_REFRESH,
            _handle_refresh,
            schema=vol.Schema({vol.Optional(ATTR_ENTRY_ID): cv.string}),
        )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    store = hass.data.get(DOMAIN, {})
    if unload_ok:
        store.pop(entry.entry_id, None)
        if not any(isinstance(v, dict) for k, v in store.items() if k != "services"):
            for service in (SERVICE_PLAY, SERVICE_REFRESH):
                if hass.services.has_service(DOMAIN, service):
                    hass.services.async_remove(DOMAIN, service)
    return unload_ok
