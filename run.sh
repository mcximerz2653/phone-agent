#!/data/data/com.termux/files/usr/bin/bash
SESSION="phone-agent"

# If already running in this session, attach to it
if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Agent already running. Attaching..."
    tmux attach-session -t "$SESSION"
    exit 0
fi

termux-wake-lock 2>/dev/null

# Start in a tmux session so it survives window closure
tmux new-session -d -s "$SESSION" -x 220 -y 50
tmux send-keys -t "$SESSION" "cd ~/phone_agent && PYTHONUNBUFFERED=1 python3 -u agent.py $*" Enter
tmux attach-session -t "$SESSION"
