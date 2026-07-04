"""Submit multiple test issues to verify clustering, dedup, and ranking."""
import requests

BASE = "http://localhost:8000"

# Register some test citizens
citizens = []
for i, (phone, name, pin) in enumerate([
    ("9876543211", "Ravi Kumar", "751024"),
    ("9876543212", "Priya Patel", "751019"),
    ("9876543213", "Suman Das", "751024"),
    ("9876543214", "Amit Mohapatra", "751012"),
    ("9876543215", "Sneha Mishra", "751007"),
]):
    r = requests.post(f"{BASE}/auth/register", json={
        "phone": phone, "password": "test1234", "name": name, "home_pin_code": pin
    })
    if r.status_code == 201:
        citizens.append({"phone": phone, "token": r.json()["access_token"]})
        print(f"Registered: {name}")
    elif r.status_code == 409:
        r2 = requests.post(f"{BASE}/auth/login", json={"phone": phone, "password": "test1234"})
        if r2.status_code == 200:
            citizens.append({"phone": phone, "token": r2.json()["access_token"]})
            print(f"Logged in: {name}")

# Submit various issues
submissions = [
    # 3 people reporting similar road issues → should cluster together
    (0, "751024", "The road near Patia market is full of potholes, very dangerous for commuters"),
    (1, "751019", "Roads in Niladri Vihar are broken with huge potholes causing accidents"),
    (2, "751024", "Patia main road has dangerous potholes near the market area"),

    # 2 people reporting water issues → different cluster
    (3, "751012", "No drinking water supply in Khandagiri area for past 2 weeks"),
    (4, "751007", "Water pipeline is broken near Jaydev Vihar, no tap water for residents"),

    # 1 person reporting school issue → new cluster
    (1, "751019", "Primary school near Niladri Vihar needs more classrooms, children sitting on floor"),

    # 1 person reporting health issue → new cluster
    (0, "751024", "Need a PHC health center in Patia area, nearest hospital is 8km away"),

    # Electricity issue
    (3, "751012", "No streetlights in Khandagiri colony sector 5, very unsafe at night"),
]

for citizen_idx, pin, text in submissions:
    if citizen_idx >= len(citizens):
        continue
    h = {"Authorization": f"Bearer {citizens[citizen_idx]['token']}"}
    r = requests.post(f"{BASE}/submissions/", headers=h, data={
        "submission_pin_code": pin, "input_type": "text",
        "raw_text": text, "raw_language": "en"
    })
    if r.status_code == 201:
        print(f"  Submitted: {r.json()['tracking_id']} — {text[:50]}...")
    else:
        print(f"  FAILED: {r.status_code} {r.json()}")

print(f"\nTotal submissions created. Run scheduler to process!")
