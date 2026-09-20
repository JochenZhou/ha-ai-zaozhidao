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
