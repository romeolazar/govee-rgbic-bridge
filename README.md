# Govee RGBIC Bridge

A small, low-latency UDP bridge that maps ambient-light RGB data to individual
segments on compatible Govee RGBIC devices. It accepts either one RGB color per
bar or multiple RGB segments per bar and supports adaptive smoothing for fast
brightness attacks and softer releases.

> [!IMPORTANT]
> This is an unofficial community project. It uses Govee LAN control and an
> RGBIC packet mode that may not be supported by every model or firmware.
> It has been tested with the Govee H6047.

## Features

- Multiple independent colors along each RGBIC bar
- Two-zone compatibility mode
- Configurable segment count and physical orientation
- Adaptive brightness and color smoothing
- No third-party Python dependencies
- Small, non-root Docker image for `amd64` and `arm64`
- Graceful container shutdown

## Requirements

- A compatible Govee RGBIC device with **LAN Control** enabled in the Govee app
- The bridge host and Govee controller reachable on the same LAN
- An ambient-light application capable of sending raw RGB bytes over UDP
- Docker with host networking, or Python 3.10+

## Quick start with Docker Compose

```sh
git clone https://github.com/romeolazar/govee-rgbic-bridge.git
cd govee-rgbic-bridge
cp .env.example .env
```

Edit `.env` and set at least:

```dotenv
GOVEE_IP=192.168.1.50
```

Then start the bridge:

```sh
docker compose up -d --build
docker compose logs -f
```

The supplied Compose file uses host networking, which is recommended for a
Linux host receiving and sending LAN UDP traffic.

## Ambient-light input

The default listener is `0.0.0.0:19446/udp`.

Packets can contain:

- 6 bytes: `left RGB + right RGB`; each color fills one complete bar.
- `SEGMENTS_PER_BAR * 2 * 3` bytes: consecutive RGB segments for the left bar,
  followed by consecutive RGB segments for the right bar.

For two bars with 10 segments each, send 60 bytes per frame. Configure the
ambient-light application with 10 LEDs on the left, 10 on the right, and zero
on the top and bottom. Use an output delay of 0 ms when the sender and bridge
are on a stable local network.

## Configuration

All configuration is provided through environment variables. No device IP,
credential, or personal setting is embedded in the image.

| Variable | Default | Description |
| --- | ---: | --- |
| `GOVEE_IP` | required | LAN address of the Govee controller |
| `GOVEE_PORT` | `4003` | Govee LAN control UDP port |
| `LISTEN_IP` | `0.0.0.0` | Local address to bind |
| `LISTEN_PORT` | `19446` | Raw RGB UDP input port |
| `SEGMENTS_PER_BAR` | `10` | Virtual RGB segments on each bar |
| `FPS_LIMIT` | `15` | Maximum updates per second |
| `SWAP_BARS` | `false` | Exchange left and right bars |
| `REVERSE_LEFT` | `false` | Reverse left segment order |
| `REVERSE_RIGHT` | `false` | Reverse right segment order |
| `ADAPTIVE_SMOOTHING` | `true` | Enable bridge-side smoothing |
| `BRIGHTNESS_ATTACK_SECONDS` | `0.15` | Approximate rise settling time |
| `BRIGHTNESS_RELEASE_SECONDS` | `0.35` | Approximate fall settling time |
| `COLOR_SETTLING_SECONDS` | `0.25` | Approximate color settling time |
| `STATUS_INTERVAL` | `5` | Seconds between status log lines |
| `ARM_INTERVAL` | `40` | Seconds between RGBIC mode refreshes |
| `TURN_OFF_ON_EXIT` | `true` | Disable RGBIC output on clean shutdown |

Boolean values accept `true`/`false`, `yes`/`no`, `on`/`off`, or `1`/`0`.

## Run without Docker

```sh
GOVEE_IP=192.168.1.50 python3 govee_bridge.py
```

## Test

```sh
python3 -m unittest discover -s tests -v
```

## Security

The bridge requires no cloud credentials. Keep the UDP listener on a trusted
LAN and do not expose it directly to the internet.

## License

[MIT](LICENSE)
