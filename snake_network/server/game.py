from __future__ import annotations

import random
import threading
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from snake_network.shared.constants import (
    BOARD_HEIGHT,
    BOARD_WIDTH,
    BULLET_MAX_AGE,
    COLORS,
    COUNTDOWN_TICKS,
    DEFAULT_BOT_COUNT,
    DEFAULT_OBSTACLE_COUNT,
    FRUIT_COUNT,
    FRUIT_TYPES,
    MIN_PLAYERS_TO_START,
    SHOOT_SCORE,
    SHOT_COOLDOWN_TICKS,
)


Point = Tuple[int, int]
Direction = Tuple[int, int]


@dataclass
class Bullet:
    owner: str
    position: Point
    direction: Direction
    age: int = 0


@dataclass
class Fruit:
    position: Point
    kind: str
    color: str
    value: int = 1
    effect: str = "normal"


@dataclass
class Player:
    username: str
    color: str
    snake: List[Point]
    direction: Direction = (0, 0)
    next_direction: Direction = (0, 0)
    score: int = 0
    alive: bool = True
    ready: bool = False
    is_bot: bool = False
    last_shot_tick: int = -999
    death_reason: str = ""
    power_message: str = ""

    @property
    def head(self) -> Point:
        return self.snake[0]

    @property
    def can_shoot(self) -> bool:
        return self.score >= SHOOT_SCORE and self.alive


@dataclass
class GameRoom:
    name: str
    room_id: str = field(default_factory=lambda: uuid.uuid4().hex[:6])
    width: int = BOARD_WIDTH
    height: int = BOARD_HEIGHT
    players: Dict[str, Player] = field(default_factory=dict)
    fruits: List[Fruit] = field(default_factory=list)
    bullets: List[Bullet] = field(default_factory=list)
    obstacles: List[Point] = field(default_factory=list)
    tick_number: int = 0
    winner: Optional[str] = None
    countdown: int = -1
    match_recorded: bool = False
    bot_count: int = DEFAULT_BOT_COUNT
    obstacle_count: int = DEFAULT_OBSTACLE_COUNT
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add_player(self, username: str, color: Optional[str] = None) -> Player:
        with self.lock:
            if username in self.players:
                return self.players[username]
            color = color or COLORS[len(self.players) % len(COLORS)]
            snake = self._create_spawn_snake()
            player = Player(username=username, color=color, snake=snake)
            self.players[username] = player
            self._ensure_bots()
            self._fill_fruits()
            return player

    def remove_player(self, username: str) -> None:
        with self.lock:
            self.players.pop(username, None)
            self.bullets = [bullet for bullet in self.bullets if bullet.owner != username]
            if len(self.players) == 0:
                self.winner = None

    def configure(self, bot_count: int, obstacle_count: int) -> None:
        with self.lock:
            self.bot_count = max(0, min(4, bot_count))
            self.obstacle_count = max(0, min(80, obstacle_count))
            self.reset_game()

    def reset_game(self) -> None:
        with self.lock:
            self.fruits = []
            self.bullets = []
            self.obstacles = []
            self.tick_number = 0
            self.winner = None
            self.countdown = -1
            self.match_recorded = False
            for index, player in enumerate(self.players.values()):
                player.snake = self._create_spawn_snake()
                player.direction = (0, 0)
                player.next_direction = (0, 0)
                player.score = 0
                player.alive = True
                player.ready = player.is_bot
                player.last_shot_tick = -999
                player.death_reason = ""
                player.power_message = ""
                player.color = COLORS[index % len(COLORS)]
            self._ensure_bots()
            self._fill_obstacles()
            self._fill_fruits()

    def set_ready(self, username: str, ready: bool) -> None:
        with self.lock:
            player = self.players.get(username)
            if player is not None and player.alive:
                player.ready = ready

    def set_color(self, username: str, color: str) -> None:
        with self.lock:
            player = self.players.get(username)
            if player is not None and color in COLORS:
                player.color = color

    def set_direction(self, username: str, direction: Direction) -> None:
        with self.lock:
            player = self.players.get(username)
            if player is None or not player.alive:
                return
            if direction == (0, 0):
                return
            if player.direction != (0, 0) and (
                direction[0] + player.direction[0],
                direction[1] + player.direction[1],
            ) == (0, 0):
                return
            player.next_direction = direction

    def shoot(self, username: str) -> None:
        with self.lock:
            player = self.players.get(username)
            if player is None or not player.can_shoot:
                return
            if self.tick_number - player.last_shot_tick < SHOT_COOLDOWN_TICKS:
                return
            dx, dy = player.direction
            bullet_position = (player.head[0] + dx, player.head[1] + dy)
            self.bullets.append(Bullet(owner=username, position=bullet_position, direction=player.direction))
            player.last_shot_tick = self.tick_number

    def update(self) -> None:
        with self.lock:
            self.tick_number += 1
            if len(self.players) < MIN_PLAYERS_TO_START:
                return
            if self.winner is not None:
                return
            self._update_countdown()
            if self.countdown != 0:
                return
            self._update_bots()

            occupied_before = self._occupied_points()
            moved_players = set()
            for player in self.players.values():
                if not player.alive:
                    continue
                player.direction = player.next_direction
                if player.direction == (0, 0):
                    continue
                moved_players.add(player.username)
                dx, dy = player.direction
                new_head = (player.head[0] + dx, player.head[1] + dy)
                player.snake.insert(0, new_head)

                fruit = self._fruit_at(new_head)
                if fruit is not None:
                    self.fruits.remove(fruit)
                    player.score += fruit.value
                    self._apply_fruit_effect(player, fruit)
                else:
                    player.snake.pop()

            head_counts: Dict[Point, int] = {}
            for player in self.players.values():
                if player.alive:
                    head_counts[player.head] = head_counts.get(player.head, 0) + 1

            for player in self.players.values():
                if not player.alive:
                    continue
                if player.username not in moved_players:
                    continue
                if self._is_wall_collision(player.head):
                    self._kill(player, "פגיעה בקיר")
                    continue
                if player.head in self.obstacles:
                    self._kill(player, "פגיעה במכשול")
                    continue
                if head_counts.get(player.head, 0) > 1:
                    self._kill(player, "התנגשות ראש בראש")
                    continue
                if self._head_hit_body(player, occupied_before):
                    self._kill(player, "פגיעה בנחש")

            self._move_bullets()
            self._fill_fruits()
            self._update_winner()

    def snapshot(self) -> Dict[str, object]:
        with self.lock:
            return {
                "type": "game_state",
                "room": {"id": self.room_id, "name": self.name},
                "width": self.width,
                "height": self.height,
                "shoot_score": SHOOT_SCORE,
                "winner": self.winner,
                "countdown": self.countdown,
                "obstacles": self.obstacles,
                "players": [
                    {
                        "username": player.username,
                        "color": player.color,
                        "snake": player.snake,
                        "direction": player.direction,
                        "score": player.score,
                        "level": 1 + player.score // 5,
                        "alive": player.alive,
                        "ready": player.ready,
                        "is_bot": player.is_bot,
                        "can_shoot": player.can_shoot,
                        "death_reason": player.death_reason,
                        "power_message": player.power_message,
                    }
                    for player in self.players.values()
                ],
                "fruits": [
                    {
                        "position": fruit.position,
                        "kind": fruit.kind,
                        "color": fruit.color,
                        "value": fruit.value,
                        "effect": fruit.effect,
                    }
                    for fruit in self.fruits
                ],
                "bullets": [
                    {"owner": bullet.owner, "position": bullet.position}
                    for bullet in self.bullets
                ],
            }

    def info(self) -> Dict[str, object]:
        with self.lock:
            return {
                "id": self.room_id,
                "name": self.name,
                "players": len(self.players),
                "alive": sum(1 for player in self.players.values() if player.alive),
                "winner": self.winner,
                "bots": sum(1 for player in self.players.values() if player.is_bot),
                "obstacles": self.obstacle_count,
            }

    def _create_spawn_snake(self) -> List[Point]:
        occupied = self._occupied_points() | set(self.obstacles)
        for _ in range(300):
            x = random.randint(5, self.width - 6)
            y = random.randint(5, self.height - 6)
            candidate = [(x, y), (x - 1, y), (x - 2, y)]
            if not any(point in occupied for point in candidate):
                return candidate
        return [(3, 3), (2, 3), (1, 3)]

    def _fill_fruits(self) -> None:
        occupied = self._occupied_points() | {fruit.position for fruit in self.fruits}
        occupied |= set(self.obstacles)
        while len(self.fruits) < FRUIT_COUNT:
            point = (random.randint(0, self.width - 1), random.randint(0, self.height - 1))
            if point not in occupied:
                fruit_type = random.choice(FRUIT_TYPES)
                self.fruits.append(Fruit(
                    point,
                    str(fruit_type["kind"]),
                    str(fruit_type["color"]),
                    int(fruit_type["value"]),
                    str(fruit_type["effect"]),
                ))
                occupied.add(point)

    def _fruit_at(self, point: Point) -> Optional[Fruit]:
        for fruit in self.fruits:
            if fruit.position == point:
                return fruit
        return None

    def _occupied_points(self) -> set[Point]:
        points: set[Point] = set()
        for player in self.players.values():
            if player.alive:
                points.update(player.snake)
        return points

    def _fill_obstacles(self) -> None:
        occupied = self._occupied_points()
        while len(self.obstacles) < self.obstacle_count:
            point = (random.randint(2, self.width - 3), random.randint(2, self.height - 3))
            if point not in occupied and point not in self.obstacles:
                self.obstacles.append(point)

    def _is_wall_collision(self, point: Point) -> bool:
        x, y = point
        return x < 0 or y < 0 or x >= self.width or y >= self.height

    def _head_hit_body(self, player: Player, occupied_before: set[Point]) -> bool:
        return player.head in occupied_before

    def _move_bullets(self) -> None:
        remaining: List[Bullet] = []
        for bullet in self.bullets:
            dx, dy = bullet.direction
            bullet.position = (bullet.position[0] + dx, bullet.position[1] + dy)
            bullet.age += 1
            if self._is_wall_collision(bullet.position) or bullet.age > BULLET_MAX_AGE:
                continue
            hit_player = self._bullet_hit_player(bullet)
            if hit_player is not None:
                self._kill(hit_player, f"נפגע מירייה של {bullet.owner}")
                continue
            remaining.append(bullet)
        self.bullets = remaining

    def _bullet_hit_player(self, bullet: Bullet) -> Optional[Player]:
        for player in self.players.values():
            if player.username == bullet.owner or not player.alive:
                continue
            if bullet.position in player.snake:
                return player
        return None

    def _kill(self, player: Player, reason: str) -> None:
        player.alive = False
        player.ready = False
        player.death_reason = reason

    def _update_winner(self) -> None:
        alive_players = [player.username for player in self.players.values() if player.alive]
        if len(self.players) >= 2 and len(alive_players) == 1:
            self.winner = alive_players[0]
        elif len(self.players) >= 1 and not alive_players:
            self.winner = "אין מנצח"

    def _update_countdown(self) -> None:
        alive_players = [player for player in self.players.values() if player.alive]
        human_players = [player for player in alive_players if not player.is_bot]
        if not alive_players or any(not player.ready for player in human_players):
            self.countdown = -1
            return
        if self.countdown == -1:
            self.countdown = COUNTDOWN_TICKS
        elif self.countdown > 0:
            self.countdown -= 1

    def _ensure_bots(self) -> None:
        existing_bots = [player for player in self.players.values() if player.is_bot]
        while len(existing_bots) < self.bot_count:
            name = f"Bot {len(existing_bots) + 1}"
            if name in self.players:
                existing_bots.append(self.players[name])
                continue
            snake = self._create_spawn_snake()
            bot = Player(
                username=name,
                color=COLORS[len(self.players) % len(COLORS)],
                snake=snake,
                ready=True,
                is_bot=True,
            )
            self.players[name] = bot
            existing_bots.append(bot)

    def _update_bots(self) -> None:
        for player in self.players.values():
            if player.is_bot and player.alive:
                player.next_direction = self._choose_bot_direction(player)

    def _choose_bot_direction(self, player: Player) -> Direction:
        directions = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        random.shuffle(directions)
        if self.fruits:
            target = min(
                self.fruits,
                key=lambda fruit: abs(fruit.position[0] - player.head[0]) + abs(fruit.position[1] - player.head[1]),
            ).position
            directions.sort(
                key=lambda direction: abs(player.head[0] + direction[0] - target[0])
                + abs(player.head[1] + direction[1] - target[1])
            )
        occupied = self._occupied_points()
        for direction in directions:
            if player.direction != (0, 0) and (
                direction[0] + player.direction[0],
                direction[1] + player.direction[1],
            ) == (0, 0):
                continue
            next_point = (player.head[0] + direction[0], player.head[1] + direction[1])
            if not self._is_wall_collision(next_point) and next_point not in occupied and next_point not in self.obstacles:
                return direction
        return player.direction

    def _apply_fruit_effect(self, player: Player, fruit: Fruit) -> None:
        if fruit.effect == "unlock_shooting":
            player.score = max(player.score, SHOOT_SCORE)
            player.power_message = "הירי נפתח"
        elif fruit.effect == "bonus":
            player.power_message = f"בונוס {fruit.value} נקודות"
        else:
            player.power_message = ""
