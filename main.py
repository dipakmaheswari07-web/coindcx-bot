import os
import time
import hmac
import hashlib
import json
import threading
import datetime
import requests
import google.generativeai as genai
from flask import Flask

app = Flask(__name__)

# --- क्रेडेंशियल्स लोड करें ---
COINDCX_API_KEY = os.getenv("COINDCX_API_KEY")
COINDCX_API_SECRET = os.getenv("COINDCX_API_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# पेपर ट्रेडिंग मोड ('True' = पेपर ट्रेडिंग, 'False' = रियल मनी ट्रेडिंग)
PAPER_TRADING = os.getenv("PAPER_TRADING", "True").lower() == "true"

# --- Gemini AI सेटअप (टॉप टियर प्रो मॉडल) ---
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-pro')

BASE_URL = "https://api.coindcx.com"

# --- ग्लोबल वेरिएबल्स (डेली स्टॉप-लॉस ट्रैक करने के लिए) ---
initial_daily_balance = 0.0
last_reset_date = None
daily_stop_loss_hit = False

def send_telegram_message(message):
    """टेलीग्राम पर अलर्ट भेजने के लिए फंक्शन"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram tokens not provided. Skipping alert.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")

def generate_signature(secret, body):
    """CoinDCX API के लिए HMAC SHA256 सिग्नेचर"""
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()

def get_market_data():
    """CoinDCX से लाइव मार्केट टिकर डेटा प्राप्त करें"""
    url = "https://public.coindcx.com/market_data/ticker"
    response = requests.get(url, timeout=10)
    return response.json()

def get_wallet_balance():
    """फ्यूचर्स वॉलेट बैलेंस फेच करें"""
    if PAPER_TRADING:
        return 1000.0  # पेपर ट्रेडिंग के लिए डिफ़ॉल्ट $1000
    
    path = "/exchange/v1/derivatives/futures/balances"
    url = BASE_URL + path
    body = {"timestamp": int(time.time() * 1000)}
    json_body = json.dumps(body)
    signature = generate_signature(COINDCX_API_SECRET, json_body)
    headers = {
        "Content-Type": "application/json",
        "X-AUTH-APIKEY": COINDCX_API_KEY,
        "X-AUTH-SIGNATURE": signature
    }
    try:
        response = requests.post(url, data=json_body, headers=headers, timeout=10)
        result = response.json()
        return float(result.get("balance", 1000.0))
    except Exception as e:
        print(f"Error fetching balance: {e}")
        return 1000.0

def check_daily_stop_loss(current_balance):
    """20% डेली स्टॉप-लॉस चेक करने का लॉजिक"""
    global initial_daily_balance, last_reset_date, daily_stop_loss_hit
    today = datetime.date.today()
    
    if last_reset_date != today:
        initial_daily_balance = current_balance
        last_reset_date = today
        daily_stop_loss_hit = False
        return False

    if daily_stop_loss_hit:
        return True

    if initial_daily_balance > 0:
        loss_percentage = (current_balance - initial_daily_balance) / initial_daily_balance
        if loss_percentage <= -0.20: # 20% या उससे ज्यादा नुकसान
            daily_stop_loss_hit = True
            return True
            
    return False

def place_futures_order(pair, side, quantity, leverage):
    """फ्यूचर्स ऑर्डर प्लेस करें (पेपर या रियल)"""
    if PAPER_TRADING:
        msg = f"📝 *[PAPER TRADING]* Order Simulated:\nPair: {pair}\nSide: {side.upper()}\nQuantity: {quantity}\nLeverage: {leverage}x"
        print(msg)
        send_telegram_message(msg)
        return {"status": "simulated"}

    path = "/exchange/v1/derivatives/futures/orders/create"
    url = BASE_URL + path
    body = {
        "side": side,
        "pair": pair,
        "total_quantity": quantity,
        "order_type": "market",
        "leverage": leverage,
        "timestamp": int(time.time() * 1000)
    }
    json_body = json.dumps(body)
    signature = generate_signature(COINDCX_API_SECRET, json_body)
    headers = {
        "Content-Type": "application/json",
        "X-AUTH-APIKEY": COINDCX_API_KEY,
        "X-AUTH-SIGNATURE": signature
    }
    response = requests.post(url, data=json_body, headers=headers, timeout=10)
    result = response.json()
    
    send_telegram_message(f"🚨 *[REAL TRADING]* Order Executed!\nResponse: `{result}`")
    return result

def trading_loop():
    """बैकग्राउंड में चलने वाला मेन ट्रेडिंग लूप (हर 5 मिनट में)"""
    mode_text = "PAPER TRADING (Simulated)" if PAPER_TRADING else "REAL MONEY TRADING 🔴"
    start_msg = f"🤖 Gemini Smart Crypto Bot Started!\nMode: *{mode_text}*\nRules: 20% Daily Stop-Loss Active | Dynamic Leverage Enabled"
    print(start_msg)
    send_telegram_message(start_msg)

    while True:
        try:
            current_balance = get_wallet_balance()

            if check_daily_stop_loss(current_balance):
                stop_msg = "🛑 *Daily Stop-Loss Hit (20% Loss Reached)!* Trading paused for the rest of the day."
                print(stop_msg)
                send_telegram_message(stop_msg)
                time.sleep(1800)
                continue

            tickers = get_market_data()
            btc_data = next((item for item in tickers if item['market'] == 'B-BTC_USDT'), None)
            
            if not btc_data:
                print("BTC market data not found. Retrying...")
                time.sleep(60)
                continue

            # Gemini AI प्रॉम्प्ट (कम लेवरेज और जरूरत पर मैक्सिमम लेवरेज का नियम)
            prompt = (
                f"Current BTC market data: {btc_data}. "
                "You are an expert crypto futures trader. "
                "STRICT RULES FOR LEVERAGE: "
                "1. Use as low leverage as possible normally (like 1x or 2x) to minimize risk. "
                "2. Only if there is an extremely strong market trend, you are allowed to increase leverage up to maximum limit (e.g. 10x). "
                "Analyze the market and output your response strictly in this exact format: "
                "DECISION: [BUY/SELL/HOLD], LEVERAGE: [integer number]"
            )
            
            response = model.generate_content(prompt)
            ai_output = response.text.strip().upper()
            print(f"Gemini Output: {ai_output}")
            
            if "BUY" in ai_output or "SELL" in ai_output:
                side = 'buy' if "BUY" in ai_output else 'sell'
                
                leverage = 2
                if "LEVERAGE:" in ai_output:
                    try:
                        lev_part = ai_output.split("LEVERAGE:")[1].strip().split()[0]
                        leverage = int(''.join(filter(str.isdigit, lev_part)))
                        if leverage < 1: leverage = 1
                        if leverage > 10: leverage = 10 
                    except:
                        leverage = 2

                place_futures_order('B-BTC_USDT', side, 0.001, leverage)
            else:
                print("Gemini Decision: HOLD. No trade executed.")
                
        except Exception as e:
            err_msg = f"❌ Error in trading loop: {e}"
            print(err_msg)
            send_telegram_message(err_msg)
            
        time.sleep(300)

# --- फ्लस्क वेब सर्वर रूट ---
@app.route('/')
def home():
    mode = "Paper Trading (Safe)" if PAPER_TRADING else "Real Money Trading 🔴"
    return f"🤖 Gemini CoinDCX Bot is running!<br>Main File: <b>main.py</b><br>Mode: <b>{mode}</b><br>Daily Stop-Loss: <b>Active (20%)</b>"

if __name__ == "__main__":
    # बैकग्राउंड थ्रेड में ट्रेडिंग लूप शुरू करें
    t = threading.Thread(target=trading_loop)
    t.daemon = True
    t.start()

    # वेब सर्वर चलाएं
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
