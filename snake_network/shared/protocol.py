import json
import socket
import struct
from typing import Any, Dict, Optional

from snake_network.shared.crypto import CryptoBox


MAX_PACKET_SIZE = 1024 * 1024


class ProtocolError(Exception):
    pass


def send_packet(sock: socket.socket, message: Dict[str, Any], crypto: Optional[CryptoBox] = None) -> None:
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    if crypto is not None:
        payload = json.dumps({"encrypted": crypto.encrypt(payload)}, separators=(",", ":")).encode("utf-8")
    header = struct.pack("!I", len(payload))
    sock.sendall(header + payload)


def receive_packet(sock: socket.socket, crypto: Optional[CryptoBox] = None) -> Dict[str, Any]:
    header = _receive_exact(sock, 4)
    if not header:
        raise ConnectionError("Socket closed")
    length = struct.unpack("!I", header)[0]
    if length <= 0 or length > MAX_PACKET_SIZE:
        raise ProtocolError(f"Invalid packet length: {length}")
    payload = _receive_exact(sock, length)
    if not payload:
        raise ConnectionError("Socket closed")

    raw_message = json.loads(payload.decode("utf-8"))
    if crypto is None:
        return raw_message

    if "encrypted" not in raw_message:
        raise ProtocolError("Expected encrypted message")
    plaintext = crypto.decrypt(raw_message["encrypted"])
    return json.loads(plaintext.decode("utf-8"))


def _receive_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            return b""
        chunks.extend(chunk)
    return bytes(chunks)
