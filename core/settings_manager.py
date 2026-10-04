import json
import os
from datetime import datetime, timezone

SETTINGS_FILE = "settings.json"

def get_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {"scanner_mode": "gate", "switch_time": None}
    with open(SETTINGS_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {"scanner_mode": "gate", "switch_time": None}

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f)

def get_current_scanner_mode():
    settings = get_settings()
    switch_time_str = settings.get("switch_time")
    mode = settings.get("scanner_mode", "gate")
    
    if switch_time_str:
        try:
            # Replace Z with +00:00 for older python compat
            switch_time_str = switch_time_str.replace("Z", "+00:00")
            switch_time = datetime.fromisoformat(switch_time_str)
            if switch_time.tzinfo is None:
                switch_time = switch_time.replace(tzinfo=timezone.utc)
                
            if datetime.now(timezone.utc) >= switch_time:
                # Timer triggered!
                return "food"
        except Exception as e:
            print("Error parsing switch time:", e)
            
    return mode
