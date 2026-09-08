from flask import Blueprint, render_template
from app.db import get_db

main = Blueprint('main', __name__)

@main.route('/')
def all_emails():
    db = get_db()
    collection = db['emails']
    emails = list(collection.find({}))

    high_emails = [e for e in emails if e.get('category') == 'High']
    medium_emails = [e for e in emails if e.get('category') == 'Medium']
    low_emails = [e for e in emails if e.get('category') == 'Low']

    return render_template('all_emails.html', high_emails=high_emails, medium_emails=medium_emails, low_emails=low_emails)
