#!/usr/bin/env python3
"""
🐾 DOG BUTTON GAME 🐾
A simple cursor navigation game for dogs using a Raspberry Pi and big physical buttons.
Includes a treat dispenser via stepper motor controlled through the Tevo Tarantula
(MKS Base / RAMPS-style) board over USB serial using G-code.

WIRING (GPIO BCM pin numbers):
  UP    button → GPIO 17  (+ GND)
  DOWN  button → GPIO 27  (+ GND)
  LEFT  button → GPIO 22  (+ GND)
  RIGHT button → GPIO 23  (+ GND)

Each button: one wire to the GPIO pin, other wire to any GND pin.
Internal pull-up resistors are enabled, so no external resistors needed.

TREAT DISPENSER:
  - Connect Tevo Tarantula board to Pi via USB
  - Stepper motor plugged into the EXTRUDER (E0) port on the board
  - Board powers up normally (12V PSU connected)
  - The game sends G-code over serial to rotate the extruder stepper ~90°
    each time the dog completes a level
  - Default USB port: /dev/ttyUSB0  (change DISPENSER_PORT below if needed)
    Run: ls /dev/ttyUSB* to find your board's port

Install dependencies:
  sudo apt update
  sudo apt install python3-pygame
  pip3 install RPi.GPIO pyserial --break-system-packages

Run:
  python3 dog_game.py

To run WITHOUT GPIO (keyboard + no dispenser testing mode):
  python3 dog_game.py --keyboard

To run with keyboard but still test the dispenser:
  python3 dog_game.py --keyboard --dispenser
"""

import pygame
import sys
import math
import random
import time
import argparse
import threading

# ─── TREAT DISPENSER (Serial / G-code) ────────────────────────────────────────
DISPENSER_PORT     = "/dev/ttyUSB0"   # change to /dev/ttyUSB1 etc. if needed
DISPENSER_BAUD     = 115200           # Tevo Tarantula default baud rate

# How far to rotate the extruder stepper for one treat.
# The Tevo extruder is typically 93–100 steps/mm.
# 90° of rotation ≈ moving ~30mm of filament — adjust TREAT_MM up/down
# to control how much your dispenser mechanism rotates.
TREAT_MM           = 30.0            # mm of extruder movement = ~90° rotation
TREAT_FEEDRATE     = 300             # mm/min — slow & controlled

def init_dispenser(force=False):
    """Open serial connection to the printer board. Returns serial object or None."""
    try:
        import serial
        ser = serial.Serial(DISPENSER_PORT, DISPENSER_BAUD, timeout=3)
        time.sleep(2)          # wait for board to finish reset after serial open
        ser.flushInput()
        # Send wake-up and configure relative extruder mode
        for cmd in ["M110 N0", "M82"]:   # reset line numbers, absolute extrusion
            ser.write((cmd + "\n").encode())
            time.sleep(0.1)
        print(f"✅ Treat dispenser connected on {DISPENSER_PORT}")
        return ser
    except ImportError:
        print("⚠️  pyserial not installed — treat dispenser disabled.")
        print("    Run: pip3 install pyserial --break-system-packages")
        return None
    except Exception as e:
        if force:
            print(f"❌ Could not open dispenser port {DISPENSER_PORT}: {e}")
        else:
            print(f"⚠️  Dispenser not found on {DISPENSER_PORT} — dispenser disabled.")
            print(f"    Check USB connection or update DISPENSER_PORT in the script.")
        return None

def dispense_treat(ser):
    """
    Fire-and-forget treat dispense in a background thread so the game
    never freezes waiting for G-code responses.
    Sends:
      G91        — relative positioning
      G1 E<mm> F<feedrate>  — extrude TREAT_MM at TREAT_FEEDRATE
      G90        — back to absolute positioning
      M400       — wait for move to finish (on the board side)
    """
    if ser is None:
        print("🦴 (Treat dispenser not connected — would dispense now)")
        return

    def _send():
        try:
            cmds = [
                "G91",                                          # relative mode
                f"G1 E{TREAT_MM:.1f} F{TREAT_FEEDRATE}",      # extrude
                "G90",                                          # back to absolute
                "M400",                                         # finish moves
            ]
            for cmd in cmds:
                ser.write((cmd + "\n").encode())
                time.sleep(0.05)
            print("🦴 Treat dispensed!")
        except Exception as e:
            print(f"⚠️  Dispenser error: {e}")

    threading.Thread(target=_send, daemon=True).start()

def close_dispenser(ser):
    if ser:
        try:
            ser.close()
        except:
            pass

# ─── GPIO SETUP ────────────────────────────────────────────────────────────────
GPIO_PINS = {
    "UP":    17,
    "DOWN":  27,
    "LEFT":  22,
    "RIGHT": 23,
}

def init_gpio():
    try:
        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM)
        for pin in GPIO_PINS.values():
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        print("✅ GPIO initialized successfully.")
        return GPIO
    except ImportError:
        print("⚠️  RPi.GPIO not found — running in keyboard mode.")
        return None
    except Exception as e:
        print(f"⚠️  GPIO error ({e}) — running in keyboard mode.")
        return None

def read_gpio(GPIO):
    """Returns a dict of which directions are currently pressed."""
    pressed = {d: False for d in GPIO_PINS}
    if GPIO:
        for direction, pin in GPIO_PINS.items():
            # Active LOW (button pulls pin to GND when pressed)
            pressed[direction] = (GPIO.input(pin) == GPIO.LOW)
    return pressed

# ─── CONSTANTS ─────────────────────────────────────────────────────────────────
SCREEN_W, SCREEN_H = 1280, 720
FPS = 60
CURSOR_SPEED = 6        # pixels per frame while button held
CURSOR_RADIUS = 28
GOAL_RADIUS   = 40
WIN_DISTANCE  = CURSOR_RADIUS + GOAL_RADIUS - 10

# Colors
BG_COLOR      = (20,  20,  40)
GRID_COLOR    = (35,  35,  60)
CURSOR_COLOR  = (255, 200,  50)   # golden paw
CURSOR_DARK   = (200, 140,  20)
GOAL_COLOR    = (255,  90,  90)   # red bone
GOAL_GLOW     = (255, 160, 160)
TRAIL_COLOR   = (255, 200,  50, 80)
TEXT_COLOR    = (255, 255, 255)
WIN_BG        = (30, 180, 100)

LEVEL_CONFIGS = [
    # (start_pos,          goal_pos,            label)
    ((200, 360),           (1080, 360),          "Level 1 — Straight Shot!"),
    ((150, 150),           (1130, 570),          "Level 2 — Corner to Corner"),
    ((640, 600),           (640, 120),           "Level 3 — Go Up!"),
    ((200, 200),           (1080, 500),          "Level 4 — Diagonal"),
    ((640, 360),           (None, None),         "RANDOM"),   # random goal
]

# ─── HELPER DRAWING ────────────────────────────────────────────────────────────
def draw_paw(surface, color, cx, cy, radius):
    pygame.draw.circle(surface, color, (cx, cy), radius)
    pad_r = int(radius * 0.32)
    offsets = [(-radius*0.55, -radius*0.7),
               ( radius*0.55, -radius*0.7),
               (-radius*0.85, -radius*0.25),
               ( radius*0.85, -radius*0.25)]
    for ox, oy in offsets:
        pygame.draw.circle(surface, color, (int(cx+ox), int(cy+oy)), pad_r)

def draw_bone(surface, color, cx, cy, size):
    s = size
    # shaft
    pygame.draw.rect(surface, color,
                     (cx - s//2, cy - s//6, s, s//3))
    # four knobs
    for bx in [cx - s//2, cx + s//2]:
        for by in [cy - s//5, cy + s//5]:
            pygame.draw.circle(surface, color, (bx, by), s//5)

def draw_grid(surface):
    for x in range(0, SCREEN_W, 80):
        pygame.draw.line(surface, GRID_COLOR, (x, 0), (x, SCREEN_H))
    for y in range(0, SCREEN_H, 80):
        pygame.draw.line(surface, GRID_COLOR, (0, y), (SCREEN_W, y))

def draw_arrow_button(surface, font, rect, label, pressed):
    color = (100, 200, 255) if pressed else (60, 80, 120)
    border = (200, 240, 255) if pressed else (80, 110, 160)
    pygame.draw.rect(surface, color, rect, border_radius=12)
    pygame.draw.rect(surface, border, rect, 3, border_radius=12)
    txt = font.render(label, True, (255,255,255))
    surface.blit(txt, (rect.centerx - txt.get_width()//2,
                       rect.centery - txt.get_height()//2))

# ─── MAIN GAME ─────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyboard", action="store_true",
                        help="Force keyboard mode (arrow keys), skip GPIO")
    parser.add_argument("--dispenser", action="store_true",
                        help="Force-enable dispenser even in keyboard mode")
    args = parser.parse_args()

    GPIO = None if args.keyboard else init_gpio()

    # Init treat dispenser (always try unless --keyboard without --dispenser)
    use_dispenser = (not args.keyboard) or args.dispenser
    dispenser = init_dispenser(force=args.dispenser) if use_dispenser else None

    pygame.init()
    pygame.display.set_caption("🐾 Dog Button Game 🐾")
    screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    clock  = pygame.time.Clock()

    try:
        font_big  = pygame.font.SysFont("dejavusans", 64, bold=True)
        font_med  = pygame.font.SysFont("dejavusans", 36)
        font_sm   = pygame.font.SysFont("dejavusans", 26)
        font_btn  = pygame.font.SysFont("dejavusans", 32, bold=True)
    except:
        font_big  = pygame.font.Font(None, 72)
        font_med  = pygame.font.Font(None, 42)
        font_sm   = pygame.font.Font(None, 30)
        font_btn  = pygame.font.Font(None, 38)

    # Trail surface
    trail_surf = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)

    level_idx   = 0
    score       = 0
    win_timer   = 0
    WIN_HOLD    = 2.5   # seconds to show win screen

    def load_level(idx):
        nonlocal trail_surf
        cfg = LEVEL_CONFIGS[idx % len(LEVEL_CONFIGS)]
        start, goal_pos, label = cfg
        if goal_pos[0] is None:
            goal_pos = (random.randint(100, SCREEN_W-100),
                        random.randint(100, SCREEN_H-200))
        trail_surf = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
        return list(start), list(goal_pos), label

    cur_pos, goal_pos, level_label = load_level(level_idx)
    won = False
    prev_pos = list(cur_pos)

    # On-screen button rects (bottom of screen) for visual feedback
    btn_size = 70
    btn_y    = SCREEN_H - btn_size - 15
    btn_cx   = SCREEN_W // 2
    btn_rects = {
        "UP":    pygame.Rect(btn_cx - btn_size//2,         btn_y - btn_size - 5, btn_size, btn_size),
        "DOWN":  pygame.Rect(btn_cx - btn_size//2,         btn_y,                btn_size, btn_size),
        "LEFT":  pygame.Rect(btn_cx - btn_size*3//2 - 10,  btn_y,                btn_size, btn_size),
        "RIGHT": pygame.Rect(btn_cx + btn_size//2 + 10,    btn_y,                btn_size, btn_size),
    }
    btn_labels = {"UP": "▲", "DOWN": "▼", "LEFT": "◀", "RIGHT": "▶"}

    running = True
    while running:
        dt = clock.tick(FPS)

        # ── Events ──
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

        # ── Read inputs ──
        gpio_state = read_gpio(GPIO)
        kb = pygame.key.get_pressed()

        # Merge GPIO + keyboard
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

            # Clamp to screen (leave room for UI at bottom)
            cur_pos[0] = max(CURSOR_RADIUS, min(SCREEN_W - CURSOR_RADIUS, cur_pos[0]))
            cur_pos[1] = max(CURSOR_RADIUS, min(SCREEN_H - 160 - CURSOR_RADIUS, cur_pos[1]))

            # Draw trail
            if any(moving.values()):
                pygame.draw.line(trail_surf,
                                 (*CURSOR_COLOR, 60),
                                 (int(prev_pos[0]), int(prev_pos[1])),
                                 (int(cur_pos[0]),  int(cur_pos[1])),
                                 8)

            # Check win
            dist = math.hypot(cur_pos[0]-goal_pos[0], cur_pos[1]-goal_pos[1])
            if dist < WIN_DISTANCE:
                won = True
                win_timer = time.time()
                score += 1
                dispense_treat(dispenser)   # 🦴 fire the treat dispenser!

        else:
            # Auto-advance after WIN_HOLD seconds
            if time.time() - win_timer > WIN_HOLD:
                level_idx += 1
                cur_pos, goal_pos, level_label = load_level(level_idx)
                won = False

        # ── Draw ──
        screen.fill(BG_COLOR)
        draw_grid(screen)
        screen.blit(trail_surf, (0, 0))

        # Pulsing goal glow
        pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 300)
        glow_r = int(GOAL_RADIUS * 1.6 + pulse * 12)
        glow_surf = pygame.Surface((glow_r*2, glow_r*2), pygame.SRCALPHA)
        pygame.draw.circle(glow_surf, (*GOAL_GLOW, 60), (glow_r, glow_r), glow_r)
        screen.blit(glow_surf, (goal_pos[0]-glow_r, goal_pos[1]-glow_r))
        draw_bone(screen, GOAL_COLOR, goal_pos[0], goal_pos[1], GOAL_RADIUS)

        # Cursor (paw)
        draw_paw(screen, CURSOR_DARK, cur_pos[0]+3, cur_pos[1]+3, CURSOR_RADIUS)
        draw_paw(screen, CURSOR_COLOR, cur_pos[0], cur_pos[1], CURSOR_RADIUS)

        # HUD
        lvl_txt = font_sm.render(f"Level {level_idx+1}  |  Score: {score}  |  {level_label}", True, TEXT_COLOR)
        screen.blit(lvl_txt, (20, 12))

        hint = font_sm.render("Arrow Keys / WASD / Physical Buttons   •   ESC = Quit", True, (120,130,160))
        screen.blit(hint, (20, SCREEN_H - 28))

        # Dispenser status indicator
        disp_color = (80, 220, 120) if dispenser else (160, 80, 80)
        disp_label = "🦴 Dispenser: READY" if dispenser else "🦴 Dispenser: OFF"
        disp_txt = font_sm.render(disp_label, True, disp_color)
        screen.blit(disp_txt, (SCREEN_W - disp_txt.get_width() - 20, SCREEN_H - 28))

        # On-screen arrow buttons
        for d, rect in btn_rects.items():
            draw_arrow_button(screen, font_btn, rect, btn_labels[d], moving[d])

        # Distance indicator
        dist = math.hypot(cur_pos[0]-goal_pos[0], cur_pos[1]-goal_pos[1])
        bar_w = 300
        bar_max_dist = math.hypot(SCREEN_W, SCREEN_H)
        fill = max(0, 1 - dist / bar_max_dist)
        pygame.draw.rect(screen, (50,50,80),  (SCREEN_W-bar_w-20, 15, bar_w, 22), border_radius=11)
        pygame.draw.rect(screen, (80,220,120),(SCREEN_W-bar_w-20, 15, int(bar_w*fill), 22), border_radius=11)
        near_txt = font_sm.render("How close? 🐾", True, (160,200,160))
        screen.blit(near_txt, (SCREEN_W-bar_w-20, 42))

        # WIN overlay
        if won:
            overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            overlay.fill((30, 180, 100, 180))
            screen.blit(overlay, (0,0))
            msgs = [
                font_big.render("🎉 GOOD DOG! 🎉",       True, (255,255,100)),
                font_med.render("You found the treat!",  True, (255,255,255)),
                font_sm.render ("Next level in a moment…", True, (200,255,200)),
            ]
            total_h = sum(m.get_height()+10 for m in msgs)
            y = SCREEN_H//2 - total_h//2
            for m in msgs:
                screen.blit(m, (SCREEN_W//2 - m.get_width()//2, y))
                y += m.get_height() + 10

        pygame.display.flip()

    if GPIO:
        GPIO.cleanup()
    close_dispenser(dispenser)
    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()
