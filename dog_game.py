#!/usr/bin/env python3
"""
🐾 DOG VIDEO GAME 🐾
A simple cursor navigation game for dogs using a Raspberry Pi and big
physical buttons. Dogs navigate a paw cursor to a bone to win a treat.

Treat dispenser uses a stepper motor wired to the Y axis port on a
Tevo Tarantula (MKS Base / RAMPS-style) board connected via USB.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BUTTON WIRING  (BCM pin numbers)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  UP    → GPIO 17  (Physical Pin 11)
  DOWN  → GPIO 27  (Physical Pin 13)
  LEFT  → GPIO 22  (Physical Pin 15)
  RIGHT → GPIO 23  (Physical Pin 16)
  GND   → Pin 6 (or any GND pin)

Each button: one wire to GPIO pin, other wire to GND.
No resistors needed — internal pull-ups are enabled in software.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TREAT DISPENSER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  - Stepper motor → Y axis port on Tevo Tarantula board
  - Tevo board → Pi via USB cable
  - Tevo board powered by its 12V PSU (not Pi USB)
  - Game sends G-code over serial: G1 Y<mm> to rotate ~90°
  - Default port: /dev/ttyUSB0
    Run `ls /dev/ttyUSB*` on Pi to confirm your port

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INSTALL DEPENDENCIES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  sudo apt update
  sudo apt install python3-pygame -y
  pip3 install RPi.GPIO pyserial --break-system-packages

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RUN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  python3 dog_game.py                        # full game
  python3 dog_game.py --keyboard             # keyboard only, no GPIO/dispenser
  python3 dog_game.py --keyboard --dispenser # keyboard + test dispenser
"""

import pygame
import sys
import math
import random
import time
import argparse
import threading


# ══════════════════════════════════════════════════════════════════════════════
#  TREAT DISPENSER  —  Y axis on Tevo Tarantula board via USB serial / G-code
# ══════════════════════════════════════════════════════════════════════════════

DISPENSER_PORT  = "/dev/ttyUSB0"   # update if `ls /dev/ttyUSB*` shows different
DISPENSER_BAUD  = 115200           # Tevo Tarantula / MKS Base default baud rate

# Rotation tuning:
# Tevo Y axis = 80 steps/mm (GT2 belt, 20T pulley).
# ~30mm of travel ≈ 90° rotation of the dispenser mechanism.
# Increase TREAT_MM for more rotation, decrease for less.
TREAT_MM        = 30.0             # mm of Y axis travel per treat
TREAT_FEEDRATE  = 300              # mm/min — keep slow for reliable dispensing


def init_dispenser(force=False):
    """
    Open USB serial connection to the Tevo board.
    Returns a serial.Serial object on success, None on failure.
    The game runs normally whether or not the dispenser is connected.
    """
    try:
        import serial
        ser = serial.Serial(DISPENSER_PORT, DISPENSER_BAUD, timeout=3)
        time.sleep(2)        # board resets on serial open — wait for it
        ser.flushInput()
        # M110 N0  — reset G-code line counter
        # M211 S0  — disable software endstops so Y can move freely
        for cmd in ["M110 N0", "M211 S0"]:
            ser.write((cmd + "\n").encode())
            time.sleep(0.1)
        print(f"✅ Treat dispenser ready on {DISPENSER_PORT} (Y axis)")
        return ser
    except ImportError:
        print("⚠️  pyserial not installed — dispenser disabled.")
        print("    Fix: pip3 install pyserial --break-system-packages")
        return None
    except Exception as e:
        if force:
            print(f"❌ Cannot open dispenser port {DISPENSER_PORT}: {e}")
        else:
            print(f"⚠️  Dispenser not found on {DISPENSER_PORT} — running without it.")
            print( "    Check USB cable or update DISPENSER_PORT at top of script.")
        return None


def dispense_treat(ser):
    """
    Rotate the Y axis stepper ~90° to dispense one treat.
    Runs in a background thread so the game never pauses waiting for G-code.

    G-code sent:
      G91           — relative positioning mode
      G1 Y## F###   — move Y axis TREAT_MM at TREAT_FEEDRATE
      G90           — back to absolute positioning mode
      M400          — wait for all moves to complete (board-side)
    """
    if ser is None:
        print("🦴 (Dispenser not connected — would dispense treat now)")
        return

    def _send():
        try:
            cmds = [
                "G91",
                f"G1 Y{TREAT_MM:.1f} F{TREAT_FEEDRATE}",
                "G90",
                "M400",
            ]
            for cmd in cmds:
                ser.write((cmd + "\n").encode())
                time.sleep(0.05)
            print("🦴 Treat dispensed!")
        except Exception as e:
            print(f"⚠️  Dispenser send error: {e}")

    threading.Thread(target=_send, daemon=True).start()


def close_dispenser(ser):
    """Cleanly close serial port on exit."""
    if ser:
        try:
            ser.close()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
#  GPIO  —  Physical button inputs on Raspberry Pi 3B+
# ══════════════════════════════════════════════════════════════════════════════

GPIO_PINS = {
    "UP":    17,
    "DOWN":  27,
    "LEFT":  22,
    "RIGHT": 23,
}


def init_gpio():
    """Set up BCM GPIO pins with internal pull-ups. Returns GPIO module or None."""
    try:
        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM)
        for pin in GPIO_PINS.values():
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        print("✅ GPIO buttons initialized.")
        return GPIO
    except ImportError:
        print("⚠️  RPi.GPIO not found — keyboard mode only.")
        return None
    except Exception as e:
        print(f"⚠️  GPIO error ({e}) — keyboard mode only.")
        return None


def read_gpio(GPIO):
    """Return dict of pressed state for each direction. Active LOW."""
    pressed = {d: False for d in GPIO_PINS}
    if GPIO:
        for direction, pin in GPIO_PINS.items():
            pressed[direction] = (GPIO.input(pin) == GPIO.LOW)
    return pressed


# ══════════════════════════════════════════════════════════════════════════════
#  GAME CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

FPS           = 60
CURSOR_SPEED  = 6      # pixels per frame while button held
CURSOR_RADIUS = 28
GOAL_RADIUS   = 40
WIN_DISTANCE  = CURSOR_RADIUS + GOAL_RADIUS - 10
WIN_HOLD      = 2.5    # seconds to show win screen before next level

# Colors
BG_COLOR     = ( 20,  20,  40)
GRID_COLOR   = ( 35,  35,  60)
CURSOR_COLOR = (255, 200,  50)   # golden paw
CURSOR_DARK  = (200, 140,  20)
GOAL_COLOR   = (255,  90,  90)   # red bone
GOAL_GLOW    = (255, 160, 160)
TEXT_COLOR   = (255, 255, 255)

# Level definitions: (start_xy, goal_xy, label)
# goal_xy = (None, None) → random position each time
LEVEL_CONFIGS = [
    ((200, 360),  (1080, 360),  "Level 1 — Straight Shot!"),
    ((150, 150),  (1130, 570),  "Level 2 — Corner to Corner"),
    ((640, 600),  ( 640, 120),  "Level 3 — Go Up!"),
    ((200, 200),  (1080, 500),  "Level 4 — Diagonal"),
    ((640, 360),  (None, None), "Level 5 — Random!"),
]


# ══════════════════════════════════════════════════════════════════════════════
#  DRAWING HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def draw_paw(surface, color, cx, cy, radius):
    """Draw a simple paw shape: one large central pad + four toe pads."""
    pygame.draw.circle(surface, color, (cx, cy), radius)
    pad_r = int(radius * 0.32)
    for ox, oy in [
        (-radius * 0.55, -radius * 0.70),
        ( radius * 0.55, -radius * 0.70),
        (-radius * 0.85, -radius * 0.25),
        ( radius * 0.85, -radius * 0.25),
    ]:
        pygame.draw.circle(surface, color, (int(cx + ox), int(cy + oy)), pad_r)


def draw_bone(surface, color, cx, cy, size):
    """Draw a simple two-knob bone shape."""
    s = size
    pygame.draw.rect(surface, color, (cx - s // 2, cy - s // 6, s, s // 3))
    for bx in [cx - s // 2, cx + s // 2]:
        for by in [cy - s // 5, cy + s // 5]:
            pygame.draw.circle(surface, color, (bx, by), s // 5)


def draw_grid(surface, w, h):
    """Draw a subtle background grid."""
    for x in range(0, w, 80):
        pygame.draw.line(surface, GRID_COLOR, (x, 0), (x, h))
    for y in range(0, h, 80):
        pygame.draw.line(surface, GRID_COLOR, (0, y), (w, y))


def draw_arrow_button(surface, font, rect, label, pressed):
    """Draw an on-screen directional button with a pressed/unpressed state."""
    color  = (100, 200, 255) if pressed else ( 60,  80, 120)
    border = (200, 240, 255) if pressed else ( 80, 110, 160)
    pygame.draw.rect(surface, color,  rect, border_radius=12)
    pygame.draw.rect(surface, border, rect, 3, border_radius=12)
    txt = font.render(label, True, (255, 255, 255))
    surface.blit(txt, (rect.centerx - txt.get_width()  // 2,
                       rect.centery - txt.get_height() // 2))


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="🐾 Dog Video Game")
    parser.add_argument("--keyboard",  action="store_true",
                        help="Use keyboard only — skips GPIO init")
    parser.add_argument("--dispenser", action="store_true",
                        help="Force-enable dispenser (useful with --keyboard for testing)")
    args = parser.parse_args()

    # Hardware init
    GPIO      = None if args.keyboard else init_gpio()
    use_disp  = (not args.keyboard) or args.dispenser
    dispenser = init_dispenser(force=args.dispenser) if use_disp else None

    # Pygame init — fullscreen at native display resolution
    pygame.init()
    pygame.display.set_caption("🐾 Dog Video Game 🐾")
    screen   = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    SW       = screen.get_width()
    SH       = screen.get_height()
    clock    = pygame.time.Clock()
    pygame.mouse.set_visible(False)

    # Fonts
    try:
        font_big = pygame.font.SysFont("dejavusans", 64, bold=True)
        font_med = pygame.font.SysFont("dejavusans", 36)
        font_sm  = pygame.font.SysFont("dejavusans", 26)
        font_btn = pygame.font.SysFont("dejavusans", 32, bold=True)
    except Exception:
        font_big = pygame.font.Font(None, 72)
        font_med = pygame.font.Font(None, 42)
        font_sm  = pygame.font.Font(None, 30)
        font_btn = pygame.font.Font(None, 38)

    # On-screen directional button positions (bottom-centre of screen)
    btn_size = 70
    btn_y    = SH - btn_size - 15
    btn_cx   = SW // 2
    btn_rects = {
        "UP":    pygame.Rect(btn_cx - btn_size // 2,          btn_y - btn_size - 5, btn_size, btn_size),
        "DOWN":  pygame.Rect(btn_cx - btn_size // 2,          btn_y,                btn_size, btn_size),
        "LEFT":  pygame.Rect(btn_cx - btn_size * 3 // 2 - 10, btn_y,                btn_size, btn_size),
        "RIGHT": pygame.Rect(btn_cx + btn_size // 2 + 10,     btn_y,                btn_size, btn_size),
    }
    btn_labels = {"UP": "▲", "DOWN": "▼", "LEFT": "◀", "RIGHT": "▶"}

    # Trail surface (alpha layer for motion trail)
    trail_surf = pygame.Surface((SW, SH), pygame.SRCALPHA)

    def load_level(idx):
        nonlocal trail_surf
        cfg = LEVEL_CONFIGS[idx % len(LEVEL_CONFIGS)]
        start, goal, label = cfg
        if goal[0] is None:
            goal = (
                random.randint(100, SW - 100),
                random.randint(100, SH - 200),
            )
        trail_surf = pygame.Surface((SW, SH), pygame.SRCALPHA)
        return list(start), list(goal), label

    # Game state
    level_idx  = 0
    score      = 0
    win_timer  = 0.0
    won        = False
    cur_pos, goal_pos, level_label = load_level(level_idx)
    prev_pos   = list(cur_pos)

    # ── Main loop ──────────────────────────────────────────────────────────────
    running = True
    while running:
        clock.tick(FPS)

        # Events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                if won and event.key == pygame.K_SPACE:
                    level_idx += 1
                    cur_pos, goal_pos, level_label = load_level(level_idx)
                    won = False

        # Inputs — merge GPIO physical buttons + keyboard fallback
        gpio_state = read_gpio(GPIO)
        kb = pygame.key.get_pressed()
        moving = {
            "UP":    gpio_state["UP"]    or kb[pygame.K_UP]    or kb[pygame.K_w],
            "DOWN":  gpio_state["DOWN"]  or kb[pygame.K_DOWN]  or kb[pygame.K_s],
            "LEFT":  gpio_state["LEFT"]  or kb[pygame.K_LEFT]  or kb[pygame.K_a],
            "RIGHT": gpio_state["RIGHT"] or kb[pygame.K_RIGHT] or kb[pygame.K_d],
        }

        if not won:
            prev_pos = list(cur_pos)
            if moving["UP"]:    cur_pos[1] -= CURSOR_SPEED
            if moving["DOWN"]:  cur_pos[1] += CURSOR_SPEED
            if moving["LEFT"]:  cur_pos[0] -= CURSOR_SPEED
            if moving["RIGHT"]: cur_pos[0] += CURSOR_SPEED

            # Keep cursor inside playfield (leave room for bottom UI)
            cur_pos[0] = max(CURSOR_RADIUS, min(SW - CURSOR_RADIUS, cur_pos[0]))
            cur_pos[1] = max(CURSOR_RADIUS, min(SH - 160 - CURSOR_RADIUS, cur_pos[1]))

            # Draw motion trail
            if any(moving.values()):
                pygame.draw.line(
                    trail_surf,
                    (*CURSOR_COLOR, 60),
                    (int(prev_pos[0]), int(prev_pos[1])),
                    (int(cur_pos[0]),  int(cur_pos[1])),
                    8,
                )

            # Win detection
            if math.hypot(cur_pos[0] - goal_pos[0], cur_pos[1] - goal_pos[1]) < WIN_DISTANCE:
                won       = True
                win_timer = time.time()
                score    += 1
                dispense_treat(dispenser)   # 🦴 dispense treat immediately!

        else:
            # Auto-advance to next level after WIN_HOLD seconds
            if time.time() - win_timer > WIN_HOLD:
                level_idx += 1
                cur_pos, goal_pos, level_label = load_level(level_idx)
                won = False

        # ── Draw ──────────────────────────────────────────────────────────────
        screen.fill(BG_COLOR)
        draw_grid(screen, SW, SH)
        screen.blit(trail_surf, (0, 0))

        # Pulsing bone goal
        pulse  = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 300)
        glow_r = int(GOAL_RADIUS * 1.6 + pulse * 12)
        glow_s = pygame.Surface((glow_r * 2, glow_r * 2), pygame.SRCALPHA)
        pygame.draw.circle(glow_s, (*GOAL_GLOW, 60), (glow_r, glow_r), glow_r)
        screen.blit(glow_s, (goal_pos[0] - glow_r, goal_pos[1] - glow_r))
        draw_bone(screen, GOAL_COLOR, goal_pos[0], goal_pos[1], GOAL_RADIUS)

        # Paw cursor with drop shadow
        draw_paw(screen, CURSOR_DARK, cur_pos[0] + 3, cur_pos[1] + 3, CURSOR_RADIUS)
        draw_paw(screen, CURSOR_COLOR, cur_pos[0],    cur_pos[1],      CURSOR_RADIUS)

        # HUD — top left: level + score
        hud = font_sm.render(
            f"Level {level_idx + 1}  |  Score: {score}  |  {level_label}",
            True, TEXT_COLOR,
        )
        screen.blit(hud, (20, 12))

        # HUD — proximity bar (top right)
        dist        = math.hypot(cur_pos[0] - goal_pos[0], cur_pos[1] - goal_pos[1])
        bar_w       = 300
        max_dist    = math.hypot(SW, SH)
        fill        = max(0.0, 1.0 - dist / max_dist)
        pygame.draw.rect(screen, ( 50, 50,  80), (SW - bar_w - 20, 15, bar_w, 22), border_radius=11)
        pygame.draw.rect(screen, ( 80,220, 120), (SW - bar_w - 20, 15, int(bar_w * fill), 22), border_radius=11)
        near_txt = font_sm.render("How close? 🐾", True, (160, 200, 160))
        screen.blit(near_txt, (SW - bar_w - 20, 42))

        # HUD — bottom left: controls hint
        hint = font_sm.render(
            "Arrow Keys / WASD / Physical Buttons   •   ESC = Quit",
            True, (120, 130, 160),
        )
        screen.blit(hint, (20, SH - 28))

        # HUD — bottom right: dispenser status
        d_color = (80, 220, 120) if dispenser else (160, 80, 80)
        d_label = "🦴 Dispenser: READY" if dispenser else "🦴 Dispenser: OFF"
        d_txt   = font_sm.render(d_label, True, d_color)
        screen.blit(d_txt, (SW - d_txt.get_width() - 20, SH - 28))

        # On-screen arrow buttons
        for d, rect in btn_rects.items():
            draw_arrow_button(screen, font_btn, rect, btn_labels[d], moving[d])

        # Win overlay
        if won:
            overlay = pygame.Surface((SW, SH), pygame.SRCALPHA)
            overlay.fill((30, 180, 100, 180))
            screen.blit(overlay, (0, 0))
            msgs = [
                font_big.render("🎉  GOOD DOG!  🎉",      True, (255, 255, 100)),
                font_med.render("You found the treat!",   True, (255, 255, 255)),
                font_sm.render( "Next level coming up…",  True, (200, 255, 200)),
            ]
            total_h = sum(m.get_height() + 10 for m in msgs)
            y = SH // 2 - total_h // 2
            for m in msgs:
                screen.blit(m, (SW // 2 - m.get_width() // 2, y))
                y += m.get_height() + 10

        pygame.display.flip()

    # ── Cleanup ───────────────────────────────────────────────────────────────
    if GPIO:
        GPIO.cleanup()
    close_dispenser(dispenser)
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
