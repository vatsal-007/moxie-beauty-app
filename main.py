import os
import json
import requests
import urllib.parse
from fastapi import FastAPI, Form, BackgroundTasks, Request
from fastapi.staticfiles import StaticFiles
from twilio.rest import Client
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI()

# 🌟 NEW: Expose your local assets folder to the web so Twilio can download the images
app.mount("/assets", StaticFiles(directory="wavy_curly_assets"), name="assets")

# Credentials
TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_NUMBER = "whatsapp:+14155238886"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# Load your local catalog
try:
    with open("wavy_curly_catalog.json", "r", encoding="utf-8") as f:
        CATALOG = json.load(f)
except FileNotFoundError:
    CATALOG = []

def process_twilio_image(sender_phone: str, media_url: str, ngrok_url: str):
    """Background task to fetch image, run AI, and reply via Twilio."""
    try:
        # 1. Download image from Twilio
        image_response = requests.get(media_url, auth=(TWILIO_SID, TWILIO_AUTH))
        if image_response.status_code != 200:
            print(f"Error downloading image: {image_response.text}")
            return
        image_bytes = image_response.content

        # 2. Run Gemini AI
        prompt = """
        Analyze the hair texture in this photo for Moxie Beauty.
        Return ONLY a JSON object with:
        - "archetype": "WAVY_VIBE_SETTER" or "CURLY_VIBE_SETTER"
        - "classification": e.g., "Type 2B Wavy"
        - "reasoning": 1-sentence analysis of texture.
        """
        
        response = gemini_client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=[types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"), prompt],
            config={"response_mime_type": "application/json"}
        )
        
        ai_data = json.loads(response.text.strip())
        
        # 3. Match Archetype & Extract Image URL
        target_handle = "wavy-vibe-setter-duo" if ai_data.get("archetype") == "WAVY_VIBE_SETTER" else "curly-vibe-setter-duo"
        matched_bundle = next((p for p in CATALOG if p.get("handle") == target_handle), None)
        
        cart_url = f"https://moxiebeauty.in/products/{target_handle}"
        product_image_url = None

        if matched_bundle:
            # Build the Cart Link
            if matched_bundle.get("variants"):
                variant_id = matched_bundle["variants"][0]["id"]
                cart_url = f"https://moxiebeauty.in/cart/{variant_id}:1?discount=MOXIEAI10"
            
            # 🌟 NEW: Format the local image path into a public Ngrok URL for Twilio
            if matched_bundle.get("images"):
                # Convert Windows backslashes to Linux forward slashes
                raw_image_path = matched_bundle["images"][0].replace("\\", "/")
                filename = os.path.basename(raw_image_path)
                
                safe_filename = urllib.parse.quote(filename)
                product_image_url = f"{ngrok_url}/assets/{safe_filename}"

        # 4. Format Message
        reply_text = (
            f"✨ *Moxie Hair Diagnosis*\n\n"
            f"*{ai_data.get('classification')}*\n"
            f"{ai_data.get('reasoning')}\n\n"
            f"🛍️ *Your Custom Routine:*\n"
            f"🛒 Tap here to buy with 10% off: {cart_url}"
        )

        # 5. Send Reply via Twilio
        client = Client(TWILIO_SID, TWILIO_AUTH)
        
        msg_params = {
            "from_": TWILIO_NUMBER,
            "body": reply_text,
            "to": sender_phone
        }
        
        # 🌟 NEW: Attach the image if we successfully constructed the URL
        if product_image_url:
            msg_params["media_url"] = [product_image_url]

        client.messages.create(**msg_params)

    except Exception as e:
        print(f"Error in background task: {e}")

@app.post("/webhook")
async def twilio_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    From: str = Form(...),
    NumMedia: int = Form(0),
    MediaUrl0: str = Form(None)
):
    # 🌟 NEW: Automatically capture your active Ngrok URL so it never breaks when you restart Ngrok
    host = request.headers.get("host")
    ngrok_url = f"https://{host}"

    if NumMedia > 0 and MediaUrl0:
        background_tasks.add_task(process_twilio_image, From, MediaUrl0, ngrok_url)
    else:
        client = Client(TWILIO_SID, TWILIO_AUTH)
        client.messages.create(
            from_=TWILIO_NUMBER,
            body="Please upload a photo of your hair so our AI can analyze your texture! ✨",
            to=From
        )
        
    return "OK"