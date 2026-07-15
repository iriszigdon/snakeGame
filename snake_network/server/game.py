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
    FRUIT_COUNT,
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
class Player:
    username: str
    color: str
    snake: List[Point]
    direction: Direction = (1, 0)
    next_direction: Direction = (1, 0)
    score: int = 0
    alive: bool = True
    last_shot_tick: int = -999
    death_reason: str = ""

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
    fruits: List[Point] = field(default_factory=list)
    bullets: List[Bullet] = field(default_factory=list)
    tick_number: int = 0
    winner: Optional[str] = None
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add_player(self, username: str) -> Player:
        with self.lock:
            if username in self.players:
                return self.players[username]
            color = COLORS[len(self.players) % len(COLORS)]
            snake = self._create_spawn_snake()
            player = Player(username=username, color=color, snake=snake)
            self.players[username] = player
            self.winner = None
            self._fill_fruits()
            return player

    def remove_player(self, username: str) -> None:
        with self.lock:
            self.players.pop(username, None)
            self.bullets = [bullet for bullet in self.bullets if bullet.owner != username]
            if len(self.players) == 0:
                self.winner = None

    def set_direction(self, username: str, direction: Direction) -> None:
        with self.lock:
            player = self.players.get(username)
            if player is None or not player.alive:
                return
            if direction == (0, 0):
                return
            if (direction[0] + player.direction[0], direction[1] + player.direction[1]) == (0, 0):
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

            occupied_before = self._occupied_points()
            for player in self.players.values():
                if not player.alive:
                    continue
                player.direction = player.next_direction
                dx, dy = player.direction
                new_head = (player.head[0] + dx, player.head[1] + dy)
                player.snake.insert(0, new_head)

                if new_head in self.fruits:
                    self.fruits.remove(new_head)
                    player.score += 1
                else:
                    player.snake.pop()

            head_counts: Dict[Point, int] = {}
            for player in self.players.values():
                if player.alive:
                    head_counts[player.head] = head_counts.get(player.head, 0) + 1

            for player in self.players.values():
                if not player.alive:
                    continue
                if self._is_wall_collision(player.head):
                    self._kill(player, "פגיעה בקיר")
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
                "players": [
                    {
                        "username": player.username,
                        "color": player.color,
                        "snake": player.snake,
                        "score": player.score,
                        "alive": player.alive,
                        "can_shoot": player.can_shoot,
                        "death_reason": player.death_reason,
                    }
                    for player in self.players.values()
                ],
                "fruits": self.fruits,
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
            }

    def _create_spawn_snake(self) -> List[Point]:
        occupied = self._occupied_points()
        for _ in range(300):
            x = random.randint(5, self.width - 6)
            y = random.randint(5, self.height - 6)
            candidate = [(x, y), (x - 1, y), (x - 2, y)]
            if not any(point in occupied for point in candidate):
                return candidate
        return [(3, 3), (2, 3), (1, 3)]

    def _fill_fruits(self) -> None:
        occupied = self._occupied_points() | set(self.fruits)
        while len(self.fruits) < FRUIT_COUNT:
            point = (random.randint(0, self.width - 1), random.randint(0, self.height - 1))
            if point not in occupied:
                self.fruits.append(point)
                occupied.add(point)

    def _occupied_points(self) -> set[Point]:
        points: set[Point] = set()
        for player in self.players.values():
            if player.alive:
                points.update(player.snake)
        return points

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
        player.death_reason = reason

    def _update_winner(self) -> None:
        alive_players = [player.username for player in self.players.values() if player.alive]
        if len(self.players) >= 2 and len(alive_players) == 1:
            self.winner = alive_players[0]
        elif len(self.players) >= 1 and not alive_players:
            self.winner = "אין מנצח"
