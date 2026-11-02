#!/usr/bin/env python3
"""
Claude Phone Control Agent
- Takes screenshots via ADB or Automate
- Sends to Claude API for analysis
- Executes tap/swipe/launch commands
- Pauses for user passwords/sensitive input
"""

import os
import sys
import json
import base64
import subprocess
import time
import re
import requests
from pathlib import Path

# ─── Config ───────────────────────────────────────────────
CONFIG_FILE = Path.home() / ".phone_agent_config.json"
AUTOMATE_PORT = 8080
ADB_DEVICE = "emulator-5554"  # Automate privileged ADB

def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}

def save_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

def get_api_key():
    cfg = load_config()
    if "api_key" in cfg:
        return cfg["api_key"]
    # Try env
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    # Try OAuth token from Claude Code credentials
    creds_file = Path.home() / ".claude" / ".credentials.json"
    if creds_file.exists():
        creds = json.loads(creds_file.read_text())
        token = creds.get("claudeAiOauth", {}).get("accessToken", "")
        if token:
            return token
    return None

# ─── Screenshot ───────────────────────────────────────────
def screenshot_via_adb():
    """Take screenshot via ADB"""
    result = subprocess.run(
        ["adb", "-s", ADB_DEVICE, "exec-out", "screencap", "-p"] if ADB_DEVICE else
        ["adb", "exec-out", "screencap", "-p"],
        capture_output=True
    )
    if result.returncode == 0 and result.stdout:
        return result.stdout
    return None

def screenshot_via_automate():
    """Take screenshot via Automate HTTP server"""
    try:
        r = requests.get(f"http://localhost:{AUTOMATE_PORT}/screenshot", timeout=10)
        if r.status_code == 200:
            return r.content
    except:
        pass
    return None

def take_screenshot():
    """Try ADB first, fallback to Automate"""
    data = screenshot_via_adb()
    if data:
        return data
    data = screenshot_via_automate()
    if data:
        return data
    print("❌ Screenshot failed — ADB and Automate both unavailable")
    return None

# ─── Input Actions ────────────────────────────────────────
def tap(x, y):
    cmd = ["adb", "shell", "input", "tap", str(x), str(y)]
    if ADB_DEVICE:
        cmd = ["adb", "-s", ADB_DEVICE] + cmd[1:]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        # Fallback to Automate
        try:
            requests.post(f"http://localhost:{AUTOMATE_PORT}/tap",
                         json={"x": x, "y": y}, timeout=5)
        except:
            print(f"❌ Tap failed at ({x},{y})")

def swipe(x1, y1, x2, y2, duration=300):
    cmd = ["adb", "shell", "input", "swipe",
           str(x1), str(y1), str(x2), str(y2), str(duration)]
    if ADB_DEVICE:
        cmd = ["adb", "-s", ADB_DEVICE] + cmd[1:]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        try:
            requests.post(f"http://localhost:{AUTOMATE_PORT}/swipe",
                         json={"x1":x1,"y1":y1,"x2":x2,"y2":y2,"duration":duration}, timeout=5)
        except:
            print(f"❌ Swipe failed")

def type_text(text):
    # Escape special chars for ADB
    escaped = text.replace(" ", "%s").replace("'", "\\'")
    cmd = ["adb", "shell", "input", "text", escaped]
    if ADB_DEVICE:
        cmd = ["adb", "-s", ADB_DEVICE] + cmd[1:]
    subprocess.run(cmd, capture_output=True)

def launch_app(package, activity=None):
    if activity:
        subprocess.run(["am", "start", "-n", f"{package}/{activity}"], capture_output=True)
    else:
        subprocess.run(["am", "start", "-a", "android.intent.action.MAIN",
                       "-c", "android.intent.category.LAUNCHER",
                       "--package", package], capture_output=True)

def press_back():
    subprocess.run(["adb", "shell", "input", "keyevent", "4"], capture_output=True)

def press_home():
    subprocess.run(["adb", "shell", "input", "keyevent", "3"], capture_output=True)

# ─── Claude API ───────────────────────────────────────────
def call_claude(api_key, screenshot_bytes, task, conversation_history):
    """Call Claude API with screenshot for instructions"""
    img_b64 = base64.standard_b64encode(screenshot_bytes).decode()

    # Detect auth type
    headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01"}
    if api_key.startswith("sk-ant-api"):
        headers["x-api-key"] = api_key
        url = "https://api.anthropic.com/v1/messages"
    else:
        # OAuth token
        headers["Authorization"] = f"Bearer {api_key}"
        url = "https://api.anthropic.com/v1/messages"

    messages = conversation_history + [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": img_b64}
                },
                {
                    "type": "text",
                    "text": f"Current task: {task}\n\nLook at this screenshot and tell me what action to take next. Respond with a JSON action:\n"
                            "- To tap: {{\"action\":\"tap\",\"x\":X,\"y\":Y,\"reason\":\"...\"}}\n"
                            "- To swipe: {{\"action\":\"swipe\",\"x1\":X1,\"y1\":Y1,\"x2\":X2,\"y2\":Y2}}\n"
                            "- To type: {{\"action\":\"type\",\"text\":\"...\"}}\n"
                            "- To launch app: {{\"action\":\"launch\",\"package\":\"com.example.app\"}}\n"
                            "- To press back: {{\"action\":\"back\"}}\n"
                            "- To press home: {{\"action\":\"home\"}}\n"
                            "- If need password/sensitive input: {{\"action\":\"ask_user\",\"prompt\":\"Please enter your Gmail password:\"}}\n"
                            "- If task is done: {{\"action\":\"done\",\"message\":\"...\"}}\n"
                            "Reply with ONLY the JSON, no explanation."
                }
            ]
        }
    ]

    body = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 500,
        "messages": messages
    }

    try:
        r = requests.post(url, headers=headers, json=body, timeout=30)
        r.raise_for_status()
        content = r.json()["content"][0]["text"].strip()
        # Extract JSON from response
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print(f"⚠️  Claude API error: {e}")
    return None

# ─── Main Agent Loop ──────────────────────────────────────
def run_agent(task):
    api_key = get_api_key()
    if not api_key:
        print("❌ No API key found. Add ANTHROPIC_API_KEY to ~/.phone_agent_config.json")
        return

    print(f"\n🤖 Starting agent for task: {task}")
    print("   Press Ctrl+C to stop\n")

    conversation_history = []
    max_steps = 30

    for step in range(max_steps):
        print(f"── Step {step+1} ──────────────────────────")

        # Take screenshot
        print("📸 Taking screenshot...")
        screenshot = take_screenshot()
        if not screenshot:
            print("Waiting 3s and retrying...")
            time.sleep(3)
            continue

        # Ask Claude what to do
        print("🧠 Analyzing screen...")
        action = call_claude(api_key, screenshot, task, conversation_history)
        if not action:
            print("⚠️  No action returned, retrying...")
            time.sleep(2)
            continue

        print(f"▶  Action: {json.dumps(action)}")

        a = action.get("action")

        if a == "done":
            print(f"\n✅ Task complete: {action.get('message','')}")
            break

        elif a == "ask_user":
            prompt = action.get("prompt", "Input needed:")
            print(f"\n🔐 {prompt}")
            user_input = input("Your input: ").strip()
            # Type it
            type_text(user_input)
            time.sleep(0.5)
            # Press enter
            subprocess.run(["adb", "shell", "input", "keyevent", "66"], capture_output=True)

        elif a == "tap":
            print(f"👆 Tapping ({action['x']}, {action['y']}) — {action.get('reason','')}")
            tap(action["x"], action["y"])
            time.sleep(1.5)

        elif a == "swipe":
            print(f"👆 Swiping")
            swipe(action["x1"], action["y1"], action["x2"], action["y2"],
                  action.get("duration", 300))
            time.sleep(1)

        elif a == "type":
            print(f"⌨️  Typing: {action['text'][:20]}...")
            type_text(action["text"])
            time.sleep(0.5)

        elif a == "launch":
            pkg = action["package"]
            print(f"🚀 Launching {pkg}")
            launch_app(pkg)
            time.sleep(2)

        elif a == "back":
            press_back()
            time.sleep(1)

        elif a == "home":
            press_home()
            time.sleep(1)

        else:
            print(f"❓ Unknown action: {a}")

        time.sleep(0.5)

    else:
        print("\n⚠️  Max steps reached")

# ─── Entry Point ──────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 agent.py \"open Gmail and check inbox\"")
        print("\nSetup: Add API key to ~/.phone_agent_config.json:")
        print('  {"api_key": "sk-ant-api..."}')
        sys.exit(1)

    task = " ".join(sys.argv[1:])
    run_agent(task)
