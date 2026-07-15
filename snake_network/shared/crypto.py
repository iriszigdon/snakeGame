import base64
import hashlib
import hmac
import secrets
from typing import Dict


# Educational Diffie-Hellman parameters. The project demonstrates key exchange
# and encrypted application messages without external packages.
DH_PRIME = 170141183460469231731687303715884105727
DH_GENERATOR = 5


def generate_private_key() -> int:
    return secrets.randbelow(DH_PRIME - 3) + 2


def public_key(private_key: int) -> int:
    return pow(DH_GENERATOR, private_key, DH_PRIME)


def build_shared_key(their_public_key: int, private_key: int) -> bytes:
    shared = pow(their_public_key, private_key, DH_PRIME)
    shared_bytes = shared.to_bytes((shared.bit_length() + 7) // 8, "big")
    return hashlib.sha256(shared_bytes).digest()


class CryptoBox:
    """Small authenticated stream-cipher wrapper for project messages.

    This is suitable for a school project that must demonstrate encrypted
    traffic and integrity checks. Real production systems should use TLS or a
    reviewed library such as cryptography/Fernet.
    """

    def __init__(self, shared_key: bytes) -> None:
        self._enc_key = hmac.new(shared_key, b"snake-enc", hashlib.sha256).digest()
        self._mac_key = hmac.new(shared_key, b"snake-mac", hashlib.sha256).digest()

    def encrypt(self, plaintext: bytes) -> Dict[str, str]:
        nonce = secrets.token_bytes(16)
        ciphertext = self._xor_with_keystream(plaintext, nonce)
        tag = hmac.new(self._mac_key, nonce + ciphertext, hashlib.sha256).digest()
        return {
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            "tag": base64.b64encode(tag).decode("ascii"),
        }

    def decrypt(self, envelope: Dict[str, str]) -> bytes:
        nonce = base64.b64decode(envelope["nonce"])
        ciphertext = base64.b64decode(envelope["ciphertext"])
        expected_tag = base64.b64decode(envelope["tag"])
        actual_tag = hmac.new(self._mac_key, nonce + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(expected_tag, actual_tag):
            raise ValueError("Encrypted message integrity check failed")
        return self._xor_with_keystream(ciphertext, nonce)

    def _xor_with_keystream(self, data: bytes, nonce: bytes) -> bytes:
        output = bytearray()
        counter = 0
        while len(output) < len(data):
            block = hmac.new(
                self._enc_key,
                nonce + counter.to_bytes(8, "big"),
                hashlib.sha256,
            ).digest()
            output.extend(block)
            counter += 1
        return bytes(value ^ key for value, key in zip(data, output))
