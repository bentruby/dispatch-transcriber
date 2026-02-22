#!/usr/bin/env python3
"""
Active911 API integration for emergency alert enrichment.
Queries the Active911 API for recent alerts and returns structured data
(address, coordinates, description) to include in dispatch notifications.

Token management:
  - Reads refresh_token from active911_config.json
  - Automatically refreshes the access token when expired
  - Writes the new access_token and expiration back to active911_config.json
  - Falls back to ACTIVE911_TOKEN env var (no auto-refresh in that case)
"""

import os
import json
import logging
import requests
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

ACTIVE911_BASE_URL = "https://access.active911.com/interface/open_api/api"
TOKEN_ENDPOINT     = "https://console.active911.com/interface/dev/api_access.php"
CONFIG_FILE        = os.getenv('ACTIVE911_CONFIG', 'active911_config.json')
ALERT_MINUTES      = int(os.getenv('ACTIVE911_ALERT_MINUTES', '3'))

# Refresh the token if it expires within this many minutes
TOKEN_EXPIRY_BUFFER_MINUTES = 5

# ============================================================================
# TOKEN MANAGEMENT
# ============================================================================

def _load_config():
    """Load active911_config.json. Returns empty dict if missing."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Active911: could not read {CONFIG_FILE}: {e}")
    return {}

def _save_config(config):
    """Write updated token fields back to active911_config.json."""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
            f.write('\n')
    except Exception as e:
        logger.error(f"Active911: could not save {CONFIG_FILE}: {e}")

def _is_token_valid(expiration):
    """
    Return True if the access token won't expire within the buffer window.
    Handles Unix timestamps (int or numeric string) and ISO-format strings.
    """
    if not expiration:
        return False
    try:
        exp_float = float(expiration)
        exp_dt = datetime.fromtimestamp(exp_float)
    except (ValueError, TypeError, OSError):
        try:
            exp_dt = datetime.fromisoformat(str(expiration))
        except (ValueError, TypeError):
            logger.warning(f"Active911: unrecognised expiration format: {expiration!r}")
            return False

    return datetime.now() < exp_dt - timedelta(minutes=TOKEN_EXPIRY_BUFFER_MINUTES)

def _refresh_access_token(refresh_token):
    """
    Exchange a refresh token for a new access token.

    POST https://console.active911.com/interface/dev/api_access.php
      refresh_token=<value>

    Returns (access_token, expiration) or (None, None) on failure.
    """
    try:
        response = requests.post(
            TOKEN_ENDPOINT,
            data={'refresh_token': refresh_token},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Active911 token refresh request failed: {e}")
        return None, None
    except ValueError as e:
        logger.error(f"Active911 token refresh response not valid JSON: {e}")
        return None, None

    access_token = data.get('access_token')
    expiration   = data.get('expiration')

    if not access_token:
        logger.error(f"Active911 token refresh: unexpected response: {data}")
        return None, None

    return access_token, expiration

def _get_valid_token():
    """
    Return a valid access token, refreshing automatically if needed.

    Priority:
      1. ACTIVE911_TOKEN env var  (static, no auto-refresh)
      2. active911_config.json    (auto-refresh when expired)
    """
    # 1. Env var override (e.g. for CI or manual testing)
    env_token = os.getenv('ACTIVE911_TOKEN')
    if env_token:
        return env_token

    # 2. Config file with auto-refresh
    config = _load_config()

    refresh_token = config.get('refresh_token', '')
    if not refresh_token or refresh_token == 'your_refresh_token_here':
        logger.warning("Active911: refresh_token not set in active911_config.json")
        return None

    access_token = config.get('access_token', '')
    expiration   = config.get('token_expiration', '')

    if access_token and _is_token_valid(expiration):
        return access_token

    # Token missing or expired — refresh it
    logger.info("Active911: access token expired or missing, refreshing...")
    new_token, new_expiration = _refresh_access_token(refresh_token)

    if not new_token:
        return None

    # Persist the new token so we don't refresh on every call
    config['access_token']    = new_token
    config['token_expiration'] = new_expiration
    _save_config(config)
    logger.info("Active911: access token refreshed and saved")

    return new_token

# ============================================================================
# API FUNCTIONS
# ============================================================================

def get_recent_alert():
    """
    Query Active911 for alerts in the last ALERT_MINUTES minutes.
    Fetches full detail for the first alert found.

    Returns a dict with keys:
        address, city, state, latitude, longitude, description, received
    Returns None if no alerts found or any request fails.
    """
    token = _get_valid_token()
    if not token:
        logger.warning("Active911: no valid token available — skipping alert lookup")
        return None

    headers = {'Authorization': f'Bearer {token}'}

    # -------------------------------------------------------------------------
    # Step 1: List recent alerts
    # -------------------------------------------------------------------------
    try:
        response = requests.get(
            f"{ACTIVE911_BASE_URL}/alerts",
            headers=headers,
            params={'alert_minutes': ALERT_MINUTES},
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Active911 alerts request failed: {e}")
        return None
    except ValueError as e:
        logger.error(f"Active911 alerts response not valid JSON: {e}")
        return None

    alerts = data.get('message', {}).get('alerts', [])
    if not alerts:
        logger.info("Active911: no recent alerts found")
        return None

    # -------------------------------------------------------------------------
    # Step 2: Fetch full detail for the first alert
    # -------------------------------------------------------------------------
    first_alert = alerts[0]

    alert_uri = first_alert.get('uri', '')
    if alert_uri:
        alert_url = alert_uri  # API returns a fully-qualified URL
    else:
        alert_id = first_alert.get('id')
        if not alert_id:
            logger.error("Active911: alert has no URI or id field")
            return None
        alert_url = f"{ACTIVE911_BASE_URL}/alerts/{alert_id}"

    try:
        detail_response = requests.get(
            alert_url,
            headers=headers,
            timeout=10
        )
        detail_response.raise_for_status()
        detail_data = detail_response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Active911 alert detail request failed: {e}")
        return None
    except ValueError as e:
        logger.error(f"Active911 alert detail response not valid JSON: {e}")
        return None

    alert = detail_data.get('message', {}).get('alert', {})
    if not alert:
        logger.error("Active911: detail response missing alert data")
        return None

    # -------------------------------------------------------------------------
    # Step 3: Extract and return structured fields
    # -------------------------------------------------------------------------
    return {
        'address':     alert.get('address', ''),
        'city':        alert.get('city', ''),
        'state':       alert.get('state', ''),
        'latitude':    alert.get('lat') or alert.get('latitude'),
        'longitude':   alert.get('lon') or alert.get('longitude'),
        'description': alert.get('description', ''),
        'received':    alert.get('received', ''),
    }

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def build_maps_url(latitude, longitude):
    """
    Build a Google Maps URL for the given coordinates.
    Returns a string like: https://maps.google.com/?q=LAT,LONG
    """
    return f"https://maps.google.com/?q={latitude},{longitude}"

# ============================================================================
# STANDALONE TEST
# ============================================================================

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )

    print("=" * 60)
    print("Active911 API Test")
    print("=" * 60)

    # Show token status before attempting anything
    cfg = _load_config()
    rt = cfg.get('refresh_token', '')
    at = cfg.get('access_token', '')
    exp = cfg.get('token_expiration', '')

    if rt and rt != 'your_refresh_token_here':
        print(f"Refresh token: {rt[:8]}...{rt[-4:]}")
    else:
        print("\nERROR: refresh_token not set.")
        print(f"Edit {CONFIG_FILE} and replace 'your_refresh_token_here' with your token.")
        sys.exit(1)

    if at and _is_token_valid(exp):
        print(f"Access token:  {at[:8]}...{at[-4:]} (valid, expires {exp})")
    else:
        print("Access token:  missing or expired — will refresh")

    print()

    token = _get_valid_token()
    if not token:
        print("ERROR: Could not obtain a valid access token.")
        sys.exit(1)

    # Re-read config to show updated values after any refresh
    cfg = _load_config()
    print(f"Access token:  {cfg.get('access_token','')[:8]}...{cfg.get('access_token','')[-4:]}")
    print(f"Expires:       {cfg.get('token_expiration','')}")
    print()

    print(f"Querying alerts from last {ALERT_MINUTES} minutes...")
    print()

    alert = get_recent_alert()

    if alert:
        print("Alert found:")
        for key, value in alert.items():
            print(f"  {key:<12}: {value}")
        print()
        if alert.get('latitude') and alert.get('longitude'):
            print(f"Maps URL: {build_maps_url(alert['latitude'], alert['longitude'])}")
    else:
        print("No recent alerts found (or request failed).")

    print()
    print("=" * 60)
