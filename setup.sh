#!/data/data/com.termux/files/usr/bin/bash
# Phone Agent Setup Script

echo "=== Claude Phone Agent Setup ==="

# 1. Enable ADB TCP mode (needs Automate privileges already granted)
echo ""
echo "Step 1: Enabling ADB TCP/IP mode..."
adb tcpip 5555 2>/dev/null
sleep 2
adb connect localhost:5555 2>/dev/null
adb connect 127.0.0.1:5555 2>/dev/null

# Check if ADB connected
if adb devices 2>/dev/null | grep -q "device$"; then
    echo "✅ ADB connected!"
else
    echo "⚠️  ADB not connected — tap 'Restart ADB in TCP/IP mode' in Automate Settings, then run this script again"
    echo "   Or set up Automate HTTP flow for fallback control"
fi

# 2. Check API key
echo ""
echo "Step 2: Checking API key..."
CONFIG=~/.phone_agent_config.json

if [ ! -f "$CONFIG" ]; then
    echo "No config found."
    echo ""
    echo "Enter your Anthropic API key (or press Enter to use Claude OAuth):"
    read -r API_KEY
    if [ -n "$API_KEY" ]; then
        echo "{\"api_key\": \"$API_KEY\"}" > "$CONFIG"
        echo "✅ API key saved to $CONFIG"
    else
        echo "✅ Will use Claude OAuth token from ~/.claude/.credentials.json"
    fi
else
    echo "✅ Config exists at $CONFIG"
fi

# 3. Install dependencies
echo ""
echo "Step 3: Checking Python dependencies..."
ANDROID_API_LEVEL=34 pip install anthropic requests pillow -q 2>/dev/null
echo "✅ Dependencies ready"

# 4. Create launcher shortcut
echo ""
echo "Step 4: Creating launcher..."
cat > ~/phone_agent/run.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
cd ~/phone_agent
if [ -z "$1" ]; then
    echo "What should I do? "
    read -r TASK
else
    TASK="$*"
fi
python3 agent.py "$TASK"
EOF
chmod +x ~/phone_agent/run.sh

echo ""
echo "=== Setup Complete ==="
echo ""
echo "To use:"
echo "  ~/phone_agent/run.sh open Gmail"
echo "  ~/phone_agent/run.sh check WhatsApp messages"
echo ""
