#!/bin/bash
# One-time setup for the SeeNARIO Raspberry Pi. Run from the repo's pi/ folder:  bash setup_pi.sh
set -e
sudo apt update
sudo apt install -y git python3-opencv python3-requests python3-venv espeak-ng alsa-utils bluez pulseaudio-utils
# a Python environment that can still see the system OpenCV
python3 -m venv --system-site-packages ~/seenario-venv
~/seenario-venv/bin/pip install --upgrade pip bleak requests
if [ ! -f ~/keys.txt ]; then
cat > ~/keys.txt <<'K'
GEMINI_API_KEY=paste-your-NEW-gemini-key
ELEVENLABS_API_KEY=paste-your-NEW-elevenlabs-key-or-leave-blank
PI_SECRET=make-up-a-long-random-password
K
chmod 600 ~/keys.txt
echo "Created ~/keys.txt. Open it (nano ~/keys.txt) and paste your NEW keys."
fi
echo
echo "NEXT:"
echo " 1. nano ~/keys.txt        (put in new keys; PI_SECRET must match Vercel's PI_SECRET)"
echo " 2. Pair the speaker:       bluetoothctl   then: scan on / pair XX / trust XX / connect XX / exit"
echo " 3. source ~/seenario-venv/bin/activate"
echo " 4. python3 seenario_pi.py --check"
echo " 5. python3 sensortile_bridge.py --simulate"
