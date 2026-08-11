import os
import json
import time
import streamlit as st
from PIL import Image
from google import genai
from google.genai import types

# -----------------------------------------------------------------------------
# 1. Page Configuration & 15-Inch Viewport CSS Styling
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="Moxie Beauty | AI Texture Diagnosis",
    page_icon="✨",
    layout="wide"
)

# Custom CSS for Moxie Visual Identity & Viewport Optimization
st.markdown("""
<style>
    /* Clean up default Streamlit elements & tighten padding for 15" screens */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 1rem !important;
        max-width: 1080px !important;
    }

    /* Canvas Background & Global Fonts */
    .stApp {
        background-color: #FAF4EE !important; /* Soft Warm Cream */
        color: #1E1E1E !important;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }

    /* Image Constraints for 15" Screen (Prevents scrolling) */
    .stImage img {
        max-height: 165px !important;
        object-fit: contain !important;
        border-radius: 12px !important;
    }

    /* Fix Dark Streamlit File Uploader Widget & Attachment Pills */
    [data-testid="stFileUploader"] {
        background-color: #FFFFFF !important;
        border: 1.5px dashed #D84261 !important;
        border-radius: 12px !important;
        padding: 8px !important;
    }
    [data-testid="stFileUploader"] section {
        background-color: #FFFFFF !important;
    }
    [data-testid="stFileUploader"] span, 
    [data-testid="stFileUploader"] small, 
    [data-testid="stFileUploader"] label {
        color: #1E1E1E !important;
    }
    
    /* Style Dark File Pill to Match Page */
    [data-testid="stFileUploaderFile"] {
        background-color: #FAF4EE !important;
        border: 1px solid #EFE3DB !important;
        border-radius: 8px !important;
    }
    [data-testid="stFileUploaderFileData"] span {
        color: #1E1E1E !important;
    }
    [data-testid="stFileUploaderDeleteFile"] button svg {
        fill: #D84261 !important;
    }

    /* Equalized White Cards */
    [data-testid="stVerticalBlockBorderWrapper"] {
        background-color: #FFFFFF !important;
        border: 1px solid #EFE3DB !important;
        border-radius: 16px !important;
        box-shadow: 0px 4px 16px rgba(0, 0, 0, 0.02) !important;
        padding: 18px !important;
    }

    /* Typography Header */
    .brand-header {
        text-align: center;
        margin-bottom: 12px;
    }
    .brand-logo {
        font-size: 1.8rem;
        font-weight: 900;
        letter-spacing: -0.5px;
        color: #1E1E1E;
        line-height: 1;
    }
    .brand-subtitle {
        font-size: 0.8rem;
        font-weight: 800;
        color: #D84261;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        margin-top: 4px;
    }

    /* Step Badges (Replaces Emojis) */
    .step-badge {
        background-color: #FEEFEE;
        color: #D84261;
        font-size: 0.7rem;
        font-weight: 800;
        padding: 3px 10px;
        border-radius: 12px;
        letter-spacing: 1px;
        text-transform: uppercase;
        display: inline-block;
        margin-bottom: 6px;
    }
    .moxie-badge {
        background-color: #FEEFEE;
        color: #D84261;
        padding: 5px 14px;
        border-radius: 20px;
        font-weight: 800;
        font-size: 0.8rem;
        letter-spacing: 0.8px;
        text-transform: uppercase;
        display: inline-block;
        margin-bottom: 8px;
    }

    /* Benefits List */
    .benefit-item {
        font-size: 0.85rem;
        color: #333333;
        margin-bottom: 6px;
        display: flex;
        align-items: center;
    }
    .benefit-check {
        color: #D84261;
        font-weight: bold;
        margin-right: 6px;
    }

    /* Custom AI Scanning Loader Animation */
    .ai-scan-container {
        border: 1.5px solid #D84261;
        background-color: #FFF8F6;
        border-radius: 12px;
        padding: 12px;
        text-align: center;
        margin-top: 10px;
    }
    .pulse-ring {
        display: inline-block;
        width: 12px;
        height: 12px;
        border-radius: 50%;
        background: #D84261;
        box-shadow: 0 0 0 0 rgba(216, 66, 97, 0.7);
        animation: pulsing 1.2s infinite;
        margin-right: 8px;
    }
    @keyframes pulsing {
        0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(216, 66, 97, 0.7); }
        70% { transform: scale(1); box-shadow: 0 0 0 10px rgba(216, 66, 97, 0); }
        100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(216, 66, 97, 0); }
    }

    /* CTA Button */
    .stButton > button {
        background-color: #D84261 !important;
        color: #FFFFFF !important;
        border-radius: 100px !important;
        padding: 10px 20px !important;
        font-weight: 700 !important;
        font-size: 0.95rem !important;
        border: none !important;
        width: 100%;
        transition: all 0.2s ease;
    }
    .stButton > button:hover {
        background-color: #C23553 !important;
    }
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 2. Data Loader & Image Caching (Pre-loads images to eliminate latency)
# -----------------------------------------------------------------------------
@st.cache_data
def load_catalog():
    catalog_path = "wavy_curly_catalog.json"
    if os.path.exists(catalog_path):
        with open(catalog_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

@st.cache_data
def load_pil_image(image_path):
    if os.path.exists(image_path):
        return Image.open(image_path)
    return None

CATALOG = load_catalog()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# -----------------------------------------------------------------------------
# 3. Brand Navbar Header
# -----------------------------------------------------------------------------
st.markdown("""
    <div class="brand-header">
        <div class="brand-logo">MOXIE BEAUTY</div>
        <div class="brand-subtitle">AI Texture Diagnosis & Routine Matcher</div>
    </div>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 4. Main App Layout (Compact 2-Column Grid)
# -----------------------------------------------------------------------------
col_left, col_right = st.columns([1, 1], gap="medium")

# -----------------------------------------------------------------------------
# LEFT COLUMN: Photo Upload & AI Hair Analysis
# -----------------------------------------------------------------------------
with col_left:
    with st.container(border=True):
        st.markdown('<div class="step-badge">STEP 01</div>', unsafe_allow_html=True)
        st.markdown("<h4 style='margin: 0px 0px 8px 0px; font-weight:700;'>Upload Hair Photo</h4>", unsafe_allow_html=True)
        
        uploaded_file = st.file_uploader(
            "Choose photo", 
            type=["jpg", "jpeg", "png"],
            label_visibility="collapsed"
        )

        if uploaded_file:
            # Preview uploaded image cleanly
            image = Image.open(uploaded_file)
            st.image(image, use_container_width=True)
            analyze_btn = st.button("Analyze Hair Texture")
        else:
            analyze_btn = False

    # AI Processing with Animated Pulse State
    if uploaded_file and analyze_btn:
        if not GEMINI_API_KEY:
            st.error("⚠️ GEMINI_API_KEY missing in environment variables.")
        else:
            # Custom Scanner Animation Box
            scan_placeholder = st.empty()
            scan_placeholder.markdown("""
                <div class="ai-scan-container">
                    <span class="pulse-ring"></span>
                    <span style="font-weight:700; color:#D84261; font-size:0.9rem;">
                        Analyzing cuticle porosity & wave pattern...
                    </span>
                </div>
            """, unsafe_allow_html=True)

            try:
                client = genai.Client(api_key=GEMINI_API_KEY)
                uploaded_file.seek(0)
                image_bytes = uploaded_file.read()

                prompt = """
                Analyze the hair texture in this photo and map it to Moxie Beauty's archetypes:
                
                1. WAVY_VIBE_SETTER: Loose or defined S-waves (Types 2A, 2B, 2C). Needs weightless hydration and light flexible hold.
                2. CURLY_VIBE_SETTER: Defined spirals, ringlets, or tight curls (Types 3A, 3B, 3C). Needs deep butter moisture and pattern definition.

                Return ONLY a JSON object with keys:
                - "archetype": "WAVY_VIBE_SETTER" or "CURLY_VIBE_SETTER"
                - "classification": e.g., "TYPE 2B WAVY" or "TYPE 3A CURLY"
                - "summary": A concise 1-sentence description of the hair texture.
                - "porosity": e.g., "Medium Porosity" or "High Moisture Need"
                - "hold_need": e.g., "Flexible Cast (Zero Weight)" or "Moisture Lock & Cast"
                """

                response = client.models.generate_content(
                    model="gemini-3.1-flash-lite",
                    contents=[
                        types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                        prompt
                    ],
                    config={"response_mime_type": "application/json"}
                )

                time.sleep(0.5) # Brief delay for smooth animation visual
                scan_placeholder.empty() # Clear loading box

                res_data = json.loads(response.text.strip())
                st.session_state["ai_result"] = res_data

            except Exception as e:
                scan_placeholder.empty()
                st.error(f"Error executing Gemini API call: {e}")

    # Render Diagnostic Result Card
    if "ai_result" in st.session_state and uploaded_file:
        res = st.session_state["ai_result"]
        with st.container(border=True):
            st.markdown('<div class="step-badge">STEP 02</div>', unsafe_allow_html=True)
            st.markdown("<h4 style='margin: 0px 0px 8px 0px; font-weight:700;'>Diagnostic Output</h4>", unsafe_allow_html=True)
            
            st.markdown(f'<div class="moxie-badge">{res.get("classification", "HAIR DIAGNOSIS")}</div>', unsafe_allow_html=True)
            st.write(f"*{res.get('summary', '')}*")
            
            m_col1, m_col2 = st.columns(2)
            with m_col1:
                st.caption("MOISTURE NEED")
                st.write(f"**{res.get('porosity', 'Balanced')}**")
            with m_col2:
                st.caption("STYLING TYPE")
                st.write(f"**{res.get('hold_need', 'Flexible Hold')}**")

# -----------------------------------------------------------------------------
# RIGHT COLUMN: Recommended Routine & Product Catalog Card
# -----------------------------------------------------------------------------
with col_right:
    with st.container(border=True):
        st.markdown("<span style='color: #D84261; font-weight: 800; font-size: 0.72rem; letter-spacing: 1px;'>RECOMMENDED ROUTINE</span>", unsafe_allow_html=True)
        
        if "ai_result" in st.session_state and uploaded_file:
            res = st.session_state["ai_result"]
            archetype = res.get("archetype", "WAVY_VIBE_SETTER")

            if archetype == "WAVY_VIBE_SETTER":
                target_handle = "wavy-vibe-setter-duo"
                title = "The Wavy Vibe Setter Routine"
                benefits = [
                    "Weightless leave-in + flexible styling serum gel",
                    "Hydrates S-waves without weighing down fine hair",
                    "Locks out humidity and prevents monsoon frizz"
                ]
            else:
                target_handle = "curly-vibe-setter-duo"
                title = "The Curly Vibe Setter Routine"
                benefits = [
                    "Rich curl cream + flexible styling serum gel",
                    "Deeply nourishes spirals with cocoa and shea butter",
                    "Defines ringlets for all-day bouncy hold"
                ]

            # Find matching bundle in catalog JSON
            matched_bundle = next((p for p in CATALOG if p.get("handle") == target_handle), None)

            st.markdown(f"<h3 style='margin:4px 0px 2px 0px; font-weight:800;'>{title}</h3>", unsafe_allow_html=True)
            st.markdown("<span style='color:#FFB800; font-size:0.85rem;'>★★★★★</span> <span style='color:#777; font-size:0.8rem;'>(142 reviews)</span>", unsafe_allow_html=True)

            # Pre-loaded Local Asset Image
            if matched_bundle and matched_bundle.get("images"):
                img_obj = load_pil_image(matched_bundle["images"][0])
                if img_obj:
                    st.image(img_obj, use_container_width=True)

            st.write("")
            for b in benefits:
                st.markdown(f'<div class="benefit-item"><span class="benefit-check">✓</span>{b}</div>', unsafe_allow_html=True)

            st.divider()

            # Price & 1-Click Cart Permalinks
            if matched_bundle and matched_bundle.get("variants"):
                variant_id = matched_bundle["variants"][0]["id"]
                price = matched_bundle["variants"][0]["price"]
                cart_url = f"https://moxiebeauty.in/cart/{variant_id}:1?discount=MOXIEAI10"
            else:
                price = "1149.00"
                cart_url = f"https://moxiebeauty.in/products/{target_handle}"

            p_col1, p_col2 = st.columns([1, 1.4])
            with p_col1:
                st.markdown(f"<span style='font-size: 1.3rem; font-weight: 800;'>₹{price}</span>", unsafe_allow_html=True)
                st.caption("10% OFF Applied")

            with p_col2:
                st.markdown(f'''
                    <a href="{cart_url}" target="_blank" style="text-decoration: none;">
                        <button style="
                            background-color: #D84261;
                            color: white;
                            border-radius: 100px;
                            padding: 10px 16px;
                            font-weight: 700;
                            border: none;
                            width: 100%;
                            cursor: pointer;
                            font-size: 0.85rem;">
                            ADD TO CART — 10% OFF
                        </button>
                    </a>
                ''', unsafe_allow_html=True)

        else:
            # Clean Placeholder UI before analysis
            st.markdown("<h3 style='margin:4px 0px 8px 0px; font-weight:800;'>Your Custom Routine</h3>", unsafe_allow_html=True)
            st.caption("Upload a photo on the left to unlock your personalized formula match.")
            
            if CATALOG:
                sample_item = CATALOG[0]
                st.write("")
                st.markdown(f"**Featured:** {sample_item.get('title')}")
                if sample_item.get("images"):
                    img_obj = load_pil_image(sample_item["images"][0])
                    if img_obj:
                        st.image(img_obj, use_container_width=True)