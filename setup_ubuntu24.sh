#!/usr/bin/env bash
# ==============================================================================
# GIGABYTE Control Center (GCC) RGB Sync - Automated Setup for Ubuntu 24.04 LTS
# Target: Gigabyte Z790 EAGLE AX (IT5702 ARGB Headers) + AMD Radeon RX 9060 XT
# ==============================================================================

set -e

echo "=========================================================="
echo "  GIGABYTE RGB Sync - Ubuntu 24.04 Automated Installer"
echo "=========================================================="

if [ "$EUID" -eq 0 ]; then
  echo "[-] Please run this script as your normal user (without sudo)."
  echo "    The script will prompt for sudo when needed."
  exit 1
fi

USER_NAME=$(whoami)

echo "[1/6] Cleaning up old PPAs & checking base dependencies..."
# Remove broken/incompatible Launchpad PPA before apt update
sudo rm -f /etc/apt/sources.list.d/*thopiekar* 2>/dev/null || true
sudo apt update
sudo apt install -y software-properties-common curl wget git i2c-tools python3 python3-pip python3-pyqt6

echo "[2/6] Installing OpenRGB for Ubuntu 24.04 LTS..."
OPENRGB_BIN_URL="https://codeberg.org/OpenRGB/OpenRGB/releases/download/release_1.1/OpenRGB_1.1_x86_64_8e16de2.AppImage"
if [ -f "/tmp/OpenRGB.AppImage" ]; then
    sudo cp /tmp/OpenRGB.AppImage /usr/local/bin/openrgb
else
    sudo wget -q -O /usr/local/bin/openrgb "$OPENRGB_BIN_URL"
fi
sudo chmod +x /usr/local/bin/openrgb
sudo ln -sf /usr/local/bin/openrgb /usr/bin/openrgb

echo "[3/6] Installing OpenRGB Python SDK..."
python3 -m pip install --break-system-packages openrgb-python || python3 -m pip install openrgb-python

echo "[4/6] Configuring Linux Kernel Modules for Gigabyte SMBus & I2C..."
# Add i2c-i801 (Intel Z790 chipset) and i2c-dev (userspace i2c)
sudo tee /etc/modules-load.d/gigabyte-rgb.conf > /dev/null << 'EOF'
i2c-dev
i2c-i801
EOF

sudo modprobe i2c-dev || true
sudo modprobe i2c-i801 || true

# Add current user to i2c group for permission to access GPU & MB buses
sudo usermod -aG i2c "$USER_NAME" || true

echo "[5/6] Installing udev rules for Gigabyte IT5702 USB & OpenRGB..."
# Download official OpenRGB udev rules
sudo wget -q -O /etc/udev/rules.d/60-openrgb.rules \
    https://gitlab.com/CalcProgrammer1/OpenRGB/-/raw/master/60-openrgb.rules || true

# Explicit rule for Gigabyte Z790 IT5702 USB RGB Controller (048d:5702)
sudo tee -a /etc/udev/rules.d/60-openrgb.rules > /dev/null << 'EOF'
# Gigabyte IT5702 USB RGB Controller (Z790 Motherboard)
SUBSYSTEMS=="usb", ATTRS{idVendor}=="048d", ATTRS{idProduct}=="5702", TAG+="uaccess", MODE="0666"
KERNEL=="hidraw*", ATTRS{idVendor}=="048d", ATTRS{idProduct}=="5702", TAG+="uaccess", MODE="0666"
EOF

sudo udevadm control --reload-rules
sudo udevadm trigger

echo "[6/6] Creating OpenRGB Server & GCC Sync Systemd Services..."
# OpenRGB headless server service (starts on boot)
sudo tee /etc/systemd/system/openrgb-server.service > /dev/null << EOF
[Unit]
Description=OpenRGB Headless SDK Server
After=network.target

[Service]
Type=simple
User=$USER_NAME
ExecStart=/usr/bin/openrgb --server
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now openrgb-server.service

# Desktop Application Shortcut
mkdir -p ~/.local/share/applications
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cat > ~/.local/share/applications/gcc-rgb-sync.desktop << EOF
[Desktop Entry]
Name=GIGABYTE RGB Sync
Comment=Synchronize Motherboard ARGB Fans and AMD GPU RGB
Exec=python3 $SCRIPT_DIR/gcc_rgb_sync.py
Icon=preferences-color
Terminal=false
Type=Application
Categories=Utility;Settings;HardwareSettings;
EOF

chmod +x "$SCRIPT_DIR/gcc_rgb_sync.py"

echo "=========================================================="
echo "  [SUCCESS] GIGABYTE RGB Sync has been successfully installed!"
echo "=========================================================="
echo " "
echo "Next Steps:"
echo " 1. To start the GUI right now, run:"
echo "    python3 $SCRIPT_DIR/gcc_rgb_sync.py"
echo " "
echo " 2. Or search for 'GIGABYTE RGB Sync' in your Ubuntu application menu."
echo " "
echo " 3. If running over CLI or in background on boot:"
echo "    python3 $SCRIPT_DIR/gcc_rgb_sync.py --cli --mode color_cycle"
echo " "
echo "Note: A system reboot is recommended once to apply the new i2c group permissions."
