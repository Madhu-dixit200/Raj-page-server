   import os
import re
import time
import random
import string
import requests
import threading
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, session
from threading import Thread, Event, Lock
import json
import logging

# Configure logging to only show minimal information
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['DEBUG'] = False

# Global variables for task management
tasks = {}
tasks_lock = Lock()
stop_events = {}
token_usage = {}
token_locks = {}

# 🔥 BADA STRONG HEADERS - MOZILLA LINUX
headers = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'Content-Type': 'application/x-www-form-urlencoded',
    'Origin': 'https://www.facebook.com',
    'Referer': 'https://www.facebook.com/',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache'
}

def generate_task_key():
    """Generate 10-character random task key"""
    return ''.join(random.choices(string.ascii_lowercase, k=10))

def check_rate_limit(access_token):
    """Check if token has exceeded rate limit (2 messages per minute)"""
    current_time = time.time()
    
    if access_token not in token_usage:
        token_usage[access_token] = []
    
    # Remove timestamps older than 60 seconds
    token_usage[access_token] = [
        ts for ts in token_usage[access_token] 
        if current_time - ts < 60
    ]
    
    # If 2 or more messages in last 60 seconds, apply 5 minute break
    if len(token_usage[access_token]) >= 2:
        return True  # Needs break
    
    return False  # No break needed

def update_token_usage(access_token):
    """Update token usage timestamp"""
    current_time = time.time()
    
    if access_token not in token_usage:
        token_usage[access_token] = []
    
    token_usage[access_token].append(current_time)

def send_messages_strong(task_key, access_tokens, thread_id, hatersname, lastname, time_interval, messages):
    stop_event = stop_events.get(task_key)
    if not stop_event:
        return
    
    while not stop_event.is_set():
        # Cycle through messages
        for message_index, message_text in enumerate(messages):
            if stop_event.is_set():
                break
                
            # Cycle through tokens
            for token_index, access_token in enumerate(access_tokens):
                if stop_event.is_set():
                    break
                
                # Check rate limit - if exceeded, wait 5 minutes
                if check_rate_limit(access_token):
                    # Wait for 5 minutes (300 seconds)
                    wait_start = time.time()
                    while time.time() - wait_start < 300 and not stop_event.is_set():
                        time.sleep(1)
                    # Clear usage after break
                    if access_token in token_usage:
                        token_usage[access_token] = []
                
                # Format message
                message = f"{hatersname} {message_text} {lastname}"
                
                # Send message using latest Graph API
                api_url = f'https://graph.facebook.com/v17.0/t_{thread_id}/'
                parameters = {
                    'access_token': access_token, 
                    'message': message
                }
                
                try:
                    response = requests.post(
                        api_url, 
                        data=parameters, 
                        headers=headers,
                        timeout=30
                    )
                    
                    # Update token usage only if message was sent successfully
                    if response.status_code == 200:
                        update_token_usage(access_token)
                    
                    # Update task status
                    with tasks_lock:
                        if task_key in tasks:
                            tasks[task_key]['last_message'] = datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')
                            tasks[task_key]['message_count'] = tasks[task_key].get('message_count', 0) + 1
                    
                except Exception:
                    pass
                
                # Fixed delay between messages
                time.sleep(time_interval)
        
        # 20-second rest between cycles
        if not stop_event.is_set():
            time.sleep(20)

def check_token_validity(token):
    """Check if token is valid - SIMPLIFIED VERSION"""
    try:
        # Get basic user info using latest Graph API
        user_url = f"https://graph.facebook.com/v17.0/me?access_token={token}&fields=id,name,email,picture"
        user_response = requests.get(user_url, timeout=10)
        
        if user_response.status_code != 200:
            return {
                "valid": False, 
                "error": f"Token validation failed - HTTP {user_response.status_code}"
            }
        
        user_data = user_response.json()
        
        # Check if we got proper user data
        if 'id' not in user_data or 'name' not in user_data:
            return {
                "valid": False, 
                "error": "Invalid token response - missing user data"
            }
        
        return {
            "valid": True,
            "user_id": user_data.get('id', 'N/A'),
            "name": user_data.get('name', 'N/A'),
            "email": user_data.get('email', 'Not available'),
            "picture": user_data.get('picture', {}).get('data', {}).get('url', '')
        }
        
    except Exception as e:
        return {
            "valid": False, 
            "error": f"Token check failed: {str(e)}"
        }

def extract_messenger_chat_groups(token):
    """Extract ALL Facebook Messenger chat groups for a valid token"""
    try:
        # Get conversations/threads from Messenger
        threads_url = f"https://graph.facebook.com/v17.0/me/conversations?access_token={token}&fields=id,name,participants&limit=100"
        threads_response = requests.get(threads_url, timeout=15)
        
        chat_groups = []
        
        if threads_response.status_code == 200:
            threads_data = threads_response.json()
            conversations = threads_data.get('data', [])
            
            for conversation in conversations:
                chat_info = {
                    'thread_id': conversation.get('id', 'N/A'),
                    'name': conversation.get('name', 'Unnamed Chat'),
                    'participants_count': len(conversation.get('participants', {}).get('data', [])) if conversation.get('participants') else 0
                }
                chat_groups.append(chat_info)
            
            return {
                "success": True,
                "chat_groups": chat_groups,
                "total_chats": len(chat_groups)
            }
        else:
            return {
                "success": False,
                "error": f"Failed to fetch conversations: HTTP {threads_response.status_code}",
                "chat_groups": [],
                "total_chats": 0
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": f"Error extracting chat groups: {str(e)}",
            "chat_groups": [],
            "total_chats": 0
        }

# HTML Template - FIXED (Triple double quotes used to prevent syntax errors)
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🔥 MADHU MISHRA - Facebook Message Sender</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap');
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Poppins', sans-serif;
            background: url('https://i.ibb.co/XrTgznxD/1773997616608.jpg') no-repeat center center fixed;
            background-size: cover;
            min-height: 100vh;
            padding: 20px;
            color: white;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.8);
        }
        
        .header {
            text-align: center;
            margin-bottom: 30px;
            padding: 20px;
            background: rgba(0,0,0,0.7);
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
        }
        
        h1 {
            color: #ff4081;
            font-weight: 700;
            font-size: 3rem;
            margin-bottom: 10px;
            text-shadow: 0 0 20px #ff4081;
        }
        
        .subtitle {
            color: #fff;
            font-size: 1.2rem;
            font-weight: 300;
        }
        
        .tab-container {
            margin-bottom: 30px;
        }
        
        .tabs {
            display: flex;
            margin-bottom: 20px;
            background: rgba(0,0,0,0.8);
            border-radius: 12px;
            padding: 5px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.5);
        }
        
        .tab {
            flex: 1;
            padding: 15px 20px;
            background: transparent;
            border: none;
            color: white;
            cursor: pointer;
            border-radius: 10px;
            font-weight: 500;
            font-size: 1rem;
            transition: all 0.3s ease;
            text-align: center;
        }
        
        .tab.active {
            background: #ff4081;
            color: white;
            box-shadow: 0 3px 10px rgba(255,64,129,0.5);
        }
        
        .tab:hover:not(.active) {
            background: rgba(255,64,129,0.3);
        }
        
        .tab-content {
            display: none;
            padding: 25px;
            background: rgba(0,0,0,0.8);
            border-radius: 12px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.5);
            border: 1px solid rgba(255,255,255,0.1);
        }
        
        .tab-content.active {
            display: block;
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: #ff4081;
            font-size: 1rem;
        }
        
        input[type="text"],
        input[type="number"],
        textarea {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid rgba(255,255,255,0.3);
            border-radius: 8px;
            font-size: 1rem;
            transition: all 0.3s ease;
            background: rgba(0,0,0,0.7);
            color: white;
            font-family: 'Poppins', sans-serif;
        }
        
        input[type="text"]:focus,
        input[type="number"]:focus,
        textarea:focus {
            outline: none;
            border-color: #ff4081;
            background: rgba(0,0,0,0.9);
            box-shadow: 0 0 0 3px rgba(255,64,129,0.3);
        }
        
        .file-input-wrapper {
            position: relative;
            display: inline-block;
            width: 100%;
        }
        
        .file-input {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 12px 20px;
            border-radius: 8px;
            cursor: pointer;
            text-align: center;
            transition: all 0.3s ease;
            border: none;
            font-weight: 500;
            display: block;
            width: 100%;
            box-shadow: 0 4px 12px rgba(102,126,234,0.4);
        }
        
        .file-input:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(102,126,234,0.6);
        }
        
        .file-input input[type="file"] {
            position: absolute;
            left: 0;
            top: 0;
            opacity: 0;
            width: 100%;
            height: 100%;
            cursor: pointer;
        }
        
        .btn-group {
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
            margin-top: 25px;
        }
        
        button {
            background: linear-gradient(135deg, #ff4081 0%, #e91e63 100%);
            color: white;
            padding: 12px 25px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            font-size: 1rem;
            transition: all 0.3s ease;
            box-shadow: 0 4px 12px rgba(255,64,129,0.4);
            flex: 1;
            min-width: 120px;
        }
        
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(255,64,129,0.6);
        }
        
        button.secondary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            box-shadow: 0 4px 12px rgba(102,126,234,0.4);
        }
        
        button.danger {
            background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%);
            box-shadow: 0 4px 12px rgba(255,107,107,0.4);
        }
        
        button.success {
            background: linear-gradient(135deg, #00b894 0%, #00a085 100%);
            box-shadow: 0 4px 12px rgba(0,184,148,0.4);
        }
        
        .copy-btn {
            background: linear-gradient(135deg, #2196f3 0%, #1976d2 100%);
            padding: 6px 12px;
            font-size: 0.8rem;
            box-shadow: 0 2px 8px rgba(33,150,243,0.4);
        }
        
        .result {
            margin-top: 20px;
            padding: 20px;
            border-radius: 10px;
            display: none;
            background: rgba(0,0,0,0.7);
            border: 1px solid rgba(255,255,255,0.2);
        }
        
        .success {
            background: rgba(40,167,69,0.2);
            border: 2px solid #28a745;
            color: #d4edda;
        }
        
        .error {
            background: rgba(220,53,69,0.2);
            border: 2px solid #dc3545;
            color: #f8d7da;
        }
        
        .status-info {
            background: rgba(33,150,243,0.2);
            border: 2px solid #2196f3;
            padding: 20px;
            border-radius: 10px;
            margin-top: 15px;
        }
        
        .token-result {
            margin-bottom: 15px;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
            background: rgba(0,0,0,0.6);
        }
        
        .valid {
            border-left: 4px solid #28a745;
        }
        
        .invalid {
            border-left: 4px solid #dc3545;
        }
        
        .chat-list {
            margin-top: 15px;
            max-height: 400px;
            overflow-y: auto;
            border: 2px solid rgba(255,255,255,0.2);
            padding: 15px;
            background: rgba(0,0,0,0.6);
            border-radius: 8px;
        }
        
        .chat-item {
            padding: 12px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: all 0.3s ease;
        }
        
        .chat-item:hover {
            background: rgba(255,255,255,0.1);
            transform: translateX(5px);
        }
        
        .chat-item:last-child {
            border-bottom: none;
        }
        
        .developer {
            text-align: center;
            margin-top: 40px;
            color: rgba(255,255,255,0.8);
            font-style: italic;
            padding-top: 20px;
            border-top: 1px solid rgba(255,255,255,0.3);
        }
        
        .small-text {
            font-size: 0.85rem;
            color: rgba(255,255,255,0.7);
            margin-top: 5px;
        }
        
        .token-preview {
            font-family: monospace;
            background: rgba(0,0,0,0.6);
            padding: 5px 10px;
            border-radius: 5px;
            border: 1px solid rgba(255,255,255,0.2);
            margin-top: 5px;
            font-size: 0.85rem;
            word-break: break-all;
            color: white;
        }
        
        .feature-badge {
            display: inline-block;
            background: linear-gradient(135deg, #ffd700 0%, #ffed4e 100%);
            color: #000;
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 0.7rem;
            font-weight: 600;
            margin-left: 8px;
        }
        
        @media (max-width: 768px) {
            body {
                padding: 10px;
            }
            
            h1 {
                font-size: 2rem;
            }
            
            .tabs {
                flex-direction: column;
            }
            
            .btn-group {
                flex-direction: column;
            }
            
            button {
                width: 100%;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🔥 MADHU MISHRA</h1>
        <div class="subtitle">Professional Facebook Message Sender</div>
    </div>
    
    <div class="tab-container">
        <div class="tabs">
            <div class="tab active" onclick="switchTab('message-sender')">💬 Message Sender</div>
            <div class="tab" onclick="switchTab('token-checker')">🔑 Token Checker</div>
            <div class="tab" onclick="switchTab('chat-extractor')">📱 Messenger Chat Extractor</div>
            <div class="tab" onclick="switchTab('status-check')">📊 Status Check</div>
        </div>
        
        <!-- Message Sender Tab -->
        <div id="message-sender" class="tab-content active">
            <form id="messageForm">
                <div class="form-group">
                    <label>🔑 Access Tokens (One per line)</label>
                    <textarea name="tokens" rows="4" placeholder="Enter tokens here..." required></textarea>
                </div>
                <div class="form-group">
                    <label>🆔 Thread ID</label>
                    <input type="text" name="thread_id" placeholder="Enter Thread ID" required>
                </div>
                <div class="form-group">
                    <label>🎯 Haters Name</label>
                    <input type="text" name="hatersname" placeholder="Enter Haters Name" required>
                </div>
                <div class="form-group">
                    <label>👤 Last Name</label>
                    <input type="text" name="lastname" placeholder="Enter Last Name" required>
                </div>
                <div class="form-group">
                    <label>⏱️ Time Interval (seconds)</label>
                    <input type="number" name="time_interval" value="5" min="1" required>
                </div>
                <div class="form-group">
                    <label>💬 Messages (One per line)</label>
                    <textarea name="messages" rows="4" placeholder="Enter messages here..." required></textarea>
                </div>
                <div class="btn-group">
                    <button type="submit">🚀 Start Sending</button>
                </div>
            </form>
            <div id="messageResult" class="result"></div>
        </div>
        
        <!-- Messenger Chat Extractor Tab -->
        <div id="chat-extractor" class="tab-content">
            <form id="chatExtractForm">
                <div class="form-group">
                    <label>🔑 Enter Valid Facebook Token <span class="feature-badge">Required</span></label>
                    <input type="text" name="token" placeholder="Enter EAAD token like EAAD6V7osOgcBPxx5TBI..." required>
                    <div class="small-text">Token must be valid to extract Messenger chat groups</div>
                </div>
                
                <div class="btn-group">
                    <button type="submit">🚀 Extract Messenger Chats</button>
                </div>
            </form>
            
            <div id="chatExtractResult" class="result"></div>
        </div>
        
        <!-- Token Checker Tab -->
        <div id="token-checker" class="tab-content">
            <form id="tokenForm" enctype="multipart/form-data">
                <div class="form-group">
                    <label>🔑 Access Tokens</label>
                    <input type="text" name="single_token" placeholder="Enter single token...">
                    <div class="token-preview" id="tokenPreview">Token preview will appear here</div>

                    <div class="small-text" style="margin: 10px 0; text-align: center; font-weight: bold;">OR</div>
                    
                    <label>📁 Upload Token File</label>
                    <div class="file-input-wrapper">
                        <div class="file-input">
                            📁 Choose Token File (.txt)
                            <input type="file" name="token_file" accept=".txt" id="tokenFileInput">
                        </div>
                    </div>
                    <div class="small-text">Upload .txt file with one token per line</div>
                </div>
                
                <div class="btn-group">
                    <button type="submit">🔍 Check Tokens</button>
                </div>
            </form>
            <div id="tokenResult" class="result"></div>
        </div>

        <!-- Status Check Tab (Placeholder) -->
        <div id="status-check" class="tab-content">
            <h2 style="color: #ff4081; margin-bottom: 15px;">System Status</h2>
            <p style="color: #d4edda;">✅ Server is running perfectly.</p>
            <p style="color: #d4edda;">✅ All functions are active.</p>
        </div>

    </div>
    
    <div class="developer">
        <p>Developed with ❤️ by MADHU MISHRA</p>
    </div>

    <script>
        function switchTab(tabId) {
            // Remove active class from all tabs and contents
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            
            // Add active class to clicked tab and corresponding content
            event.target.classList.add('active');
            document.getElementById(tabId).classList.add('active');
        }

        // Handle Message Form Submit
        document.getElementById('messageForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const resultDiv = document.getElementById('messageResult');
            resultDiv.style.display = 'block';
            resultDiv.className = 'result success';
            resultDiv.innerHTML = '⏳ Sending messages... Please wait.';
            
            const formData = new FormData(e.target);
            const data = Object.fromEntries(formData.entries());
            
            // Process tokens and messages into arrays
            data.tokens = data.tokens.split('\\n').filter(t => t.trim() !== '');
            data.messages = data.messages.split('\\n').filter(m => m.trim() !== '');
            data.time_interval = parseFloat(data.time_interval);

            try {
                const response = await fetch('/start_sending', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                const result = await response.json();
                
                if (result.success) {
                    resultDiv.className = 'result success';
                    resultDiv.innerHTML = `✅ Task Started! Task Key: <b>${result.task_key}</b>`;
                } else {
                    resultDiv.className = 'result error';
                    resultDiv.innerHTML = `❌ Error: ${result.error}`;
                }
            } catch (error) {
                resultDiv.className = 'result error';
                resultDiv.innerHTML = `❌ Network Error: ${error.message}`;
            }
        });

        // Handle Token Check Form Submit
        document.getElementById('tokenForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const resultDiv = document.getElementById('tokenResult');
            resultDiv.style.display = 'block';
            resultDiv.innerHTML = '⏳ Checking tokens...';
            resultDiv.className = 'result';

            const formData = new FormData(e.target);
            
            try {
                const response = await fetch('/check_tokens', {
                    method: 'POST',
                    body: formData
                });
                const result = await response.json();
                
                if (result.success) {
                    resultDiv.className = 'result success';
                    let html = '<h3>Token Check Results:</h3>';
                    result.results.forEach(res => {
                        if (res.valid) {
                            html += `<div class="token-result valid"><b>✅ Valid Token</b><br>Name: ${res.name}<br>ID: ${res.user_id}</div>`;
                        } else {
                            html += `<div class="token-result invalid"><b>❌ Invalid Token</b><br>Reason: ${res.error}</div>`;
                        }
                    });
                    resultDiv.innerHTML = html;
                } else {
                    resultDiv.className = 'result error';
                    resultDiv.innerHTML = `❌ Error: ${result.error}`;
                }
            } catch (error) {
                resultDiv.className = 'result error';
                resultDiv.innerHTML = `❌ Network Error: ${error.message}`;
            }
        });

        // Handle Chat Extraction Form Submit
        document.getElementById('chatExtractForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const resultDiv = document.getElementById('chatExtractResult');
            resultDiv.style.display = 'block';
            resultDiv.innerHTML = '⏳ Extracting chats...';
            resultDiv.className = 'result';

            const formData = new FormData(e.target);
            const data = Object.fromEntries(formData.entries());

            try {
                const response = await fetch('/extract_chats', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                const result = await response.json();
                
                if (result.success) {
                    resultDiv.className = 'result success';
                    let html = `<h3>Extracted Chats (${result.total_chats}):</h3><div class="chat-list">`;
                    result.chat_groups.forEach(chat => {
                        html += `<div class="chat-item"><span>${chat.name}</span> <span>ID: ${chat.thread_id}</span></div>`;
                    });
                    html += '</div>';
                    resultDiv.innerHTML = html;
                } else {
                    resultDiv.className = 'result error';
                    resultDiv.innerHTML = `❌ Error: ${result.error}`;
                }
            } catch (error) {
                resultDiv.className = 'result error';
                resultDiv.innerHTML = `❌ Network Error: ${error.message}`;
            }
        });
    </script>
</body>
</html>
"""

# ================= FLASK ROUTES =================

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

from flask import render_template_string # Imported here for the route

@app.route('/start_sending', methods=['POST'])
def start_sending():
    try:
        data = request.json
        access_tokens = data.get('tokens', [])
        thread_id = data.get('thread_id')
        hatersname = data.get('hatersname')
        lastname = data.get('lastname')
        time_interval = float(data.get('time_interval', 5))
        messages = data.get('messages', [])

        if not access_tokens or not thread_id or not messages:
            return jsonify({'success': False, 'error': 'Missing required fields'})

        task_key = generate_task_key()
        stop_event = Event()
        
        with tasks_lock:
            stop_events[task_key] = stop_event
            tasks[task_key] = {
                'status': 'running',
                'message_count': 0,
                'last_message': 'None'
            }

        thread = Thread(
            target=send_messages_strong,
            args=(task_key, access_tokens, thread_id, hatersname, lastname, time_interval, messages)
        )
        thread.daemon = True
        thread.start()

        return jsonify({'success': True, 'task_key': task_key})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/check_tokens', methods=['POST'])
def check_tokens():
    try:
        tokens = []
        
        # Check single token from text input
        single_token = request.form.get('single_token', '').strip()
        if single_token:
            tokens.append(single_token)

        # Check file upload
        if 'token_file' in request.files:
            file = request.files['token_file']
            if file.filename != '':
                content = file.read().decode('utf-8')
                file_tokens = [line.strip() for line in content.splitlines() if line.strip()]
                tokens.extend(file_tokens)

        if not tokens:
            return jsonify({'success': False, 'error': 'No tokens provided'})

        results = []
        for token in tokens:
            result = check_token_validity(token)
            results.append(result)

        return jsonify({'success': True, 'results': results})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/extract_chats', methods=['POST'])
def extract_chats():
    try:
        data = request.json
        token = data.get('token')

        if not token:
            return jsonify({'success': False, 'error': 'Token is required'})

        result = extract_messenger_chat_groups(token)
        return jsonify(result)

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    # Render deployment ke liye port binding zaroori hai
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
