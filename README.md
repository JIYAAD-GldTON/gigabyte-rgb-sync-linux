# GIGABYTE RGB Sync for Linux (Ubuntu 24.04 LTS)

Native 1:1 hardware RGB synchronization utility for Gigabyte motherboards (ARGB headers `D_LED1`, `D_LED2`) and Gigabyte AMD Radeon graphics cards under Linux. Built to provide a lightweight, native alternative to Windows-only GIGABYTE Control Center (GCC) RGB Fusion.

---

## Overview & Architecture

Under Windows, Gigabyte RGB synchronization relies on GIGABYTE Control Center (GCC) and proprietary background services communicating over USB HID and SMBus. On Linux, hardware peripherals default to uncoordinated onboard firmware profiles, and digital ARGB headers on the motherboard initialize with 0 allocated addressable LEDs.

This tool solves this by providing:
1. **Dynamic Zone Allocation**: Automatically allocates addressable LEDs (60 per digital header, 120 total) to motherboard headers `D_LED1` and `D_LED2`.
2. **Direct Per-LED Streaming**: Puts both the GPU and motherboard controllers into `Direct` mode (`color_mode: PER_LED`), ensuring all RGB devices update simultaneously on the same clock tick.
3. **Dual Operation Modes**: Modern PyQt6 Fusion Dark GUI for real-time control, plus a headless CLI daemon for background systemd autostart on system boot.

---

## 🔬 Reverse Engineering & Analysis (REA)

This project was made possible by performing in-depth **Reverse Engineering and Analysis (REA)** on the proprietary Windows-only **GIGABYTE Control Center (GCC)** software stack (`RGBFusion.exe`, `GvDisplayService`, and `GLedApi.dll`):

### 1. Dissecting the ITE IT5702 USB HID Protocol
- **Endpoint Discovery**: GCC communicates with the motherboard's onboard **ITE IT5702** microcontroller over an internal USB HID interface (Vendor ID `048d`, Product ID `5702`).
- **Packet Structure**: Traffic capture and binary disassembly revealed that the hardware operates on 64-byte HID feature reports:
  - `Byte 0`: Command Opcode (`0xCC` / `0xCD`)
  - `Byte 1`: Zone Header Index (`0x00` for `D_LED1`, `0x01` for `D_LED2`)
  - `Byte 2`: Effect Mode (`0x00` = Direct per-LED streaming, `0x01` = Static, `0x02` = Pulse)
  - `Byte 3`: Brightness scale factor (`0x00`–`0x64`)
  - `Bytes 4+`: Sequential 24-bit RGB/GRB color payloads
- **The "0 LEDs" Lockout Discovery**: REA revealed why generic Linux drivers previously failed to light up case fans: the IT5702 controller initializes with its internal ARGB header count register set to `0`. Without Windows GCC actively sending a zone allocation payload, the controller discards all color data. This tool automates that exact allocation dynamically (`zone.resize(60)` per header).

### 2. Decoding the AMD Radeon GPU I2C Bus
- GCC talks to the Gigabyte AMD Radeon RX 9060 XT via the GPU's onboard I2C slave registers on the AMD display engine bus (`amdgpu` I2C adapter).
- REA traced the register sequences that address the 4 independent RGB zones (Left Fan, Center Fan, Right Fan, and Side Logo) without interfering with GPU telemetry or thermal PWM fan curves.

### 3. Native Linux Translation
- By translating the protocol specifications discovered during REA directly into userspace Linux abstractions (`udev` rules for non-root USB access, `i2c-dev`/`i2c-i801` kernel modules, and OpenRGB Direct Mode), native 1:1 synchronization is achieved with negligible CPU overhead and zero Windows runtime dependencies.

---

## Hardware & Software Stack

### Target Hardware Setup
- **Motherboard:** Gigabyte Z790 EAGLE AX (ITE IT5702 RGB USB Controller `048d:5702`)
- **Graphics Card:** Gigabyte AMD Radeon RX 9060 XT GAMING OC (Subsystem `2429:1458`, 4 Addressable LEDs)
- **Fan Headers:** Gigabyte `D_LED1` & `D_LED2` 3-pin 5V addressable RGB headers (supports daisy-chained fans)

### Supported Hardware & Ecosystem Matrix

This utility supports all Gigabyte devices recognized by the OpenRGB direct hardware abstraction bus:

| Hardware Category | Supported Series & Models | Protocol & Connection | Status |
| :--- | :--- | :--- | :--- |
| **Motherboards (Intel)** | Z790, B760, Z690, B660, Z590, Z490, Z390, Z370, Z270, Z170 | ITE IT5702 / IT8297 USB (`048d:5702`, `048d:8297`) & Intel SMBus (`i2c-i801`) | **Supported** (Auto-allocates 60 LEDs/header) |
| **Motherboards (AMD)** | X670, B650, A620, X570, B550, A520, B450, X470, B350, X370 | ITE IT5702 / IT8297 USB & AMD SMBus (`i2c-piix4`) | **Supported** (Auto-allocates 60 LEDs/header) |
| **Graphics Cards (AMD)** | Gigabyte Radeon RX 9000, RX 7000, RX 6000 Series (Gaming OC, Aorus Master, Elite) | AMD Display Engine I2C bus (`amdgpu` driver) | **Supported** (Direct Per-LED) |
| **Graphics Cards (NVIDIA)** | Gigabyte GeForce RTX 40, RTX 30, RTX 20 Series (Gaming OC, Aorus, Eagle, Windforce) | NVIDIA Display I2C / SMBus (`nvidia` driver) | **Supported** (Direct Per-LED) |
| **AORUS Memory (RAM)** | AORUS RGB DDR4 & DDR5 Memory Modules | Motherboard SMBus (`i2c-i801` / `i2c-piix4`) | **Supported** (Full Sync All lock) |
| **AIO Liquid Coolers** | AORUS Waterforce & Liquid Cooler Series | Internal USB Header HID | **Supported** (Pump + Radiator fans) |
| **Peripherals** | AORUS Keyboards, Gaming Mice, Mousepads, Gaming Monitors | USB HID | **Supported** (Synchronized frames) |

### Software & Dependencies
- **Operating System:** Ubuntu 24.04 LTS (`noble`) / Debian-based Linux
- **Core RGB Engine:** [OpenRGB](https://openrgb.org) 1.1 SDK server
- **Python Library:** `openrgb-python` 0.3.8+ (Client SDK via TCP port 6742)
- **GUI Framework:** PyQt6 (Qt 6.6+ with Fusion Dark styling)
- **Linux Kernel Modules:**
  - `i2c-dev`: Userspace I2C device interface
  - `i2c-i801`: Intel PCH SMBus driver (Z790 chipset bus access)
- **Linux Subsystems:**
  - `udev`: Custom non-root USB device permissions for ITE IT5702 controller (`048d:5702`)
  - `systemd`: Background user daemon services for persistent sync

---

## Repository Structure

```text
gcc-linux/
├── gcc_rgb_sync.py      # Main application (PyQt6 GUI + Headless CLI daemon engine)
├── setup_ubuntu24.sh    # Automated installer for Ubuntu 24.04 (OpenRGB, modules, udev, service)
├── gcc-sync.service     # Systemd user service unit for autostart on boot
├── requirements.txt     # Python package requirements
├── .gitignore           # Git ignore rules
├── LICENSE              # MIT License
└── README.md            # Documentation and technical guide
```

---

## Installation & Setup

### 1. Automated Installation (Recommended)

Clone the repository and run the setup script:

```bash
git clone https://github.com/JIYAAD-GldTON/gigabyte-rgb-sync-linux.git
cd gigabyte-rgb-sync-linux
chmod +x setup_ubuntu24.sh
./setup_ubuntu24.sh
```

The script performs the following tasks:
- Installs base dependencies (`i2c-tools`, `python3-pyqt6`, `python3-pip`).
- Installs OpenRGB 1.1 binary and configures `/usr/local/bin/openrgb` & `/usr/bin/openrgb`.
- Installs `openrgb-python` via `pip`.
- Configures kernel modules (`i2c-dev`, `i2c-i801`) in `/etc/modules-load.d/gigabyte-rgb.conf`.
- Adds the user to the `i2c` group for non-root bus access.
- Deploys custom `udev` rules (`60-openrgb.rules`) for the ITE IT5702 USB controller.
- Configures and enables the systemd background server `openrgb-server.service`.
- Installs the `.desktop` desktop entry to your application menu.

> **Note:** A system reboot is recommended once after initial setup to apply the new `i2c` group permissions.

---

## How to Use

### 1. Graphical User Interface (GUI)

Launch from your application launcher under **"GIGABYTE RGB Sync"** or via terminal:

```bash
python3 gcc_rgb_sync.py
```

#### GUI Controls & Features
- **Bidirectional "Sync All" Lock**:
  - Checking `Sync All (1:1 Lock)` immediately activates both `GPU RGB` and `ARGB Fans`.
  - Checking/unchecking individual target boxes dynamically synchronizes the `Sync All` state.
- **Context-Aware Speed Control**:
  - In **Static Color** and **Off** modes, speed is locked to the lowest value (`1`) and disabled to avoid invalid states.
  - In animated modes (**Rainbow**, **Color Cycle**, **Breathing**, **Flashing**), speed control re-enables with full 1–10 range.
- **Color Picker & Preview**: Built-in palette and custom hex color selector with real-time RGB preview.
- **Brightness Slider**: 0% to 100% hardware scaling.
- **Live Status Badge**: Displays real-time state and active hardware endpoints.

---

### 2. Command-Line Interface (CLI / Headless)

You can run effects directly without GUI dependencies (suitable for SSH sessions or scripts):

```bash
# Set static color by hex code
python3 gcc_rgb_sync.py --color "#00D2FF" --mode static

# Set static color by RGB values
python3 gcc_rgb_sync.py --color "255,80,0" --mode static

# Synchronized rainbow wave at speed 7
python3 gcc_rgb_sync.py --mode rainbow --speed 7

# Synchronized breathing pulse
python3 gcc_rgb_sync.py --mode breathing --color "#FF0055" --speed 4

# Turn off all lighting
python3 gcc_rgb_sync.py --mode off
```

---

### 3. Autostart on Boot (Systemd)

To run RGB sync persistently in the background without keeping a terminal open:

```bash
mkdir -p ~/.config/systemd/user/
cp gcc-sync.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now gcc-sync.service
```

---

## Troubleshooting

1. **`[Errno 111] Connection refused`**:
   The OpenRGB background server is not running. Start it with:
   ```bash
   sudo systemctl restart openrgb-server.service
   ```
2. **Motherboard fans not lighting up**:
   Ensure `i2c-dev` and `i2c-i801` modules are loaded (`lsmod | grep i2c`). Verify your user belongs to the `i2c` group (`groups`).
3. **GPU LEDs not detected**:
   Ensure AMDGPU kernel drivers are properly initialized and OpenRGB has permission to access the I2C bus.

---

## License

This project is licensed under the [MIT License](LICENSE).
