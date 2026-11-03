#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock 2>/dev/null &
cd ~/phone_agent
PYTHONUNBUFFERED=1 python3 -u agent.py "$@"
termux-wake-unlock 2>/dev/null
