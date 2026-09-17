import os
import sqlite3
import base64
import requests
from flask import Flask, request, jsonify, render_template_string, redirect, session
from groq import Groq

# --- কনফিগারেশন ---
client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "")

# ফেসবুক অ্যাপ ক্রেডেনশিয়ালস (ফেসবুক ডেভেলপার কনসোল থেকে পাবে)
FB_APP_ID = os.environ.get("FB_APP_ID", "YOUR_FACEBOOK_APP_ID")
FB_APP_SECRET = os.environ.get("FB_APP_SECRET", "YOUR_FACEBOOK_APP_SECRET")

SYSTEM_PROMPT = """
তুমি AutoCraft Agency-এর একজন প্রফেশনাল বিজনেস অটোমেশন স্পেশালিস্ট।
তোমার প্রধান লক্ষ্য হলো কাস্টমারের সাথে একজন বিশ্বস্ত বন্ধুর মতো কথা বলা, তাদের ফেসবুক পেজের অটোমেশনের সুবিধা ও অল-ইন-ওয়ান বান্ডেল প্যাকেজ বোঝানো এবং ফ্রি ট্রায়াল বা বুকিং নেওয়া।
উত্তর সবসময় ২-৩ বাক্যের মধ্যে রাখবে। ছোট ছোট মেসেজে চ্যাট করবে।
"""

# --- ডাটাবেস সেটআপ ---
def init_db():
    conn = sqlite3.connect("bot_memory.db")
    cursor = conn.cursor()
    # ক্লায়েন্ট টেবিল (পেজ আইডি, টোকেন, নাম এবং বট অন/অফ স্ট্যাটাস)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            page_id TEXT PRIMARY KEY,
            page_access_token TEXT,
            client_name TEXT,
            bot_status BOOLEAN DEFAULT 1
        )
    """)
    # চ্যাট হিস্ট্রি টেবিল
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

def get_client_token(page_id):
    conn = sqlite3.connect("bot_memory.db")
    cursor = conn.cursor()
    cursor.execute("SELECT page_access_token, bot_status FROM clients WHERE page_id = ?", (page_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0], row[1]
    return None, False

def get_user_history(page_id, sender_id):
    conn = sqlite3.connect("bot_memory.db")
    cursor = conn.cursor()
    cursor.execute("SELECT role, content FROM chat_history WHERE page_id = ? AND sender_id = ?", (page_id, sender_id))
    rows = cursor.fetchall()
    conn.close()
    
    history = [{"role": "system", "content": SYSTEM_PROMPT}]
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
flask_app.secret_key = os.environ.get("FLASK_SECRET_KEY", "super_secret_saas_key")

# --- ফ্রন্টএন্ড হোমপেজ (যেখান থেকে ক্লায়েন্ট ফেসবুক দিয়ে কানেক্ট করবে) ---
HOME_TEMPLATE = """
<!DOCTYPE html>
<html lang="bn">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AutoCraft SaaS - Connect Page</title>
    <style>
        body { background-color: #121212; color: #ffffff; font-family: Arial, sans-serif; text-align: center; padding: 60px 20px; }
        .card { background: #1e1e1e; max-width: 420px; margin: 0 auto; padding: 40px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }
        .btn-fb { background-color: #1877f2; color: white; padding: 14px 25px; border-radius: 8px; text-decoration: none; font-weight: bold; display: inline-block; margin-top: 20px; }
        .btn-fb:hover { opacity: 0.9; }
    </style>
</head>
<body>
    <div class="card">
        <h2>AutoCraft AI Bot</h2>
        <p style="color: #00ffcc; margin-bottom: 30px;">আপনার ফেসবুক পেজ কানেক্ট করে অটোমেশন চালু করুন</p>
        <a href="/auth/facebook" class="btn-fb">🔵 Connect with Facebook</a>
    </div>
</body>
</html>
"""

# --- ক্লায়েন্ট রিমোট কন্ট্রোল ড্যাশবোর্ড (যেখান থেকে বট অন/অফ করবে) ---
CONTROL_TEMPLATE = """
<!DOCTYPE html>
<html lang="bn">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Client Remote Control</title>
    <style>
        body { background-color: #121212; color: #ffffff; font-family: Arial, sans-serif; text-align: center; padding: 50px 20px; }
        .card { background: #1e1e1e; max-width: 420px; margin: 0 auto; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }
        .status { font-size: 16px; font-weight: bold; padding: 12px; border-radius: 8px; margin: 20px 0; }
        .running { background-color: #28a745; color: white; }
        .stopped { background-color: #dc3545; color: white; }
        .btn { display: inline-block; padding: 12px 25px; font-size: 15px; font-weight: bold; color: white; border: none; border-radius: 8px; cursor: pointer; text-decoration: none; }
        .btn-start { background-color: #28a745; }
        .btn-stop { background-color: #dc3545; }
    </style>
</head>
<body>
    <div class="card">
        <h2>{{ client_name }}</h2>
        <p style="color: #888; font-size: 13px;">Page ID: {{ page_id }}</p>
        
        {% if bot_status %}
            <div class="status running">🟢 YOUR BOT IS LIVE</div>
            <a href="/toggle/{{ page_id }}" class="btn btn-stop">⏹ STOP BOT</a>
        {% else %}
            <div class="status stopped">🔴 YOUR BOT IS OFF</div>
            <a href="/toggle/{{ page_id }}" class="btn btn-start">▶ START BOT</a>
        {% endif %}
    </div>
</body>
</html>
"""

@flask_app.route("/")
def index():
    return render_template_string(HOME_TEMPLATE)

# --- ফেসবুক অথেন্টিকেশন রিডাইরেক্ট ---
@flask_app.route("/auth/facebook")
def fb_login():
    # ফেসবুক লগইন উইন্ডোতে রিডাইরেক্ট করা (pages_messaging ও pages_show_list পার্মিশন সহ)
    redirect_uri = "https://agent-for-me.onrender.com/auth/facebook/callback"
    fb_auth_url = (
        f"https://www.facebook.com/v18.0/dialog/oauth?client_id={FB_APP_ID}"
        f"&redirect_uri={redirect_uri}&scope=pages_messaging,pages_show_list,pages_manage_metadata"
    )
    return redirect(fb_auth_url)

@flask_app.route("/auth/facebook/callback")
def fb_callback():
    code = request.args.get("code")
    if not code:
        return "Authorization failed!", 400
        
    # ১. এক্সেস টোকেন নেওয়া
    redirect_uri = "https://agent-for-me.onrender.com/auth/facebook/callback"
    token_url = (
        f"https://graph.facebook.com/v18.0/oauth/access_token?client_id={FB_APP_ID}"
        f"&redirect_uri={redirect_uri}&client_secret={FB_APP_SECRET}&code={code}"
    )
    res = requests.get(token_url).json()
    user_access_token = res.get("access_token")
    
    if not user_access_token:
        return "Failed to get access token from Facebook.", 400
        
    # ২. ইউজারের পেজগুলোর তালিকা এবং পেজ টোকেন ফেচ করা
    pages_url = f"https://graph.facebook.com/v18.0/me/accounts?access_token={user_access_token}"
    pages_res = requests.get(pages_url).json()
    
    data = pages_res.get("data", [])
    if not data:
        return "No Facebook pages found for this account.", 400
        
    # আপাতত প্রথম পেজটি অটো-সিলেক্ট বা কানেক্ট করা হচ্ছে (তুমি চাইলে পেজ সিলেকশন পেজ বানাতে পারো)
    page_info = data[0]
    page_id = page_info["id"]
    page_name = page_info["name"]
    page_access_token = page_info["access_token"]
    
    # ৩. ডাটাবেসে ক্লায়েন্ট সেভ করা
    conn = sqlite3.connect("bot_memory.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO clients (page_id, page_access_token, client_name, bot_status)
        VALUES (?, ?, ?, 1)
    """, (page_id, page_access_token, page_name))
    conn.commit()
    conn.close()
    
    # সেশন বা কুக்கியে পেজ আইডি সেভ করে ড্যাশবোর্ডে পাঠানো
    return redirect(f"/dashboard/{page_id}")

@flask_app.route("/dashboard/<page_id>")
def client_dashboard(page_id):
    conn = sqlite3.connect("bot_memory.db")
    cursor = conn.cursor()
    cursor.execute("SELECT client_name, bot_status FROM clients WHERE page_id = ?", (page_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return "Client not found!", 404
        
    return render_template_string(CONTROL_TEMPLATE, client_name=row[0], page_id=page_id, bot_status=row[1])

@flask_app.route("/toggle/<page_id>")
def toggle_client_bot(page_id):
    conn = sqlite3.connect("bot_memory.db")
    cursor = conn.cursor()
    cursor.execute("SELECT bot_status FROM clients WHERE page_id = ?", (page_id,))
    row = cursor.fetchone()
    if row:
        new_status = 0 if row[0] else 1
        cursor.execute("UPDATE clients SET bot_status = ? WHERE page_id = ?", (new_status, page_id))
        conn.commit()
    conn.close()
    return redirect(f"/dashboard/{page_id}")

# --- ফেসবুক ওয়েব হুক রাউট (সকল ক্লায়েন্টের মেসেজ হ্যান্ডেল করার জন্য) ---
@flask_app.route("/webhook", methods=["GET", "POST"])
def facebook_webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        
        if mode and token and mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200
        return "Verification failed", 403

    if request.method == "POST":
        data = request.json
        try:
            if data.get("object") == "page":
                for entry in data.get("entry", []):
                    page_id = entry.get("id")
                    page_access_token, bot_is_running = get_client_token(page_id)
                    
                    if not page_access_token or not bot_is_running:
                        continue

                    for messaging_event in entry.get("messaging", []):
                        if "message" in messaging_event and "text" in messaging_event["message"]:
                            sender_id = messaging_event["sender"]["id"]
                            user_message_text = messaging_event["message"]["text"]
                            
                            chat_messages = get_user_history(page_id, sender_id)
                            save_message_to_db(page_id, sender_id, "user", user_message_text)
                            chat_messages.append({"role": "user", "content": user_message_text})

                            # AI রেসপন্স জেনারেট
                            completion = client.chat.completions.create(
                                model="qwen/qwen3.8-27b",
                                messages=chat_messages,
                                temperature=0.7,
                                max_tokens=300,
                            )
                            ai_reply = completion.choices[0].message.content
                            
                            save_message_to_db(page_id, sender_id, "assistant", ai_reply)
                            
                            # নির্দিষ্ট ক্লায়েন্টের পেজ টোকেন দিয়ে মেসেজ পাঠানো
                            send_fb_message(page_id, sender_id, ai_reply, page_access_token)
                            
        except Exception as e:
            print(f"Webhook error: {e}")
            
        return jsonify({"status": "event received"}), 200

def send_fb_message(page_id, recipient_id, message_text, page_access_token):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={page_access_token}"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": message_text}
    }
    requests.post(url, json=payload)

if __name__ == "__main__":
    port = int(os.environ.com.get("PORT", 5000)) if hasattr(os.environ, 'com') else int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)
