# Network Snake

Network Snake is a Python final-project style implementation of a multiplayer Snake game.
It includes a threaded TCP server, encrypted application messages, user registration/login,
multiple rooms, several snakes per game, bullets, scoring, and a Tkinter GUI client.

## Run

Open two terminals from this folder.

```powershell
python -m snake_network.server.main
```

Then start one or more clients:

```powershell
python -m snake_network.client.main
```

The server listens on `0.0.0.0:5050` by default, so other computers on the same
home network can connect to it.

## Run On A Home LAN

On the computer that runs the server, find its local IPv4 address:

```powershell
ipconfig
```

Look for an address like `192.168.1.25` or `10.0.0.8`.

Start the server on that computer:

```powershell
python -m snake_network.server.main
```

On the same computer, you can run a client with:

```powershell
python -m snake_network.client.main --host 127.0.0.1
```

On another computer in the same Wi-Fi/home network, copy the project folder and run:

```powershell
python -m snake_network.client.main --host 192.168.1.25
```

Replace `192.168.1.25` with the real IPv4 address of the server computer.
If Windows Firewall asks for permission, allow Python on private networks.

## Controls

- Arrow keys or `WASD`: change direction
- `Space`: shoot after reaching the configured score
- Join an existing room or create a new one from the lobby

## Project Requirements Covered

- Object-oriented design with multiple classes.
- TCP sockets with a custom length-prefixed JSON protocol.
- Threaded multi-client server.
- Encrypted client/server messages after a Diffie-Hellman key exchange.
- Registration and login with salted password hashes stored in files.
- Tkinter interactive GUI.
- Multiple games in parallel, each with multiple snakes.
- Server-authoritative game logic for collisions, fruits, scoring, bullets, and winners.
