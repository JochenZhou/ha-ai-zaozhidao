"""Constants for the AI早知道播客 integration."""

DOMAIN = "ai_zaozhidao"

CONF_PODCAST = "podcast"
CONF_TITLE_PREFIX = "title_prefix"
CONF_MEDIA_PLAYER = "media_player"
CONF_NOTIFY_SERVICE = "notify_service"
CONF_NOTIFY_TARGET = "notify_target"
CONF_VOLUME = "volume"

DEFAULT_PODCAST = "6a6e4a2ec654846ef0ee0795"
DEFAULT_TITLE_PREFIX = "AI早知道"
DEFAULT_SCAN_INTERVAL_MINUTES = 30

PLATFORMS = ["sensor", "binary_sensor", "button"]

SERVICE_PLAY = "play"
SERVICE_REFRESH = "refresh"

ATTR_TITLE = "title"
ATTR_ENTRY_ID = "entry_id"
