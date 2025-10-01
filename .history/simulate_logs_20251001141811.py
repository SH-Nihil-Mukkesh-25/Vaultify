import requests
import time
import random

url = "https://vaultify-6rbk.onrender.com/api/logs"

events = [
    {"event": "door_unlocked", "detail": "RFID authorized"},
    {"event": "motion_alert", "detail": "Simulated intrusion"},
    {"event": "door_autolock", "detail": "Auto-lock executed"},
    {"event": "rfid_invalid", "detail": "Unauthorized card scan"}
]

while True:
    event = random.choice(events)
    response = requests.post(url, json=event)
    print(f"Sent: {event}, Status: {response.status_code}")
    time.sleep(5)  # send every 5 seconds
