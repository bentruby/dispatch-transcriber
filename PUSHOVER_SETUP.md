# Pushover Notification Setup

## Get Pushover Credentials

1. **Install Pushover app on your phone**
   - iOS: https://apps.apple.com/us/app/pushover-notifications/id506088175
   - Android: https://play.google.com/store/apps/details?id=net.superblock.pushover

2. **Create Pushover account** at https://pushover.net/

3. **Get your User Key**
   - Login to https://pushover.net/
   - Your User Key is displayed at the top of the dashboard

4. **Create an Application**
   - Go to https://pushover.net/apps/build
   - Name: "Dispatch Transcription" (or whatever you want)
   - Type: Application
   - Description: "Emergency dispatch transcriptions"
   - Click "Create Application"
   - Copy your **API Token/Key**

## Configure the Script

### Mac
```bash
cd ~/Documents/Whisper/V3
source whisper-env/bin/activate

# Install requests library
pip install requests

# Set environment variables
export PUSHOVER_USER_KEY="your_user_key_here"
export PUSHOVER_API_TOKEN="your_api_token_here"
export PUSHOVER_ENABLED="true"

# Run
python process_dispatcher.py
```

### Raspberry Pi
```bash
cd ~/dispatch-transcribe

# Install requests library
pip3 install requests --break-system-packages

# Set environment variables
export PUSHOVER_USER_KEY="your_user_key_here"
export PUSHOVER_API_TOKEN="your_api_token_here"
export PUSHOVER_ENABLED="true"

# Run
python3 process_dispatcher.py
```

## Test Pushover

Before running the full processor, test that Pushover works:

```bash
# Set your credentials first (see above)
export PUSHOVER_USER_KEY="your_user_key_here"
export PUSHOVER_API_TOKEN="your_api_token_here"
export PUSHOVER_ENABLED="true"

# Run test
python3 pushover_notify.py "Test message from dispatch system"
```

You should receive a notification on your phone!

## Make Environment Variables Permanent

### Mac (add to ~/.zshrc or ~/.bash_profile)
```bash
nano ~/.zshrc
```

Add these lines:
```bash
export PUSHOVER_USER_KEY="your_user_key_here"
export PUSHOVER_API_TOKEN="your_api_token_here"
export PUSHOVER_ENABLED="true"
```

Save and reload:
```bash
source ~/.zshrc
```

### Pi (add to systemd service)

Edit the service file:
```bash
sudo nano /etc/systemd/system/dispatch-processor.service
```

Add the environment variables to the `[Service]` section:
```ini
[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/dispatch-transcribe
Environment="MODEL_SIZE=tiny"
Environment="PUSHOVER_USER_KEY=your_user_key_here"
Environment="PUSHOVER_API_TOKEN=your_api_token_here"
Environment="PUSHOVER_ENABLED=true"
ExecStart=/usr/bin/python3 /home/pi/dispatch-transcribe/process_dispatcher.py
Restart=always
RestartSec=10
```

Reload and restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart dispatch-processor.service
```

## Notification Format

You'll receive notifications like:

```
🚑 Dispatch

You need to respond to N8510 Old Railroad, 
86 year old male who fell and passed out 
for a short period of time. Not sure if 
he injured himself in the fall, he is 
breathing and talking slightly now.

[1764408369902.mp3 • 5.7s]
```

## Priority Levels

The script uses `priority=1` (high priority) by default. You can customize this in `process_dispatcher.py`:

- `-2`: Silent (no sound/vibration)
- `-1`: Quiet (no sound, vibration only)
- `0`: Normal priority
- `1`: High priority (bypasses quiet hours) ← **Default**
- `2`: Emergency (requires acknowledgment)

To change, edit this line in `process_dispatcher.py`:
```python
send_pushover("🚑 Dispatch", message, priority=1)  # Change the 1 to your preference
```

## Troubleshooting

### "Pushover enabled but pushover_notify.py not found"
Make sure `pushover_notify.py` is in the same directory as `process_dispatcher.py`.

### "Pushover credentials not configured"
Check that you've set the environment variables:
```bash
echo $PUSHOVER_USER_KEY
echo $PUSHOVER_API_TOKEN
echo $PUSHOVER_ENABLED
```

All three should show values.

### Not receiving notifications
1. Check that Pushover app is installed on your phone
2. Check that you're logged into the same account
3. Test with: `python3 pushover_notify.py "test"`
4. Check Pushover logs at https://pushover.net/

### Notifications delayed
This is normal - Pushover typically delivers in 1-5 seconds, but can be slower depending on network.

## Disable Notifications Temporarily

```bash
export PUSHOVER_ENABLED="false"
python3 process_dispatcher.py
```

Or just don't set the environment variables at all.

## Cost

Pushover costs $5 USD one-time per platform (iOS/Android). No subscription, unlimited notifications.

## Files Needed

- `process_dispatcher.py` (updated with Pushover support)
- `pushover_notify.py` (notification module)
- `transcription_config.json` (your corrections)

Make sure all three are in the same directory.
