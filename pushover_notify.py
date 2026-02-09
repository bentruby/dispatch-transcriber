#!/usr/bin/env python3
"""
Send Pushover notifications for dispatch transcriptions
"""

import requests

def send_pushover(title, message, config):
    """
    Send a Pushover notification using config settings
    
    Args:
        title: Notification title
        message: Notification body
        config: Dict with 'user_key', 'api_token', 'priority' keys
    
    Returns:
        True if successful, False otherwise
    """
    # Support both "user_keys" (array) and legacy "user_key" (string)
    user_keys = config.get('user_keys', [])
    if not user_keys:
        legacy_key = config.get('user_key', '')
        if legacy_key:
            user_keys = [legacy_key]

    api_token = config.get('api_token', '')
    priority = config.get('priority', 1)

    if not user_keys or not api_token:
        print("  ⚠️  Pushover credentials not configured in config file")
        return False

    all_success = True
    for user_key in user_keys:
        try:
            response = requests.post(
                'https://api.pushover.net/1/messages.json',
                data={
                    'token': api_token,
                    'user': user_key,
                    'title': title,
                    'message': message,
                    'priority': priority
                },
                timeout=10
            )

            if response.status_code != 200:
                print(f"  ⚠️  Pushover failed for {user_key[:8]}...: {response.status_code} - {response.text}")
                all_success = False

        except Exception as e:
            print(f"  ⚠️  Pushover error for {user_key[:8]}...: {e}")
            all_success = False

    return all_success

def format_dispatch_message(corrected_text, filename, transcription_time):
    """Format the dispatch text for notification"""
    
    # Truncate if too long (Pushover limit is 1024 chars)
    max_length = 900  # Leave room for metadata
    
    if len(corrected_text) > max_length:
        message = corrected_text[:max_length] + "..."
    else:
        message = corrected_text
    
    # Add metadata footer
    message += f"\n\n[{filename} • {transcription_time:.1f}s]"
    
    return message

if __name__ == "__main__":
    # Test notification
    import sys
    import json
    
    # Try to load config
    try:
        with open('transcription_config.json', 'r') as f:
            config = json.load(f)
            pushover_config = config.get('pushover', {})
    except:
        print("Error: Could not load transcription_config.json")
        print("\nAdd this to your config file:")
        print('"pushover": {')
        print('  "enabled": true,')
        print('  "user_keys": ["user_key_1", "user_key_2"],')
        print('  "api_token": "your_api_token_here",')
        print('  "priority": 1')
        print('}')
        sys.exit(1)
    
    if len(sys.argv) > 1:
        test_message = ' '.join(sys.argv[1:])
    else:
        test_message = "Test dispatch notification from transcription system"
    
    print("Sending test Pushover notification...")
    print(f"User key: {pushover_config.get('user_key', 'NOT SET')[:10]}...")
    
    success = send_pushover("Dispatch Test", test_message, pushover_config)
    
    if success:
        print("✓ Test notification sent successfully!")
    else:
        print("✗ Test notification failed")