"""ffmpeg 预处理：铃声前缀 + 变速，生成可流式播放的合成音频。

输出写到 /config/www/ai-zaozhidao/，播放走 http://<HA>/local/ai-zaozhidao/xx.m4a
（ESPHome 音箱无法直接播 file://，必须给 HTTP URL）。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
import time
from pathlib import Path
from urllib.parse import quote

from homeassistant.core import HomeAssistant

from .const import OUTPUT_DIRNAME

_LOGGER = logging.getLogger(__name__)

MIN_SPEED = 0.5
MAX_SPEED = 3.0
RINGTONE_FADE_SECONDS = 2.5
GAP_SECONDS = 0.5
_PROC_TIMEOUT = 300
# 合成结果保留时长：超过后视为过期，下次合成/启动时删除
RETENTION_SECONDS = 24 * 3600


class ProcessError(Exception):
    """音频合成失败。"""


def ringtone_asset_path() -> Path:
    """包内自带铃声的绝对路径。"""
    return Path(__file__).resolve().parent / "assets" / "morning-alarm-ringtone.mp3"


def output_dir(hass: HomeAssistant) -> Path:
    return Path(hass.config.path("www")) / OUTPUT_DIRNAME


async def _probe_duration(path: Path) -> float:
    """ffprobe 取媒体时长（秒）。"""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise ProcessError("容器内没有 ffprobe，无法读取音频时长")
    proc = await asyncio.create_subprocess_exec(
        ffprobe,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), _PROC_TIMEOUT)
    except TimeoutError as err:
        proc.kill()
        raise ProcessError("ffprobe 超时") from err
    if proc.returncode != 0:
        raise ProcessError(f"ffprobe 失败: {stderr.decode(errors='ignore')[:200]}")
    try:
        return float(stdout.decode().strip())
    except ValueError as err:
        raise ProcessError("ffprobe 未返回时长") from err


async def _download(hass: HomeAssistant, url: str, dest: Path) -> None:
    import aiohttp
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    session = async_get_clientsession(hass)
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            if resp.status != 200:
                raise ProcessError(f"下载源音频失败: HTTP {resp.status}")
            data = await resp.read()
    except ProcessError:
        raise
    except Exception as err:  # noqa: BLE001
        raise ProcessError(f"下载源音频失败: {err}") from err
    await asyncio.get_running_loop().run_in_executor(None, dest.write_bytes, data)


async def _run_ffmpeg(
    src: Path,
    out: Path,
    ringtone: Path | None,
    speed: float,
) -> None:
    """铃声(原速,淡出) + 0.5s 静音 + 播客正文(变速不变调)，合成 AAC。"""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise ProcessError("容器内没有 ffmpeg，无法合成音频")

    fade_start = 0.0
    if ringtone is not None:
        if not ringtone.is_file():
            raise ProcessError(f"铃声文件不存在: {ringtone}")
        ring_dur = await _probe_duration(ringtone)
        if ring_dur <= 0:
            raise ProcessError("铃声文件无法读取时长")
        fade_start = max(ring_dur - RINGTONE_FADE_SECONDS, 0)

    ep = "[0:a]"
    if abs(speed - 1.0) > 1e-6:
        ep += f"atempo={speed:.4f},"
    ep += "aresample=44100,aformat=channel_layouts=stereo[ep]"

    if ringtone is not None:
        filters = [
            ep,
            "[1:a]aresample=44100,pan=stereo|c0=c0|c1=c0,"
            f"afade=t=out:st={fade_start:.3f}:d={RINGTONE_FADE_SECONDS}[ring]",
            f"anullsrc=r=44100:cl=stereo,atrim=0:{GAP_SECONDS}[gap]",
            "[ring][gap][ep]concat=n=3:v=0:a=1[out]",
        ]
        inputs = [str(src), str(ringtone)]
        map_target = "[out]"
    else:
        filters = [ep]
        inputs = [str(src)]
        map_target = "[ep]"

    cmd = [
        ffmpeg, "-y", "-v", "error",
        *[x for inp in inputs for x in ("-i", inp)],
        "-filter_complex", ";".join(filters),
        "-map", map_target,
        "-c:a", "aac", "-b:a", "128k",
        str(out),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), _PROC_TIMEOUT)
    except TimeoutError as err:
        proc.kill()
        raise ProcessError("ffmpeg 合成超时") from err
    if proc.returncode != 0:
        raise ProcessError(f"ffmpeg 合成失败: {stderr.decode(errors='ignore')[:300]}")


def cleanup_expired(hass: HomeAssistant, keep: Path | None = None) -> int:
    """删除过期（>1 天）的合成音频，保留 keep 指定文件。返回删除数。"""
    out_dir = output_dir(hass)
    if not out_dir.is_dir():
        return 0
    now = time.time()
    removed = 0
    for f in out_dir.iterdir():
        if not f.is_file() or f == keep:
            continue
        try:
            if now - f.stat().st_mtime > RETENTION_SECONDS:
                f.unlink()
                removed += 1
        except OSError as err:
            _LOGGER.warning("清理过期音频失败 %s: %s", f.name, err)
    if removed:
        _LOGGER.info("已清理 %d 个过期合成音频", removed)
    return removed


async def build_processed_audio(
    hass: HomeAssistant,
    source_url: str,
    *,
    ringtone_path: Path | None,
    speed: float,
    title: str,
) -> str:
    """下载源音频并按配置合成，返回 /local/... 相对 URL（play_media 直接可用）。"""
    speed = min(max(float(speed or 1.0), MIN_SPEED), MAX_SPEED)
    out_dir = output_dir(hass)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 文件名含参数摘要：同配置重复播放直接复用，配置变了自动重新合成
    digest = hashlib.sha1(
        f"{title}|{source_url}|{speed:.2f}|{(ringtone_path or Path('')).name}".encode()
    ).hexdigest()[:12]
    safe_title = "".join(c if c.isalnum() or c in "-_" else "_" for c in title) or "episode"
    out_name = f"{safe_title}_{digest}.m4a"
    out_path = out_dir / out_name
    if out_path.exists() and out_path.stat().st_size > 0:
        # 缓存命中也顺带清理过期文件（不删自己）
        await hass.async_add_executor_job(cleanup_expired, hass, out_path)
        return f"/local/{OUTPUT_DIRNAME}/{quote(out_name)}"

    src = out_dir / f".src_{digest}.m4a"
    try:
        await _download(hass, source_url, src)
        await _run_ffmpeg(src, out_path, ringtone_path, speed)
    finally:
        src.unlink(missing_ok=True)

    # 合成完成后清理过期文件（不删刚生成的）
    await hass.async_add_executor_job(cleanup_expired, hass, out_path)
    _LOGGER.info("音频合成完成: %s (铃声=%s, 倍速=%.2f)", out_name, bool(ringtone_path), speed)
    return f"/local/{OUTPUT_DIRNAME}/{quote(out_name)}"
