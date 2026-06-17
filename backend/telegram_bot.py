import requests
import socket
import psutil
import datetime
import getpass
import os

def send_telegram_message(token, chat_id, message):
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message
        }
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
    except Exception as e:
        print(f"Telegram Send Error: {e}")

def get_cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp = float(f.read()) / 1000.0
        return f"{temp:.1f}°C"
    except:
        return "N/A"

def get_mac_address():
    import uuid
    mac = uuid.getnode()
    return ':'.join(('%012X' % mac)[i:i+2] for i in range(0, 12, 2))

def send_boot_notification(token, chat_id):
    try:
        hostname = socket.gethostname()
        user = getpass.getuser()
        
        # Get internal IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            internal_ip = s.getsockname()[0]
        except:
            internal_ip = "Unknown"
        finally:
            s.close()
            
        # Get external IP
        try:
            external_ip = requests.get('https://api.ipify.org', timeout=3).text
        except:
            external_ip = "Unknown"
            
        mac = get_mac_address()
        cpu_temp = get_cpu_temp()
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage('/').percent
        
        # Boot time
        boot_time = datetime.datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")

        message = (
            "🟢 設備開機通知\n\n"
            f"📦 設備名稱 : {hostname}\n"
            f"👤 SSH User : {user}\n"
            f"🌐 內網IP : {internal_ip}\n"
            f"🌍 外網IP : {external_ip}\n"
            f"🏷️ MAC : {mac}\n\n"
            f"🌡️ CPU溫度 : {cpu_temp}\n"
            f"💾 RAM使用率 : {ram}%\n"
            f"💿 DISK使用率 : {disk}%\n\n"
            f"🕒 開機時間 :\n{boot_time}"
        )
        
        send_telegram_message(token, chat_id, message)
    except Exception as e:
        print(f"Failed to build boot notification: {e}")
