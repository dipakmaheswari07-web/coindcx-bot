import os
import time
import requests
from google import genai
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

# पर्यावरण चर (Environment Variables)
COINDCX_API_KEY = os.environ.get("COINDCX_API_KEY")
COINDCX_API_SECRET = os.environ.get("COINDCX_API_SECRET")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
PAPER_TRADING = os.environ.get("PAPER_TRADING", "True").lower() == "true"

# नए google.genai पैकेज का उपयोग करके क्लाइंट सेटअप
client = None
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)

# रेंडर हेल्थ चेक के लिए इन-बिल्ट एचटीटीपी सर्वर
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"Gemini Crypto Futures Trading Bot is Live and Running!")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server_address = ('', port)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    print(f"वेब सर्वर पोर्ट {port} पर चल रहा है")
    httpd.serve_forever()

def send_telegram(msg):
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
        except Exception as e:
            print(f"टेलीग्राम त्रुटि: {e}")

def fetch_coindcx_market_data():
    """कॉइनडीसीएक्स पब्लिक एपीआई से लाइव मार्केट डेटा फेच करना"""
    try:
        url = "https://public.coindcx.com/market_data/ticker"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            filtered_data = [item for item in data if item.get('market', '').endswith('USDT')][:30]
            return str(filtered_data)
    except Exception as e:
        print(f"मार्केट डेटा फेच करने में त्रुटि: {e}")
    return "Market data unavailable"

def analyze_and_trade():
    system_prompt = """
    You are an autonomous Crypto Futures Trader. 
    Strict Rule: Your maximum daily stop-loss is strictly 20%. Capital protection is mandatory.
    Other than this single rule, you have full authority and intelligence to analyze the provided live market data, select coins, choose optimal leverage, manage risk, and execute trades for maximum profit.
    """
    
    print("कॉइनडीसीएक्स से लाइव डेटा फेच किया जा रहा है और एआई विश्लेषण कर रहा है...")
    market_data = fetch_coindcx_market_data()
    
    prompt_input = f"{system_prompt}\n\nLive Market Data:\n{market_data}\n\nAnalyze the data and provide your optimal trading decisions."
    
    try:
        if client:
            response = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=prompt_input
            )
            ai_decision = response.text
            print(f"AI Decision: {ai_decision}")
            
            if PAPER_TRADING:
                send_telegram(f"🤖 **पेपर ट्रेडिंग लाइव अपडेट**\n\n{ai_decision}")
            else:
                send_telegram(f"🚀 **लाइव ट्रेड सिग्नल**\n\n{ai_decision}")
        else:
            print("Gemini API Key missing.")
            
    except Exception as e:
        print(f"एआई विश्लेषण त्रुटि: {e}")

if __name__ == "__main__":
    web_thread = threading.Thread(target=run_web_server)
    web_thread.daemon = True
    web_thread.start()

    while True:
        try:
            analyze_and_trade()
        except Exception as e:
            print(f"एक्जीक्यूशन त्रुटि: {e}")
        time.sleep(300)
