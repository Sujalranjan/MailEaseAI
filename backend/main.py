from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict
from beckend.email_utils import fetch_emails  # Import the fetch_emails function

app = FastAPI()

# Configure CORS
origins = [
    "http://localhost:3000",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "MailEase AI Backend is running!"}

@app.get("/emails/", response_model=List[Dict])
async def get_emails():
    """
    API endpoint to fetch emails.
    Replace with your actual email credentials and server.
    """
    mail_server = "imap.gmail.com"  # Or your email provider's server
    email_user = "sujalranjan02@gmail.com"  # Replace with your email
    email_pass = "@Sujal14112005"  # Replace with your password

    try:
        emails = fetch_emails(mail_server, email_user, email_pass)
        return emails
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)