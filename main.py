import os
import hmac
import hashlib
import requests
from flask import Flask, jsonify
from google import genai

app = Flask(__name__)

# ==================== CONFIGURATION ====================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
COINDCX_API_KEY = os.getenv("COINDCX_API_KEY")
COINDCX_SECRET_KEY = os.getenv("COINDCX_SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_ID = os.getenv("TELEGRAM_ID")

# True = पेपर ट्रेडिंग, False = रियल मनी लाइव ट्रेडिंग
PAPER_TRADING = os.getenv("PAPER_TRADING", "True").lower() == "true"

# Gemini क्लाइंट इनिशियलाइज करें
client = genai.Client(api_key=GEMINI_API_KEY)

# सिस्टम प्रॉम्प्ट जिसमें स्पष्ट निर्देश है कि फुल डे का स्टॉप लॉस 20% है
GEMINI_SYSTEM_INSTRUCTION = (
    "आप एक क्रिप्टो ट्रेडिंग असिस्टेंट हैं। आपके लिए सख्त नियम है: "
    "फुल डे का स्टॉप लॉस 20% है। किसी भी ट्रेड का सुझाव देते समय या विश्लेषण करते समय "
    "इस 20% डेली स्टॉप-लॉस सीमा का कड़ाई से पालन करें। यदि नुकसान 20% तक पहुँच जाए, तो ट्रेडिंग बंद कर दें।"
)

# ==================== HELPER FUNCTIONS ====================

def send_telegram_message(message: str):
    """टेलीग्राम पर मैसेज भेजने के लिए फंक्शन"""
    if not TELEGRAM_TOKEN or not TELEGRAM_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_ID, "text": message})
    except Exception as e:
        print(f"Telegram error: {e}")

def get_coindcx_signature(secret_string: str) -> str:
    """CoinDCX API के लिए HMAC SHA256 सिग्नेचर जनरेट करना"""
    secret_bytes = bytes(COINDCX_SECRET_KEY, encoding='utf-8')
    signature = hmac.new(secret_bytes, secret_string.encode('utf-8'), hashlib.sha256).hexdigest()
    return signature

# ==================== WEB SERVER ROUTES ====================

@app.route("/")
def home():
    mode_name = "🟢 PAPER TRADING (वर्चुअल)" if PAPER_TRADING else "🔴 LIVE TRADING (रियल मनी)"
    return jsonify({
        "status": "Web Server is Running",
        "trading_mode": mode_name,
        "full_day_stop_loss": "20%"
    })

@app.route("/check-and-trade", methods=["GET", "POST"])
def check_and_trade():
    """यह एंडपॉइंट मार्केट चेक करेगा और Gemini की सलाह लेगा"""
    mode_str = "PAPER TRADING" if PAPER_TRADING else "LIVE TRADING (REAL MONEY)"
    
    try:
        # Gemini से विश्लेषण प्राप्त करना
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=f"{GEMINI_SYSTEM_INSTRUCTION}\n\nCurrent Mode: {mode_str}. कॉइन डीसीएक्स फ्यूचर्स INR वॉलेट के लिए मार्केट डेटा का विश्लेषण करें। फुल डे का स्टॉप लॉस 20% का ध्यान रखते हुए क्या ट्रेड लेना सुरक्षित है?"
        )
        ai_advice = response.text
    except Exception as e:
        ai_advice = f"Gemini Error: {e}"

    # मोड के आधार पर एक्शन
    if PAPER_TRADING:
        log_msg = f"🧪 [Paper Trading Check]\nGemini: {ai_advice}"
    else:
        log_msg = f"⚠️ [LIVE REAL MONEY TRADING CHECK]\nGemini: {ai_advice}"
        # यहाँ CoinDCX फ्यूचर्स लाइव आर्डर प्लेसमेंट का कोड जोड़ा जाएगा

    send_telegram_message(log_msg)
    
    return jsonify({
        "status": "Success",
        "mode": mode_str,
        "gemini_advice": ai_advice
    })

if __name__ == "__main__":
    # Render द्वारा दिए गए PORT पर सर्वर शुरू करें
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
