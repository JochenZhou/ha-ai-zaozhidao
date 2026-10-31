"""AI早知道播客 —— 抓取当天最新一期并播放到指定 media_player。"""

from __future__ import annotations

import logging
from pathlib import Path

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
    CONF_BASE_URL,
    CONF_MEDIA_PLAYER,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_TARGET,
    CONF_PODCAST,
    CONF_RINGTONE_ENABLED,
    CONF_RINGTONE_FILE,
    CONF_SPEED,
    CONF_TITLE_PREFIX,
    CONF_VOLUME,
    DEFAULT_PODCAST,
    DEFAULT_RINGTONE_ENABLED,
    DEFAULT_RINGTONE_FILE,
    DEFAULT_SPEED,
    DEFAULT_TITLE_PREFIX,
    DOMAIN,
    SERVICE_PLAY,
    SERVICE_REFRESH,
)
from .coordinator import AiZaoZhiDaoCoordinator
from .processor import ProcessError, build_processed_audio, cleanup_expired, ringtone_asset_path

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


def _url_from_adapters(hass: HomeAssistant) -> str | None:
    """按网卡 IPv4 推断 HA 地址（无 internal_url 时的兜底）。"""
    try:
        from homeassistant.helpers import network

        adapters = network.async_get_adapters(hass)
    except Exception:  # noqa: BLE001
        return None
    port = getattr(hass.http, "server_port", 8123)
    suffix = "" if port in (80, 443) else f":{port}"

    def _first_ip(adapter: dict) -> str | None:
        for ip_info in adapter.get("ipv4", []):
            address = ip_info.get("address")
            if not address:
                continue
            if address.startswith(("127.", "169.254.")):
                continue
            # 跳过 docker 默认网桥段，播放器访问不到
            if address.startswith(("172.17.", "172.18.", "172.19.")):
                continue
            return address
        return None

    usable = [a for a in adapters if a.get("enabled", True)]
    # 先默认路由网卡，再其他
    for group in ([a for a in usable if a.get("default")], usable):
        for adapter in group:
            address = _first_ip(adapter)
            if address:
                return f"http://{address}{suffix}"
    return None


def _url_from_socket(hass: HomeAssistant) -> str | None:
    """最后兜底：取本机出网网卡 IP（UDP connect 不发包）。"""
    import socket

    port = getattr(hass.http, "server_port", 8123)
    suffix = "" if port in (80, 443) else f":{port}"
    for target in (("8.8.8.8", 80), ("223.5.5.5", 80), ("192.168.1.1", 80)):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(0.2)
            sock.connect(target)
            address = sock.getsockname()[0]
            if address and not address.startswith(("127.", "0.0.0.0")):
                return f"http://{address}{suffix}"
        except OSError:
            continue
        finally:
            sock.close()
    return None


def _base_url(hass: HomeAssistant, data: dict) -> str:
    """播放器可访问的 HA 地址：手填 > HA 配置 > 自动探测 > 网卡 IP。"""
    custom = str(data.get(CONF_BASE_URL) or "").strip()
    if custom:
        return custom.rstrip("/")
    for attr in ("internal_url", "external_url"):
        value = getattr(hass.config, attr, None)
        if value:
            return str(value).rstrip("/")
    try:
        from homeassistant.helpers.network import get_url

        return get_url(hass, allow_ip=True, allow_cloud=False, prefer_internal=True).rstrip("/")
    except Exception:  # noqa: BLE001
        pass
    guessed = _url_from_adapters(hass)
    if guessed:
        return guessed
    guessed = _url_from_socket(hass)
    if guessed:
        return guessed
    raise HomeAssistantError(
        "无法确定 HA 的访问地址，请在集成选项里填写「服务地址」，如 http://192.168.101.75"
    )


async def _resolve_media_url(hass: HomeAssistant, data: dict, episode) -> str:
    """按配置决定播放地址：开了铃声/变速就先合成，否则直接用源 URL。"""
    ringtone_enabled = bool(data.get(CONF_RINGTONE_ENABLED, DEFAULT_RINGTONE_ENABLED))
    speed = float(data.get(CONF_SPEED) or DEFAULT_SPEED)
    ringtone_path: Path | None = None
    if ringtone_enabled:
        custom = str(data.get(CONF_RINGTONE_FILE) or "").strip()
        if custom:
            ringtone_path = Path(custom)
            if not ringtone_path.is_file():
                raise HomeAssistantError(f"自定义铃声文件不存在: {custom}")
        else:
            ringtone_path = ringtone_asset_path()
            if not ringtone_path.is_file():
                raise HomeAssistantError(f"集成自带铃声缺失: {ringtone_path}")

    if ringtone_path is None and abs(speed - 1.0) <= 1e-6:
        return episode.url

    try:
        rel_url = await build_processed_audio(
            hass,
            episode.url,
            ringtone_path=ringtone_path,
            speed=speed,
            title=episode.title,
        )
    except ProcessError as err:
        raise HomeAssistantError(f"音频合成失败: {err}") from err

    # 播放器拿不到相对路径，必须给绝对地址
    if rel_url.startswith("/"):
        return f"{_base_url(hass, data)}{rel_url}"
    return rel_url


def player_problem(hass: HomeAssistant, media_player: str, title: str = "") -> str | None:
    """目标播放器不可播时返回原因；可播返回 None。"""
    state = hass.states.get(media_player)
    if state is None:
        return f"目标播放器 {media_player} 不存在，请在集成选项里重新选择"
    if state.state in ("unavailable", "unknown"):
        suffix = f"，本次未播放《{title}》" if title else "，本次未播放"
        return f"目标播放器 {media_player} 当前不可用（{state.state}）{suffix}"
    return None


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

    # 目标播放器不可用时播放会静默失败，必须提前拦住并提醒
    problem = player_problem(hass, media_player, episode.title)
    if problem:
        _LOGGER.warning("%s", problem)
        await _async_notify(hass, data, coordinator.title_prefix, problem)
        if raise_on_missing:
            raise HomeAssistantError(problem)
        return problem

    media_url = await _resolve_media_url(hass, data, episode)

    volume = data.get("volume") or 0
    if volume and float(volume) > 0:
        await hass.services.async_call(
            "media_player",
            "volume_set",
            {"entity_id": media_player, "volume_level": float(volume)},
            blocking=True,
        )

    try:
        await hass.services.async_call(
            "media_player",
            "play_media",
            {
                "entity_id": media_player,
                "media_content_id": media_url,
                "media_content_type": "music",
            },
            blocking=True,
        )
    except Exception as err:  # noqa: BLE001
        message = f"播放失败：{media_player} 拒绝播放（{err}）"
        _LOGGER.warning("%s", message)
        await _async_notify(hass, data, coordinator.title_prefix, message)
        raise HomeAssistantError(message) from err

    _LOGGER.info("已播放 %s -> %s (%s)", episode.title, media_player, media_url)
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
        CONF_RINGTONE_ENABLED: bool(cfg.get(CONF_RINGTONE_ENABLED, DEFAULT_RINGTONE_ENABLED)),
        CONF_RINGTONE_FILE: cfg.get(CONF_RINGTONE_FILE) or DEFAULT_RINGTONE_FILE,
        CONF_SPEED: float(cfg.get(CONF_SPEED) or DEFAULT_SPEED),
        CONF_BASE_URL: (cfg.get(CONF_BASE_URL) or "").strip(),
    }

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # 启动时清理过期的合成音频（保留 1 天）；仅 stat 扫描，直接执行不阻塞
    await hass.async_add_executor_job(cleanup_expired, hass)

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
