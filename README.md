# 🐾 Dog Video Game

A Raspberry Pi-powered interactive video game built for dogs. Using large physical arcade buttons, dogs navigate a golden paw cursor across the screen toward a glowing bone. When they complete a level, a treat dispenser fires automatically — rewarding them with a real treat via a stepper motor driven by a repurposed Tevo Tarantula 3D printer control board.

---

## 🗂 Repo Structure

```
Dog-Video-Game/
├── dog_game.py          # Main game + treat dispenser
├── wiring_diagram.svg   # Full GPIO + dispenser wiring reference
├── README.md            # You are here
└── .gitignore
```

---

## 🧰 Hardware Required

| Component | Details |
|-----------|---------|
| Raspberry Pi 3B+ | Any 40-pin Pi works |
| MicroSD Card | 8GB+ — Raspberry Pi OS (64-bit) |
| HDMI TV or Monitor | Full-size HDMI input |
| Micro-USB Power Supply | 2.5A minimum — official Pi PSU recommended |
| 4× Large Push Buttons | Big arcade-style buttons dogs can press |
| Jumper Wires | Connecting buttons to GPIO header |
| Tevo Tarantula Board | MKS Base / RAMPS-style printer control board |
| Stepper Motor | Wired to Y axis port on the printer board |
| USB-A to USB-B Cable | Raspberry Pi → Tevo board |
| 12V Power Supply | Powers the Tevo board + stepper motor |
| Treat Dispenser Mechanism | 3D printed or DIY, driven by the stepper |

---

## ⚡ Wiring

### Button GPIO Connections

Each button needs only **2 wires** — one to the GPIO pin and one to GND. No resistors are required; the Pi's internal pull-up resistors are enabled in software.

| Button | BCM Pin | Physical Pin |
|--------|---------|--------------|
| UP     | GPIO 17 | Pin 11       |
| DOWN   | GPIO 27 | Pin 13       |
| LEFT   | GPIO 22 | Pin 15       |
| RIGHT  | GPIO 23 | Pin 16       |
| GND    | —       | Pin 6 (or any GND pin) |

See [`wiring_diagram.svg`](wiring_diagram.svg) for a full visual diagram.

### Treat Dispenser

| Connection | Details |
|------------|---------|
| Stepper motor | Y axis port on Tevo Tarantula board |
| Tevo board → Pi | USB-A to USB-B cable |
| Tevo board power | 12V PSU (required — Pi USB alone cannot drive the stepper) |
| Communication | G-code over USB serial at 115200 baud |

The game sends these G-code commands to dispense one treat:

```
G91          → relative positioning
G1 Y30 F300  → move Y axis 30mm at 300mm/min (~90° rotation)
G90          → back to absolute positioning
M400         → wait for move to complete
```

---

## 🖥 Software Setup

### 1. Flash Raspberry Pi OS

Download **Raspberry Pi Imager** from [raspberrypi.com/software](https://www.raspberrypi.com/software/). Flash **Raspberry Pi OS (64-bit)** to your SD card. Boot and complete first-run setup.

### 2. Clone This Repo

Open a Terminal on the Pi:

```bash
git clone https://github.com/naatechinc/Dog-Video-Game.git
cd Dog-Video-Game
```

### 3. Install Dependencies

```bash
sudo apt update
sudo apt install python3-pygame -y
pip3 install RPi.GPIO pyserial --break-system-packages
```

### 4. Find Your USB Port

Plug the Tevo board into the Pi, then run:

```bash
ls /dev/ttyUSB*
```

It will likely show `/dev/ttyUSB0`. If different, open `dog_game.py` and update:

```python
DISPENSER_PORT = "/dev/ttyUSB0"   # ← change this line
```

---

## ▶️ Running the Game

```bash
# Full game — physical buttons + treat dispenser
python3 dog_game.py

# Keyboard only (no GPIO, no dispenser) — for testing on any computer
python3 dog_game.py --keyboard

# Keyboard + dispenser — test dispenser without physical buttons
python3 dog_game.py --keyboard --dispenser
```

### Controls

| Input | Action |
|-------|--------|
| UP button / ↑ / W | Move paw up |
| DOWN button / ↓ / S | Move paw down |
| LEFT button / ← / A | Move paw left |
| RIGHT button / → / D | Move paw right |
| ESC | Quit |

---

## 🎮 How It Works

- A golden **paw cursor** starts at one position on the screen
- A glowing red **bone** marks the goal
- The **proximity bar** (top right) fills up as the dog gets closer
- When the paw touches the bone → **"GOOD DOG! 🎉"** screen appears and a treat is dispensed immediately
- The game auto-advances through 5 levels (straight, diagonal, vertical, corner-to-corner, random) then loops
- The **dispenser status** is shown in the bottom-right corner at all times:
  - 🟢 `Dispenser: READY` — connected and working
  - 🔴 `Dispenser: OFF` — not connected, game still runs fine

---

## ⚙️ Tuning the Dispenser

Adjust these two constants near the top of `dog_game.py`:

```python
TREAT_MM       = 30.0   # mm of Y axis travel — increase for more rotation
TREAT_FEEDRATE = 300    # mm/min — decrease for slower, more controlled movement
```

The Tevo Tarantula Y axis runs at **80 steps/mm** by default (GT2 belt, 20T pulley). At that calibration, 30mm of travel ≈ 90° of stepper rotation. Adjust `TREAT_MM` to dial in the exact amount for your dispenser mechanism.

> **Note:** The Y axis stepper driver current (Vref) on the board is tuned for the original Y axis motor. If your dispenser stepper draws different current, you may need to adjust the Vref trim pot on the Y driver to prevent overheating or stalling.

---

## 🔁 Auto-Start on Boot (Optional)

To launch the game automatically when the Pi powers on:

```bash
mkdir -p ~/.config/autostart
nano ~/.config/autostart/dogvideogame.desktop
```

Paste the following:

```ini
[Desktop Entry]
Type=Application
Name=Dog Video Game
Exec=python3 /home/pi/Dog-Video-Game/dog_game.py
```

Save (`Ctrl+O`, Enter, `Ctrl+X`) and reboot. The game will launch on the desktop automatically.

---

## 🔄 Updating the Game

When you push changes from your PC to GitHub, pull them on the Pi with:

```bash
cd Dog-Video-Game
git pull
```

---

## 🐛 Troubleshooting

| Problem | Fix |
|---------|-----|
| Blank screen on boot | Plug HDMI in **before** powering the Pi on. Use the port closest to the power connector. |
| "display" error when running | Boot to desktop: `sudo raspi-config` → System Options → Boot → Desktop |
| Dispenser not found | Run `ls /dev/ttyUSB*`, confirm port matches `DISPENSER_PORT`. Confirm 12V PSU is powering the board. |
| GPIO permission error | Run `sudo python3 dog_game.py` or: `sudo usermod -aG gpio $USER` then reboot |
| Buttons not responding | Each button connects GPIO pin to GND when pressed. Verify with `gpio readall`. |
| Stepper stalls or overheats | Adjust Vref trim pot on Y axis driver chip on the Tevo board to match your motor's rated current. |

---

## 📄 License

MIT License — free to use, modify, and share.

---

## 🙏 Built With

- [Python 3](https://python.org)
- [Pygame](https://pygame.org)
- [RPi.GPIO](https://pypi.org/project/RPi.GPIO/)
- [PySerial](https://pyserial.readthedocs.io/)
- Tevo Tarantula 3D printer control board (repurposed)
- A lot of love for dogs 🐕
