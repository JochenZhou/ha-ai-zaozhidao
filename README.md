# AI早知道播客（Home Assistant 自定义集成）

[![一键添加到 HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=JochenZhou&repository=ha-ai-zaozhidao&category=integration)
[![打开 Home Assistant 添加集成](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=ai_zaozhidao)

抓取小宇宙播客《AI早知道》**当天那一期**，播放到指定的 `media_player`。
当天还没更新时只发提醒、不播放。

> 本集成只做「抓取公开页面 + 调 HA 播放服务」，不托管、不分发任何音频文件或链接。

## 功能

- 每 30 分钟轮询播客列表页，解析出最新一期与「今天那一期」
- 提供 `ai_zaozhidao.play` 服务：播当天那一期；当天没更新则发送提醒
- 提供实体：最新一期标题 / 日期、今日是否已更新、一键播放按钮
- 播放前可选择固定音量，或保持音箱当前音量不变
- **铃声前缀**（默认关闭）：正片播放前先响一段铃声（内置 Morning 铃声，结尾淡出，音量不变），也可指定 HA 容器内的自定义音频文件
- **播放倍速**（默认 1.0）：正片 0.5-3.0 倍变速不变调，铃声始终原速

## 安装

### 一键添加（推荐）

点顶部第一个徽章 **“一键添加到 HACS”**，浏览器会跳转到你的 HA 并打开本仓库的 HACS 页面，
确认添加即可。之后在 HACS 里搜索「AI早知道播客」下载，然后**重启 Home Assistant**。

> 一键按钮需要：已在 HA 里装好 HACS，且用能访问你 HA 地址的浏览器打开。
> 如果你的 HA 不在 `http://homeassistant.local:8123`，会先让你填一次地址。

装好并重启后，点顶部第二个徽章 **“打开 Home Assistant 添加集成”** 直接进入配置页面。

### 手动添加

1. HACS → 右上角 ⋮ → **自定义存储库**
2. 仓库填 `https://github.com/JochenZhou/ha-ai-zaozhidao`，类别选 **集成（Integration）**
3. 搜索「AI早知道播客」→ 下载
4. **重启 Home Assistant**
5. 设置 → 设备与服务 → 添加集成 → 搜索「AI早知道播客」

### 完全手动安装

把 `custom_components/ai_zaozhidao/` 整个目录拷到 HA 配置目录下的
`custom_components/ai_zaozhidao/`，重启 HA。

## 配置项

| 字段 | 说明 | 默认 |
|---|---|---|
| 播客链接或 ID | 小宇宙播客完整链接或 24 位 ID | `6a6e4a2ec654846ef0ee0795` |
| 标题前缀 | 期号按「前缀-YY-MM-DD」精确匹配 | `AI早知道` |
| 目标媒体播放器 | 播放到哪台音箱/播放器 | 必填 |
| 提醒服务 | 当天未更新时调用的 notify 服务，如 `notify.wework` | 空（只留持久通知） |
| 提醒目标 | 传给提醒服务的目标/接收人 | 空 |
| 播放前音量 | `0` = 不修改音箱当前音量 | `0` |
| 铃声前缀 | 开启后正片播放前先响一段铃声（内置 Morning 铃声，结尾淡出） | 关 |
| 自定义铃声文件 | HA 容器内绝对路径，如 `/config/local/my-ring.mp3`；留空用内置铃声 | 空 |
| 播放倍速 | 正片 0.5-3.0 倍变速不变调；铃声始终原速 | `1.0` |
| 服务地址 | 播放器访问 HA 用的地址，如 `http://192.168.101.75`；留空自动探测 | 空 |
| 播完续播随机音乐 | 播完后让 Music Assistant 从曲库随机挑歌接着放（需 MA 集成） | 关 |
| 无新一期时直接播音乐 | 当天没更新时不发提醒，直接随机放音乐 | 关 |
| 续播曲目数 | 随机几首，1 = 只放一首（续播与无新一期模式共用） | 1 |
| 续播播放器 | 续播用的 MA 播放器，默认同播客播放器 | 播客播放器 |

> 铃声 / 倍速都开启时，播放前会先由 HA 容器内的 **ffmpeg**（官方容器自带）把铃声与正片合成为一个音频，
> 输出缓存到 `/config/www/ai-zaozhidao/`，并通过 HA 内置 `/local/` 路径播放；
> 同一期同配置只合成一次，重复播放零等待。都关闭时与旧版一致，直接播放小宇宙源地址。
>
> **服务地址**：合成后的音频通过 HA 的 `/local/` 路径播放，播放器必须能访问该地址。
> 留空时按「HA 内网/外网地址 → 自动探测 → 网卡 IP」顺序推断；如果你的 HA 前面有反代、
> 端口非标准、或多网卡，请手动填写（如 `http://192.168.101.75`）。
>
> 目标播放器 `unavailable`/`unknown` 时，集成不会假装播放成功，而是跳过播放并发送提醒。
>
> **播完续播**：播放开始后在目标播放器上挂一个监听，播放状态从 `playing` 落到 `idle`/`off`
> 且已播时长（优先取播放器自报的 `media_position`）≥ 音频时长的 80% 时，调
> `music_assistant.get_library(order_by=random)` 取曲目、再用 `music_assistant.play_media` 接着放。
> 手动提前停止不算播完；中途切到别的媒体会自动注销监听；监听最长存活 4 小时。
> MA 曲库为空或播放器不归 MA 管时会发提醒，不会静默失败。
>
> > 判断「是不是我们那一期」时不直接比字符串：MA 会把播放地址包成
> > `builtin://sound_effect/<URL>` 并再做一次百分号编码，直接比较会导致刚开播就误判成
> > 「用户切了别的媒体」而注销监听（v0.3.1 的 bug，v0.3.2 修复）。
> > 排查时看 `sensor.*_latest_episode` 的属性：`continue_music` 是否开启、
> > `active_watchers` 是否 ≥ 1（0 = 没挂上监听）。
>
> **无新一期时直接播音乐**：把这当「播客优先、音乐兜底」。当天没有新一期时不再只发提醒，
> 而是直接用「续播曲目数」+「音乐播放器（MA）」随机放歌；失败了会明确告诉你原因。

## 实体

| 实体 | 说明 |
|---|---|
| `sensor.*_latest_episode` | 最新一期标题；属性含日期、音频地址、今日匹配情况 |
| `sensor.*_latest_episode_date` | 最新一期日期 |
| `binary_sensor.*_today_s_episode_available` | 今天那期是否已发布 |
| `button.*_play_today_s_episode` | 手动播放当天那一期 |

## 服务

### `ai_zaozhidao.play`

播放当天那一期；当天没更新则只发送提醒。支持返回响应，便于自动化里读取结果。

| 字段 | 说明 |
|---|---|
| `title` | 可选。指定要播放的完整标题，留空 = 当天那一期 |
| `entry_id` | 可选。多条目时指定操作对象 |

### `ai_zaozhidao.refresh`

立刻重新抓取播客列表并更新实体。

## 自动化示例：每天 06:50 自动播放

```yaml
alias: AI早知道 每日播放（06:50）
triggers:
  - trigger: time
    at: "06:50:00"
conditions: []
actions:
  - action: ai_zaozhidao.play
    data: {}
mode: single
```

## 说明与限制

- 播客没有可用 RSS，集成直接解析列表页内嵌的 `__NEXT_DATA__`；页面结构若变动，
  集成会抛错并在实体上体现为不可用，而不是静默给错数据。
- 目标音箱是 ESPHome 的 speaker 时，可直接播放公网音频地址，无需转码或内网托管。
  部分这类设备不支持跳转播放位置，因此只提供「整期播放」。

## 许可

MIT
