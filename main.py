import os
import time
import hmac
import hashlib
import json
import threading
import requests
import google.generativeai as genai
from flask import Flask

app = Flask(__name__)

# एनवायरनमेंट वेरिएबल्स से सभी क्रेडेंशियल्स लोड करें
COINDCX_API_KEY = os.getenv("COINDCX_API_KEY")
COINDCX_API_SECRET = os.getenv("COINDCX_API_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# टेलीग्राम क्रेडेंशियल्स
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# पेपर ट्रेडिंग मोड ('True' यानी पेपर ट्रेडिंग, 'False' यानी रियल ट्रेडिंग)
PAPER_TRADING = os.getenv("PAPER_TRADING", "True").lower() == "true"

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-pro')

BASE_URL = "https://api.coindcx.com"

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
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")

def generate_signature(secret, body):
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()

def get_market_data():
    url = "https://public.coindcx.com/market_data/ticker"
    response = requests.get(url)
    return response.json()

def place_futures_order(pair, side, quantity, leverage):
    if PAPER_TRADING:
        msg = f"📝 *[PAPER TRADING]* Order Simulated:\nPair: {pair}\nSide: {side}\nQuantity: {quantity}\nLeverage: {leverage}x"
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
    response = requests.post(url, data=json_body, headers=headers)
    result = response.json()
    
    send_telegram_message(f"🚨 *[REAL TRADING]* Order Executed!\nResponse: `{result}`")
    return result

def trading_loop():
    mode_text = "PAPER TRADING (Simulated)" if PAPER_TRADING else "REAL MONEY TRADING"
    start_msg = f"🤖 Gemini CoinDCX Web Bot Started!\nMode: *{mode_text}*"
    print(start_msg)
    send_telegram_message(start_msg)

    while True:
        try:
            tickers = get_market_data()
            btc_data = next((item for item in tickers if item['market'] == 'B-BTC_USDT'), None)
            
            prompt = f"Current market data for BTC: {btc_data}. Analyze market trends and give a short trading decision: BUY, SELL, or HOLD for futures."
            response = model.generate_content(prompt)
            decision = response.text.strip().upper()
            
            print(f"Gemini Decision: {decision}")
            
            if "BUY" in decision:
                place_futures_order('B-BTC_USDT', 'buy', 0.001, 2)
            elif "SELL" in decision:
                place_futures_order('B-BTC_USDT', 'sell', 0.001, 2)
            else:
                print("Holding position. No trade executed.")
                
        except Exception as e:
            err_msg = f"❌ Error in trading loop: {e}"
            print(err_msg)
            send_telegram_message(err_msg)
            
        time.sleep(300) # हर 5 मिनट में लूप चलेगा

# फ्लस्क रूट (वेब सर्वर चेक करने के लिए)
@app.route('/')
def home():
    mode = "Paper Trading" if PAPER_TRADING else "Real Trading"
    return f"Gemini CoinDCX Bot is running! Mode: {mode}"

if __name__ == "__main__":
    # ट्रेडिंग लूप को बैकग्राउंड थ्रेड में शुरू करें ताकि वेब सर्वर भी साथ में चल सके
    t = threading.Thread(target=trading_loop)
    t.daemon = True
    t.start()

    # रेंडर द्वारा दिए गए पोर्ट पर फ्लस्क सर्वर चलाएं
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
