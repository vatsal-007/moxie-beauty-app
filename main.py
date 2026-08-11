import os
import uuid
import requests
from fastapi import FastAPI, Form, BackgroundTasks, Request
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = "whatsapp:+14155238886"

HAIRGPT_URL = "https://hairgpt-preview-586722022195.asia-south1.run.app/chat"

# In-memory session store mapping phone numbers to HairGPT sessions & conversation history
# Structure: { "+123456": {"session_id": "...", "history": []} }
USER_SESSIONS = {}

def call_hairgpt_api(user_message: str, session_data: dict) -> str:
    """Payload forwarder to Moxie's actual HairGPT endpoint."""
    headers = {
        "accept": "*/*",
        "content-type": "application/json",
        "origin": "https://moxiebeauty.in",
        "referer": "https://moxiebeauty.in/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
    }

    payload = {
        "message": user_message,
        "session_id": session_data["session_id"],
        "history": session_data["history"],
        "device_info": {
            "userAgent": headers["user-agent"],
            "platform": "Win32",
            "language": "en-US",
            "isMobile": True
        },
        "ga_context": {}
    }

    try:
        response = requests.post(HAIRGPT_URL, json=payload, headers=headers, timeout=15)
        
        if response.status_code == 200:
            # Handle both JSON string response or dict response
            try:
                res_data = response.json()
                # Extract text if returned inside an object or as plain text
                reply_text = res_data.get("response") or res_data.get("message") or response.text
            except Exception:
                reply_text = response.text

            # Clean up raw quotes if returned as a JSON string
            reply_text = reply_text.strip().strip('"')

            # Update conversation history for the next turn
            session_data["history"].append({"role": "user", "content": user_message})
            session_data["history"].append({"role": "assistant", "content": reply_text})

            return reply_text
        else:
            print(f"HairGPT API Error ({response.status_code}): {response.text}")
            return "I'm having a bit of trouble connecting to Moxie HairGPT right now. Please try again!"

    except Exception as e:
        print(f"Exception calling HairGPT API: {e}")
        return "Sorry, I couldn't process that request right now."

def process_whatsapp_chat(sender_phone: str, user_text: str):
    """Background task to bridge WhatsApp and HairGPT."""
    # Initialize session if first time messaging
    if sender_phone not in USER_SESSIONS:
        USER_SESSIONS[sender_phone] = {
            "session_id": str(uuid.uuid4()),
            "history": []
        }

    session = USER_SESSIONS[sender_phone]
    
    # Get response from Moxie HairGPT API
    bot_reply = call_hairgpt_api(user_text, session)

    # Dispatch back to WhatsApp
    twilio_client = Client(TWILIO_SID, TWILIO_AUTH)
    twilio_client.messages.create(
        from_=TWILIO_NUMBER,
        body=bot_reply,
        to=sender_phone
    )

@app.post("/webhook")
async def twilio_webhook(
    background_tasks: BackgroundTasks,
    From: str = Form(...),
    Body: str = Form(None)
):
    if Body:
        background_tasks.add_task(process_whatsapp_chat, From, Body)

    return "OK"