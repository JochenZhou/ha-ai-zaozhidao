"""Constants for the AI早知道播客 integration."""

DOMAIN = "ai_zaozhidao"

CONF_PODCAST = "podcast"
CONF_TITLE_PREFIX = "title_prefix"
CONF_MEDIA_PLAYER = "media_player"
CONF_NOTIFY_SERVICE = "notify_service"
CONF_NOTIFY_TARGET = "notify_target"
CONF_VOLUME = "volume"
CONF_RINGTONE_ENABLED = "ringtone_enabled"
CONF_RINGTONE_FILE = "ringtone_file"
CONF_SPEED = "speed"
CONF_BASE_URL = "base_url"

DEFAULT_PODCAST = "6a6e4a2ec654846ef0ee0795"
DEFAULT_TITLE_PREFIX = "AI早知道"
DEFAULT_SCAN_INTERVAL_MINUTES = 30
DEFAULT_RINGTONE_ENABLED = False
DEFAULT_RINGTONE_FILE = ""
DEFAULT_SPEED = 1.0

# 包内自带铃声（集成目录下）
RINGTONE_ASSET = "assets/morning-alarm-ringtone.mp3"
# 合成输出目录：/config/www/<OUTPUT_DIRNAME>，经 /local/<OUTPUT_DIRNAME> 播放
OUTPUT_DIRNAME = "ai-zaozhidao"

PLATFORMS = ["sensor", "binary_sensor", "button"]

SERVICE_PLAY = "play"
SERVICE_REFRESH = "refresh"

ATTR_TITLE = "title"
ATTR_ENTRY_ID = "entry_id"
