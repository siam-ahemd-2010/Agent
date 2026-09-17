import os
import sqlite3
import base64
import requests
from flask import Flask, request, jsonify, render_template_string, redirect, session
from groq import Groq

# --- কনফিগারেশন ---
client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "")

# ফেসবুক অ্যাপ ক্রেডেনশিয়ালস (রেন্ডার এনভায়রনমেন্ট ভেরিয়েবল থেকে নেবে)
FB_APP_ID = os.environ.get("FB_APP_ID", "")
FB_APP_SECRET = os.environ.get("FB_APP_SECRET", "")
# তোর রেন্ডার লাইভ লিংক বা লোকালহোস্ট (যেমন: https://agent-for-me.onrender.com)
BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000")

# --- ডাটাবেস সেটআপ ---
def init_db():
    conn = sqlite3.connect("bot_memory.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            page_id TEXT PRIMARY KEY,
            page_access_token TEXT,
            client_name TEXT,
            custom_prompt TEXT,
            bot_status BOOLEAN DEFAULT 1
        )
    """)
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

def get_client_details(page_id):
    conn = sqlite3.connect("bot_memory.db")
    cursor = conn.cursor()
    cursor.execute("SELECT page_access_token, custom_prompt, bot_status FROM clients WHERE page_id = ?", (page_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0], row[1], row[2]
    return None, None, False

def get_user_history(page_id, sender_id, custom_prompt):
    conn = sqlite3.connect("bot_memory.db")
    cursor = conn.cursor()
    cursor.execute("SELECT role, content FROM chat_history WHERE page_id = ? AND sender_id = ?", (page_id, sender_id))
    rows = cursor.fetchall()
    conn.close()
    
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
flask_app.secret_key = os.environ.get("FLASK_SECRET_KEY", "super_secret_key_autocraft")

# --- আপডেট করা SaaS ড্যাশবোর্ড (যেখানে শুধু প্রম্পট লিখে ফেসবুক কানেক্ট বাটনে ক্লিক করতে হবে) ---
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
        textarea, button { width: 100%; padding: 12px; margin: 10px 0; border-radius: 6px; border: none; font-size: 15px; box-sizing: border-box; }
        textarea { background: #2a2a2a; color: white; resize: vertical; height: 140px; }
        .fb-btn { background-color: #1877f2; color: white; font-weight: bold; cursor: pointer; text-align: center; display: block; text-decoration: none; padding: 12px; border-radius: 6px; }
        .fb-btn:hover { opacity: 0.9; }
        h2, p { text-align: center; }
    </style>
</head>
<body>
    <div class="card">
        <h2>AutoCraft SaaS Bot</h2>
        <p style="color: #00ffcc; font-size: 14px;">আপনার এআই নির্দেশিকা লিখে সরাসরি ফেসবুক পেজ কানেক্ট করুন</p>
        
        <form action="/save-prompt" method="POST">
            <label>বটের জন্য নির্দেশিকা বা System Prompt:</label>
            <textarea name="custom_prompt" placeholder="যেমন: আপনি ফেশন হাউসের সেলস প্রতিনিধি। কাস্টমারকে আমাদের নতুন কালেকশন দেখাবেন এবং অর্ডার কনফার্ম করার জন্য ফোন নম্বর ও ঠিকানা চাইবেন..." required></textarea>
            
            <button type="submit" style="background-color: #28a745; color: white; font-weight: bold; cursor: pointer;">প্রম্পট সেভ করুন ও ফেসবুক দিয়ে লগইন করুন</button>
        </form>
    </div>
</body>
</html>
"""

@flask_app.route("/")
def dashboard():
    return render_template_string(HTML_TEMPLATE)

@flask_app.route("/save-prompt", methods=["POST"])
def save_prompt():
    # ক্লায়েন্টের প্রম্পটটি সাময়িকবাবে সেশনে সেভ করে ফেসবুক অথ-এ পাঠানো হচ্ছে
    session['custom_prompt'] = request.form.get("custom_prompt")
    
    # ফেসবুক লগইন ইউআরএলে রিডাইরেক্ট করা (যাতে পেজ ম্যানেজমেন্ট পারমিশন নেওয়া যায়)
    fb_login_url = (
        f"https://www.facebook.com/v18.0/dialog/oauth?"
        f"client_id={FB_APP_ID}&"
        f"redirect_uri={BASE_URL}/auth/facebook/callback&"
        f"scope=pages_messaging,pages_show_list,pages_manage_metadata"
    )
    return redirect(fb_login_url)

@flask_app.route("/auth/facebook/callback")
def facebook_callback():
    code = request.args.get("code")
    if not code:
        return "Facebook Auth Failed!", 400
        
    custom_prompt = session.get('custom_prompt', "আপনি এই পেজের প্রফেশনাল এআই অ্যাসিস্ট্যান্ট।")

    # ১. ইউজার কোড দিয়ে ফেসবুক থেকে শর্ট-লিভড ইউজার এক্সেস টোকেন আনা
    token_url = (
        f"https://graph.facebook.com/v18.0/oauth/access_token?"
        f"client_id={FB_APP_ID}&"
        f"redirect_uri={BASE_URL}/auth/facebook/callback&"
        f"client_secret={FB_APP_SECRET}&"
        f"code={code}"
    )
    res = requests.get(token_url).json()
    user_access_token = res.get("access_token")

    if not user_access_token:
        return f"Token Error: {res}", 400

    # ২. ইউজারের পেজগুলোর লিস্ট এবং পেজ এক্সেস টোকেন ফেচ করা
    pages_url = f"https://graph.facebook.com/v18.0/me/accounts?access_token={user_access_token}"
    pages_res = requests.get(pages_url).json()
    
    pages = pages_res.get("data", [])
    if not pages:
        return "কোনো ফেসবুক পেজ পাওয়া যায়নি! দয়া করে আপনার একটি ফেসবুক পেজ থাকা নিশ্চিত করুন।", 400

    # আপাতত ইউজারের প্রথম পেজটি অটো-সিলেক্ট করে কানেক্ট করে দিচ্ছি (বা মাল্টি-পেজ লিস্টও দেখানো যায়)
    conn = sqlite3.connect("bot_memory.db")
    cursor = conn.cursor()

    for page in pages:
        page_id = page["id"]
        page_name = page["name"]
        page_access_token = page["access_token"]

        # ডাটাবেসে পেজ আইডি, টোকেন ও প্রম্পট সেভ করা
        cursor.execute("""
            INSERT OR REPLACE INTO clients (page_id, page_access_token, client_name, custom_prompt, bot_status)
            VALUES (?, ?, ?, ?, 1)
        """, (page_id, page_access_token, page_name, custom_prompt))

        # অটোমেটিক ফেসবুক ওয়েবহুকের জন্য পেজ সাবস্ক্রাইব করানো
        sub_url = f"https://graph.facebook.com/v18.0/{page_id}/subscribed_apps?subscribed_fields=messages&access_token={page_access_token}"
        requests.post(sub_url)

    conn.commit()
    conn.close()

    return f"""
    <div style='background:#121212; color:white; text-align:center; padding:50px; font-family:Arial;'>
        <h1 style='color:#28a745;'>অভিনন্দন! আপনার ফেসবুক পেজ সফলভাবে কানেক্ট হয়েছে।</h1>
        <p>বট এখন থেকে আপনার পেজে অটোমেটিক মেসেজ রিপ্লাই করবে।</p>
    </div>
    """

# --- ফেসবুক ওয়েব হুক রাউট ---
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
