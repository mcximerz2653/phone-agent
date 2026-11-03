#!/data/data/com.termux/files/usr/bin/bash
# Keeps ADB connected by auto-triggering Automate privileged service

while true; do
    DEVICES=$(adb devices 2>/dev/null | grep -c "device$")
    if [ "$DEVICES" -eq 0 ]; then
        echo "$(date): ADB dropped, reconnecting..."
        # Wake Automate privileged service
        am startservice -n com.llamalab.automate/.PrivilegedService 2>/dev/null
        # Also try via activity
        am start -n com.llamalab.automate/.MainActivity 2>/dev/null
        sleep 3
        adb kill-server 2>/dev/null
        sleep 1
        adb start-server 2>/dev/null
        sleep 5
        DEVICES=$(adb devices 2>/dev/null | grep -c "device$")
        echo "$(date): Reconnect result: $DEVICES device(s)"
    fi
    sleep 10
done
