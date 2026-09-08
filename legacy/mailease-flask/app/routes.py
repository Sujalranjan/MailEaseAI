from flask import Blueprint, render_template
from app.email_utils import fetch_emails

main = Blueprint('main', __name__)

@main.route("/")
def home():
    return render_template("home.html")  # Circular cards UI

@main.route("/emails/<priority>")
def emails_by_priority(priority):
    all_emails = fetch_emails()
    filtered = [email for email in all_emails if email["category"].lower() == priority.lower()]
    return render_template("emails.html", emails=filtered, priority=priority.capitalize())
