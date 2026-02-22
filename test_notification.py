#!/usr/bin/env python3
"""
End-to-end notification test.
Fetches the most recent Active911 alert (ignoring time window),
builds a realistic dispatch message, and sends a real Pushover notification.
Run with:  python3 test_notification.py
"""

import json
import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# ── Load configs ──────────────────────────────────────────────────────────────

try:
    with open('transcription_config.json') as f:
        config = json.load(f)
except FileNotFoundError:
    print("ERROR: transcription_config.json not found")
    sys.exit(1)

pushover_config = config.get('pushover', {})
if not pushover_config.get('enabled'):
    print("ERROR: Pushover is not enabled in transcription_config.json")
    sys.exit(1)

# ── Fetch most recent Active911 alert (no time filter) ───────────────────────

import active911
active911.ALERT_MINUTES = 999999  # override to get historical alerts

from active911 import get_recent_alert, build_maps_url
from pushover_notify import send_pushover, format_dispatch_message

print("\nFetching most recent Active911 alert...")
alert = get_recent_alert()

if not alert:
    print("ERROR: No alert returned from Active911 — check token and connectivity")
    sys.exit(1)

address_parts = [alert['address'], alert['city'], alert['state']]
address_str = ', '.join(p for p in address_parts if p)
maps_url = build_maps_url(alert['latitude'], alert['longitude'])

print(f"\nAlert found:")
print(f"  Address:     {address_str}")
print(f"  Description: {alert['description']}")
print(f"  Received:    {alert['received']}")
print(f"  Maps URL:    {maps_url}")

# ── Build message exactly as process_dispatcher does ─────────────────────────

FAKE_TRANSCRIPT = "Wausaukee Rescue respond to a motor vehicle accident with injuries."
FAKE_FILENAME   = "test_page.mp3"
FAKE_XSCRIBE_TIME = 3.7

message = format_dispatch_message(FAKE_TRANSCRIPT, FAKE_FILENAME, FAKE_XSCRIBE_TIME)
message += f"\n\n📍 {address_str}\n{maps_url}"

print(f"\nFull notification message:\n{'-'*40}")
print(message)
print('-' * 40)

# ── Send it ───────────────────────────────────────────────────────────────────

print("\nSending Pushover notification...")
success = send_pushover("🚑 WRS Page [TEST]", message, pushover_config)

if success:
    print("\n✓ Notification sent — check your phone")
else:
    print("\n✗ Notification failed — check Pushover config")
