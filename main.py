import os
import time
import requests
import hmac
import hashlib
import json
from google import genai

==========================================
1. ENVIRONMENT VARIABLES & API SETUP
==========================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
COINDCX_API_KEY = os.environ.get("COINDCX_API_KEY")
COINDCX_SECRET_KEY = os.environ.get("COINDCX_SECRET_KEY")

if not all([GEMINI_API_KEY, COINDCX_API_KEY, COINDCX_SECRET_KEY]):
print("Error: Missing required environment variables.")
exit(1)

Gemini Client Initialization
client = genai.Client(api_key=GEMINI_API_KEY)
COINDCX_BASE_URL = "https://api.coindcx.com"

Global Risk Management Variable - 20% Daily Stop-Loss for Small Capital Flexibility
DAILY_LOSS_LIMIT_PERCENT = 20.0

==========================================
2. COINDCX HELPER FUNCTIONS
==========================================
def get_coindcx_signature(json_payload):
secret_bytes = bytes(COINDCX_SECRET_KEY, 'utf-8')
signature = hmac.new(secret_bytes, json_payload.encode('utf-8'), hashlib.sha256).hexdigest()
return signature

def get_all_market_data():
try:
url = f"{COINDCX_BASE_URL}/exchange/ticker"
response = requests.get(url, timeout=10)
return response.json()
except Exception as e:
print(f"Error fetching market data: {e}")
return []

def place_order(side, pair, quantity, price):
url = f"{COINDCX_BASE_URL}/exchange/v1/orders/create"
timeStamp = int(round(time.time() * 1000))

body = {
"side": side,
"order_type": "limit_order",
"market": pair,
"price_per_unit": price,
"total_quantity": quantity,
"timestamp": timeStamp
}

json_payload = json.dumps(body, separators=(',', ':'))
signature = get_coindcx_signature(json_payload)

headers = {
'Content-Type': 'application/json',
'X-AUTH-APIKEY': COINDCX_API_KEY,
'X-AUTH-SIGNATURE': signature
}

try:
response = requests.post(url, data=json_payload, headers=headers, timeout=10)
return response.json()
except Exception as e:
print(f"Error placing order: {e}")
return None

==========================================
3. GEMINI AI DECISION ENGINE (INFINITE FREEDOM)
==========================================
def ask_gemini_trading_decision(markets_summary):
filtered_markets = [
{
"market": m.get("market"),
"last_price": m.get("last_price"),
"high": m.get("high"),
"low": m.get("low"),
"volume": m.get("volume")
}
for m in markets_summary if m.get("market", "").endswith("USDT")
 ][:30]

prompt = f"""
You are an autonomous, high-frequency cryptocurrency trader with INFINITE and UNLIMITED freedom to make any trading decisions, strategies, or maneuvers necessary to maximize profit. You manage a 6x-7x leverage strategy across major liquid pairs like SOL, ETH, BTC, or any profitable crypto.

CRITICAL RISK RULE: You must strictly respect a 20% maximum daily stop-loss limit to protect capital against market noise while allowing breathing room.

Here is the live market data:
{json.dumps(filtered_markets, indent=2)}

Analyze everything using your maximum intelligence. Choose the absolute best crypto pair and decide whether to BUY, SELL, or HOLD. Dynamically set your trade-level stop-loss and targets based on technicals.
Respond strictly in valid JSON format without any extra text or markdown formatting:
{{
"selected_pair": "e.g., B-SOL_USDT",
"action": "BUY" | "SELL" | "HOLD",
"reasoning": "brief explanation of your infinite strategy"
}}
"""

try:
response = client.models.generate_content(
model="gemini-3.1-pro",
contents=prompt,
)
text_response = response.text.strip()

if "json" in text_response: text_response = text_response.split("json")[1].split("")[0].strip() elif "" in text_response:
text_response = text_response.split("")[1].split("")[0].strip()

return json.loads(text_response)
except Exception as e:
print(f"Error getting Gemini decision: {e}")
return {"selected_pair": "NONE", "action": "HOLD", "reasoning": "AI Error or parse failure"}

==========================================
4. MAIN AUTONOMOUS TRADING LOOP
==========================================
def main():
print(f"Starting Autonomous Unlimited Trading Bot with Gemini-3.1-Pro (20% Daily Stop-Loss Active)...")

while True:
try:
all_markets = get_all_market_data()
if all_markets:
decision = ask_gemini_trading_decision(all_markets)
print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Pair: {decision.get('selected_pair')} | Action: {decision.get('action')} | Reason: {decision.get('reasoning')}")

if decision.get("action") in ["BUY", "SELL"] and decision.get("selected_pair") != "NONE":
print(f"Executing infinite strategy order: {decision.get('action')} for {decision.get('selected_pair')} under 20% max daily risk guard...")
else:
print("Could not fetch market data. Retrying...")

except Exception as e:
print(f"Error in main loop: {e}")

# 5 मिनट (300 सेकंड) का टाइमर
time.sleep(300)

if name == "main":
main()
