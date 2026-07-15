import argparse
import queue
import socket
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Optional

from snake_network.shared.constants import CELL_SIZE, DEFAULT_SERVER_HOST, PORT
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
        self.username = ""
        self.current_state: Optional[dict[str, object]] = None

        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure("TButton", font=("Segoe UI", 11), padding=8)
        self.style.configure("TLabel", background="#111827", foreground="#E5E7EB", font=("Segoe UI", 11))
        self.style.configure("Title.TLabel", background="#111827", foreground="#22D3EE", font=("Segoe UI", 28, "bold"))
        self.style.configure("Panel.TFrame", background="#1F2937")

        self.container = ttk.Frame(self.root, style="Panel.TFrame")
        self.container.pack(fill="both", expand=True, padx=24, pady=24)

        self._connect_to_server()
        self._show_login()
        self.root.after(40, self._process_messages)

    def run(self) -> None:
        self.root.mainloop()

    def _connect_to_server(self) -> None:
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
        except OSError as error:
            messagebox.showerror(
                "Connection Error",
                f"Cannot connect to server {self.server_host}:{self.server_port}\n{error}",
            )
            self.root.destroy()

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
        self._clear()
        top = ttk.Frame(self.container, style="Panel.TFrame")
        top.pack(fill="x", pady=(0, 16))
        ttk.Label(top, text=f"Lobby - {self.username}", style="Title.TLabel").pack(side="left")
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
            line = f'{room["id"]} | {room["name"]:<24} | players: {room["players"]} | winner: {room.get("winner") or "-"}'
            self.rooms_list.insert(tk.END, line)

        ttk.Button(self.container, text="Join Selected Room", command=self._join_selected_room).pack(pady=14)

    def _create_room(self) -> None:
        name = simpledialog.askstring("Create Room", "Room name:", parent=self.root)
        if name:
            self.network.send({"type": "create_room", "name": name})

    def _join_selected_room(self) -> None:
        selection = self.rooms_list.curselection()
        if not selection:
            messagebox.showinfo("Join Room", "Select a room first.")
            return
        self.network.send({"type": "join_room", "room_id": self.room_ids[selection[0]]})

    def _show_game(self) -> None:
        self._clear()
        self.game_title = ttk.Label(self.container, text="Game", style="Title.TLabel")
        self.game_title.pack(anchor="w")

        self.info_label = ttk.Label(self.container, text="Arrow keys/WASD to move, Space to shoot")
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

        self.score_box = tk.Text(self.container, width=28, height=30, bg="#0F172A", fg="#E5E7EB", font=("Consolas", 12))
        self.score_box.pack(side="left", fill="y")

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

    def _process_messages(self) -> None:
        while not self.messages.empty():
            message = self.messages.get()
            self._handle_message(message)
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
        elif message_type == "error":
            messagebox.showerror("Server Error", str(message.get("message", "")))
        elif message_type == "connection_closed":
            messagebox.showwarning("Disconnected", "The server connection was closed.")

    def _draw_game(self, state: dict[str, object]) -> None:
        if not hasattr(self, "canvas"):
            return
        width = int(state["width"])
        height = int(state["height"])
        self.canvas.config(width=width * CELL_SIZE, height=height * CELL_SIZE)
        self.canvas.delete("all")

        for x in range(width):
            self.canvas.create_line(x * CELL_SIZE, 0, x * CELL_SIZE, height * CELL_SIZE, fill="#111827")
        for y in range(height):
            self.canvas.create_line(0, y * CELL_SIZE, width * CELL_SIZE, y * CELL_SIZE, fill="#111827")

        for fruit in state.get("fruits", []):
            self._cell(fruit, "#F97316", oval=True)
        for bullet in state.get("bullets", []):
            self._cell(bullet["position"], "#F8FAFC", oval=True, inset=6)

        score_lines = []
        for player in state.get("players", []):
            color = str(player["color"])
            snake = player["snake"]
            for index, point in enumerate(snake):
                self._cell(point, "#FFFFFF" if index == 0 else color, inset=2 if index == 0 else 1)
            status = "ALIVE" if player["alive"] else f'DEAD ({player["death_reason"]})'
            weapon = " | can shoot" if player["can_shoot"] else ""
            score_lines.append(f'{player["username"]}: {player["score"]} | {status}{weapon}')

        winner = state.get("winner")
        room = state.get("room", {})
        self.game_title.config(text=f'Room: {room.get("name", "")}')
        if winner:
            self.info_label.config(text=f"Winner: {winner}")
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
