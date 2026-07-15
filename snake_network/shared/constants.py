SERVER_BIND_HOST = "0.0.0.0"
DEFAULT_SERVER_HOST = "127.0.0.1"
PORT = 5050

BOARD_WIDTH = 40
BOARD_HEIGHT = 30
CELL_SIZE = 20

TICK_RATE = 5
FRUIT_COUNT = 6
MIN_PLAYERS_TO_START = 1
DEFAULT_OBSTACLE_COUNT = 18
DEFAULT_BOT_COUNT = 0
COUNTDOWN_TICKS = TICK_RATE * 3

SHOOT_SCORE = 5
SHOT_COOLDOWN_TICKS = 8
BULLET_MAX_AGE = 60

USERNAME_MIN = 3
USERNAME_MAX = 16
PASSWORD_MIN = 4

COLORS = [
    "#00E676",
    "#40C4FF",
    "#FFEA00",
    "#FF5252",
    "#E040FB",
    "#FFAB40",
    "#69F0AE",
    "#B388FF",
]

FRUIT_TYPES = [
    {"kind": "apple", "color": "#EF4444", "value": 1, "effect": "normal"},
    {"kind": "orange", "color": "#F97316", "value": 1, "effect": "normal"},
    {"kind": "grape", "color": "#8B5CF6", "value": 1, "effect": "normal"},
    {"kind": "lemon", "color": "#FACC15", "value": 2, "effect": "bonus"},
    {"kind": "melon", "color": "#22C55E", "value": 2, "effect": "bonus"},
    {"kind": "gold", "color": "#FDE047", "value": 3, "effect": "bonus"},
    {"kind": "blaster", "color": "#38BDF8", "value": 1, "effect": "unlock_shooting"},
]
