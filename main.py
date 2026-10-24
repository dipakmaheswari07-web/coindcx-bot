import os
import time
import json
import re
import requests
import ccxt
from google import genai
from datetime import datetime, timezone
from threading import Thread
from flask import Flask

# ==========================================
# 0. Render पोर्ट बाइंडिंग के लिए वेब सर्वर
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "🚀 Crypto AI Trading Bot is Running Live!"

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# ==========================================
# 1. पर्यावरण वेरिएबल्स (Environment Variables)
# ==========================================
COINDCX_API_KEY = os.getenv("COINDCX_API_KEY")
COINDCX_SECRET_KEY = os.getenv("COINDCX_SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

PAPER_TRADING = os.getenv("PAPER_TRADING", "False").lower() == "true"
DAILY_MAX_LOSS_PERCENT = 0.20  # 20% दैनिक स्टॉप-लॉस

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable is missing!")

if not COINDCX_API_KEY or not COINDCX_SECRET_KEY:
    raise ValueError("CoinDCX API Keys are missing!")

# ==========================================
# 2. क्लाइंट और एक्सचेंज सेटअप (CCXT & Gemini)
# ==========================================
client = genai.Client(api_key=GEMINI_API_KEY)

exchange = ccxt['coindcx']({
    'apiKey': COINDCX_API_KEY,
    'secret': COINDCX_SECRET_KEY,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',
    }
})

day_start_balance = None
last_reset_day = None
stop_loss_hit_today = False

# ==========================================
# 3. टेलीग्राम नोटिफिकेशन सिस्टम
# ==========================================
def send_telegram_alert(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"Telegram Alert (Console Only): {message}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram Dispatch Error: {e}")

def log_and_alert(message):
    print(message)
    send_telegram_alert(message)

# ==========================================
# 4. जेमिनी एआई का सिस्टम इंस्ट्रक्शन
# ==========================================
GEMINI_SYSTEM_INSTRUCTION = """
नियम: 
1. फुल डे का स्टॉप-लॉस 20% है।
2. लेवरेज का चयन: हमेशा कम से कम (लो से लो, जैसे 1x) लेवरेज रखने की कोशिश करें, लेकिन जरूरत पड़ने पर अधिकतम (Maximum) लेवरेज तक ले सकते हैं।
3. आपके पास पोर्टफोलियो का बैलेंस, 5-मिनट की कैंडलें और वर्तमान ओपन पोजीशन (Open Position) का डेटा होगा। उसके आधार पर ही सही निर्णय लें। अगर कोई पोजीशन पहले से लाइव है और टारगेट की तरफ सही दिशा में बढ़ रही है, तो अनावश्यक बंद न करें, बल्कि "HOLD" का निर्णय दें जब तक कि दिशा बदलने की आवश्यकता न हो।

काम: लाइव मार्केट डेटा और ओपन पोजीशन का विश्लेषण करके अपना निर्णय केवल और केवल एक वैध JSON फॉर्मेट में भेजें।

JSON Format:
{
  "action": "BUY" या "SELL" या "HOLD",
  "symbol": "BTC/USDT",
  "quantity": 0.001,
  "leverage": 1,
  "stop_loss": 0.0,
  "take_profit": 0.0,
  "reason": "संक्षिप्त कारण"
}
"""

# ==========================================
# 5. 20% डेली स्टॉप-लॉस और बैलेंस चेकर (USDT)
# ==========================================
def check_daily_stop_loss():
    global day_start_balance, last_reset_day, stop_loss_hit_today
    current_day = datetime.now(timezone.utc).date()

    if last_reset_day != current_day:
        day_start_balance = None
        last_reset_day = current_day
        stop_loss_hit_today = False

    if stop_loss_hit_today:
        return True, 0.0

    try:
        balance_info = exchange.fetch_balance()
        current_balance = float(balance_info.get('total', {}).get('USDT', 0.0))
        
        if current_balance <= 0:
            current_balance = float(balance_info.get('free', {}).get('USDT', 10.0))

        if day_start_balance is None:
            day_start_balance = current_balance
            log_and_alert(f"🌅 **New Trading Day Started**\nStarting Balance: {day_start_balance:.2f} USDT")

        loss_amount = day_start_balance - current_balance
        max_allowed_loss = day_start_balance * DAILY_MAX_LOSS_PERCENT

        if loss_amount >= max_allowed_loss:
            stop_loss_hit_today = True
            alert_msg = f"🛑 **CRITICAL: 20% Daily Stop-Loss Hit!**\nDay Start: {day_start_balance:.2f} USDT\nCurrent: {current_balance:.2f} USDT\nHalting trading for the rest of the day."
            log_and_alert(alert_msg)
            return True, current_balance

        return False, current_balance

    except Exception as e:
        err_msg = f"⚠️ **Balance Check Error:** {e}"
        log_and_alert(err_msg)
        return False, 0.0

# ==========================================
# 6. मार्केट डेटा और ओपन पोजीशन फेच करना
# ==========================================
def fetch_market_and_position_data(symbol='BTC/USDT'):
    try:
        ticker = exchange.fetch_ticker(symbol)
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='5m', limit=36)
        
        open_positions = []
        try:
            positions = exchange.fetch_positions([symbol])
            if positions:
                for p in positions:
                    if float(p.get('contracts', 0)) > 0:
                        open_positions.append(p)
        except Exception as pos_err:
            print(f"Position fetch warning: {pos_err}")

        return {
            "ticker": ticker, 
            "ohlcv": ohlcv,
            "open_positions": open_positions
        }
    except Exception as e:
        err_msg = f"⚠️ **Market Data Fetch Error:** {e}"
        log_and_alert(err_msg)
        return None

# ==========================================
# 7. जेमिनी एआई से डिसीजन प्राप्त करना
# ==========================================
def get_ai_decision(market_data, current_balance):
    prompt_payload = {
        "current_balance_usdt": current_balance,
        "market_data": market_data
    }

    prompt = f"""
    {GEMINI_SYSTEM_INSTRUCTION}

    वर्तमान लाइव बाज़ार, ओपन पोजीशन और पोर्टफोलियो डेटा:
    {json.dumps(prompt_payload, default=str)}
    """

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            text = response.text.strip()
            
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            else:
                raise ValueError("No valid JSON found in AI response.")
        except Exception as e:
            print(f"Attempt {attempt + 1} - Gemini Parsing Error: {e}")
            if attempt == 2:
                log_and_alert(f"⚠️ **Gemini API/Parsing Error after 3 attempts:** {e}")
                return None
            time.sleep(2)
    return None

# ==========================================
# 8. ट्रेड निष्पादन
# ==========================================
def execute_trade(decision):
    if not decision or not isinstance(decision, dict):
        log_and_alert("⚠️ **Invalid AI decision structure received.**")
        return

    action = decision.get("action", "HOLD").upper()
    symbol = decision.get("symbol", "BTC/USDT")
    raw_quantity = float(decision.get("quantity", 0.0))
    ai_leverage = int(decision.get("leverage", 1))
    stop_loss = float(decision.get("stop_loss", 0.0))
    take_profit = float(decision.get("take_profit", 0.0))
    reason = decision.get("reason", "No reason provided.")

    if action not in ["BUY", "SELL"]:
        log_and_alert(f"ℹ️ **AI Decision Status: {action}**\n- **Symbol:** {symbol}\n- **Reason:** {reason}")
        return

    try:
        quantity = float(exchange.amount_to_precision(symbol, raw_quantity))
        formatted_sl = float(exchange.price_to_precision(symbol, stop_loss)) if stop_loss > 0 else 0.0
        formatted_tp = float(exchange.price_to_precision(symbol, take_profit)) if take_profit > 0 else 0.0
    except Exception as e:
        log_and_alert(f"⚠️ **Precision Formatting Error:** {e}")
        return

    msg = f"""🤖 **AI Trading Decision Executed**
- **Action:** {action}
- **Symbol:** {symbol}
- **Quantity:** {quantity}
- **Leverage:** {ai_leverage}x
- **Stop Loss:** {formatted_sl} USDT
- **Target:** {formatted_tp} USDT
- **Reason:** {reason}
- **Mode:** {'PAPER TRADING' if PAPER_TRADING else '⚡ REAL LIVE MONEY'}"""

    log_and_alert(msg)

    if PAPER_TRADING:
        log_and_alert(f"🧪 [PAPER TRADING] Simulated {action} trade logged for {symbol}.")
        return

    try:
        try:
            exchange.set_leverage(ai_leverage, symbol)
        except Exception as lev_err:
            log_and_alert(f"⚠️ Leverage Set Warning: {lev_err}")

        if action == "BUY":
            order = exchange.create_market_buy_order(symbol, quantity)
            log_and_alert(f"✅ **Live BUY Order Placed Successfully!**\n`{json.dumps(order, default=str)}`")
        elif action == "SELL":
            order = exchange.create_market_sell_order(symbol, quantity)
            log_and_alert(f"✅ **Live SELL Order Placed Successfully!**\n`{json.dumps(order, default=str)}`")
    except Exception as e:
        log_and_alert(f"❌ **Live Order Execution Error:** {str(e)}")

# ==========================================
# 9. मुख्य लूप (5-मिनट सिंक्रोनाइजेशन)
# ==========================================
def wait_for_next_5m_candle():
    now = datetime.now(timezone.utc)
    seconds_into_hour = now.minute * 60 + now.second
    next_boundary = ((seconds_into_hour // 300) + 1) * 300
    sleep_seconds = next_boundary - seconds_into_hour + 3
    time.sleep(sleep_seconds)

def main():
    log_and_alert("🚀 **Fully Synchronized & Tracked Crypto Futures Trading Bot Started!**")

    symbol = 'BTC/USDT'

    try:
        exchange.load_markets()
    except Exception as e:
        log_and_alert(f"⚠️ Market load warning: {e}")

    while True:
        try:
            stop_hit, current_balance = check_daily_stop_loss()
            if stop_hit:
                log_and_alert("🛑 **Daily 20% Stop Loss hit.** Trading halted. Checking again in 30 minutes...")
                time.sleep(1800)
                continue

            market_data = fetch_market_and_position_data(symbol)
            if market_data:
                decision = get_ai_decision(market_data, current_balance)
                if decision:
                    execute_trade(decision)

        except Exception as e:
            log_and_alert(f"⚠️ **Main Loop Critical Error:** {e}")

        wait_for_next_5m_candle()

if __name__ == "__main__":
    bot_thread = Thread(target=main)
    bot_thread.daemon = True
    bot_thread.start()

    run_web_server()
