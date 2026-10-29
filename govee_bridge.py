#!/usr/bin/env python3
"""Low-latency UDP bridge for compatible Govee RGBIC devices."""

from __future__ import annotations

import base64
import json
import math
import os
import signal
import socket
import time
from dataclasses import dataclass


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false, got {value!r}")


def env_int(name: str, default: int, minimum: int = 1) -> int:
    value = int(os.getenv(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def env_float(name: str, default: float, minimum: float = 0.001) -> float:
    value = float(os.getenv(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


@dataclass(frozen=True)
class Settings:
    govee_ip: str
    govee_port: int = 4003
    listen_ip: str = "0.0.0.0"
    listen_port: int = 19446
    segments_per_bar: int = 10
    fps_limit: int = 15
    status_interval: float = 5.0
    arm_interval: float = 40.0
    swap_bars: bool = False
    reverse_left: bool = False
    reverse_right: bool = False
    adaptive_smoothing: bool = True
    brightness_attack_seconds: float = 0.15
    brightness_release_seconds: float = 0.35
    color_settling_seconds: float = 0.25
    turn_off_on_exit: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        govee_ip = os.getenv("GOVEE_IP", "").strip()
        if not govee_ip:
            raise ValueError("GOVEE_IP is required")

        return cls(
            govee_ip=govee_ip,
            govee_port=env_int("GOVEE_PORT", 4003),
            listen_ip=os.getenv("LISTEN_IP", "0.0.0.0").strip(),
            listen_port=env_int("LISTEN_PORT", 19446),
            segments_per_bar=env_int("SEGMENTS_PER_BAR", 10),
            fps_limit=env_int("FPS_LIMIT", 15),
            status_interval=env_float("STATUS_INTERVAL", 5.0),
            arm_interval=env_float("ARM_INTERVAL", 40.0),
            swap_bars=env_bool("SWAP_BARS", False),
            reverse_left=env_bool("REVERSE_LEFT", False),
            reverse_right=env_bool("REVERSE_RIGHT", False),
            adaptive_smoothing=env_bool("ADAPTIVE_SMOOTHING", True),
            brightness_attack_seconds=env_float(
                "BRIGHTNESS_ATTACK_SECONDS", 0.15
            ),
            brightness_release_seconds=env_float(
                "BRIGHTNESS_RELEASE_SECONDS", 0.35
            ),
            color_settling_seconds=env_float(
                "COLOR_SETTLING_SECONDS", 0.25
            ),
            turn_off_on_exit=env_bool("TURN_OFF_ON_EXIT", True),
        )


def send_command(
    sock: socket.socket,
    settings: Settings,
    command: str,
    data: dict[str, object],
) -> None:
    message = json.dumps(
        {"msg": {"cmd": command, "data": data}}, separators=(",", ":")
    ).encode()
    sock.sendto(message, (settings.govee_ip, settings.govee_port))


def send_raw(
    sock: socket.socket,
    settings: Settings,
    opcode: int,
    payload: list[int],
) -> None:
    frame = (
        bytes([0xBB])
        + len(payload).to_bytes(2, "big")
        + bytes([opcode])
        + bytes(payload)
    )

    checksum = 0
    for value in frame:
        checksum ^= value
    frame += bytes([checksum])

    send_command(
        sock,
        settings,
        "razer",
        {"pt": base64.b64encode(frame).decode()},
    )


def decode_colors(
    data: bytes, settings: Settings
) -> tuple[list[tuple[int, int, int]], list[tuple[int, int, int]], str] | None:
    """Decode either two RGB zones or two bars of RGB segments."""
    if len(data) == 6:
        left = tuple(data[:3])
        right = tuple(data[3:6])
        left_colors = [left] * settings.segments_per_bar
        right_colors = [right] * settings.segments_per_bar
        mode = "2-zone"
    elif len(data) == settings.segments_per_bar * 2 * 3:
        colors = [
            tuple(data[offset : offset + 3])
            for offset in range(0, len(data), 3)
        ]
        left_colors = colors[: settings.segments_per_bar]
        right_colors = colors[settings.segments_per_bar :]
        mode = f"{settings.segments_per_bar * 2}-segment"
    else:
        return None

    if settings.reverse_left:
        left_colors.reverse()
    if settings.reverse_right:
        right_colors.reverse()
    if settings.swap_bars:
        left_colors, right_colors = right_colors, left_colors

    return left_colors, right_colors, mode


def smooth_colors(
    current: list[list[float]] | None,
    target: list[tuple[int, int, int]],
    elapsed: float,
    settings: Settings,
) -> tuple[list[list[float]], list[tuple[int, int, int]]]:
    """Smooth each segment, using a faster rise than fall time."""
    if not settings.adaptive_smoothing or current is None:
        state = [[float(channel) for channel in color] for color in target]
        return state, list(target)

    elapsed = max(0.001, min(elapsed, 0.5))
    result: list[tuple[int, int, int]] = []

    for previous, wanted in zip(current, target):
        previous_level = max(previous)
        wanted_level = max(wanted)

        if wanted_level > previous_level + 1:
            settling = settings.brightness_attack_seconds
        elif wanted_level < previous_level - 1:
            settling = settings.brightness_release_seconds
        else:
            settling = settings.color_settling_seconds

        # About 95% of the transition is complete after the settling time.
        alpha = 1 - math.exp(math.log(0.05) * elapsed / settling)

        for channel in range(3):
            previous[channel] += alpha * (wanted[channel] - previous[channel])

        if max(abs(wanted[i] - previous[i]) for i in range(3)) < 0.75:
            previous[:] = [float(channel) for channel in wanted]

        result.append(
            tuple(max(0, min(255, round(channel))) for channel in previous)
        )

    return current, result


def update_bars(
    sock: socket.socket,
    settings: Settings,
    left_colors: list[tuple[int, int, int]],
    right_colors: list[tuple[int, int, int]],
) -> None:
    colors = left_colors + right_colors
    payload = [0, len(colors)]
    for color in colors:
        payload.extend(color)
    send_raw(sock, settings, 0xB0, payload)


def run(settings: Settings) -> None:
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    receiver.bind((settings.listen_ip, settings.listen_port))
    receiver.settimeout(1.0)

    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    stopping = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    print(
        f"Listening on {settings.listen_ip}:{settings.listen_port}/udp; "
        f"device={settings.govee_ip}:{settings.govee_port}; "
        f"segments={settings.segments_per_bar * 2}",
        flush=True,
    )

    send_command(sender, settings, "turn", {"value": 1})
    time.sleep(0.3)
    send_raw(sender, settings, 0xB1, [1])
    time.sleep(1.0)

    last_frame = 0.0
    last_arm = time.monotonic()
    last_status = 0.0
    smoothed_state: list[list[float]] | None = None

    try:
        while not stopping:
            try:
                data, _address = receiver.recvfrom(4096)
            except socket.timeout:
                continue

            decoded = decode_colors(data, settings)
            if decoded is None:
                continue

            now = time.monotonic()
            if now - last_frame < 1 / settings.fps_limit:
                continue

            if now - last_arm > settings.arm_interval:
                send_raw(sender, settings, 0xB1, [1])
                last_arm = now

            left_target, right_target, mode = decoded
            target = left_target + right_target
            smoothed_state, colors = smooth_colors(
                smoothed_state,
                target,
                now - last_frame if last_frame else 1 / settings.fps_limit,
                settings,
            )
            left_colors = colors[: settings.segments_per_bar]
            right_colors = colors[settings.segments_per_bar :]

            update_bars(sender, settings, left_colors, right_colors)
            last_frame = now

            if now - last_status >= settings.status_interval:
                print(
                    f"{mode} | left={left_colors[0]}..{left_colors[-1]} | "
                    f"right={right_colors[0]}..{right_colors[-1]}",
                    flush=True,
                )
                last_status = now
    finally:
        if settings.turn_off_on_exit:
            send_raw(sender, settings, 0xB1, [0])
        receiver.close()
        sender.close()
        print("Bridge stopped", flush=True)


def main() -> int:
    try:
        settings = Settings.from_env()
        run(settings)
    except (OSError, ValueError) as error:
        print(f"Configuration or network error: {error}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
