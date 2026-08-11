import os
import json
import uuid
import requests
from fastapi import FastAPI, Form, BackgroundTasks
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# Credentials
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = "whatsapp:+14155238886"

# Moxie HairGPT Cloud Run Endpoints
HAIRGPT_CHAT_URL = "https://hairgpt-preview-586722022195.asia-south1.run.app/chat"
HAIRGPT_ANALYZE_URL = "https://hairgpt-preview-586722022195.asia-south1.run.app/photo/analyze"

COMMON_HEADERS = {
    "accept": "*/*",
    "origin": "https://moxiebeauty.in",
    "referer": "https://moxiebeauty.in/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
}

# In-memory session store mapping phone numbers to HairGPT sessions & history
USER_SESSIONS = {}


def parse_moxie_response(res_data):
    """Extracts response text and suggested_options from Moxie's response JSON."""
    reply_text = ""
    suggested_options = []

    if isinstance(res_data, dict):
        # Check all possible keys Moxie uses across /chat and /photo/analyze
        reply_text = (
            res_data.get("analysis") or 
            res_data.get("response") or 
            res_data.get("message") or 
            res_data.get("text") or 
            res_data.get("result") or 
            ""
        )
        suggested_options = res_data.get("suggested_options") or []
        
        # Fallback: If no known text key matched, check if there's any value string
        if not reply_text and res_data:
            print(f"Unrecognized dictionary keys from Moxie: {res_data.keys()}")
            # If there is only one string value in the dict, use it
            for val in res_data.values():
                if isinstance(val, str) and len(val) > 10:
                    reply_text = val
                    break

    elif isinstance(res_data, str):
        reply_text = res_data.strip().strip('"')

    # Guaranteed fallback if reply_text is still empty
    if not reply_text:
        reply_text = "Analysis complete! I see your hair photo, but couldn't parse the detailed breakdown. How can I help you style it?"

    return reply_text, suggested_options


def send_whatsapp_text(to_phone: str, body_text: str, options: list = None):
    """Sends a clean, text-only message to WhatsApp with formatted suggested options."""
    twilio_client = Client(TWILIO_SID, TWILIO_AUTH)

    # Ensure body_text is never empty
    final_text = body_text.strip() if body_text else "Here is your response from Moxie HairGPT:"

    # Append suggested options as bullet points if available
    if options and isinstance(options, list):
        final_text += "\n\n*Suggested options:*\n" + "\n".join([f"• {opt}" for opt in options])

    try:
        twilio_client.messages.create(
            from_=TWILIO_NUMBER,
            body=final_text,
            to=to_phone
        )
    except Exception as e:
        print(f"Error sending WhatsApp message: {e}")


def call_moxie_photo_analyze(image_bytes: bytes, filename: str = "hair.jpg"):
    """Uploads image bytes to Moxie's /photo/analyze endpoint."""
    try:
        files = {"file": (filename, image_bytes, "image/jpeg")}
        response = requests.post(
            HAIRGPT_ANALYZE_URL,
            files=files,
            headers=COMMON_HEADERS,
            timeout=25
        )

        if response.status_code == 200:
            try:
                res_data = response.json()
                return parse_moxie_response(res_data)
            except Exception:
                return response.text.strip().strip('"'), []
        
        return "I received your photo, but couldn't process it with Moxie HairGPT. Please try sending it again!", []

    except Exception as e:
        print(f"Error calling Moxie photo/analyze: {e}")
        return "Sorry, there was an issue analyzing your photo.", []


def call_moxie_chat(user_message: str, session_data: dict):
    """Forwards text message to Moxie's /chat endpoint."""
    headers = {**COMMON_HEADERS, "content-type": "application/json"}

    payload = {
        "message": user_message,
        "session_id": session_data["session_id"],
        "history": session_data["history"],
        "device_info": {
            "userAgent": COMMON_HEADERS["user-agent"],
            "platform": "Win32",
            "language": "en-US",
            "isMobile": True
        },
        "ga_context": {}
    }

    try:
        response = requests.post(HAIRGPT_CHAT_URL, json=payload, headers=headers, timeout=15)
        
        if response.status_code == 200:
            try:
                res_data = response.json()
                reply_text, suggested_options = parse_moxie_response(res_data)
            except Exception:
                reply_text, suggested_options = response.text.strip().strip('"'), []

            # Save to conversation history
            session_data["history"].append({"role": "user", "content": user_message})
            session_data["history"].append({"role": "assistant", "content": reply_text})

            return reply_text, suggested_options
        
        return "I am having trouble connecting to Moxie's chat service right now.", []

    except Exception as e:
        print(f"Error calling Moxie chat: {e}")
        return "Sorry, I couldn't process your message.", []


def process_whatsapp_payload(sender_phone: str, text: str, media_url: str):
    """Handles incoming WhatsApp payloads with chained photo-to-chat flow."""
    if sender_phone not in USER_SESSIONS:
        USER_SESSIONS[sender_phone] = {
            "session_id": str(uuid.uuid4()),
            "history": []
        }
    
    session = USER_SESSIONS[sender_phone]
    options = []

    # CASE 1: USER SENT AN IMAGE (2-Step Chain to mirror Moxie Web UI)
    if media_url:
        img_res = requests.get(media_url, auth=(TWILIO_SID, TWILIO_AUTH))
        if img_res.status_code == 200:
            # Step 1: Extract raw vision analysis
            raw_analysis, _ = call_moxie_photo_analyze(img_res.content)
            
            # Step 2: Pass raw vision analysis into /chat so HairGPT talks naturally
            chat_prompt = (
                f"[User uploaded a hair photo. Analysis: {raw_analysis}]\n\n"
                "Please respond to this hair analysis naturally."
            )
            bot_reply, options = call_moxie_chat(chat_prompt, session)
        else:
            bot_reply, options = "Could not download the image from WhatsApp. Please send it again!", []

    # CASE 2: USER SENT TEXT
    elif text:
        bot_reply, options = call_moxie_chat(text, session)
        
    else:
        bot_reply, options = "Please send a message or a photo of your hair to get started!", []

    # Send natural conversational response back to WhatsApp
    send_whatsapp_text(sender_phone, bot_reply, options)


@app.post("/webhook")
async def twilio_webhook(
    background_tasks: BackgroundTasks,
    From: str = Form(...),
    Body: str = Form(None),
    NumMedia: int = Form(0),
    MediaUrl0: str = Form(None)
):
    background_tasks.add_task(
        process_whatsapp_payload,
        sender_phone=From,
        text=Body,
        media_url=MediaUrl0 if NumMedia > 0 else None
    )
    return "OK"