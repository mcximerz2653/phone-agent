#!/usr/bin/env python3
"""
Claude Phone Control Agent
- No API key needed — uses claude CLI (already authenticated)
- Screenshots via ADB
- Taps/swipes via ADB
- Pauses and asks user for passwords/sensitive input
"""

import os
import sys
import json
import subprocess
import tempfile
import time
import re
from pathlib import Path

ADB_DEVICE = "emulator-5554"

# ─── ADB ──────────────────────────────────────────────────
def get_device():
    """Return first connected ADB device"""
    r = subprocess.run(["adb", "devices"], capture_output=True, text=True)
    for line in r.stdout.splitlines()[1:]:
        if "\tdevice" in line:
            return line.split("\t")[0]
    return ADB_DEVICE

def adb(*args):
    cmd = ["adb", "-s", get_device()] + list(args)
    return subprocess.run(cmd, capture_output=True)

def ensure_adb():
    """Reconnect ADB if needed — tries automatically via Automate intent"""
    r = subprocess.run(["adb", "devices"], capture_output=True, text=True)
    if ADB_DEVICE in r.stdout and "device" in r.stdout:
        return True

    print("🔌 Reconnecting ADB...")

    # Try to wake Automate's privileged service via intent
    subprocess.run([
        "am", "startservice",
        "-n", "com.llamalab.automate/.PrivilegedService"
    ], capture_output=True)
    time.sleep(2)

    # Try restarting ADB server to pick up new connections
    subprocess.run(["adb", "kill-server"], capture_output=True)
    time.sleep(1)
    subprocess.run(["adb", "start-server"], capture_output=True)
    time.sleep(3)

    r = subprocess.run(["adb", "devices"], capture_output=True, text=True)
    if ADB_DEVICE in r.stdout:
        print("✅ ADB reconnected")
        return True

    # Last resort — try TCP connections
    for port in [5555, 5554]:
        subprocess.run(["adb", "connect", f"localhost:{port}"], capture_output=True)
    time.sleep(2)

    r = subprocess.run(["adb", "devices"], capture_output=True, text=True)
    if ADB_DEVICE in r.stdout or "device" in r.stdout:
        print("✅ ADB reconnected via TCP")
        return True

    print("⚠️  ADB disconnected — waiting 10s for Automate to reconnect...")
    time.sleep(10)
    r = subprocess.run(["adb", "devices"], capture_output=True, text=True)
    return ADB_DEVICE in r.stdout

# ─── Screenshot ───────────────────────────────────────────
def take_screenshot():
    result = adb("exec-out", "screencap", "-p")
    if result.returncode != 0 or not result.stdout:
        return None
    # Resize for faster processing
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(result.stdout)).convert("RGB")
        img = img.resize((540, int(img.height * 540 / img.width)))
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False,
                                          dir="/sdcard/Download")
        img.save(tmp.name, quality=70)
        return tmp.name
    except Exception as e:
        print(f"⚠️  Screenshot resize failed: {e}")
        return None

# ─── Actions ──────────────────────────────────────────────
def tap(x, y):
    adb("shell", "input", "tap", str(x), str(y))

def swipe(x1, y1, x2, y2, duration=300):
    adb("shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration))

def type_text(text):
    escaped = text.replace("\\", "\\\\").replace(" ", "%s").replace("'", "\\'") \
                  .replace("\"", "\\\"").replace("&", "\\&")
    adb("shell", "input", "text", escaped)

def press_key(keycode):
    adb("shell", "input", "keyevent", str(keycode))

KNOWN_APPS = {
    "com.google.android.gm": "com.google.android.gm/.ConversationListActivityGmail",
    "com.android.chrome": "com.android.chrome/com.google.android.apps.chrome.Main",
    "com.whatsapp": "com.whatsapp/.HomeActivity",
    "com.android.settings": "com.android.settings/.Settings",
    "com.google.android.youtube": "com.google.android.youtube/.HomeActivity",
    "com.instagram.android": "com.instagram.android/.activity.MainTabActivity",
    "com.facebook.katana": "com.facebook.katana/.LoginActivity",
}

def launch_app(package):
    if package in KNOWN_APPS:
        subprocess.run(["am", "start", "-n", KNOWN_APPS[package]], capture_output=True)
    else:
        subprocess.run(["monkey", "-p", package, "-c",
                       "android.intent.category.LAUNCHER", "1"], capture_output=True)
    time.sleep(3)

# ─── Ask Claude via CLI ───────────────────────────────────
PROMPT_TEMPLATE = """You are controlling an Android phone. Current task: {task}

Look at this screenshot and decide the next action. The screen is 1080x2400 pixels.

Reply with ONLY a single JSON object (no markdown, no explanation):
- Tap:    {{"action":"tap","x":X,"y":Y,"reason":"why"}}
- Swipe:  {{"action":"swipe","x1":X1,"y1":Y1,"x2":X2,"y2":Y2,"duration":300}}
- Type:   {{"action":"type","text":"text to type"}}
- Launch: {{"action":"launch","package":"com.package.name"}}
- Back:   {{"action":"back"}}
- Home:   {{"action":"home"}}
- Enter:  {{"action":"enter"}}
- Need password/sensitive input: {{"action":"ask_user","prompt":"what to ask user"}}
- Done:   {{"action":"done","message":"what was accomplished"}}

Common packages: Gmail=com.google.android.gm, Chrome=com.android.chrome, WhatsApp=com.whatsapp, Settings=com.android.settings"""

def ask_claude(screenshot_path, task):
    prompt = PROMPT_TEMPLATE.format(task=task)
    prompt_with_image = f"{prompt}\n\n@{screenshot_path}"

    result = subprocess.run(
        ["claude", "-p", prompt_with_image],
        capture_output=True, text=True, timeout=60
    )
    output = result.stdout.strip()
    if not output:
        output = result.stderr.strip()

    # Extract JSON
    match = re.search(r'\{[^{}]*\}', output, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    print(f"⚠️  Could not parse response: {output[:200]}")
    return None

# ─── Main Loop ────────────────────────────────────────────
def run(task):
    print(f"\n🤖 Task: {task}")
    print("   Ctrl+C to stop\n")

    if not ensure_adb():
        return

    max_steps = 30
    for step in range(max_steps):
        print(f"── Step {step+1} ──")

        if not ensure_adb():
            print("Waiting 5s...")
            time.sleep(5)
            continue

        print("📸 Screenshot...")
        img_path = take_screenshot()
        if not img_path:
            print("⚠️  Screenshot failed, retrying...")
            time.sleep(3)
            continue

        print("🧠 Thinking...")
        action = ask_claude(img_path, task)
        os.unlink(img_path)  # cleanup temp file

        if not action:
            time.sleep(2)
            continue

        a = action.get("action", "")
        print(f"▶  {json.dumps(action)}")

        if a == "done":
            print(f"\n✅ {action.get('message','Done!')}")
            break

        elif a == "ask_user":
            print(f"\n🔐 {action.get('prompt','Input needed:')}")
            user_input = input("You: ").strip()
            type_text(user_input)
            time.sleep(0.3)
            press_key(66)  # Enter

        elif a == "tap":
            tap(action["x"], action["y"])
            time.sleep(1.5)

        elif a == "swipe":
            swipe(action["x1"], action["y1"], action["x2"], action["y2"],
                  action.get("duration", 300))
            time.sleep(1)

        elif a == "type":
            type_text(action["text"])
            time.sleep(0.5)

        elif a == "launch":
            launch_app(action["package"])

        elif a == "back":
            press_key(4)
            time.sleep(1)

        elif a == "home":
            press_key(3)
            time.sleep(1)

        elif a == "enter":
            press_key(66)
            time.sleep(1)

        time.sleep(0.5)
    else:
        print("\n⚠️  Max steps reached")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 agent.py \"open Gmail\"")
        sys.exit(1)
    run(" ".join(sys.argv[1:]))
