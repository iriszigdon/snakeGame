from __future__ import annotations

import argparse
import queue
import socket
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Optional

try:
    import winsound
except ImportError:
    winsound = None

from snake_network.shared.constants import CELL_SIZE, COLORS, DEFAULT_SERVER_HOST, PORT
from snake_network.shared.crypto import CryptoBox, build_shared_key, generate_private_key, public_key
from snake_network.shared.protocol import receive_packet, send_packet


class NetworkClient:
    def __init__(self, incoming: "queue.Queue[dict[str, object]]") -> None:
        self.incoming = incoming
        self.sock: Optional[socket.socket] = None
        self.crypto: Optional[CryptoBox] = None
        self.running = False
        self._send_lock = threading.Lock()

    def connect(self, host: str = DEFAULT_SERVER_HOST, port: int = PORT) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock.connect((host, port))
        private = generate_private_key()
        send_packet(self.sock, {"type": "key_init", "public_key": str(public_key(private))})
        reply = receive_packet(self.sock)
        if reply.get("type") != "key_reply":
            raise ConnectionError("Server did not complete key exchange")
        shared_key = build_shared_key(int(reply["public_key"]), private)
        self.crypto = CryptoBox(shared_key)
        self.running = True
        threading.Thread(target=self._listen, daemon=True).start()

    def send(self, message: dict[str, object]) -> None:
        if self.sock is None or self.crypto is None:
            return
        with self._send_lock:
            send_packet(self.sock, message, self.crypto)

    def close(self) -> None:
        self.running = False
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass

    def _listen(self) -> None:
        assert self.sock is not None
        assert self.crypto is not None
        while self.running:
            try:
                self.incoming.put(receive_packet(self.sock, self.crypto))
            except (ConnectionError, OSError, ValueError):
                self.incoming.put({"type": "connection_closed"})
                self.running = False
                break


class SnakeClientApp:
    def __init__(self, server_host: str = DEFAULT_SERVER_HOST, server_port: int = PORT) -> None:
        self.root = tk.Tk()
        self.root.title("Network Snake")
        self.root.geometry("980x760")
        self.root.configure(bg="#111827")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.messages: "queue.Queue[dict[str, object]]" = queue.Queue()
        self.network = NetworkClient(self.messages)
        self.server_host = server_host
        self.server_port = server_port
        self.ready = False
        self.in_game = False
        self.username = ""
        self.current_state: Optional[dict[str, object]] = None
        self.selected_color = COLORS[0]
        self.last_score = 0
        self.last_alive = True
        self.last_winner = None

        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure("TButton", font=("Segoe UI", 11), padding=8)
        self.style.configure("TLabel", background="#111827", foreground="#E5E7EB", font=("Segoe UI", 11))
        self.style.configure("Title.TLabel", background="#111827", foreground="#22D3EE", font=("Segoe UI", 28, "bold"))
        self.style.configure("Panel.TFrame", background="#1F2937")

        self.container = ttk.Frame(self.root, style="Panel.TFrame")
        self.container.pack(fill="both", expand=True, padx=24, pady=24)

        if not self._connect_to_server():
            return
        self.ready = True
        self._show_login()
        self.root.after(40, self._process_messages)

    def run(self) -> None:
        if self.ready:
            self.root.mainloop()

    def _connect_to_server(self) -> bool:
        if self.server_host == "":
            chosen_host = simpledialog.askstring(
                "Server Address",
                "Enter server IP address:",
                initialvalue=DEFAULT_SERVER_HOST,
                parent=self.root,
            )
            self.server_host = (chosen_host or DEFAULT_SERVER_HOST).strip()
        try:
            self.network.connect(self.server_host, self.server_port)
            return True
        except (OSError, ConnectionError, ValueError) as error:
            messagebox.showerror(
                "Connection Error",
                f"Cannot connect to server {self.server_host}:{self.server_port}\n{error}",
            )
            self.root.destroy()
            return False

    def _clear(self) -> None:
        for widget in self.container.winfo_children():
            widget.destroy()

    def _show_login(self) -> None:
        self._clear()
        frame = ttk.Frame(self.container, style="Panel.TFrame")
        frame.place(relx=0.5, rely=0.5, anchor="center")

        ttk.Label(frame, text="Network Snake", style="Title.TLabel").grid(row=0, column=0, columnspan=2, pady=(0, 24))
        ttk.Label(frame, text="Username").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Label(frame, text="Password").grid(row=2, column=0, sticky="w", pady=6)

        self.username_entry = ttk.Entry(frame, font=("Segoe UI", 13), width=24)
        self.password_entry = ttk.Entry(frame, font=("Segoe UI", 13), width=24, show="*")
        self.username_entry.grid(row=1, column=1, pady=6)
        self.password_entry.grid(row=2, column=1, pady=6)

        ttk.Button(frame, text="Login", command=lambda: self._auth("login")).grid(row=3, column=0, sticky="ew", pady=16, padx=4)
        ttk.Button(frame, text="Register", command=lambda: self._auth("register")).grid(row=3, column=1, sticky="ew", pady=16, padx=4)

    def _auth(self, action: str) -> None:
        self.network.send({
            "type": action,
            "username": self.username_entry.get().strip(),
            "password": self.password_entry.get(),
        })

    def _show_lobby(self, rooms: list[dict[str, object]]) -> None:
        self.in_game = False
        self._clear()
        top = ttk.Frame(self.container, style="Panel.TFrame")
        top.pack(fill="x", pady=(0, 16))
        ttk.Label(top, text=f"Lobby - {self.username}", style="Title.TLabel").pack(side="left")
        ttk.Button(top, text="Help", command=self._show_help).pack(side="right", padx=4)
        ttk.Button(top, text="Scores", command=lambda: self.network.send({"type": "stats"})).pack(side="right", padx=4)
        if self.username.lower() == "admin":
            ttk.Button(top, text="Delete Room", command=self._delete_selected_room).pack(side="right", padx=4)
        ttk.Button(top, text="Snake Color", command=self._choose_color).pack(side="right", padx=4)
        ttk.Button(top, text="Refresh", command=lambda: self.network.send({"type": "list_rooms"})).pack(side="right", padx=4)
        ttk.Button(top, text="Create Room", command=self._create_room).pack(side="right", padx=4)

        self.rooms_list = tk.Listbox(
            self.container,
            height=14,
            bg="#0F172A",
            fg="#E5E7EB",
            selectbackground="#0891B2",
            font=("Consolas", 13),
            activestyle="none",
        )
        self.rooms_list.pack(fill="both", expand=True)
        self.room_ids: list[str] = []
        for room in rooms:
            self.room_ids.append(str(room["id"]))
            line = (
                f'{room["id"]} | {room["name"]:<18} | players: {room["players"]} '
                f'| bots: {room.get("bots", 0)} | obstacles: {room.get("obstacles", 0)} '
                f'| winner: {room.get("winner") or "-"}'
            )
            self.rooms_list.insert(tk.END, line)

        ttk.Button(self.container, text="Join Selected Room", command=self._join_selected_room).pack(pady=14)

    def _create_room(self) -> None:
        name = simpledialog.askstring("Create Room", "Room name:", parent=self.root)
        if name:
            bot_count = simpledialog.askinteger("Bots", "Number of bots (0-4):", initialvalue=0, minvalue=0, maxvalue=4, parent=self.root)
            obstacle_count = simpledialog.askinteger(
                "Obstacles",
                "Number of obstacles (0-80):",
                initialvalue=18,
                minvalue=0,
                maxvalue=80,
                parent=self.root,
            )
            self.network.send({
                "type": "create_room",
                "name": name,
                "bot_count": bot_count or 0,
                "obstacle_count": obstacle_count if obstacle_count is not None else 18,
            })

    def _join_selected_room(self) -> None:
        selection = self.rooms_list.curselection()
        if not selection:
            messagebox.showinfo("Join Room", "Select a room first.")
            return
        self.network.send({"type": "set_color", "color": self.selected_color})
        self.network.send({"type": "join_room", "room_id": self.room_ids[selection[0]]})

    def _delete_selected_room(self) -> None:
        selection = self.rooms_list.curselection()
        if selection:
            self.network.send({"type": "delete_room", "room_id": self.room_ids[selection[0]]})

    def _choose_color(self) -> None:
        color = simpledialog.askstring(
            "Snake Color",
            "Choose color:\n" + "\n".join(COLORS),
            initialvalue=self.selected_color,
            parent=self.root,
        )
        if color in COLORS:
            self.selected_color = color
            self.network.send({"type": "set_color", "color": color})

    def _show_help(self) -> None:
        messagebox.showinfo(
            "Game Help",
            "Controls:\n"
            "Arrow keys or WASD - move\n"
            "Space - shoot after enough points\n"
            "Ready - starts the countdown\n\n"
            "Special fruits give bonus points or unlock shooting.\n"
            "Avoid walls, snakes, bullets and obstacles.\n"
            "If you are disqualified, you can keep watching or return to the rooms.",
        )

    def _show_game(self) -> None:
        self.in_game = True
        self._clear()
        top = ttk.Frame(self.container, style="Panel.TFrame")
        top.pack(fill="x")
        self.game_title = ttk.Label(top, text="Game", style="Title.TLabel")
        self.game_title.pack(side="left", anchor="w")
        ttk.Button(top, text="Back To Rooms", command=lambda: self.network.send({"type": "leave_room"})).pack(
            side="right",
            padx=4,
        )
        ttk.Button(top, text="New Game In Room", command=lambda: self.network.send({"type": "restart_room"})).pack(
            side="right",
            padx=4,
        )
        ttk.Button(top, text="Ready", command=lambda: self.network.send({"type": "ready", "ready": True})).pack(
            side="right",
            padx=4,
        )

        self.info_label = ttk.Label(self.container, text="Press an arrow key or WASD to start. Space shoots later.")
        self.info_label.pack(anchor="w", pady=(0, 8))

        self.canvas = tk.Canvas(
            self.container,
            width=40 * CELL_SIZE,
            height=30 * CELL_SIZE,
            bg="#020617",
            highlightthickness=2,
            highlightbackground="#22D3EE",
        )
        self.canvas.pack(side="left", padx=(0, 16))

        side_panel = ttk.Frame(self.container, style="Panel.TFrame")
        side_panel.pack(side="left", fill="y")
        self.score_box = tk.Text(side_panel, width=32, height=18, bg="#0F172A", fg="#E5E7EB", font=("Consolas", 12))
        self.score_box.pack(fill="x")
        self.chat_box = tk.Text(side_panel, width=32, height=10, bg="#111827", fg="#E5E7EB", font=("Segoe UI", 10))
        self.chat_box.pack(fill="x", pady=(8, 4))
        chat_row = ttk.Frame(side_panel, style="Panel.TFrame")
        chat_row.pack(fill="x")
        self.chat_entry = ttk.Entry(chat_row)
        self.chat_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(chat_row, text="Send", command=self._send_chat).pack(side="left", padx=4)
        self.chat_entry.bind("<Return>", lambda event: self._send_chat())

        self.root.bind("<Up>", lambda event: self._direction(0, -1))
        self.root.bind("<Down>", lambda event: self._direction(0, 1))
        self.root.bind("<Left>", lambda event: self._direction(-1, 0))
        self.root.bind("<Right>", lambda event: self._direction(1, 0))
        self.root.bind("w", lambda event: self._direction(0, -1))
        self.root.bind("s", lambda event: self._direction(0, 1))
        self.root.bind("a", lambda event: self._direction(-1, 0))
        self.root.bind("d", lambda event: self._direction(1, 0))
        self.root.bind("<space>", lambda event: self.network.send({"type": "shoot"}))

    def _direction(self, dx: int, dy: int) -> None:
        self.network.send({"type": "direction", "dx": dx, "dy": dy})

    def _send_chat(self) -> None:
        text = self.chat_entry.get().strip()
        if text:
            self.network.send({"type": "chat", "message": text})
            self.chat_entry.delete(0, tk.END)

    def _process_messages(self) -> None:
        latest_game_state = None
        while not self.messages.empty():
            message = self.messages.get()
            if message.get("type") == "game_state":
                latest_game_state = message
            else:
                self._handle_message(message)
        if latest_game_state is not None and self.in_game:
            self._handle_message(latest_game_state)
        self.root.after(40, self._process_messages)

    def _handle_message(self, message: dict[str, object]) -> None:
        message_type = message.get("type")
        if message_type == "auth_result":
            if message.get("ok"):
                self.username = str(message["username"])
            else:
                messagebox.showerror("Login Failed", str(message.get("message", "Authentication failed")))
        elif message_type == "room_list":
            self._show_lobby(message.get("rooms", []))  # type: ignore[arg-type]
        elif message_type == "room_created":
            self.network.send({"type": "list_rooms"})
        elif message_type == "join_result":
            if message.get("ok"):
                self._show_game()
        elif message_type == "game_state":
            self.current_state = message
            self._draw_game(message)
        elif message_type == "chat_message":
            self._append_chat(str(message.get("username", "")), str(message.get("message", "")))
        elif message_type == "stats":
            self._show_stats(message)
        elif message_type == "error":
            messagebox.showerror("Server Error", str(message.get("message", "")))
        elif message_type == "connection_closed":
            messagebox.showwarning("Disconnected", "The server connection was closed.")

    def _draw_game(self, state: dict[str, object]) -> None:
        if not self.in_game or not hasattr(self, "canvas") or not self.canvas.winfo_exists():
            return
        width = int(state["width"])
        height = int(state["height"])
        self.canvas.config(width=width * CELL_SIZE, height=height * CELL_SIZE)
        self.canvas.delete("all")

        for x in range(width):
            self.canvas.create_line(x * CELL_SIZE, 0, x * CELL_SIZE, height * CELL_SIZE, fill="#111827")
        for y in range(height):
            self.canvas.create_line(0, y * CELL_SIZE, width * CELL_SIZE, y * CELL_SIZE, fill="#111827")

        for obstacle in state.get("obstacles", []):
            self._cell(obstacle, "#64748B", inset=2)
        for fruit in state.get("fruits", []):
            self._draw_fruit(fruit)
        for bullet in state.get("bullets", []):
            self._cell(bullet["position"], "#F8FAFC", oval=True, inset=6)

        winner = state.get("winner")
        score_lines = []
        for player in state.get("players", []):
            color = str(player["color"])
            snake = player["snake"]
            for index, point in enumerate(snake):
                if index == 0:
                    self._draw_snake_head(point, color, player.get("direction", [1, 0]))
                else:
                    self._cell(point, color, inset=1)
            status = "ALIVE" if player["alive"] else f'DEAD ({player["death_reason"]})'
            weapon = " | can shoot" if player["can_shoot"] else ""
            ready = " | ready" if player.get("ready") else ""
            bot = " | bot" if player.get("is_bot") else ""
            power = f' | {player.get("power_message")}' if player.get("power_message") else ""
            score_lines.append(
                f'{player["username"]}: {player["score"]} | level {player.get("level", 1)} | '
                f'{status}{weapon}{ready}{bot}{power}'
            )
            if player["username"] == self.username:
                self._play_state_sounds(player, winner)

        room = state.get("room", {})
        self.game_title.config(text=f'Room: {room.get("name", "")}')
        countdown = int(state.get("countdown", -1))
        if winner:
            self.info_label.config(text=f"Winner: {winner}. You can start a new game or go back to the rooms.")
        elif countdown > 0:
            self.info_label.config(text=f"Game starts in {max(1, countdown // 5 + 1)}...")
        elif countdown == -1:
            self.info_label.config(text="Press Ready when everyone is prepared.")
        else:
            self.info_label.config(text=f"Reach {state.get('shoot_score')} points to unlock shooting. Space = shoot.")
        self.score_box.delete("1.0", tk.END)
        self.score_box.insert(tk.END, "\n".join(score_lines))

    def _cell(self, point: object, color: str, oval: bool = False, inset: int = 3) -> None:
        x, y = point
        x1 = int(x) * CELL_SIZE + inset
        y1 = int(y) * CELL_SIZE + inset
        x2 = (int(x) + 1) * CELL_SIZE - inset
        y2 = (int(y) + 1) * CELL_SIZE - inset
        if oval:
            self.canvas.create_oval(x1, y1, x2, y2, fill=color, outline="")
        else:
            self.canvas.create_rectangle(x1, y1, x2, y2, fill=color, outline="")

    def _draw_snake_head(self, point: object, color: str, direction: object) -> None:
        x, y = point
        x1 = int(x) * CELL_SIZE + 1
        y1 = int(y) * CELL_SIZE + 1
        x2 = (int(x) + 1) * CELL_SIZE - 1
        y2 = (int(y) + 1) * CELL_SIZE - 1
        self.canvas.create_oval(x1, y1, x2, y2, fill=color, outline="#ECFEFF", width=2)

        dx, dy = self._direction_parts(direction)
        if (dx, dy) == (0, 0):
            dx = 1
        center_x = (x1 + x2) // 2
        center_y = (y1 + y2) // 2
        eye_offset = 5
        forward = 4

        if dx != 0:
            eye_x = center_x + dx * forward
            eye_y1 = center_y - eye_offset
            eye_y2 = center_y + eye_offset
            tongue_start = (center_x + dx * 8, center_y)
            tongue_end = (center_x + dx * 14, center_y)
            self._eye(eye_x, eye_y1)
            self._eye(eye_x, eye_y2)
        else:
            eye_y = center_y + dy * forward
            eye_x1 = center_x - eye_offset
            eye_x2 = center_x + eye_offset
            tongue_start = (center_x, center_y + dy * 8)
            tongue_end = (center_x, center_y + dy * 14)
            self._eye(eye_x1, eye_y)
            self._eye(eye_x2, eye_y)

        self.canvas.create_line(*tongue_start, *tongue_end, fill="#F43F5E", width=2)

    def _draw_fruit(self, fruit: object) -> None:
        position = fruit.get("position", [0, 0])
        kind = str(fruit.get("kind", "apple"))
        color = str(fruit.get("color", "#F97316"))
        x, y = position
        x1 = int(x) * CELL_SIZE + 3
        y1 = int(y) * CELL_SIZE + 3
        x2 = (int(x) + 1) * CELL_SIZE - 3
        y2 = (int(y) + 1) * CELL_SIZE - 3

        if kind == "grape":
            self.canvas.create_oval(x1, y1, x1 + 8, y1 + 8, fill=color, outline="")
            self.canvas.create_oval(x1 + 7, y1, x1 + 15, y1 + 8, fill=color, outline="")
            self.canvas.create_oval(x1 + 4, y1 + 7, x1 + 12, y1 + 15, fill=color, outline="")
        elif kind == "lemon":
            self.canvas.create_oval(x1, y1 + 2, x2, y2 - 2, fill=color, outline="#FEF08A", width=2)
        elif kind == "melon":
            self.canvas.create_oval(x1, y1, x2, y2, fill=color, outline="#BBF7D0", width=2)
            self.canvas.create_line(x1 + 5, y1 + 2, x2 - 5, y2 - 2, fill="#166534", width=2)
        else:
            self.canvas.create_oval(x1, y1, x2, y2, fill=color, outline="")
            self.canvas.create_rectangle((x1 + x2) // 2 - 1, y1 - 2, (x1 + x2) // 2 + 1, y1 + 4, fill="#78350F", outline="")
        self.canvas.create_oval(x2 - 5, y1 - 2, x2 + 1, y1 + 4, fill="#22C55E", outline="")

    def _eye(self, x: int, y: int) -> None:
        self.canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill="#020617", outline="")

    def _append_chat(self, username: str, message: str) -> None:
        if hasattr(self, "chat_box") and self.chat_box.winfo_exists():
            self.chat_box.insert(tk.END, f"{username}: {message}\n")
            self.chat_box.see(tk.END)

    def _show_stats(self, message: dict[str, object]) -> None:
        lines = ["High Scores:"]
        for item in message.get("high_scores", []):
            lines.append(
                f'{item["username"]}: wins={item["wins"]}, best={item["best_score"]}, games={item["games"]}'
            )
        lines.append("\nRecent Matches:")
        for item in message.get("matches", []):
            lines.append(f'{item["time"]} | {item["room"]} | winner: {item["winner"]}')
        messagebox.showinfo("Scores And History", "\n".join(lines) if len(lines) > 2 else "No games recorded yet.")

    def _play_state_sounds(self, player: dict[str, object], winner: object) -> None:
        score = int(player["score"])
        alive = bool(player["alive"])
        if score > self.last_score:
            self._beep(900, 80)
        if self.last_alive and not alive:
            self._beep(220, 200)
        if winner == self.username and self.last_winner != winner:
            self._beep(1200, 160)
        self.last_score = score
        self.last_alive = alive
        self.last_winner = winner

    def _beep(self, frequency: int, duration: int) -> None:
        if winsound is not None:
            try:
                winsound.Beep(frequency, duration)
            except RuntimeError:
                pass

    def _direction_parts(self, direction: object) -> tuple[int, int]:
        try:
            return int(direction[0]), int(direction[1])
        except (TypeError, ValueError, IndexError):
            return 1, 0

    def _on_close(self) -> None:
        self.network.close()
        self.root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Network Snake Tkinter client")
    parser.add_argument("--host", default="", help="Server LAN IP address. Empty value opens a prompt.")
    parser.add_argument("--port", type=int, default=PORT, help="Server TCP port.")
    args = parser.parse_args()
    SnakeClientApp(args.host.strip(), args.port).run()


if __name__ == "__main__":
    main()
