from flask import Flask
from app.routes import main
from app.db import get_db  # If you need to use it for database connection

def clean_email_content(content):
    if not content:
        return ''
    lines = content.splitlines()
    cleaned_lines = [line.rstrip() for line in lines]  # remove trailing spaces
    if cleaned_lines:
        cleaned_lines[0] = cleaned_lines[0].strip()  # fix the first line
    return '\n'.join(cleaned_lines)



from flask import Flask
from app.routes import main  # <-- make sure this import is correct

def create_app():
    app = Flask(__name__)

    app.register_blueprint(main)  # <-- make sure this is here

    return app





