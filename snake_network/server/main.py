from __future__ import annotations

import argparse
import socket
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Set

from snake_network.server.auth import UserStore
from snake_network.server.game import GameRoom
from snake_network.server.stats import StatsStore
from snake_network.shared.constants import PORT, SERVER_BIND_HOST, TICK_RATE
from snake_network.shared.crypto import CryptoBox, build_shared_key, generate_private_key, public_key
from snake_network.shared.protocol import ProtocolError, receive_packet, send_packet


PROJECT_ROOT = Path(__file__).resolve().parents[2]
USERS_PATH = PROJECT_ROOT / "snake_network" / "data" / "users.json"
STATS_PATH = PROJECT_ROOT / "snake_network" / "data" / "stats.json"


class GameHub:
    """Owns all rooms and the mapping between clients and one active room."""

    def __init__(self, stats: StatsStore) -> None:
        self.rooms: Dict[str, GameRoom] = {}
        self.room_clients: Dict[str, Set["ClientHandler"]] = {}
        self.stats = stats
        self.lock = threading.RLock()
        self.create_room("Main Room")

    def create_room(self, name: str, bot_count: int = 0, obstacle_count: int = 18) -> GameRoom:
        with self.lock:
            clean_name = (name or "Snake Room").strip()[:30]
            room = GameRoom(clean_name)
            room.configure(bot_count, obstacle_count)
            self.rooms[room.room_id] = room
            self.room_clients[room.room_id] = set()
            return room

    def list_rooms(self) -> list[dict[str, object]]:
        with self.lock:
            return [room.info() for room in self.rooms.values()]

    def join_room(self, client: "ClientHandler", room_id: str) -> GameRoom:
        if client.username is None:
            raise ValueError("יש להתחבר לפני הצטרפות למשחק")
        with self.lock:
            if room_id not in self.rooms:
                raise ValueError("החדר לא קיים")
            self.leave_room(client)
            room = self.rooms[room_id]
            if room.winner is not None:
                room.reset_game()
            room.add_player(client.username, client.preferred_color)
            self.room_clients[room_id].add(client)
            client.room_id = room_id
            return room

    def leave_room(self, client: "ClientHandler") -> None:
        with self.lock:
            room_id = client.room_id
            if room_id is None:
                return
            room = self.rooms.get(room_id)
            if room is not None and client.username is not None:
                room.remove_player(client.username)
            self.room_clients.get(room_id, set()).discard(client)
            client.room_id = None

    def handle_direction(self, client: "ClientHandler", dx: int, dy: int) -> None:
        room = self._client_room(client)
        if room is not None and client.username is not None:
            room.set_direction(client.username, (dx, dy))

    def handle_shoot(self, client: "ClientHandler") -> None:
        room = self._client_room(client)
        if room is not None and client.username is not None:
            room.shoot(client.username)

    def restart_room(self, client: "ClientHandler") -> Optional[GameRoom]:
        room = self._client_room(client)
        if room is not None:
            room.reset_game()
        return room

    def set_ready(self, client: "ClientHandler", ready: bool) -> None:
        room = self._client_room(client)
        if room is not None and client.username is not None:
            room.set_ready(client.username, ready)

    def set_color(self, client: "ClientHandler", color: str) -> None:
        client.preferred_color = color
        room = self._client_room(client)
        if room is not None and client.username is not None:
            room.set_color(client.username, color)

    def send_chat(self, client: "ClientHandler", text: str) -> None:
        room = self._client_room(client)
        if room is None or client.username is None:
            return
        message = {
            "type": "chat_message",
            "username": client.username,
            "message": text[:160],
        }
        with self.lock:
            clients = list(self.room_clients.get(room.room_id, set()))
        for room_client in clients:
            room_client.send(message)

    def delete_room(self, room_id: str) -> None:
        with self.lock:
            if room_id not in self.rooms or len(self.rooms) == 1:
                return
            clients = list(self.room_clients.get(room_id, set()))
            for client in clients:
                client.room_id = None
                client.send({"type": "left_room"})
                client.send({"type": "room_list", "rooms": self.list_rooms()})
            self.room_clients.pop(room_id, None)
            self.rooms.pop(room_id, None)

    def tick_and_broadcast(self) -> None:
        with self.lock:
            rooms = list(self.rooms.values())
        for room in rooms:
            room.update()
            if room.winner is not None and not room.match_recorded:
                self.stats.record_match(
                    room.name,
                    room.winner,
                    [
                        {"username": player.username, "score": player.score}
                        for player in room.players.values()
                    ],
                )
                room.match_recorded = True
            snapshot = room.snapshot()
            with self.lock:
                clients = list(self.room_clients.get(room.room_id, set()))
            for client in clients:
                client.send(snapshot)

    def broadcast_rooms(self) -> None:
        message = {"type": "room_list", "rooms": self.list_rooms()}
        with self.lock:
            clients = {client for clients in self.room_clients.values() for client in clients}
        for client in clients:
            client.send(message)

    def _client_room(self, client: "ClientHandler") -> Optional[GameRoom]:
        with self.lock:
            if client.room_id is None:
                return None
            return self.rooms.get(client.room_id)


class ClientHandler(threading.Thread):
    def __init__(self, server: "SnakeServer", conn: socket.socket, address: tuple[str, int]) -> None:
        super().__init__(daemon=True)
        self.server = server
        self.conn = conn
        self.address = address
        self.crypto: Optional[CryptoBox] = None
        self.username: Optional[str] = None
        self.room_id: Optional[str] = None
        self.preferred_color: Optional[str] = None
        self._send_lock = threading.Lock()
        self._running = True

    def run(self) -> None:
        try:
            self._handshake()
            while self._running:
                message = receive_packet(self.conn, self.crypto)
                self._handle_message(message)
        except (ConnectionError, OSError, ProtocolError, ValueError):
            pass
        finally:
            self.close()

    def send(self, message: dict[str, object]) -> None:
        if not self._running or self.crypto is None:
            return
        try:
            with self._send_lock:
                send_packet(self.conn, message, self.crypto)
        except OSError:
            self.close()

    def close(self) -> None:
        if not self._running:
            return
        self._running = False
        if self.username is not None:
            self.server.logout_user(self.username)
        self.server.hub.leave_room(self)
        try:
            self.conn.close()
        except OSError:
            pass

    def _handshake(self) -> None:
        message = receive_packet(self.conn)
        if message.get("type") != "key_init":
            raise ProtocolError("Missing key_init")
        client_public = int(message["public_key"])
        private = generate_private_key()
        server_public = public_key(private)
        send_packet(self.conn, {"type": "key_reply", "public_key": str(server_public)})
        shared_key = build_shared_key(client_public, private)
        self.crypto = CryptoBox(shared_key)

    def _handle_message(self, message: dict[str, object]) -> None:
        command = message.get("type")
        if command in {"register", "login"}:
            self._handle_auth(command, message)
            return
        if self.username is None:
            self.send({"type": "error", "message": "יש להתחבר לפני ביצוע פעולה"})
            return

        if command == "list_rooms":
            self.send({"type": "room_list", "rooms": self.server.hub.list_rooms()})
        elif command == "create_room":
            room = self.server.hub.create_room(
                str(message.get("name", "Snake Room")),
                int(message.get("bot_count", 0)),
                int(message.get("obstacle_count", 18)),
            )
            self.send({"type": "room_created", "room": room.info()})
            self.send({"type": "room_list", "rooms": self.server.hub.list_rooms()})
        elif command == "join_room":
            room = self.server.hub.join_room(self, str(message.get("room_id", "")))
            self.send({"type": "join_result", "ok": True, "room": room.info()})
        elif command == "leave_room":
            self.server.hub.leave_room(self)
            self.send({"type": "left_room"})
            self.send({"type": "room_list", "rooms": self.server.hub.list_rooms()})
        elif command == "direction":
            self.server.hub.handle_direction(self, int(message.get("dx", 0)), int(message.get("dy", 0)))
        elif command == "shoot":
            self.server.hub.handle_shoot(self)
        elif command == "restart_room":
            room = self.server.hub.restart_room(self)
            if room is not None:
                self.send(room.snapshot())
        elif command == "ready":
            self.server.hub.set_ready(self, bool(message.get("ready", True)))
        elif command == "set_color":
            self.server.hub.set_color(self, str(message.get("color", "")))
        elif command == "chat":
            self.server.hub.send_chat(self, str(message.get("message", "")))
        elif command == "stats":
            self.send(self.server.stats.snapshot())
        elif command == "delete_room":
            if self.username and self.username.lower() == "admin":
                self.server.hub.delete_room(str(message.get("room_id", "")))
                self.send({"type": "room_list", "rooms": self.server.hub.list_rooms()})
            else:
                self.send({"type": "error", "message": "רק מנהל יכול למחוק חדרים"})
        else:
            self.send({"type": "error", "message": "פקודה לא מוכרת"})

    def _handle_auth(self, command: object, message: dict[str, object]) -> None:
        username = str(message.get("username", "")).strip()
        password = str(message.get("password", ""))
        try:
            if self.server.is_user_online(username):
                raise ValueError("המשתמש כבר מחובר ממחשב אחר")
            if command == "register":
                self.server.users.register(username, password)
                logged_in_username = self.server.users.login(username, password)
            else:
                logged_in_username = self.server.users.login(username, password)
            self.username = logged_in_username
            self.server.mark_user_online(logged_in_username)
            self.send({"type": "auth_result", "ok": True, "username": logged_in_username})
            self.send({"type": "room_list", "rooms": self.server.hub.list_rooms()})
        except ValueError as error:
            self.send({"type": "auth_result", "ok": False, "message": str(error)})


class SnakeServer:
    def __init__(self, host: str = SERVER_BIND_HOST, port: int = PORT) -> None:
        self.host = host
        self.port = port
        self.users = UserStore(USERS_PATH)
        self.stats = StatsStore(STATS_PATH)
        self.hub = GameHub(self.stats)
        self._active_users: Set[str] = set()
        self._active_lock = threading.Lock()
        self._running = True

    def is_user_online(self, username: str) -> bool:
        with self._active_lock:
            return username.lower() in self._active_users

    def mark_user_online(self, username: str) -> None:
        with self._active_lock:
            self._active_users.add(username.lower())

    def logout_user(self, username: str) -> None:
        with self._active_lock:
            self._active_users.discard(username.lower())

    def start(self) -> None:
        threading.Thread(target=self._game_loop, daemon=True).start()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind((self.host, self.port))
            server_socket.listen()
            print(f"Snake server listening on {self.host}:{self.port}")
            while self._running:
                conn, address = server_socket.accept()
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                ClientHandler(self, conn, address).start()

    def _game_loop(self) -> None:
        delay = 1 / TICK_RATE
        while self._running:
            started = time.perf_counter()
            self.hub.tick_and_broadcast()
            elapsed = time.perf_counter() - started
            time.sleep(max(0.01, delay - elapsed))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Network Snake server")
    parser.add_argument("--host", default=SERVER_BIND_HOST, help="Address to bind. Use 0.0.0.0 for LAN clients.")
    parser.add_argument("--port", type=int, default=PORT, help="TCP port to listen on.")
    args = parser.parse_args()
    SnakeServer(args.host, args.port).start()


if __name__ == "__main__":
    main()
