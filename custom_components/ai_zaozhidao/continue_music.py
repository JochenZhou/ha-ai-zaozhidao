"""播客播完后，用 Music Assistant 随机续播音乐。

只依赖 MA 的 HA 服务，不需要 MA token：
  music_assistant.get_library(media_type=track, order_by=random, limit=N)
  music_assistant.play_media(media_id=<uri>, media_type=track, enqueue=play/add)
"""

from __future__ import annotations

import logging
from urllib.parse import unquote, urlsplit

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

_LOGGER = logging.getLogger(__name__)

MA_DOMAIN = "music_assistant"
# 播到 80% 以上才算「正常播完」，手动提前停止不续播
MIN_PLAY_RATIO = 0.8
# 播放器在结尾自动暂停（不落到 idle）时，允许从 paused 判定为播完
END_PAUSE_RATIO = 0.98
# 监听器最长存活时间，防止永远挂着
WATCH_MAX_SECONDS = 4 * 3600
STOP_STATES = ("idle", "off")
PLAY_STATES = ("playing",)
# MA 会把播放地址包一层内置前缀，比较时要剥掉
BUILTIN_PREFIXES = (
    "builtin://sound_effect/",
    "builtin://play_media/",
    "builtin://announcement/",
    "builtin://",
)


def _normalize_media_id(value: str | None) -> str:
    """把播放器回传的 media_content_id 归一化，便于和原始地址比较。"""
    if not value:
        return ""
    text = str(value).strip()
    # MA/DLNA 可能对 URL 再编码一次，反复解码到稳定
    for _ in range(3):
        decoded = unquote(text)
        if decoded == text:
            break
        text = decoded
    lowered = text.lower()
    for prefix in BUILTIN_PREFIXES:
        if lowered.startswith(prefix):
            text = text[len(prefix) :]
            break
    return text.strip().rstrip("/")


def _basename(value: str) -> str:
    """取路径最后一段（不含查询串）。"""
    try:
        return urlsplit(value).path.rsplit("/", 1)[-1]
    except ValueError:
        return value.rsplit("/", 1)[-1]


def same_media(current: str | None, expected: str | None) -> bool:
    """播放器上的当前媒体是不是我们放的那一期。

    MA 会把 `http://ha/local/x.m4a` 记成
    `builtin://sound_effect/http://ha/local/x.m4a`，还可能二次百分号编码，
    所以先用归一化后的完整地址比，再退回文件名比。
    """
    left, right = _normalize_media_id(current), _normalize_media_id(expected)
    if not left or not right:
        # 一方没有信息时不要误判成「换了媒体」
        return True
    if left == right or left.endswith(right) or right.endswith(left):
        return True
    left_name, right_name = _basename(left), _basename(right)
    return bool(left_name) and left_name == right_name


def should_continue(
    old_state: str,
    new_state: str,
    elapsed: float,
    expected: float,
    position: float = 0.0,
    *,
    end_pause: bool = False,
) -> bool:
    """是否为「正常播完」：playing → idle/off，且已播够 80%。

    播放器在结尾可能直接暂停（不落到 idle），这算暂停式播完（end_pause）；
    暂停在结尾之后被关掉（paused → idle）也算，但要求位置已在 98% 以上。
    """
    played = max(elapsed, position or 0.0)
    near_end = expected > 0 and played >= expected * END_PAUSE_RATIO

    if new_state == "paused":
        return bool(end_pause and near_end)
    if new_state not in STOP_STATES:
        return False
    if old_state not in PLAY_STATES and not (old_state == "paused" and near_end):
        return False
    if expected <= 0:
        return True
    return played >= expected * MIN_PLAY_RATIO


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


def _library_items(response) -> list[dict]:
    """兼容 MA 不同版本的返回结构：{items: []} 或 {response: {items: []}}。"""
    if not isinstance(response, dict):
        return []
    if isinstance(response.get("items"), list):
        return response["items"]
    inner = response.get("response")
    if isinstance(inner, dict) and isinstance(inner.get("items"), list):
        return inner["items"]
    return []


def _ma_entry_id(hass: HomeAssistant) -> str | None:
    """MA 2.x 的 get_library 需要 config_entry_id，取一个已加载的条目。"""
    entries = hass.config_entries.async_entries(MA_DOMAIN)
    for entry in entries:
        if entry.state is ConfigEntryState.LOADED:
            return entry.entry_id
    return entries[0].entry_id if entries else None


async def _get_random_tracks(hass: HomeAssistant, count: int) -> list[dict]:
    """调 MA 取 count 首随机曲目。"""
    if not hass.services.has_service(MA_DOMAIN, "get_library"):
        raise HomeAssistantError(
            "没找到 Music Assistant 的 get_library 服务，请确认 MA 集成已安装并加载"
        )
    base = {"media_type": "track", "limit": count, "order_by": "random"}
    entry_id = _ma_entry_id(hass)
    payloads = [{**base, "config_entry_id": entry_id}] if entry_id else []
    payloads.append(base)  # 老版本 MA 不认 config_entry_id，回退一次

    last_error: Exception | None = None
    for payload in payloads:
        try:
            response = await hass.services.async_call(
                MA_DOMAIN, "get_library", payload, blocking=True, return_response=True
            )
        except Exception as err:  # noqa: BLE001
            last_error = err
            continue
        items = _library_items(response)
        if items:
            return items
    if last_error is not None:
        raise HomeAssistantError(f"MA 取随机曲目失败（{last_error}）") from last_error
    raise HomeAssistantError("MA 曲库没有可用曲目，无法续播")


async def async_play_random_tracks(
    hass: HomeAssistant, count: int, target: str
) -> str:
    """MA 随机取 count 首曲目并播放到 target；返回结果说明。"""
    count = max(1, int(count or 1))
    items = await _get_random_tracks(hass, count)
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
        on_change=None,
    ) -> None:
        self.hass = hass
        self._entity_id = entity_id
        self._media_content_id = media_content_id
        self._expected = float(expected_duration or 0)
        self._count = count
        self._target = target
        self._notify = notify
        self._on_change = on_change
        self._started = hass.loop.time()
        self._unsub = None
        self._unsub_timeout = None
        self._done = False
        self._seen_own = False

    def _notify_change(self) -> None:
        """告诉上层「监听状态变了」，便于诊断属性实时刷新。"""
        if self._on_change is None:
            return
        try:
            self._on_change()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("续播监听状态回调失败", exc_info=True)

    @property
    def entity_id(self) -> str:
        return self._entity_id

    @property
    def media_content_id(self) -> str:
        return self._media_content_id

    @property
    def is_done(self) -> bool:
        """监听是否已经结束（触发过或超时）。"""
        return self._done

    @callback
    def async_start(self) -> None:
        """开始监听（播放成功之后调用）。"""
        self._unsub = async_track_state_change_event(
            self.hass, [self._entity_id], self._handle_change
        )
        self._unsub_timeout = async_call_later(
            self.hass, WATCH_MAX_SECONDS, self._handle_timeout
        )
        self._notify_change()

    @callback
    def async_stop(self) -> None:
        """注销监听。"""
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        if self._unsub_timeout is not None:
            self._unsub_timeout()
            self._unsub_timeout = None
        self._notify_change()

    def _expected_seconds(self, new_state) -> float:
        """优先用播放器自报的 media_duration，其次用抓到的单集时长。"""
        duration = (new_state.attributes or {}).get("media_duration") if new_state else None
        try:
            duration = float(duration)
        except (TypeError, ValueError):
            duration = 0.0
        return duration if duration > 0 else self._expected

    def _position(self, new_state) -> float:
        try:
            return float((new_state.attributes or {}).get("media_position") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @callback
    def _handle_change(self, event: Event) -> None:
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        if new_state is None or self._done:
            return

        current = (new_state.attributes or {}).get("media_content_id")
        if new_state.state in PLAY_STATES:
            if same_media(current, self._media_content_id):
                self._seen_own = True
            elif self._seen_own:
                # 我们那一期确实播过，现在换成了别的媒体 → 自动退出，不打扰
                _LOGGER.info(
                    "播放器已切到其他媒体，取消续播监听: %s -> %s",
                    self._media_content_id,
                    current,
                )
                self._done = True
                self.async_stop()
                return

        old_value = old_state.state if old_state else ""
        elapsed = self.hass.loop.time() - self._started
        expected = self._expected_seconds(new_state)
        position = self._position(new_state)
        end_pause = (
            new_state.state == "paused"
            and expected > 0
            and position >= expected * END_PAUSE_RATIO
        )
        if not should_continue(
            old_value,
            new_state.state,
            elapsed,
            expected,
            position,
            end_pause=end_pause,
        ):
            return

        _LOGGER.info(
            "播客已播完（%ss/%ss），开始续播随机音乐 -> %s",
            int(max(elapsed, position)),
            int(expected),
            self._target,
        )
        self._done = True
        self.async_stop()
        self.hass.async_create_task(self._run())

    @callback
    def _handle_timeout(self, _now) -> None:
        if not self._done:
            self._done = True
            self.async_stop()
            _LOGGER.info("续播监听已超时（4 小时），注销: %s", self._entity_id)

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
