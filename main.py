import os
import json
import uuid
import requests
from fastapi import FastAPI, Form, BackgroundTasks
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# Twilio Credentials
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

# In-memory session store mapping phone numbers to HairGPT session IDs & history
USER_SESSIONS = {}


def parse_moxie_response(res_data):
    """Extracts text response and suggested_options list from Moxie's response JSON."""
    reply_text = ""
    suggested_options = []

    if isinstance(res_data, dict):
        reply_text = res_data.get("response") or res_data.get("message") or ""
        suggested_options = res_data.get("suggested_options") or []
    elif isinstance(res_data, str):
        reply_text = res_data.strip().strip('"')

    return reply_text, suggested_options


def send_whatsapp_message_with_buttons(to_phone: str, body_text: str, options: list = None):
    """Sends message with WhatsApp Quick Reply buttons via Twilio API."""
    twilio_client = Client(TWILIO_SID, TWILIO_AUTH)

    valid_buttons = []
    if options and isinstance(options, list):
        # WhatsApp limits interactive quick reply buttons to max 3 buttons, 20 chars each
        for idx, option in enumerate(options[:3]):
            clean_text = str(option)[:20]
            valid_buttons.append({
                "type": "reply",
                "reply": {
                    "id": f"btn_{idx}",
                    "title": clean_text
                }
            })

    if valid_buttons:
        interactive_payload = {
            "type": "button",
            "body": {"text": body_text},
            "action": {"buttons": valid_buttons}
        }
        
        try:
            twilio_client.messages.create(
                from_=TWILIO_NUMBER,
                to=to_phone,
                persistent_action=[f"interactive:{json.dumps(interactive_payload)}"]
            )
            return
        except Exception as e:
            print(f"Interactive buttons fallback trigger: {e}")

    # Fallback to standard text with bullet points if buttons fail or exceed limits
    fallback_text = body_text
    if options:
        fallback_text += "\n\n*Suggested options:*\n" + "\n".join([f"• {opt}" for opt in options])

    twilio_client.messages.create(
        from_=TWILIO_NUMBER,
        body=fallback_text,
        to=to_phone
    )


def call_moxie_photo_analyze(image_bytes: bytes, filename: str = "hair.jpg"):
    """Uploads photo to Moxie's /photo/analyze endpoint and returns (reply_text, suggested_options)."""
    try:
        files = {
            "file": (filename, image_bytes, "image/jpeg")
        }
        
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
        
        return "I received your photo, but couldn't get a proper analysis from Moxie HairGPT. Please try uploading again!", []

    except Exception as e:
        print(f"Error calling Moxie photo/analyze: {e}")
        return "Sorry, there was an issue analyzing your photo right now.", []


def call_moxie_chat(user_message: str, session_data: dict):
    """Forwards text message to Moxie's /chat endpoint and returns (reply_text, suggested_options)."""
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

            # Sync session history for multi-turn conversations
            session_data["history"].append({"role": "user", "content": user_message})
            session_data["history"].append({"role": "assistant", "content": reply_text})

            return reply_text, suggested_options
        
        return "I am having trouble connecting to Moxie's chat service right now.", []

    except Exception as e:
        print(f"Error calling Moxie chat: {e}")
        return "Sorry, I couldn't process your text message.", []


def process_whatsapp_payload(sender_phone: str, text: str, media_url: str):
    """Background task processing text or photo payload and dispatching interactive responses."""
    if sender_phone not in USER_SESSIONS:
        USER_SESSIONS[sender_phone] = {
            "session_id": str(uuid.uuid4()),
            "history": []
        }
    
    session = USER_SESSIONS[sender_phone]
    options = []

    # CASE 1: USER SENT AN IMAGE
    if media_url:
        img_res = requests.get(media_url, auth=(TWILIO_SID, TWILIO_AUTH))
        if img_res.status_code == 200:
            bot_reply, options = call_moxie_photo_analyze(img_res.content)
        else:
            bot_reply, options = "Could not download the image from WhatsApp. Please send it again!", []

    # CASE 2: USER SENT TEXT OR TAPPED A BUTTON
    elif text:
        bot_reply, options = call_moxie_chat(text, session)
        
    else:
        bot_reply, options = "Please send a message or a photo of your hair to get started!", []

    # Dispatch back to WhatsApp with buttons / options
    send_whatsapp_message_with_buttons(sender_phone, bot_reply, options)


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