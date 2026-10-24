import os
import time
import hmac
import hashlib
import json
import requests
import datetime
import threading
from flask import Flask
import google.generativeai as genai
from telegram import Bot

# ==========================================
# 1. Flask Web Server Setup (Render के लिए जरूरी)
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Gemini AI Autonomous Trading Bot is Live and Running!"

@app.route('/health')
def health_check():
    return "OK", 200

# ==========================================
# 2. Environment Variables & Setup
# ==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
COINDCX_API_KEY = os.environ.get("COINDCX_API_KEY")
COINDCX_SECRET_KEY = os.environ.get("COINDCX_SECRET_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Gemini API सेटअप
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("gemini-1.5-flash")

# Telegram Bot Setup
tg_bot = Bot(token=TELEGRAM_TOKEN) if TELEGRAM_TOKEN else None

def send_telegram(message):
    """Telegram पर संदेश भेजने का फ़ंक्शन"""
    if tg_bot and TELEGRAM_CHAT_ID:
        try:
            tg_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode="Markdown")
        except Exception as e:
            print(f"Telegram भेजते समय त्रुटि: {e}")

# ==========================================
# 3. CoinDCX Helper Functions
# ==========================================
BASE_URL = "https://api.coindcx.com"

def get_coindcx_signature(payload_bytes):
    return hmac.new(
        COINDCX_SECRET_KEY.encode('utf-8'),
        payload_bytes,
        hashlib.sha256
    ).hexdigest()

def get_account_balance():
    """CoinDCX Wallet Balance निकालता है"""
    url = f"{BASE_URL}/exchange/v1/users/balances"
    timeStamp = int(round(time.time() * 1000))
    body = {"timestamp": timeStamp}
    json_body = json.dumps(body, separators=(',', ':'))
    
    headers = {
        'Content-Type': 'application/json',
        'X-AUTH-APIKEY': COINDCX_API_KEY,
        'X-AUTH-SIGNATURE': get_coindcx_signature(json_body.encode('utf-8'))
    }
    
    try:
        response = requests.post(url, data=json_body, headers=headers)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Balance fetch error: {e}")
    return []

def get_market_candles(market="B-BTC_INR"):
    """हाल के कैंडलस्टिक डेटा प्राप्त करें"""
    url = f"https://public.coindcx.com/market_data/candles?pair={market}&interval=1m&limit=30"
    try:
        res = requests.get(url)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"Candles fetch error: {e}")
    return []

def execute_coindcx_order(side, market, price, quantity):
    """CoinDCX पर Order प्लेस करता है"""
    url = f"{BASE_URL}/exchange/v1/orders/create"
    timeStamp = int(round(time.time() * 1000))
    
    body = {
        "side": side,  # "buy" या "sell"
        "order_type": "market_order" if price == 0 else "limit_order",
        "market": market,
        "total_quantity": str(quantity),
        "timestamp": timeStamp
    }
    if price > 0:
        body["price_per_unit"] = str(price)
        
    json_body = json.dumps(body, separators=(',', ':'))
    headers = {
        'Content-Type': 'application/json',
        'X-AUTH-APIKEY': COINDCX_API_KEY,
        'X-AUTH-SIGNATURE': get_coindcx_signature(json_body.encode('utf-8'))
    }
    
    try:
        res = requests.post(url, data=json_body, headers=headers)
        return res.json()
    except Exception as e:
        print(f"Order error: {e}")
        return None

# ==========================================
# 4. Gemini AI Autonomous Decision Engine
# ==========================================
def get_gemini_autonomous_decision(market_data, balances):
    prompt = f"""
आप एक पूरी तरह से स्वतंत्र और कुशल क्रिप्टो एल्गो-ट्रेडर AI हैं। आपको मार्केट की हर स्थिति पर पूर्ण निर्णय (Full Autonomy) लेने की अनुमति है।
आपके पास निम्नलिखित डेटा उपलब्ध है:
1. मार्केट कैंडलस्टिक डेटा (OHLCV): {json.dumps(market_data)}
2. वर्तमान वॉलेट बैलेंस: {json.dumps(balances)}

आपको निम्नलिखित में से **केवल एक** JSON फॉर्मेट में सटीक निर्णय देना है:
- निर्णय प्रकार (`decision`): "BUY", "SELL", "HOLD", या "CLOSE_POSITION"
- कारण (`reason`): आपके फैसले के पीछे तकनीकी और रणनीतिक कारण।
- सुझाए गए मूल्य (`suggested_price`): यदि लिमिट ऑर्डर है तो कीमत, अन्यथा 0।
- मात्रा अनुपात (`quantity_ratio`): उपलब्ध बैलेंस का कितना हिस्सा उपयोग करना है (जैसे 0.1 यानी 10%)।

कृपया केवल इस JSON प्रारूप में उत्तर दें, बिना किसी अतिरिक्त टेक्स्ट या मार्कडाउन के:
{{
    "decision": "HOLD",
    "reason": "यहाँ कारण लिखें",
    "suggested_price": 0.0,
    "quantity_ratio": 0.1
}}
"""
    try:
        response = gemini_model.generate_content(prompt)
        cleaned_text = response.text.replace("```json", "").replace("```", "").strip()
        decision_data = json.loads(cleaned_text)
        return decision_data
    except Exception as e:
        print(f"Gemini AI decision error: {e}")
        return {"decision": "HOLD", "reason": f"AI Parsing Error: {e}", "suggested_price": 0.0, "quantity_ratio": 0.0}

# ==========================================
# 5. Background Trading Loop + 20% Stop-Loss
# ==========================================
def run_trading_bot():
    """यह फ़ंक्शन बैकग्राउंड में लगातार ट्रेड लूप चलाएगा"""
    time.sleep(10) # सर्वर पूरी तरह उठने का इंतज़ार
    send_telegram("🤖 **Web Server Mode:** Fully Autonomous Gemini AI Bot सक्रिय हो गया है!")
    
    current_day = datetime.datetime.now().day
    start_day_balance = None
    TARGET_MARKET = "B-BTC_INR"
    
    while True:
        try:
            now = datetime.datetime.now()
            
            balances = get_account_balance()
            inr_bal = next((float(b['balance']) for b in balances if b['currency'] == 'INR'), 0.0) if balances else 0.0
            
            if start_day_balance is None or now.day != current_day:
                current_day = now.day
                start_day_balance = inr_bal
                send_telegram(f"🌅 **नया दिन शुरू!** आज का शुरुआती बैलेंस: ₹{start_day_balance}")

            # 1. 20% डेली स्टॉप-लॉस चेक
            if start_day_balance > 0:
                loss_percentage = ((start_day_balance - inr_bal) / start_day_balance) * 100
                if loss_percentage >= 20.0:
                    msg = f"🛑 **DAILY STOP-LOSS HIT (20%)!**\nआज का नुकसान 20% तक पहुँच चुका है ({loss_percentage:.2f}%)। सुरक्षा के लिए बोट आज ट्रेडिंग बंद कर रहा है।"
                    send_telegram(msg)
                    time.sleep(3600 * 6)  # 6 घंटे विश्राम
                    continue

            # 2. मार्केट डेटा इकट्ठा करें
            candles = get_market_candles(TARGET_MARKET)
            if not candles:
                time.sleep(60)
                continue

            # 3. Gemini से स्वतंत्र निर्णय लें
            ai_res = get_gemini_autonomous_decision(candles, balances)
            decision = ai_res.get("decision")
            reason = ai_res.get("reason")
            price = ai_res.get("suggested_price", 0.0)
            ratio = ai_res.get("quantity_ratio", 0.1)

            print(f"AI Decision: {decision} | Reason: {reason}")

            # 4. निर्णय के आधार पर एक्शन लें
            if decision in ["BUY", "SELL"]:
                available_inr = inr_bal * ratio
                current_price = candles[-1][4] if candles else 5000000 
                quantity = round(available_inr / float(current_price), 6)
                
                if quantity > 0:
                    order_res = execute_coindcx_order(decision.lower(), TARGET_MARKET, price, quantity)
                    log_msg = f"⚡ **AI Trade Executed**\n*Action:* {decision}\n*Market:* {TARGET_MARKET}\n*Reason:* {reason}\n*Response:* `{order_res}`"
                    send_telegram(log_msg)
                else:
                    send_telegram(f"⚠️ AI ने {decision} चाहा, लेकिन पर्याप्त बैलेंस उपलब्ध नहीं है।")

            elif decision == "CLOSE_POSITION":
                send_telegram(f"🔄 **AI Action: CLOSE POSITION**\n*Reason:* {reason}\nसभी खुली पोजीशन को रीसेट किया जा रहा है।")

            elif decision == "HOLD":
                print(f"AI Holding... Reason: {reason}")

            time.sleep(180)

        except Exception as e:
            print(f"Main Loop Error: {e}")
            time.sleep(60)

# ==========================================
# 6. Server Entry Point
# ==========================================
if __name__ == "__main__":
    # ट्रेडिंग बोट को बैकग्राउंड थ्रेड में शुरू करें
    bot_thread = threading.Thread(target=run_trading_bot, daemon=True)
    bot_thread.start()

    # Render द्वारा दिए गए पोर्ट या डिफॉल्ट 10000 पर Flask वेब सर्वर चलाएं
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
