# SNKRS Auto-Purchase Bot

An automated checkout bot for Nike's SNKRS platform that uses direct API calls with built-in anti-detection to purchase limited-edition sneakers at launch time.

> **Disclaimer:** This script may violate Nike's Terms of Service. Your account could be suspended or banned. Use at your own risk.

## How It Works

The bot authenticates with your Nike account via the SNKRS API, looks up the target product and size, waits until the exact launch time, then fires rapid purchase requests with automatic retries. The entire flow bypasses the app/web UI and talks directly to Nike's backend.

## Features

### Core

- **Auto login** — OAuth 2.0 authentication against the Nike API
- **Product lookup** — Fetches product info and resolves your target size to a SKU ID
- **Timed launch** — Precision countdown with configurable early-fire offset (default: 1s before drop)
- **Auto retry** — Configurable retry count with incremental backoff + random jitter
- **Token keep-alive** — Refreshes the access token every 30 minutes during long waits

### Anti-Detection

| Layer | Description |
|---|---|
| **TLS Fingerprinting** | Uses `curl_cffi` to impersonate real browser/app TLS handshakes (JA3). Supports Safari iOS, Chrome, etc. |
| **Device Fingerprinting** | Generates realistic device profiles from real iPhone/Android model databases. Fingerprint stays consistent within a session. |
| **Header Randomization** | Varies secondary HTTP headers (Accept-Language, Accept-Encoding) per request while keeping core fields stable. |
| **Proxy Rotation** | Cycles through a pool of HTTP/SOCKS5 proxies. Failed proxies are auto-blacklisted and reset when all are exhausted. |
| **Behavior Simulation** | Attaches synthetic mouse trajectories (web) or touch events (mobile) to checkout requests. Uses log-normal delay distribution. |
| **Kasada Token Stub** | Generates format-matching anti-bot tokens. (See Limitations below.) |

## Requirements

- Python 3.8+
- `requests`
- `curl_cffi` (strongly recommended for TLS fingerprint spoofing)

```bash
git clone http://github.com/Linqizhe07/SNKRS-bot.git
cd SNKRS-bot
pip install requests curl_cffi
```

For SOCKS5 proxy support:

```bash
pip install requests[socks]
```

## Quick Start

1. Open `snkrs_bot.py` and edit the `CONFIG` section:

   ```python
   CONFIG = {
       "email": "you@example.com",
       "password": "your_password",
       "product_id": "DZ5485-612",       # Style-color code from SNKRS
       "size": "42.5",                    # EU size
       "launch_time": "2026-03-10 02:00:00",  # UTC time
       ...
   }
   ```

2. Run:

   ```bash
   python snkrs_bot.py
   ```

3. The bot will log in, look up the product, wait for launch, and attempt checkout automatically.

## Configuration Reference

### Account & Product

| Key | Type | Description |
|---|---|---|
| `email` | `str` | Nike account email |
| `password` | `str` | Nike account password |
| `product_id` | `str` | Style-color code (e.g. `"DZ5485-612"`) |
| `size` | `str` | EU shoe size (e.g. `"42.5"`) |
| `launch_time` | `str` | Drop time in UTC, format `"YYYY-MM-DD HH:MM:SS"` |

### Timing & Retry

| Key | Default | Description |
|---|---|---|
| `advance_seconds` | `1.0` | How many seconds before launch to start firing requests |
| `max_retries` | `5` | Number of checkout attempts |
| `timeout` | `10` | HTTP request timeout in seconds |

### Anti-Detection

| Key | Default | Description |
|---|---|---|
| `proxies` | `[]` | List of proxy URLs. Supports `http://`, `socks5://`, and authenticated proxies |
| `rotate_proxy` | `true` | Cycle through proxies on each request |
| `tls_fingerprint` | `"safari_ios17_2"` | TLS impersonation target. Options: `chrome120`, `chrome124`, `safari17_0`, `safari_ios17_2` |
| `device_type` | `"ios"` | Simulated device. Options: `ios`, `android`, `web` |
| `min_delay` | `0.1` | Minimum random delay between requests (seconds) |
| `max_delay` | `0.5` | Maximum random delay between requests (seconds) |

## Architecture

```
SNKRSBot
├── DeviceFingerprint    — Generates consistent device identity per session
├── HeaderRandomizer     — Produces varied but realistic HTTP headers
├── ProxyManager         — Rotates and health-checks proxy pool
└── BehaviorSimulator    — Creates synthetic mouse/touch telemetry
```

**Execution flow:**

```
Login → Product Lookup → SKU Resolution → Wait (with keep-alive) → Checkout (with retries)
```

## Limitations

- **Kasada/Akamai challenges** — The Kasada token generator in this script is a format stub only. If Nike enforces full JS challenge verification, you'll need to integrate a dedicated Kasada solver service.
- **CAPTCHA / 2FA** — The script cannot handle CAPTCHAs or two-factor authentication prompts during login.
- **Payment info** — Your default payment method and shipping address must already be saved in your Nike account.
- **Draw releases** — For raffle/draw drops, a successful submission means you've entered the draw — not guaranteed a pair.
- **API changes** — Nike may change API endpoints, payloads, or authentication flows at any time, which could break the script.

## License

MIT
