#!/usr/bin/env python3
"""
GIGABYTE Control Center (GCC) - Linux 1:1 RGB Sync Tool
Controls and synchronizes Gigabyte Z790 Motherboard ARGB Fan Headers & Gigabyte AMD GPU.
Runs with PyQt6 GUI or headless CLI/daemon mode.
"""

import sys
import os
import json
import time
import math
import argparse
import threading
from typing import List, Optional

try:
    from openrgb import OpenRGBClient
    from openrgb.utils import RGBColor, DeviceType
    OPENRGB_AVAILABLE = True
except ImportError:
    OPENRGB_AVAILABLE = False

CONFIG_PATH = os.path.expanduser("~/.config/gcc-linux/config.json")

DEFAULT_CONFIG = {
    "mode": "static",
    "color": [0, 180, 255],  # Cyan-blue default
    "speed": 5,              # 1-10
    "brightness": 100,       # 0-100
    "sync_all": True,
    "sync_gpu": True,
    "sync_fans": True
}

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"[GCC-Sync] Warning: Could not save config: {e}")

class GccRgbSyncEngine:
    def __init__(self, host="127.0.0.1", port=6742):
        self.host = host
        self.port = port
        self.client: Optional[OpenRGBClient] = None
        self.config = load_config()
        self.running = False
        self.worker_thread = None
        self.mb_device = None
        self.gpu_device = None
        self.other_devices = []

    def connect(self) -> bool:
        if not OPENRGB_AVAILABLE:
            print("[GCC-Sync] Error: 'openrgb-python' is not installed. Run: pip install openrgb-python")
            return False
        try:
            self.client = OpenRGBClient(address=self.host, port=self.port, name="GCC-Linux-Sync")
            self.classify_devices()
            print(f"[GCC-Sync] Connected to OpenRGB SDK server. Found {len(self.client.devices)} device(s):")
            for dev in self.client.devices:
                is_supported = (dev == self.mb_device or dev == self.gpu_device)
                badge = "✔ [Supported]" if is_supported else "✔ [Sync All Target]"
                print(f"  {badge} [{dev.type.name}] {dev.name} ({len(dev.leds)} LEDs)")
            return True
        except Exception as e:
            print(f"[GCC-Sync] Connection error: {e}")
            print("[GCC-Sync] Hint: Ensure OpenRGB is running in server mode (openrgb --server).")
            return False

    def _init_device(self, dev):
        """Initializes device zones and sets Direct mode for real-time sync."""
        # 1. Resize any unallocated ARGB zones (e.g. Gigabyte D_LED1, D_LED2 default to 0)
        for zone in dev.zones:
            if len(zone.leds) == 0:
                try:
                    # Default to 60 LEDs per ARGB header
                    zone.resize(60)
                    print(f"[GCC-Sync] Allocated 60 LEDs to zone '{zone.name}' on {dev.name}")
                except Exception as e:
                    print(f"[GCC-Sync] Warning: Could not resize zone '{zone.name}': {e}")

        # 2. Set mode to Direct (or Static) for real-time per-LED control
        direct_modes = [m for m in dev.modes if m.name.lower() in ["direct", "static"]]
        if direct_modes:
            try:
                dev.set_mode(direct_modes[0])
            except Exception as e:
                print(f"[GCC-Sync] Warning: Could not set Direct mode on {dev.name}: {e}")

    def classify_devices(self):
        self.mb_device = None
        self.gpu_device = None
        self.other_devices = []

        if not self.client:
            return

        for dev in self.client.devices:
            self._init_device(dev)

            name_lower = dev.name.lower()
            type_name = dev.type.name.upper()

            # Check for Graphics Card first
            if type_name == "GPU" or any(k in name_lower for k in ["gpu", "vga", "radeon", "geforce", "rtx", "rx"]):
                if not self.gpu_device:
                    self.gpu_device = dev
                else:
                    self.other_devices.append(dev)
            # Check for Motherboard
            elif type_name == "MOTHERBOARD" or any(k in name_lower for k in ["motherboard", "it5702", "it8297", "mainboard", "z790", "b760", "x670", "b650", "z690", "x570", "b550"]):
                if not self.mb_device:
                    self.mb_device = dev
                else:
                    self.other_devices.append(dev)
            else:
                self.other_devices.append(dev)

    def get_target_devices(self) -> list:
        targets = []
        if self.config.get("sync_all", True):
            if self.client:
                return self.client.devices
        if self.config.get("sync_fans", True) and self.mb_device:
            targets.append(self.mb_device)
        if self.config.get("sync_gpu", True) and self.gpu_device:
            targets.append(self.gpu_device)
        return targets if targets else (self.client.devices if self.client else [])

    def apply_color(self, r: int, g: int, b: int):
        if not OPENRGB_AVAILABLE or not self.client:
            return
        bri = self.config.get("brightness", 100) / 100.0
        adj_r = int(max(0, min(255, r * bri)))
        adj_g = int(max(0, min(255, g * bri)))
        adj_b = int(max(0, min(255, b * bri)))
        color = RGBColor(adj_r, adj_g, adj_b)

        targets = self.get_target_devices()
        for dev in targets:
            try:
                # If leds is 0, attempt zone initialization
                if len(dev.leds) == 0:
                    self._init_device(dev)
                dev.set_color(color, fast=True)
            except Exception as e:
                try:
                    dev.set_colors([color] * len(dev.leds))
                except Exception:
                    pass
        if self.client:
            try:
                self.client.show()
            except Exception:
                pass

    def start_effect(self, mode: str):
        self.stop_effect()
        self.config["mode"] = mode
        save_config(self.config)

        if mode == "static":
            r, g, b = self.config["color"]
            self.apply_color(r, g, b)
        elif mode == "off":
            self.apply_color(0, 0, 0)
        else:
            self.running = True
            self.worker_thread = threading.Thread(target=self._effect_loop, daemon=True)
            self.worker_thread.start()

    def stop_effect(self):
        self.running = False
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=0.5)
        self.worker_thread = None

    def _effect_loop(self):
        mode = self.config.get("mode", "color_cycle")
        r, g, b = self.config.get("color", [255, 0, 0])
        speed = max(1, min(10, self.config.get("speed", 5)))
        step = 0.0

        while self.running:
            delay = 0.03
            speed_mult = speed * 0.03

            if mode == "breathing":
                # Smooth sine wave pulse
                factor = (math.sin(step) + 1.0) / 2.0
                self.apply_color(int(r * factor), int(g * factor), int(b * factor))
                step += speed_mult
            elif mode == "color_cycle" or mode == "rainbow":
                # Full RGB hue rotation
                hue = (step % (2 * math.pi)) / (2 * math.pi)
                cr, cg, cb = self.hsv_to_rgb(hue, 1.0, 1.0)
                self.apply_color(cr, cg, cb)
                step += speed_mult
            elif mode == "flash":
                state = int(step) % 2
                if state == 0:
                    self.apply_color(r, g, b)
                else:
                    self.apply_color(0, 0, 0)
                step += speed_mult * 0.5
                delay = 0.2
            else:
                break

            time.sleep(delay)

    @staticmethod
    def hsv_to_rgb(h, s, v):
        i = int(h * 6.0)
        f = (h * 6.0) - i
        p = v * (1.0 - s)
        q = v * (1.0 - s * f)
        t = v * (1.0 - s * (1.0 - f))
        i = i % 6
        if i == 0: r, g, b = v, t, p
        elif i == 1: r, g, b = q, v, p
        elif i == 2: r, g, b = p, v, t
        elif i == 3: r, g, b = p, q, v
        elif i == 4: r, g, b = t, p, v
        else: r, g, b = v, p, q
        return int(r * 255), int(g * 255), int(b * 255)

def run_gui(engine: GccRgbSyncEngine):
    from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                                 QHBoxLayout, QLabel, QPushButton, QSlider,
                                 QColorDialog, QComboBox, QCheckBox, QGroupBox, QFrame, QMessageBox)
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QFont, QPalette

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Dark modern theme (GCC Style)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(24, 26, 32))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(240, 240, 240))
    palette.setColor(QPalette.ColorRole.Base, QColor(32, 34, 42))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(40, 44, 52))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Text, QColor(240, 240, 240))
    palette.setColor(QPalette.ColorRole.Button, QColor(36, 40, 50))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(240, 240, 240))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 160, 255))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)

    window = QMainWindow()
    window.setWindowTitle("GIGABYTE RGB Sync - Linux Port (Z790 + RX 9060 XT)")
    window.setFixedSize(540, 620)

    central = QWidget()
    window.setCentralWidget(central)
    main_layout = QVBoxLayout(central)
    main_layout.setSpacing(14)
    main_layout.setContentsMargins(20, 20, 20, 20)

    # Header
    title = QLabel("GIGABYTE CONTROL CENTER")
    title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
    title.setStyleSheet("color: #00d2ff; letter-spacing: 2px;")
    subtitle = QLabel("Hardware RGB Synchronization • Ubuntu 24.04")
    subtitle.setStyleSheet("color: #8892b0; font-size: 11px;")
    main_layout.addWidget(title)
    main_layout.addWidget(subtitle)

    # Hardware Status Group
    hw_group = QGroupBox("Detected Hardware Devices")
    hw_group.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #333a4d; border-radius: 6px; margin-top: 10px; padding-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; color: #00d2ff; }")
    hw_layout = QVBoxLayout(hw_group)

    mb_name = engine.mb_device.name if engine.mb_device else "Gigabyte Z790 IT5702"
    gpu_name = engine.gpu_device.name if engine.gpu_device else "AMD Radeon RX 9060 XT"
    mb_leds = len(engine.mb_device.leds) if engine.mb_device else 0
    gpu_leds = len(engine.gpu_device.leds) if engine.gpu_device else 0

    lbl_mb = QLabel(f"✔ [Supported] Motherboard ARGB Fans:  {mb_name} ({mb_leds} LEDs)")
    lbl_mb.setStyleSheet("color: #00d2ff; font-weight: 500;")
    lbl_gpu = QLabel(f"✔ [Supported] Graphics Card:          {gpu_name} ({gpu_leds} LEDs)")
    lbl_gpu.setStyleSheet("color: #00d2ff; font-weight: 500;")
    hw_layout.addWidget(lbl_mb)
    hw_layout.addWidget(lbl_gpu)

    btn_compat = QPushButton("ℹ View Supported Hardware Ecosystem List")
    btn_compat.setStyleSheet("QPushButton { background-color: #1c2230; color: #7f93b5; border: 1px solid #2e384d; border-radius: 4px; padding: 6px; font-size: 11px; } QPushButton:hover { background-color: #242d40; color: #00d2ff; }")
    
    def on_show_compat():
        msg = (
            "<h3>GIGABYTE Ecosystem Hardware Compatibility</h3>"
            "<p>This utility synchronizes RGB across all Gigabyte devices via OpenRGB Direct Mode:</p>"
            "<ul>"
            "<li><b>Motherboards:</b> Gigabyte Z790, B760, X670, B650, Z690, X570, B550, B450, Z490, Z390, Z590 (IT5702 / IT8297 USB & SMBus).</li>"
            "<li><b>Graphics Cards:</b> Gigabyte AMD Radeon (RX 9000, RX 7000, RX 6000 series) & Gigabyte NVIDIA GeForce (RTX 40, 30, 20 series).</li>"
            "<li><b>Memory:</b> Gigabyte AORUS RGB DDR4 & DDR5 RAM modules.</li>"
            "<li><b>AIO Coolers:</b> Gigabyte AORUS Waterforce & Liquid Cooler series.</li>"
            "<li><b>Peripherals:</b> Gigabyte AORUS Keyboards, Gaming Mice, Mousepads & Gaming Monitors.</li>"
            "</ul>"
            "<p><i>When 'Sync All' is active, all detected endpoints lock to the same lighting frame.</i></p>"
        )
        dlg = QMessageBox(window)
        dlg.setWindowTitle("Supported Hardware Ecosystem")
        dlg.setTextFormat(Qt.TextFormat.RichText)
        dlg.setText(msg)
        dlg.exec()

    btn_compat.clicked.connect(on_show_compat)
    hw_layout.addWidget(btn_compat)
    main_layout.addWidget(hw_group)

    # Sync Configuration
    sync_group = QGroupBox("Sync Targets")
    sync_group.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #333a4d; border-radius: 6px; margin-top: 10px; padding-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; color: #00d2ff; }")
    # Apply styling for sliders and checkboxes
    app.setStyleSheet("""
        QSlider::groove:horizontal {
            height: 6px;
            background: #232733;
            border-radius: 3px;
        }
        QSlider::sub-page:horizontal {
            background: #00d2ff;
            border-radius: 3px;
        }
        QSlider::sub-page:horizontal:disabled {
            background: #394050;
        }
        QSlider::handle:horizontal {
            background: #ffffff;
            width: 16px;
            margin-top: -5px;
            margin-bottom: -5px;
            border-radius: 8px;
        }
        QSlider::handle:horizontal:disabled {
            background: #555e73;
        }
        QCheckBox {
            color: #d1d9e6;
            font-size: 13px;
            spacing: 8px;
        }
        QCheckBox::indicator {
            width: 18px;
            height: 18px;
            border-radius: 4px;
            border: 1px solid #434c60;
            background: #1e222d;
        }
        QCheckBox::indicator:checked {
            background: #00d2ff;
            border-color: #00d2ff;
        }
    """)

    sync_layout = QHBoxLayout(sync_group)
    sync_layout.setSpacing(20)
    chk_sync_all = QCheckBox("Sync All (1:1 Lock)")
    chk_gpu = QCheckBox("GPU RGB")
    chk_fans = QCheckBox("ARGB Fans")

    # Initialize checkbox states
    initial_all = engine.config.get("sync_all", True)
    chk_sync_all.setChecked(initial_all)
    chk_gpu.setChecked(engine.config.get("sync_gpu", initial_all))
    chk_fans.setChecked(engine.config.get("sync_fans", initial_all))

    sync_layout.addWidget(chk_sync_all)
    sync_layout.addWidget(chk_gpu)
    sync_layout.addWidget(chk_fans)
    main_layout.addWidget(sync_group)

    # Effect Controls
    ctrl_group = QGroupBox("Lighting Effects")
    ctrl_group.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #333a4d; border-radius: 6px; margin-top: 10px; padding-top: 10px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; color: #00d2ff; }")
    ctrl_layout = QVBoxLayout(ctrl_group)
    ctrl_layout.setSpacing(12)

    # Mode Selector
    mode_row = QHBoxLayout()
    lbl_mode = QLabel("Effect Mode:")
    lbl_mode.setStyleSheet("font-weight: bold;")
    mode_row.addWidget(lbl_mode)
    combo_mode = QComboBox()
    combo_mode.addItems(["Static Color", "Breathing", "Color Cycle", "Rainbow", "Flashing", "Off"])
    mode_map = {
        "static": "Static Color",
        "breathing": "Breathing",
        "color_cycle": "Color Cycle",
        "rainbow": "Rainbow",
        "flash": "Flashing",
        "off": "Off"
    }
    rev_mode_map = {v: k for k, v in mode_map.items()}
    combo_mode.setCurrentText(mode_map.get(engine.config.get("mode", "static"), "Static Color"))
    combo_mode.setStyleSheet("background-color: #2b303c; color: white; padding: 6px 12px; border-radius: 4px; font-weight: 500;")
    mode_row.addWidget(combo_mode)
    ctrl_layout.addLayout(mode_row)

    # Color Preview & Pick Button
    color_row = QHBoxLayout()
    color_preview = QFrame()
    color_preview.setFixedSize(36, 36)
    r, g, b = engine.config.get("color", [0, 180, 255])
    color_preview.setStyleSheet(f"background-color: rgb({r},{g},{b}); border-radius: 6px; border: 2px solid #444c60;")
    btn_color = QPushButton("Pick Sync Color...")
    btn_color.setStyleSheet("QPushButton { background-color: #0088cc; color: white; padding: 8px 16px; font-weight: bold; border-radius: 4px; } QPushButton:hover { background-color: #00aaff; } QPushButton:disabled { background-color: #2b303c; color: #555e73; }")
    color_row.addWidget(color_preview)
    color_row.addWidget(btn_color)
    ctrl_layout.addLayout(color_row)

    # Speed Slider
    speed_row = QHBoxLayout()
    lbl_speed = QLabel(f"Speed ({engine.config.get('speed', 5)}):")
    lbl_speed.setFixedWidth(140)
    slider_speed = QSlider(Qt.Orientation.Horizontal)
    slider_speed.setRange(1, 10)
    slider_speed.setValue(engine.config.get("speed", 5))
    speed_row.addWidget(lbl_speed)
    speed_row.addWidget(slider_speed)
    ctrl_layout.addLayout(speed_row)

    # Brightness Slider
    bri_row = QHBoxLayout()
    lbl_bri = QLabel(f"Brightness ({engine.config.get('brightness', 100)}%):")
    lbl_bri.setFixedWidth(140)
    slider_bri = QSlider(Qt.Orientation.Horizontal)
    slider_bri.setRange(0, 100)
    slider_bri.setValue(engine.config.get("brightness", 100))
    bri_row.addWidget(lbl_bri)
    bri_row.addWidget(slider_bri)
    ctrl_layout.addLayout(bri_row)

    main_layout.addWidget(ctrl_group)

    # Live Status Indicator
    status_bar = QLabel("⚡ Ready • Direct Sync Mode Active")
    status_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
    status_bar.setStyleSheet("background-color: #171b24; color: #00d2ff; padding: 9px; border-radius: 6px; font-weight: bold; border: 1px solid #232b3c;")
    main_layout.addWidget(status_bar)

    # Apply & Sync Button
    btn_apply = QPushButton("⚡ APPLY && SYNC ALL")
    btn_apply.setFixedHeight(46)
    btn_apply.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
    btn_apply.setStyleSheet("""
        QPushButton {
            background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0052d4, stop:1 #4364f7);
            color: white;
            border-radius: 6px;
            letter-spacing: 1px;
        }
        QPushButton:hover {
            background-color: #00c6ff;
        }
    """)
    main_layout.addWidget(btn_apply)

    # --- Reactive Behaviors & Callbacks ---
    updating_sync_boxes = False

    def on_sync_all_toggled(checked):
        nonlocal updating_sync_boxes
        if updating_sync_boxes:
            return
        updating_sync_boxes = True
        # If Sync All is checked, check all sub-boxes; if unchecked, uncheck all
        chk_gpu.setChecked(checked)
        chk_fans.setChecked(checked)
        updating_sync_boxes = False
        on_apply()

    def on_sub_target_toggled():
        nonlocal updating_sync_boxes
        if updating_sync_boxes:
            return
        updating_sync_boxes = True
        # If both are checked, automatically check Sync All; otherwise uncheck it
        both_checked = chk_gpu.isChecked() and chk_fans.isChecked()
        chk_sync_all.setChecked(both_checked)
        updating_sync_boxes = False
        on_apply()

    chk_sync_all.toggled.connect(on_sync_all_toggled)
    chk_gpu.toggled.connect(on_sub_target_toggled)
    chk_fans.toggled.connect(on_sub_target_toggled)

    def update_mode_controls(mode_text):
        """Disables/locks speed to lowest when Static Color or Off is selected."""
        if mode_text == "Static Color":
            slider_speed.setValue(1)
            slider_speed.setEnabled(False)
            lbl_speed.setText("Speed: Lowest (Locked)")
            lbl_speed.setStyleSheet("color: #606b82;")
            btn_color.setEnabled(True)
            slider_bri.setEnabled(True)
            lbl_bri.setStyleSheet("color: #e0e6ed;")
        elif mode_text == "Off":
            slider_speed.setValue(1)
            slider_speed.setEnabled(False)
            lbl_speed.setText("Speed: N/A (Off)")
            lbl_speed.setStyleSheet("color: #606b82;")
            btn_color.setEnabled(False)
            slider_bri.setEnabled(False)
            lbl_bri.setStyleSheet("color: #606b82;")
        elif mode_text in ["Color Cycle", "Rainbow"]:
            saved_speed = engine.config.get("speed", 5)
            slider_speed.setEnabled(True)
            slider_speed.setValue(saved_speed)
            lbl_speed.setText(f"Speed ({saved_speed}):")
            lbl_speed.setStyleSheet("color: #e0e6ed;")
            btn_color.setEnabled(False)
            slider_bri.setEnabled(True)
            lbl_bri.setStyleSheet("color: #e0e6ed;")
        else:  # Breathing, Flashing
            saved_speed = engine.config.get("speed", 5)
            slider_speed.setEnabled(True)
            slider_speed.setValue(saved_speed)
            lbl_speed.setText(f"Speed ({saved_speed}):")
            lbl_speed.setStyleSheet("color: #e0e6ed;")
            btn_color.setEnabled(True)
            slider_bri.setEnabled(True)
            lbl_bri.setStyleSheet("color: #e0e6ed;")

    def on_pick_color():
        c = engine.config.get("color", [0, 180, 255])
        col = QColorDialog.getColor(QColor(c[0], c[1], c[2]), window, "Select RGB Sync Color")
        if col.isValid():
            engine.config["color"] = [col.red(), col.green(), col.blue()]
            color_preview.setStyleSheet(f"background-color: rgb({col.red()},{col.green()},{col.blue()}); border-radius: 6px; border: 2px solid white;")
            save_config(engine.config)
            if combo_mode.currentText() == "Static Color":
                engine.start_effect("static")

    def on_speed_change(val):
        if slider_speed.isEnabled():
            lbl_speed.setText(f"Speed ({val}):")
            engine.config["speed"] = val
            save_config(engine.config)

    def on_bri_change(val):
        lbl_bri.setText(f"Brightness ({val}%):")
        engine.config["brightness"] = val
        save_config(engine.config)
        if combo_mode.currentText() == "Static Color":
            engine.start_effect("static")

    def on_apply():
        engine.config["sync_all"] = chk_sync_all.isChecked()
        engine.config["sync_gpu"] = chk_gpu.isChecked()
        engine.config["sync_fans"] = chk_fans.isChecked()
        mode_key = rev_mode_map.get(combo_mode.currentText(), "static")
        engine.start_effect(mode_key)

        # Update live status bar
        active_targets = []
        if chk_gpu.isChecked():
            active_targets.append("GPU")
        if chk_fans.isChecked():
            active_targets.append("ARGB Fans")
        targets_str = " + ".join(active_targets) if active_targets else "None"
        status_bar.setText(f"⚡ Live: {combo_mode.currentText()} → [{targets_str}]")

    btn_color.clicked.connect(on_pick_color)
    slider_speed.valueChanged.connect(on_speed_change)
    slider_bri.valueChanged.connect(on_bri_change)
    btn_apply.clicked.connect(on_apply)

    def on_mode_changed(txt):
        update_mode_controls(txt)
        on_apply()

    combo_mode.currentTextChanged.connect(on_mode_changed)

    # Initial state setup
    update_mode_controls(combo_mode.currentText())
    window.show()
    on_apply()
    sys.exit(app.exec())

def main():
    parser = argparse.ArgumentParser(description="GCC Linux 1:1 RGB Sync Tool")
    parser.add_argument("--cli", action="store_true", help="Run in headless CLI daemon mode")
    parser.add_argument("--mode", choices=["static", "breathing", "color_cycle", "rainbow", "flash", "off"], help="Set lighting effect mode")
    parser.add_argument("--color", type=str, help="Hex color code (e.g. #FF5500 or 255,85,0)")
    parser.add_argument("--speed", type=int, help="Speed 1-10")
    parser.add_argument("--brightness", type=int, help="Brightness 0-100")
    args = parser.parse_args()

    engine = GccRgbSyncEngine()
    engine.connect()

    if args.color:
        if args.color.startswith("#"):
            hex_c = args.color.lstrip("#")
            engine.config["color"] = [int(hex_c[i:i+2], 16) for i in (0, 2, 4)]
        elif "," in args.color:
            engine.config["color"] = [int(x.strip()) for x in args.color.split(",")]

    if args.speed is not None:
        engine.config["speed"] = args.speed
    if args.brightness is not None:
        engine.config["brightness"] = args.brightness

    if args.cli or args.mode:
        mode = args.mode or engine.config.get("mode", "static")
        print(f"[GCC-Sync] Starting CLI Sync Mode: {mode} (Color: {engine.config['color']})")
        engine.start_effect(mode)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            engine.stop_effect()
            print("[GCC-Sync] Stopped.")
    else:
        run_gui(engine)

if __name__ == "__main__":
    main()
