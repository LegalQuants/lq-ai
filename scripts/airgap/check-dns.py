"""Exercise Docker DNS inside the sealed gateway without third-party libraries."""

import secrets
import socket
import struct


def query(server: str, name: str, *, tcp: bool) -> tuple[int, int]:
    """Return DNS response code and answer count; timeouts mean no response."""
    transaction = secrets.randbelow(65536)
    question = b"".join(bytes([len(part)]) + part.encode("ascii") for part in name.split("."))
    message = struct.pack("!HHHHHH", transaction, 0x100, 1, 0, 0, 0)
    message += question + b"\x00\x00\x01\x00\x01"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM) as sock:
        sock.settimeout(8)
        try:
            sock.connect((server, 53))
            if tcp:
                sock.sendall(struct.pack("!H", len(message)) + message)
                length = struct.unpack("!H", receive(sock, 2))[0]
                response = receive(sock, length)
            else:
                sock.sendall(message)
                response = sock.recv(4096)
        except (TimeoutError, ConnectionError):
            return -1, 0
    response_id, flags, _, answers, _, _ = struct.unpack("!HHHHHH", response[:12])
    if response_id != transaction or not flags & 0x8000:
        raise RuntimeError("DNS control received an invalid response")
    return flags & 15, answers


def receive(sock: socket.socket, length: int) -> bytes:
    """Read a complete TCP DNS frame or fail the control."""
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise ConnectionError("incomplete DNS response")
        data += chunk
    return data


def main() -> None:
    """Check internal discovery and fresh external queries over UDP and TCP."""
    # A unique name prevents a previous/pre-seal cached response hiding forwarding.
    external = f"airgap-{secrets.token_hex(8)}.example.com"
    for tcp in (False, True):
        transport = "TCP" if tcp else "UDP"
        code, answers = query("127.0.0.11", "postgres", tcp=tcp)
        if code != 0 or answers == 0:
            raise RuntimeError(f"internal service DNS failed over {transport}")
        code, answers = query("127.0.0.11", external, tcp=tcp)
        if code not in (-1, 2, 5) or answers:
            raise RuntimeError(f"external DNS unexpectedly answered over {transport}")
        print(f"DNS control: internal name resolves; external name blocked ({transport})")


if __name__ == "__main__":
    main()
