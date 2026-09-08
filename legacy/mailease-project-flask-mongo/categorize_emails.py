from pymongo import MongoClient
from collections import Counter
import re
import sys

# MongoDB setup
try:
    client = MongoClient("mongodb://localhost:27017/")
    db = client["mailease"]  # Replace with your actual DB name if different
    collection = db["emails"]
except Exception as e:
    print(f"❌ MongoDB connection failed: {e}")
    sys.exit(1)

# Keywords for categorization
HIGH_PRIORITY = ['urgent','placement','test', 'asap', 'deadline', 'immediate', 'today', 'tomorrow','last date', 'submit by', 'final call', 'submission', 'due','hackathon', 'hack', 'urgent request', 'important', 'critical', 'action required', 'emergency', 'alert', 'warning', 'notice','Date']
MEDIUM_PRIORITY = ['reminder', 'follow up', 'event', 'schedule', 'session', 'meeting', 'workshop', 'appointment', 'call', 'update']

def categorize_email(subject, content):
    text = f"{subject} {content}".lower()
    if any(word in text for word in HIGH_PRIORITY):
        return "High"
    elif any(word in text for word in MEDIUM_PRIORITY):
        return "Medium"
    return "Low"

def categorize_all_emails():
    emails = collection.find()
    counts = Counter()

    for email in emails:
        subject = email.get("Subject", "")
        content = email.get("Content", "")
        category = categorize_email(subject, content)

        collection.update_one(
            {"_id": email["_id"]},
            {"$set": {"category": category}}
        )

        counts[category] += 1
        print(f"✅ Categorized: {subject[:40]}... → {category}")

    print("\n📊 Category Summary:")
    for cat in ["High", "Medium", "Low"]:
        print(f"  {cat}: {counts[cat]} emails")

if __name__ == "__main__":
    categorize_all_emails()
