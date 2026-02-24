# fix_urls.py - CORRECTED VERSION
from pymongo import MongoClient
from bson import ObjectId

client = MongoClient('mongodb://localhost:27017/')
db = client.scavenger_hunt_db

# YOUR NEW NGROK URL:
PUBLIC_URL = "https://unmoralising-nonpungently-edward.ngrok-free.dev"

# YOUR CORRECT HUNT ID (from check_ids.py output):
CORRECT_HUNT_ID = ObjectId('694a61cdaa1fb9a51243f3e3')  # NEW CORRECT ID
# Find only YOUR hunt
hunt = db.hunts.find_one({'_id': CORRECT_HUNT_ID})
if hunt:
    print(f"Updating hunt: {hunt.get('name', 'Unnamed Hunt')}")
    for q in hunt.get('questions', []):
        if 'qr_token' in q:
            new_url = f"{PUBLIC_URL}/student/question/{q['qr_token']}"
            db.hunts.update_one(
                {'_id': CORRECT_HUNT_ID, 'questions.id': q['id']},
                {'$set': {'questions.$.qr_url': new_url}}
            )
            print(f"✓ Fixed: {new_url}")
    print("✅ Done! Database updated with public URL.")
else:
    print(f"❌ ERROR: Hunt with ID {CORRECT_HUNT_ID} not found!")