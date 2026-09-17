import os
import sqlite3
import base64
import requests
from flask import Flask, request, jsonify, render_template_string
from groq import Groq

# --- কনফিগারেশন ---
client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "")

# --- ডাটাবেস সেটআপ (মাল্টি-টেনেন্ট: ক্লায়েন্ট টোকেন, প্রম্পট এবং চ্যাট মেমোরি) ---
def init_db():
    conn = sqlite3.connect("bot_memory.db")
    cursor = conn.cursor()
    
    # ১. ক্লায়েন্টদের পেজ, টোকেন ও তাদের নিজস্ব প্রম্পট সেভ রাখার টেবিল
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            page_id TEXT PRIMARY KEY,
            page_access_token TEXT,
            client_name TEXT,
            custom_prompt TEXT,
            bot_status BOOLEAN DEFAULT 1
        )
    """)
    
    # ২. চ্যাট হিস্ট্রি টেবিল (কোন পেজের কোন ইউজারের চ্যাট তা আলাদা করার জন্য)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            page_id TEXT,
            sender_id TEXT,
            role TEXT,
            content TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ডাটাবেস থেকে নির্দিষ্ট পেজের টোকেন, প্রম্পট এবং বট স্ট্যাটাস আনার ফাংশন
def get_client_details(page_id):
    conn = sqlite3.connect("bot_memory.db")
    cursor = conn.cursor()
    cursor.execute("SELECT page_access_token, custom_prompt, bot_status FROM clients WHERE page_id = ?", (page_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0], row[1], row[2] # token, custom_prompt, bot_status
    return None, None, False

def get_user_history(page_id, sender_id, custom_prompt):
    conn = sqlite3.connect("bot_memory.db")
    cursor = conn.cursor()
    cursor.execute("SELECT role, content FROM chat_history WHERE page_id = ? AND sender_id = ?", (page_id, sender_id))
    rows = cursor.fetchall()
    conn.close()
    
    # ক্লায়েন্টের নিজস্ব প্রম্পট সিস্টেম প্রম্পট হিসেবে সেট হবে
    history = [{"role": "system", "content": custom_prompt}]
    for row in rows:
        history.append({"role": row[0], "content": row[1]})
    return history

def save_message_to_db(page_id, sender_id, role, content):
    conn = sqlite3.connect("bot_memory.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO chat_history (page_id, sender_id, role, content) VALUES (?, ?, ?, ?)", (page_id, sender_id, role, content))
    conn.commit()
    conn.close()

# Flask অ্যাপ সেটআপ
flask_app = Flask(__name__)

# --- SaaS ড্যাশবোর্ড (যেখান থেকে ক্লায়েন্ট তার পেজ, টোকেন এবং নিজস্ব প্রম্পট সেট করবে) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="bn">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AutoCraft SaaS Onboarding</title>
    <style>
        body { background-color: #121212; color: #ffffff; font-family: Arial, sans-serif; text-align: center; margin: 0; padding: 40px 20px; }
        .card { background: #1e1e1e; max-width: 500px; margin: 0 auto; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); text-align: left; }
        input, textarea, button { width: 100%; padding: 12px; margin: 10px 0; border-radius: 6px; border: none; font-size: 15px; box-sizing: border-box; }
        input, textarea { background: #2a2a2a; color: white; }
        textarea { resize: vertical; height: 120px; }
        button { background-color: #28a745; color: white; font-weight: bold; cursor: pointer; }
        button:hover { opacity: 0.8; }
        h2, p { text-align: center; }
    </style>
</head>
<body>
    <div class="card">
        <h2>AutoCraft SaaS Bot</h2>
        <p style="color: #00ffcc; font-size: 14px;">আপনার ফেসবুক পেজ এবং এআই নির্দেশিকা কনফিগার করুন</p>
        
        <form action="/register" method="POST">
            <label>ক্লায়েন্ট / পেজের নাম:</label>
            <input type="text" name="client_name" placeholder="যেমন: Fashion House" required>
            
            <label>ফেসবুক পেজ আইডি (Page ID):</label>
            <input type="text" name="page_id" placeholder="যেমন: 10293848576" required>
            
            <label>পেজ এক্সেস টোকেন (Page Access Token):</label>
            <input type="text" name="page_access_token" placeholder="EAAG..." required>
            
            <label>বটের জন্য নির্দেশিকা বা System Prompt (যেভাবে আপনার বট কথা বলবে):</label>
            <textarea name="custom_prompt" placeholder="যেমন: আপনি ফেশন হাউসের সেলস প্রতিনিধি। কাস্টমারকে আমাদের নতুন জামাকাপড়ের কালেকশন দেখাবেন এবং অর্ডার কনফার্ম করার জন্য ফোন নম্বর ও ঠিকানা চাইবেন..." required></textarea>
            
            <button type="submit">বট একটিভ করুন</button>
        </form>
    </div>
</body>
</html>
"""

@flask_app.route("/")
def dashboard():
    return render_template_string(HTML_TEMPLATE)

@flask_app.route("/register", methods=["POST"])
def register_client():
    client_name = request.form.get("client_name")
    page_id = request.form.get("page_id")
    page_access_token = request.form.get("page_access_token")
    custom_prompt = request.form.get("custom_prompt")
    
    conn = sqlite3.connect("bot_memory.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO clients (page_id, page_access_token, client_name, custom_prompt, bot_status)
        VALUES (?, ?, ?, ?, 1)
    """, (page_id, page_access_token, client_name, custom_prompt))
    conn.commit()
    conn.close()
    
    return f"<h1 style='color:white; background:#121212; text-align:center; padding:50px;'>অভিনন্দন! {client_name} পেজের জন্য বট এবং কাস্টম প্রম্পট সফলভাবে সেভ হয়েছে।</h1>"

# --- সিঙ্গেল ফেসবুক ওয়েব হুক রাউট ---
@flask_app.route("/webhook", methods=["GET", "POST"])
def facebook_webhook():
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
        data = request.json
        try:
            if data.get("object") == "page":
                for entry in data.get("entry", []):
                    page_id = entry.get("id")
                    
                    # ডাটাবেস থেকে ওই পেজের টোকেন, কাস্টম প্রম্পট এবং বট স্ট্যাটাস নিয়ে আসা
                    page_access_token, custom_prompt, bot_is_running = get_client_details(page_id)
                    
                    if not page_access_token or not bot_is_running or not custom_prompt:
                        continue

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
                                    user_message_text = "এই ছবিটি দেখে আপনার সার্ভিস অনুযায়ী রেসপন্স করুন।"
                                elif att["type"] == "audio":
                                    audio_url = att["payload"]["url"]
                                    user_message_text = "ভয়েস মেসেজ পাঠানো হয়েছে।"

                        if user_message_text or image_url or audio_url:
                            # ওই ক্লায়েন্টের কাস্টম প্রম্পট সহ হিস্ট্রি লোড করা
                            chat_messages = get_user_history(page_id, sender_id, custom_prompt)
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

                            save_message_to_db(page_id, sender_id, "user", final_input_text)
                            chat_messages.append({"role": "user", "content": final_input_text})

                            ai_reply = generate_ai_reply(chat_messages, image_url)
                            save_message_to_db(page_id, sender_id, "assistant", ai_reply)
                            
                            send_facebook_message(page_id, sender_id, ai_reply, page_access_token)
                            
        except Exception as e:
            print(f"Error processing webhook: {e}")
            
        return jsonify({"status": "event received"}), 200

def generate_ai_reply(messages, image_url=None):
    try:
        model_to_use = "qwen/qwen3.8-27b"
        
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

def send_facebook_message(page_id, recipient_id, message_text, page_access_token):
    url = f"https://graph.facebook.0m/v18.0/me/messages?access_token={page_access_token}" # fix URL if needed
    # Correct URL format:
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={page_access_token}"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": message_text}
    }
    headers = {"Content-Type": "application/json"}
    requests.post(url, json=payload, headers=headers)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)
