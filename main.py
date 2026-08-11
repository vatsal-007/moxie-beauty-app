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
    """Extracts response text, suggested options, and routine product details from Moxie's JSON."""
    reply_text = ""
    suggested_options = []
    routine_data = None

    if isinstance(res_data, dict):
        reply_text = (
            res_data.get("response") or 
            res_data.get("message") or 
            res_data.get("analysis") or 
            ""
        )
        suggested_options = res_data.get("suggested_options") or []
        routine_data = res_data.get("routine")
        
    elif isinstance(res_data, str):
        reply_text = res_data.strip().strip('"')

    return reply_text, suggested_options, routine_data


def format_routine_response(reply_text: str, routine_data: dict) -> str:
    """Formats the routine steps, product links, and total price into a clean WhatsApp recommendation message."""
    if not routine_data or not routine_data.get("steps"):
        return reply_text

    routine_title = routine_data.get("routine", "Your Custom Hair Routine")
    steps = routine_data.get("steps", [])

    formatted_msg = f"{reply_text}\n\n"
    formatted_msg += f"✨ *RECOMMENDED ROUTINE: {routine_title.upper()}* ✨\n"
    formatted_msg += "───────────────\n"

    cart_items = []

    for step in steps:
        step_num = step.get("step")
        name = step.get("name")
        price = step.get("price")
        why = step.get("why")
        url = step.get("url")
        
        formatted_msg += f"*{step_num}. {name}* ({price})\n"
        formatted_msg += f"💡 _{why}_\n"
        if url:
            formatted_msg += f"🔗 Details: {url}\n"
        formatted_msg += "\n"

    formatted_msg += "───────────────\n"
    
    # 🛒 Build 1-Click Buy Link
    # Moxie main bundle checkout fallback
    formatted_msg += "🛒 *Ready to transform your hair?*\n"
    formatted_msg += "Tap here to view bundle & add to cart:\n"
    formatted_msg += "👉 https://moxiebeauty.in/collections/all\n"

    return formatted_msg


def send_whatsapp_text(to_phone: str, body_text: str, options: list = None):
    """Sends clean text response with formatted bullet options."""
    twilio_client = Client(TWILIO_SID, TWILIO_AUTH)

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
    """Uploads photo to Moxie's /photo/analyze endpoint."""
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
                return response.text.strip().strip('"'), [], None
        
        return "I received your photo, but couldn't analyze it right now. Please try again!", [], None

    except Exception as e:
        print(f"Error calling Moxie photo/analyze: {e}")
        return "Sorry, there was an issue analyzing your photo.", [], None


def call_moxie_chat(user_message: str, session_data: dict):
    """Forwards query to Moxie's /chat endpoint."""
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
                reply_text, suggested_options, routine_data = parse_moxie_response(res_data)
            except Exception:
                reply_text, suggested_options, routine_data = response.text.strip().strip('"'), [], None

            # Sync session history
            session_data["history"].append({"role": "user", "content": user_message})
            session_data["history"].append({"role": "assistant", "content": reply_text})

            return reply_text, suggested_options, routine_data
        
        return "I am having trouble connecting to Moxie's chat service right now.", [], None

    except Exception as e:
        print(f"Error calling Moxie chat: {e}")
        return "Sorry, I couldn't process your message.", [], None


def process_whatsapp_payload(sender_phone: str, text: str, media_url: str):
    """Processes incoming messages, photo uploads, and routine recommendations."""
    if sender_phone not in USER_SESSIONS:
        USER_SESSIONS[sender_phone] = {
            "session_id": str(uuid.uuid4()),
            "history": []
        }
    
    session = USER_SESSIONS[sender_phone]
    options = []
    routine_data = None

    # CASE 1: USER SENT AN IMAGE (2-step chain to get friendly chat response)
    if media_url:
        img_res = requests.get(media_url, auth=(TWILIO_SID, TWILIO_AUTH))
        if img_res.status_code == 200:
            raw_analysis, _, _ = call_moxie_photo_analyze(img_res.content)
            
            chat_prompt = (
                f"[User uploaded a hair photo. Analysis: {raw_analysis}]\n\n"
                "Please respond to this hair analysis naturally."
            )
            bot_reply, options, routine_data = call_moxie_chat(chat_prompt, session)
        else:
            bot_reply, options = "Could not download the image from WhatsApp. Please send it again!", []

    # CASE 2: USER SENT TEXT
    elif text:
        bot_reply, options, routine_data = call_moxie_chat(text, session)
        
    else:
        bot_reply, options = "Please send a message or a photo of your hair to get started!", []

    # Format text if routine products were returned in the payload
    if routine_data:
        bot_reply = format_routine_response(bot_reply, routine_data)

    # Dispatch to WhatsApp
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