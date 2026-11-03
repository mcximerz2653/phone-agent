#!/usr/bin/env python3
"""
Claude Phone Agent — seamless phone control via ADB + Claude CLI
"""

import os, sys, json, subprocess, tempfile, time, re, threading, signal
from pathlib import Path
from PIL import Image
import io

# ─── ADB ──────────────────────────────────────────────────────────────────────

def _connected_device():
    r = subprocess.run(["adb", "devices"], capture_output=True, text=True)
    for line in r.stdout.splitlines()[1:]:
        if "\tdevice" in line:
            return line.split("\t")[0]
    return None

def _reconnect():
    """Reconnect ADB by restarting server — Automate auto-reconnects"""
    subprocess.run(["adb", "kill-server"], capture_output=True)
    time.sleep(1)
    subprocess.run(["adb", "start-server"], capture_output=True)
    for _ in range(10):
        time.sleep(2)
        if _connected_device():
            return True
    return False

def adb(*args, check=False):
    dev = _connected_device()
    if not dev:
        if not _reconnect():
            return subprocess.CompletedProcess(args, 1, b"", b"no device")
        dev = _connected_device()
    return subprocess.run(["adb", "-s", dev] + list(args), capture_output=True)

# ─── Keepalive ────────────────────────────────────────────────────────────────

_keepalive_running = False

def start_keepalive():
    """Background thread that auto-reconnects ADB if it drops"""
    global _keepalive_running
    _keepalive_running = True
    def _loop():
        while _keepalive_running:
            time.sleep(15)
            if not _connected_device():
                _reconnect()
    t = threading.Thread(target=_loop, daemon=True)
    t.start()

# ─── Screenshot ───────────────────────────────────────────────────────────────

def screenshot(path):
    result = adb("exec-out", "screencap", "-p")
    if not result.stdout:
        return False
    try:
        img = Image.open(io.BytesIO(result.stdout)).convert("RGB")
        w, h = img.size
        img = img.resize((540, int(h * 540 / w)), Image.LANCZOS)
        img.save(path, "JPEG", quality=65)
        return True
    except Exception:
        return False

# ─── Actions ──────────────────────────────────────────────────────────────────

APPS = {
    "com.google.android.gm":      "com.google.android.gm/.ConversationListActivityGmail",
    "com.android.chrome":         "com.android.chrome/com.google.android.apps.chrome.Main",
    "com.whatsapp":               "com.whatsapp/.HomeActivity",
    "com.android.settings":       "com.android.settings/.Settings",
    "com.google.android.youtube": "com.google.android.youtube/.HomeActivity",
    "com.instagram.android":      "com.instagram.android/.activity.MainTabActivity",
    "com.facebook.katana":        "com.facebook.katana/.LoginActivity",
    "com.telegram.messenger":     "com.telegram.messenger/.DefaultIcon",
    "com.twitter.android":        "com.twitter.android/.StartActivity",
    "com.spotify.music":          "com.spotify.music/.MainActivity",
}

def tap(x, y):        adb("shell", "input", "tap", str(x), str(y))
def key(code):        adb("shell", "input", "keyevent", str(code))
def back():           key(4)
def home():           key(3)
def enter():          key(66)
def swipe(x1,y1,x2,y2,ms=300):
    adb("shell","input","swipe",str(x1),str(y1),str(x2),str(y2),str(ms))

def type_text(text):
    safe = text.replace("\\","\\\\").replace(" ","%s") \
               .replace("'","\\'").replace("\"","\\\"") \
               .replace("&","\\&").replace("<","\\<").replace(">","\\>") \
               .replace(";","\\;").replace("|","\\|")
    adb("shell", "input", "text", safe)

def launch(package):
    global _active_app
    # Kill previous active app if switching
    if _active_app and _active_app != package:
        adb("shell", "am", "force-stop", _active_app)
    _active_app = package
    if package in APPS:
        subprocess.run(["am","start","-n",APPS[package]], capture_output=True)
    else:
        subprocess.run(["am","start","-a","android.intent.action.MAIN",
                       "-c","android.intent.category.LAUNCHER",
                       "--package", package], capture_output=True)
    time.sleep(2.5)

MANAGED_APPS = [
    "com.facebook.katana",
    "com.facebook.orca",
    "com.instagram.android",
    "com.twitter.android",
    "com.shopee.my",
    "com.microsoft.skydrive",
    "com.microsoft.office.outlook",
    "com.google.android.youtube",
    "com.google.android.googlequicksearchbox",
    "org.zwanoo.android.speedtest",
    "com.google.android.apps.messaging",
    "com.samsung.android.networkdiagnostic",
    "com.whatsapp",
    "com.google.android.gm",
    "com.android.chrome",
    "com.telegram.messenger",
    "com.spotify.music",
]

_active_app = None  # currently allowed app

def _kill_background(exclude=None):
    for pkg in MANAGED_APPS:
        if pkg != exclude:
            adb("shell", "am", "force-stop", pkg)

def free_ram():
    """Kill all managed apps at startup"""
    print("🧹 Freeing RAM...")
    _kill_background()
    adb("shell", "am", "kill-all")
    print("  ✅ RAM freed\n")

def start_ram_manager():
    """Background thread — re-kills apps every 30s, spares active app"""
    def _loop():
        while _keepalive_running:
            time.sleep(30)
            _kill_background(exclude=_active_app)
    threading.Thread(target=_loop, daemon=True).start()

def wake_screen():
    r = adb("shell", "dumpsys", "power")
    if b"mWakefulness=Awake" not in r.stdout:
        key(26)  # power button
        time.sleep(0.5)
        swipe(540, 1600, 540, 800, 300)  # swipe to unlock
        time.sleep(0.5)

# ─── Vision ───────────────────────────────────────────────────────────────────

PROMPT = """You control an Android phone (1080x2400 screen). Task: {task}

Previous actions: {history}

Look at the screenshot. Reply with ONE JSON action only — no explanation, no markdown:
{{"action":"tap","x":X,"y":Y,"reason":"..."}}
{{"action":"swipe","x1":X1,"y1":Y1,"x2":X2,"y2":Y2,"duration":300}}
{{"action":"type","text":"..."}}
{{"action":"launch","package":"com.package.name"}}
{{"action":"back"}}  {{"action":"home"}}  {{"action":"enter"}}
{{"action":"ask_user","prompt":"what to ask"}}
{{"action":"done","message":"what was done"}}

Known packages: Gmail=com.google.android.gm WhatsApp=com.whatsapp Chrome=com.android.chrome Settings=com.android.settings YouTube=com.google.android.youtube Instagram=com.instagram.android Telegram=com.telegram.messenger Twitter=com.twitter.android Spotify=com.spotify.music"""

def think(img_path, task, history):
    prompt = PROMPT.format(task=task, history=", ".join(history[-5:]) if history else "none")
    r = subprocess.run(
        ["claude", "-p", f"{prompt}\n\n@{img_path}"],
        capture_output=True, text=True, timeout=60
    )
    text = (r.stdout or r.stderr).strip()
    m = re.search(r'\{[^{}]*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except:
            pass
    return None

# ─── Agent ────────────────────────────────────────────────────────────────────

def run_task(task):
    print(f"\n🤖 {task}")
    wake_screen()

    img_path = str(Path("/sdcard/Download/.agent_screen.jpg"))
    history = []
    last_actions = []  # loop detection
    step = 0

    while step < 25:
        step += 1

        if not screenshot(img_path):
            print("  📸 retrying...")
            time.sleep(2)
            continue

        action = think(img_path, task, history)
        if not action:
            time.sleep(2)
            continue

        a = action.get("action", "")
        reason = action.get("reason", action.get("message", ""))
        print(f"  ▶ {a}" + (f" — {reason}" if reason else ""))

        # Loop detection
        sig = json.dumps(action, sort_keys=True)
        last_actions.append(sig)
        if len(last_actions) > 4 and len(set(last_actions[-4:])) == 1:
            print("  ⚠️  Stuck in loop — trying home")
            home(); time.sleep(1)
            last_actions.clear()
            continue

        history.append(f"{a}({reason})")

        if a == "done":
            print(f"  ✅ {action.get('message','Done')}\n")
            return True

        elif a == "ask_user":
            prompt = action.get("prompt", "Input needed:")
            print(f"\n  🔐 {prompt}")
            user_input = input("  > ").strip()
            type_text(user_input)
            time.sleep(0.3)
            enter()

        elif a == "tap":     tap(action["x"], action["y"]); time.sleep(1.2)
        elif a == "swipe":   swipe(action["x1"],action["y1"],action["x2"],action["y2"],action.get("duration",300)); time.sleep(1)
        elif a == "type":    type_text(action["text"]); time.sleep(0.5)
        elif a == "launch":  launch(action["package"])
        elif a == "back":    back(); time.sleep(1)
        elif a == "home":    home(); _active_app = None; time.sleep(1)
        elif a == "enter":   enter(); time.sleep(1)

    print("  ⚠️  Max steps reached\n")
    return False

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    # Ensure ADB is up
    if not _connected_device():
        print("🔌 Connecting ADB...")
        if not _reconnect():
            print("❌ ADB failed. Open Automate → Settings → Privileged service → ADB → GRANT")
            sys.exit(1)
    print("✅ ADB ready")

    start_keepalive()
    free_ram()
    start_ram_manager()

    # Single task mode
    if len(sys.argv) > 1:
        run_task(" ".join(sys.argv[1:]))
        return

    # Interactive mode
    print("📱 Phone agent ready. Type a task (or 'exit'):\n")
    while True:
        try:
            task = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break
        if not task:
            continue
        if task.lower() in ("exit", "quit", "q"):
            break
        run_task(task)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    main()
