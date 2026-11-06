"""播客播完后，用 Music Assistant 随机续播音乐。

只依赖 MA 的 HA 服务，不需要 MA token：
  music_assistant.get_library(media_type=track, order_by=random)
  music_assistant.play_media(media_id=<uri>, media_type=track, enqueue=play/add)
"""

from __future__ import annotations

import logging

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

_LOGGER = logging.getLogger(__name__)

MA_DOMAIN = "music_assistant"
# 播到 80% 以上才算「正常播完」，手动提前停止不续播
MIN_PLAY_RATIO = 0.8
# 监听器最长存活时间，防止永远挂着
WATCH_MAX_SECONDS = 4 * 3600
STOP_STATES = ("idle", "off")


def should_continue(old_state: str, new_state: str, elapsed: float, expected: float) -> bool:
    """是否为「正常播完」：playing → idle/off，且已播够 80%。"""
    if new_state not in STOP_STATES or old_state != "playing":
        return False
    if expected > 0 and elapsed < expected * MIN_PLAY_RATIO:
        return False
    return True


def _pick_uris(items: list[dict], count: int) -> list[str]:
    """从 get_library 结果里取曲目 uri。"""
    uris: list[str] = []
    for item in items or []:
        uri = item.get("uri")
        if uri:
            uris.append(str(uri))
        if len(uris) >= count:
            break
    return uris


async def async_play_random_tracks(
    hass: HomeAssistant, count: int, target: str
) -> str:
    """MA 随机取 count 首曲目并播放到 target；返回结果说明。"""
    if not hass.services.has_service(MA_DOMAIN, "get_library"):
        raise HomeAssistantError(
            "没找到 Music Assistant 的 get_library 服务，请确认 MA 集成已安装并加载"
        )
    count = max(1, int(count or 1))
    try:
        response = await hass.services.async_call(
            MA_DOMAIN,
            "get_library",
            {"media_type": "track", "limit": count, "order_by": "random"},
            blocking=True,
            return_response=True,
        )
    except Exception as err:  # noqa: BLE001
        raise HomeAssistantError(f"MA 取随机曲目失败（{err}）") from err

    items = []
    if isinstance(response, dict):
        items = response.get("items") or []
    uris = _pick_uris(items, count)
    if not uris:
        raise HomeAssistantError("MA 曲库没有可用曲目，无法续播")

    for index, uri in enumerate(uris):
        await hass.services.async_call(
            MA_DOMAIN,
            "play_media",
            {
                "media_id": uri,
                "media_type": "track",
                "enqueue": "play" if index == 0 else "add",
            },
            target={"entity_id": target},
            blocking=True,
        )
    _LOGGER.info("已续播 %s 首随机音乐 -> %s", len(uris), target)
    return f"已续播 {len(uris)} 首随机音乐"


class ContinueMusicWatcher:
    """盯住一次播客播放，播完就触发续播。"""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        entity_id: str,
        media_content_id: str,
        expected_duration: float,
        count: int,
        target: str,
        notify,
    ) -> None:
        self.hass = hass
        self._entity_id = entity_id
        self._media_content_id = media_content_id
        self._expected = float(expected_duration or 0)
        self._count = count
        self._target = target
        self._notify = notify
        self._started = hass.loop.time()
        self._unsub = None
        self._unsub_timeout = None
        self._done = False

    @property
    def entity_id(self) -> str:
        return self._entity_id

    @callback
    def async_start(self) -> None:
        """开始监听（播放成功之后调用）。"""
        self._unsub = async_track_state_change_event(
            self.hass, [self._entity_id], self._handle_change
        )
        self._unsub_timeout = async_call_later(
            self.hass, WATCH_MAX_SECONDS, self._handle_timeout
        )

    @callback
    def async_stop(self) -> None:
        """注销监听。"""
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        if self._unsub_timeout is not None:
            self._unsub_timeout()
            self._unsub_timeout = None

    def _expected_seconds(self, new_state) -> float:
        """优先用播放器自报的 media_duration，其次用抓到的单集时长。"""
        duration = (new_state.attributes or {}).get("media_duration") if new_state else None
        try:
            duration = float(duration)
        except (TypeError, ValueError):
            duration = 0.0
        return duration if duration > 0 else self._expected

    @callback
    def _handle_change(self, event: Event) -> None:
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if new_state is None or self._done:
            return

        # 用户中途换成了别的媒体 → 我们自动退出，不打扰
        current = (new_state.attributes or {}).get("media_content_id")
        if (
            new_state.state == "playing"
            and current
            and self._media_content_id
            and current != self._media_content_id
        ):
            _LOGGER.debug("播放器已切到其他媒体，取消续播监听: %s", current)
            self._done = True
            self.async_stop()
            return

        old_value = old_state.state if old_state else ""
        elapsed = self.hass.loop.time() - self._started
        if not should_continue(old_value, new_state.state, elapsed, self._expected_seconds(new_state)):
            return

        self._done = True
        self.async_stop()
        self.hass.async_create_task(self._run())

    @callback
    def _handle_timeout(self, _now) -> None:
        if not self._done:
            self._done = True
            self.async_stop()
            _LOGGER.debug("续播监听超时，已注销: %s", self._entity_id)

    async def _run(self) -> None:
        try:
            message = await async_play_random_tracks(self.hass, self._count, self._target)
        except Exception as err:  # noqa: BLE001
            message = f"播客已播完，但随机音乐续播失败：{err}"
            _LOGGER.warning("%s", message)
            await self._notify(message)
            return
        _LOGGER.info("%s", message)
        await self._notify(message)
