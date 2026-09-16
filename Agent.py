import os
import sqlite3
import base64
import requests
from flask import Flask, request, jsonify, render_template_string
from groq import Groq

# --- কনফিগারেশন ---
# ক্লাউডের এনভায়রনমেন্ট থেকে বা সরাসরি এখানে কি বসাতে পারো
client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))

PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN", "")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "autocraft_secure_token_123")

SYSTEM_PROMPT = """
তুমি AutoCraft Agency-এর একজন প্রফেশনাল বিজনেস অটোমেশন স্পেশালিস্ট।
তোমার প্রধান লক্ষ্য হলো কাস্টমারের সাথে একজন বিশ্বস্ত বন্ধুর মতো কথা বলা, তাদের ফেসবুক পেজের অটোমেশনের সুবিধা ও অল-ইন-ওয়ান বান্ডেল প্যাকেজ বোঝানো এবং ফ্রি ট্রায়াল বা বুকিং নেওয়া।

কথা বলার টোন ও ট্রাস্ট বিল্ডিং গাইডলাইন:
১. প্রথম মেসেজ: কোনো রোবোটিক বা ফর্মাল অভিবাদন দেবে না। প্রফেশনাল কিন্তু চ্যাট স্টাইলে কথা শুরু করবে।
   উদাহরণ: "হ্যালো! AutoCraft Agency থেকে বলছি। আপনার ফেসবুক পেজের মেসেজ/কমেন্ট অটোমেশন আর বিজনেসের জন্য ল্যান্ডিং পেজ নিয়ে ভাবছেন? বলুন তো ঠিক কোন জায়গায় সাহায্য লাগবে?"

২. সার্ভিস ও প্রাইসিং (All-in-One Bundle Package):
- Auto Message Reply, Auto Comment Reply, Regular Posting Automation, Responsive Landing Page.
- প্রারম্ভিক সেটআপ ফি: আলোচনা সাপেক্ষে | মান্থলি মেইনটেন্যান্স ফি: মাত্র ৫০০ টাকা/মাস!

৩. তথ্য সংগ্রহের নিয়ম:
কাস্টমার ফ্রি ট্রায়াল বা পেইড সার্ভিস বুক করতে রাজি হলে, তার কাছ থেকে কেবল এই ৪টি তথ্য চেয়ে নেবে:
১. Customer_Name | ২. Phone_Number | ৩. Email | ৪. Business_Page_Name / Page_URL

৪. মেসেজ সাইজ: উত্তর ২-৩ বাক্যের বেশি দেবে না। ছোট ছোট মেসেজে চ্যাট করবে।
"""

# --- ডাটাবেস সেটআপ (মেমোরি ধরে রাখার জন্য) ---
def init_db():
    conn = sqlite3.connect("bot_memory.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            sender_id TEXT,
            role TEXT,
            content TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

def get_user_history(sender_id):
    conn = sqlite3.connect("bot_memory.db")
    cursor = conn.cursor()
    cursor.execute("SELECT role, content FROM chat_history WHERE sender_id = ?", (sender_id,))
    rows = cursor.fetchall()
    conn.close()
    
    history = [{"role": "system", "content": SYSTEM_PROMPT}]
    for row in rows:
        history.append({"role": row[0], "content": row[1]})
    return history

def save_message_to_db(sender_id, role, content):
    conn = sqlite3.connect("bot_memory.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO chat_history (sender_id, role, content) VALUES (?, ?, ?)", (sender_id, role, content))
    conn.commit()
    conn.close()

# Flask অ্যাপ সেটআপ
flask_app = Flask(__name__)
BOT_IS_RUNNING = False  # গ্লোবাল রিমোট সুইচ

# --- রিমোট কন্ট্রোল ড্যাশবোর্ড (মোবাইল ও পিসি ফ্রেন্ডলি ওয়েব UI) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="bn">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AutoCraft Remote Controller</title>
    <style>
        body { background-color: #121212; color: #ffffff; font-family: Arial, sans-serif; text-align: center; margin: 0; padding: 50px 20px; }
        .card { background: #1e1e1e; max-width: 400px; margin: 0 auto; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }
        .status { font-size: 18px; font-weight: bold; padding: 12px; border-radius: 8px; margin-bottom: 25px; }
        .running { background-color: #28a745; color: white; }
        .stopped { background-color: #dc3545; color: white; }
        .btn { display: inline-block; padding: 12px 25px; font-size: 16px; font-weight: bold; color: white; border: none; border-radius: 8px; cursor: pointer; text-decoration: none; margin: 5px; }
        .btn-start { background-color: #28a745; }
        .btn-stop { background-color: #dc3545; }
        .btn:hover { opacity: 0.8; }
    </style>
</head>
<body>
    <div class="card">
        <h2>AutoCraft Remote Panel</h2>
        <p style="color: #00ffcc; margin-bottom: 25px;">ফেইসবুক পেজ অটোমেশন রিমোট কন্ট্রোলার</p>
        
        {% if bot_status %}
            <div class="status running">🟢 BOT IS LIVE & RUNNING</div>
            <a href="/toggle" class="btn btn-stop">⏹ STOP BOT</a>
        {% else %}
            <div class="status stopped">🔴 BOT IS CURRENTLY OFF</div>
            <a href="/toggle" class="btn btn-start">▶ START BOT</a>
        {% endif %}
        
        <p style="font-size: 12px; color: #888; margin-top: 30px;">যেকোনো মোবাইল বা পিসি থেকে এই লিংকে এসে বট কন্ট্রোল করতে পারবেন।</p>
    </div>
</body>
</html>
"""

@flask_app.route("/")
def dashboard():
    return render_template_string(HTML_TEMPLATE, bot_status=BOT_IS_RUNNING)

@flask_app.route("/toggle")
def toggle_bot():
    global BOT_IS_RUNNING
    BOT_IS_RUNNING = not BOT_IS_RUNNING
    return dashboard()

# --- ফেসগুক ওয়েব হুক রাউট ---
@flask_app.route("/webhook", methods=["GET", "POST"])
def facebook_webhook():
    global BOT_IS_RUNNING
    
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        
        if mode and token:
            if mode == "subscribe" and token == VERIFY_TOKEN:
                return challenge, 200
            else:
                return "Verification failed", 403
        return "Hello World", 200

    if request.method == "POST":
        # যদি রিমোট থেকে বট অফ করা থাকে, তবে মেসেজ ইগ্নোর করবে
        if not BOT_IS_RUNNING:
            return jsonify({"status": "bot is off"}), 200

        data = request.json
        try:
            if data.get("object") == "page":
                for entry in data.get("entry", []):
                    for messaging_event in entry.get("messaging", []):
                        sender_id = messaging_event["sender"]["id"]
                        
                        user_message_text = ""
                        image_url = None
                        audio_url = None

                        if "message" in messaging_event and "text" in messaging_event["message"]:
                            user_message_text = messaging_event["message"]["text"]

                        if "message" in messaging_event and "attachments" in messaging_event["message"]:
                            for att in messaging_event["message"]["attachments"]:
                                if att["type"] == "image":
                                    image_url = att["payload"]["url"]
                                    user_message_text = "এই ছবিটি দেখে আপনার সার্ভিস অনুযায়ী রেসপন্স করুন।"
                                elif att["type"] == "audio":
                                    audio_url = att["payload"]["url"]
                                    user_message_text = "ভয়েস মেসেজ পাঠানো হয়েছে।"

                        if user_message_text or image_url or audio_url:
                            chat_messages = get_user_history(sender_id)
                            final_input_text = user_message_text

                            if audio_url:
                                audio_data = requests.get(audio_url).content
                                audio_path = f"temp_{sender_id}.mp3"
                                with open(audio_path, "wb") as f:
                                    f.write(audio_data)
                                
                                with open(audio_path, "rb") as file:
                                    transcription = client.audio.translations.create(
                                        file=(audio_path, file.read()),
                                        model="whisper-large-v3",
                                        response_format="text"
                                    )
                                final_input_text = f"[Voice Transcribed]: {transcription}"
                                os.remove(audio_path)

                            save_message_to_db(sender_id, "user", final_input_text)
                            chat_messages.append({"role": "user", "content": final_input_text})

                            ai_reply = generate_ai_reply(chat_messages, image_url)
                            save_message_to_db(sender_id, "assistant", ai_reply)
                            send_facebook_message(sender_id, ai_reply)
                            
        except Exception as e:
            print(f"Error processing webhook: {e}")
            
        return jsonify({"status": "event received"}), 200

def generate_ai_reply(messages, image_url=None):
    try:
        model_to_use = "qwen/qwen3.8-27b" # আপনার নির্দিষ্ট মডেল
        
        if image_url:
            img_response = requests.get(image_url)
            base64_image = base64.b64encode(img_response.content).decode('utf-8')
            
            messages[-1] = {
                "role": "user",
                "content": [
                    {"type": "text", "text": messages[-1]["content"]},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }

        completion = client.chat.completions.create(
            model=model_to_use,
            messages=messages,
            temperature=0.7,
            max_tokens=300,
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"দুঃখিত, এই মুহূর্তে একটু সমস্যা হচ্ছে। ({str(e)})"

def send_facebook_message(recipient_id, message_text):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": message_text}
    }
    headers = {"Content-Type": "application/json"}
    requests.post(url, json=payload, headers=headers)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)