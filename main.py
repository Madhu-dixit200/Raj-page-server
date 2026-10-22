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

# HTML Template
HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>❤️ MADHU PANDIT🖤 - Facebook Message Sender</title>
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
        <h1>❤️MADHU PANDIT❤️</h1>
        <div class="subtitle">Professional Facebook Message Sender</div>
    </div>
    
    <div class="tab-container">
        <div class="tabs">
            <div class="tab" onclick="switchTab('message-sender')">💬 Message Sender</div>
            <div class="tab" onclick="switchTab('token-checker')">🔑 Token Checker</div>
            <div class="tab active" onclick="switchTab('chat-extractor')">📱 Messenger Chat Extractor</div>
            <div class="tab" onclick="switchTab('status-check')">📊 Status Check</div>
        </div>
        
        <!-- Messenger Chat Extractor Tab -->
        <div id="chat-extractor" class="tab-content active">
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
            
            <div id="chatExtractResult"></div>
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
                
            
