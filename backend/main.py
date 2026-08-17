from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel
from typing import List
import sqlite3
import os
import serial.tools.list_ports
import json
import subprocess
import csv
import psutil
import shutil
from datetime import datetime
from io import StringIO
from apscheduler.schedulers.background import BackgroundScheduler
from database import get_db_connection, init_db
from rs485_worker import poll_devices

app = FastAPI(title="RS485 Dashboard System")

scheduler = BackgroundScheduler()

# Function to update scheduler interval dynamically
def get_polling_interval():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT polling_interval FROM system_settings WHERE id=1")
        res = cursor.fetchone()
        conn.close()
        return res['polling_interval'] if res and res['polling_interval'] > 0 else 5
    except:
        return 5

def scheduled_job():
    poll_devices()

def check_and_reconnect_wifi():
    import platform, subprocess, time
    if platform.system() == "Windows":
        return
    # Wait a few seconds to let NetworkManager settle
    time.sleep(5)
    try:
        res = subprocess.check_output(['nmcli', '-t', '-f', 'ACTIVE', 'dev', 'wifi'], text=True)
        if 'yes' in res:
            return # Already connected
            
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT ssid, password FROM wifi_profiles WHERE is_auto_reconnect=1 ORDER BY last_connected_at DESC")
        profiles = cursor.fetchall()
        conn.close()
        
        for p in profiles:
            try:
                if p['password']:
                    subprocess.run(['nmcli', 'dev', 'wifi', 'connect', p['ssid'], 'password', p['password']], timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    subprocess.run(['nmcli', 'dev', 'wifi', 'connect', p['ssid']], timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
                res2 = subprocess.check_output(['nmcli', '-t', '-f', 'ACTIVE', 'dev', 'wifi'], text=True)
                if 'yes' in res2:
                    break
            except:
                pass
    except:
        pass

# Initialize database on startup
@app.on_event("startup")
def startup_event():
    init_db()
    
    import threading
    threading.Thread(target=check_and_reconnect_wifi, daemon=True).start()
    
    # Try to send boot notification if enabled
    try:
        from telegram_bot import send_boot_notification
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT telegram_enabled, telegram_boot_notify, telegram_token, telegram_chat_id, telegram_recipients FROM system_settings WHERE id=1")
        sys_set = cursor.fetchone()
        conn.close()
        
        if sys_set and sys_set['telegram_enabled'] and sys_set['telegram_boot_notify']:
            import json
            recipients = []
            try:
                recipients = json.loads(sys_set['telegram_recipients'] or '[]')
            except:
                pass
            
            sent_any = False
            if isinstance(recipients, list) and len(recipients) > 0:
                for r in recipients:
                    if r.get('enabled') and r.get('token') and r.get('chat_id'):
                        send_boot_notification(r['token'], r['chat_id'])
                        sent_any = True
                        
            if not sent_any:
                if sys_set['telegram_token'] and sys_set['telegram_chat_id']:
                    send_boot_notification(sys_set['telegram_token'], sys_set['telegram_chat_id'])
    except Exception as e:
        print(f"Failed to send boot notification: {e}")

    interval = get_polling_interval()
    scheduler.add_job(scheduled_job, 'interval', seconds=interval, id='poll_job')
    scheduler.start()

@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown()

# Mount frontend files
frontend_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'frontend')
os.makedirs(frontend_path, exist_ok=True)
app.mount("/static", StaticFiles(directory=frontend_path), name="static")

@app.get("/", response_class=HTMLResponse)
async def read_index():
    index_path = os.path.join(frontend_path, 'index.html')
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return "<h1>RS485 System Backend is Running</h1><p>index.html not found in frontend directory.</p>"

@app.get("/login", response_class=HTMLResponse)
async def read_login():
    login_path = os.path.join(frontend_path, 'login.html')
    if os.path.exists(login_path):
        return FileResponse(login_path)
    return "<h1>Login page not found</h1>"

@app.get("/settings", response_class=HTMLResponse)
async def read_settings(request: Request):
    if request.cookies.get("session_token") != "admin_session":
        return RedirectResponse(url="/login")
    settings_path = os.path.join(frontend_path, 'settings.html')
    if os.path.exists(settings_path):
        return FileResponse(settings_path)
    return "<h1>Settings page not found</h1>"

class LoginRequest(BaseModel):
    username: str
    password: str

class SaveConfigReq(BaseModel):
    name: str

@app.post("/api/login")
def login(req: LoginRequest, request: Request):
    from fastapi.responses import JSONResponse
    if req.username == "admin" and req.password == "cyc12345":
        res = JSONResponse(content={"status": "success", "message": "Login successful"})
        res.set_cookie(key="session_token", value="admin_session", httponly=False)
        return res
    return JSONResponse(status_code=401, content={"status": "error", "message": "Invalid username or password"})

# API to get system status (Time, CPU, Temp, Storage)
@app.get("/api/system_status")
def get_system_status():
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cpu_usage = psutil.cpu_percent(interval=None)
    
    total, used, free = shutil.disk_usage("/")
    storage_total_gb = total // (2**30)
    storage_used_gb = used // (2**30)
    storage_percent = round((used / total) * 100, 1) if total > 0 else 0
    storage_str = f"{storage_used_gb}GB / {storage_total_gb}GB ({storage_percent}%)"
    
    temp = "N/A"
    try:
        if os.path.exists('/sys/class/thermal/thermal_zone0/temp'):
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                t = int(f.read().strip()) / 1000.0
                temp = f"{t:.1f}°C"
        else:
            temps = psutil.sensors_temperatures()
            if temps and 'coretemp' in temps:
                t = temps['coretemp'][0].current
                temp = f"{t:.1f}°C"
    except Exception:
        pass

    return {
        "time": current_time,
        "cpu_usage": f"{cpu_usage}%",
        "storage": storage_str,
        "temperature": temp
    }

# API to scan COM ports
@app.get("/api/ports")
def scan_ports():
    ports = serial.tools.list_ports.comports()
    return [{"port": p.device, "description": p.description} for p in ports]

# API to get system settings
@app.get("/api/system_settings")
def get_system_settings():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM system_settings WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return {}

class SystemSettingsUpdate(BaseModel):
    mqtt_enabled: bool
    mqtt_host: str
    mqtt_port: int
    mqtt_user: str
    mqtt_pass: str
    mqtt_topic: str
    telegram_enabled: bool
    telegram_boot_notify: bool
    telegram_token: str
    telegram_chat_id: str
    telegram_recipients: str
    polling_interval: int
    serial_port: str
    simulation_mode: bool
    mqtt_upload_on_change: bool
    mqtt_upload_change_percent: float
    mqtt_upload_on_timer: bool
    mqtt_upload_interval: int
    mqtt_use_mac_prefix: bool
    serial_baudrate: int
    serial_bytesize: int
    serial_parity: str
    serial_stopbits: int

@app.post("/api/system_settings")
def update_system_settings(settings: SystemSettingsUpdate, request: Request):
    if request.cookies.get("session_token") != "admin_session":
        raise HTTPException(status_code=401, detail="Not authenticated")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE system_settings SET
            mqtt_enabled=?, mqtt_host=?, mqtt_port=?, mqtt_user=?, mqtt_pass=?, mqtt_topic=?,
            telegram_enabled=?, telegram_boot_notify=?, telegram_token=?, telegram_chat_id=?, telegram_recipients=?,
            polling_interval=?, serial_port=?, simulation_mode=?,
            mqtt_upload_on_change=?, mqtt_upload_change_percent=?, mqtt_upload_on_timer=?, mqtt_upload_interval=?, mqtt_use_mac_prefix=?,
            serial_baudrate=?, serial_bytesize=?, serial_parity=?, serial_stopbits=?
        WHERE id=1
    ''', (
        settings.mqtt_enabled, settings.mqtt_host, settings.mqtt_port, settings.mqtt_user, settings.mqtt_pass, settings.mqtt_topic,
        settings.telegram_enabled, settings.telegram_boot_notify, settings.telegram_token, settings.telegram_chat_id, settings.telegram_recipients,
        settings.polling_interval, settings.serial_port, settings.simulation_mode,
        settings.mqtt_upload_on_change, settings.mqtt_upload_change_percent, settings.mqtt_upload_on_timer, settings.mqtt_upload_interval, settings.mqtt_use_mac_prefix,
        settings.serial_baudrate, settings.serial_bytesize, settings.serial_parity, settings.serial_stopbits
    ))
    conn.commit()
    conn.close()
    return {"status": "success"}

class DeviceModel(BaseModel):
    id: int = None
    slave_id: int
    register_address: int = 0
    register_count: int = 1
    irat: float = 1.0
    urat: float = 1.0

class GroupUpdate(BaseModel):
    id: int
    name: str
    is_enabled: bool
    command: str
    parse_method: str
    limit_min: float
    limit_max: float
    command_name: str = ""
    devices: List[DeviceModel]

class CommandItemModel(BaseModel):
    id: int = None
    name: str
    command: str
    parse_method: str
    register_address: int
    register_count: int

# API to get RS485 Commands
@app.get("/api/rs485_commands")
def get_rs485_commands():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM rs485_commands")
    commands = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return commands

@app.post("/api/rs485_commands")
def update_rs485_commands(commands: List[CommandItemModel], request: Request):
    if request.cookies.get("session_token") != "admin_session":
        raise HTTPException(status_code=401, detail="Not authenticated")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM rs485_commands")
    for cmd in commands:
        # Avoid passing id if it is None (new command) so it auto-increments
        if cmd.id is not None:
            cursor.execute('''
                INSERT INTO rs485_commands (id, name, command, parse_method, register_address, register_count)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (cmd.id, cmd.name, cmd.command, cmd.parse_method, cmd.register_address, cmd.register_count))
        else:
            cursor.execute('''
                INSERT INTO rs485_commands (name, command, parse_method, register_address, register_count)
                VALUES (?, ?, ?, ?, ?)
            ''', (cmd.name, cmd.command, cmd.parse_method, cmd.register_address, cmd.register_count))
    conn.commit()
    conn.close()
    return {"status": "success"}

class TestConnectionRequest(BaseModel):
    test_type: str
    settings: SystemSettingsUpdate

@app.post("/api/test_connection")
def test_connection(req: TestConnectionRequest, request: Request):
    if request.cookies.get("session_token") != "admin_session":
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    test_type = req.test_type
    settings = req.settings

    if test_type == "serial":
        try:
            import serial
            s = serial.Serial(
                settings.serial_port, 
                baudrate=settings.serial_baudrate, 
                bytesize=settings.serial_bytesize, 
                parity=settings.serial_parity, 
                stopbits=settings.serial_stopbits, 
                timeout=1
            )
            s.close()
            return {"status": "success", "message": f"Serial port {settings.serial_port} opened successfully."}
        except Exception as e:
            return JSONResponse(status_code=400, content={"status": "error", "message": f"Serial Error: {str(e)}"})
            
    elif test_type == "mqtt":
        try:
            import paho.mqtt.client as mqtt
            import time
            import ssl
            import datetime
            client = mqtt.Client()
            if settings.mqtt_user and settings.mqtt_pass:
                client.username_pw_set(settings.mqtt_user, settings.mqtt_pass)
            
            # Use TLS for secure ports
            if settings.mqtt_port in [8883, 8884]:
                import certifi
                client.tls_set(ca_certs=certifi.where(), tls_version=ssl.PROTOCOL_TLS)
            
            # Simple synchronous connect to test
            client.connect(settings.mqtt_host, settings.mqtt_port, 5)
            client.loop_start()
            
            # Wait for CONNACK and TLS handshake to complete
            time.sleep(1)
            
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            payload = f'{{"status": "test_ok", "time": "{timestamp}"}}'
            
            import uuid
            
            base_topic = settings.mqtt_topic
            if settings.mqtt_use_mac_prefix:
                mac = hex(uuid.getnode())[2:].upper()
                if base_topic:
                    base_topic = f"{mac}/{base_topic}"
                else:
                    base_topic = mac
            
            topic = (base_topic + "/test") if base_topic else "test"
            if topic.startswith("/"):
                topic = topic[1:] # avoid empty level
                
            msg_info = client.publish(topic, payload, qos=1)
            msg_info.wait_for_publish(timeout=3)
            
            time.sleep(0.5) # Allow network buffers to flush
            client.disconnect()
            client.loop_stop()
            return {"status": "success", "message": "MQTT connected and test message sent."}
        except Exception as e:
            return JSONResponse(status_code=400, content={"status": "error", "message": f"MQTT Error: {str(e)}"})
            
    elif test_type == "telegram":
        try:
            import requests
            import json
            recipients = []
            try:
                recipients = json.loads(settings.telegram_recipients or '[]')
            except:
                pass
            
            sent_any = False
            errors = []
            if isinstance(recipients, list) and len(recipients) > 0:
                for r in recipients:
                    if r.get('enabled') and r.get('token') and r.get('chat_id'):
                        url = f"https://api.telegram.org/bot{r.get('token')}/sendMessage"
                        payload = {
                            "chat_id": r.get('chat_id'),
                            "text": f"🔔 [測試] 系統通訊測試成功！\n\n聯絡人: {r.get('name') or '未命名'}\n您的 RS485 儀表板已經可以正常發送推播通知。"
                        }
                        resp = requests.post(url, json=payload, timeout=5)
                        if resp.status_code == 200:
                            sent_any = True
                        else:
                            errors.append(f"{r.get('name') or 'Unnamed'}: {resp.text}")
            
            if not sent_any:
                if settings.telegram_token and settings.telegram_chat_id:
                    url = f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage"
                    payload = {
                        "chat_id": settings.telegram_chat_id,
                        "text": "🔔 [測試] 系統通訊測試成功！\n\n您的 RS485 儀表板已經可以正常發送推播通知。"
                    }
                    resp = requests.post(url, json=payload, timeout=5)
                    if resp.status_code == 200:
                        sent_any = True
                    else:
                        errors.append(f"Legacy: {resp.text}")
            
            if sent_any:
                msg = "Telegram message sent successfully."
                if errors:
                    msg += " Errors: " + "; ".join(errors)
                return {"status": "success", "message": msg}
            else:
                return JSONResponse(status_code=400, content={"status": "error", "message": f"Telegram API Error: {'; '.join(errors) if errors else 'No active recipients configured.'}"})
        except Exception as e:
            return JSONResponse(status_code=400, content={"status": "error", "message": f"Telegram Error: {str(e)}"})
            
    return JSONResponse(status_code=400, content={"status": "error", "message": "Unknown test type."})

# API to get RS485 Groups
@app.get("/api/rs485_groups")
def get_rs485_groups():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM rs485_groups")
    groups = [dict(row) for row in cursor.fetchall()]
    
    for g in groups:
        cursor.execute("SELECT * FROM rs485_devices WHERE group_id=?", (g['id'],))
        g['devices'] = [{
            "id": d["id"], 
            "slave_id": d["slave_id"],
            "register_address": d["register_address"],
            "register_count": d["register_count"],
            "irat": d["irat"] if "irat" in d.keys() else 1.0,
            "urat": d["urat"] if "urat" in d.keys() else 1.0
        } for d in cursor.fetchall()]
    conn.close()
    return groups

@app.post("/api/rs485_groups")
def update_rs485_group(group: GroupUpdate, request: Request):
    if request.cookies.get("session_token") != "admin_session":
        raise HTTPException(status_code=401, detail="Not authenticated")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE rs485_groups SET
        name=?, is_enabled=?, command=?, parse_method=?, limit_min=?, limit_max=?, command_name=?
        WHERE id=?
    ''', (group.name, group.is_enabled, group.command, group.parse_method, group.limit_min, group.limit_max, group.command_name, group.id))
    
    cursor.execute("DELETE FROM rs485_devices WHERE group_id=?", (group.id,))
    for dev in group.devices:
        cursor.execute('''
            INSERT INTO rs485_devices (group_id, slave_id, register_address, register_count, irat, urat)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (group.id, dev.slave_id, dev.register_address, dev.register_count, dev.irat, dev.urat))
        
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.post("/api/test_rs485_group")
def test_rs485_group(group: GroupUpdate, request: Request):
    if request.cookies.get("session_token") != "admin_session":
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not group.devices:
        return JSONResponse(status_code=400, content={"status": "error", "message": "此群組沒有設定任何設備"})
        
    dev = group.devices[0] # Test the first device
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT serial_port, serial_baudrate, serial_bytesize, serial_parity, serial_stopbits FROM system_settings WHERE id=1")
    sys_set = cursor.fetchone()
    conn.close()
    
    if not sys_set or not sys_set['serial_port']:
        return JSONResponse(status_code=400, content={"status": "error", "message": "尚未設定 Serial Port"})
        
    from pymodbus.client import ModbusSerialClient
    from rs485_worker import parse_payload
    
    client = None
    try:
        try:
            client = ModbusSerialClient(
                port=sys_set['serial_port'], 
                baudrate=sys_set['serial_baudrate'], 
                bytesize=sys_set['serial_bytesize'], 
                parity=sys_set['serial_parity'], 
                stopbits=sys_set['serial_stopbits'], 
                timeout=1
            )
        except TypeError:
            # Fallback for older pymodbus versions
            client = ModbusSerialClient(
                method='rtu', 
                port=sys_set['serial_port'], 
                baudrate=sys_set['serial_baudrate'], 
                bytesize=sys_set['serial_bytesize'], 
                parity=sys_set['serial_parity'], 
                stopbits=sys_set['serial_stopbits'], 
                timeout=1
            )
            
        if not client.connect():
            return JSONResponse(status_code=400, content={"status": "error", "message": f"無法開啟 {sys_set['serial_port']}"})
            
        result = None
        if group.command == 'read_holding_registers':
            try:
                result = client.read_holding_registers(address=dev.register_address, count=dev.register_count, device_id=dev.slave_id)
            except TypeError:
                try:
                    result = client.read_holding_registers(address=dev.register_address, count=dev.register_count, slave=dev.slave_id)
                except TypeError:
                    result = client.read_holding_registers(address=dev.register_address, count=dev.register_count, unit=dev.slave_id)
        elif group.command == 'read_input_registers':
            try:
                result = client.read_input_registers(address=dev.register_address, count=dev.register_count, device_id=dev.slave_id)
            except TypeError:
                try:
                    result = client.read_input_registers(address=dev.register_address, count=dev.register_count, slave=dev.slave_id)
                except TypeError:
                    result = client.read_input_registers(address=dev.register_address, count=dev.register_count, unit=dev.slave_id)
        else:
            return JSONResponse(status_code=400, content={"status": "error", "message": f"不支援的指令: {group.command}"})
            
        if result and not result.isError():
            val = parse_payload(result.registers, group.parse_method, dev.irat, dev.urat)
            return {"status": "success", "message": "連線測試成功", "data": val, "raw": result.registers}
        else:
            return JSONResponse(status_code=400, content={"status": "error", "message": "連線逾時或設備無回應 (Modbus Error)"})
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})
    finally:
        if client:
            client.close()

# --- Advanced Wi-Fi Management ---
@app.get("/api/wifi/status")
def get_wifi_status():
    import platform
    if platform.system() == "Windows":
        return {
            "ssid": "Mock_Windows_Network",
            "signal": "80%",
            "ip": "192.168.0.100",
            "interface": "wlan0"
        }
    else:
        try:
            # Check current connection using nmcli
            res = subprocess.check_output(['nmcli', '-t', '-f', 'ACTIVE,SSID,SIGNAL,DEVICE', 'dev', 'wifi'], text=True)
            for line in res.strip().split('\n'):
                if line.startswith('yes:'):
                    parts = line.split(':')
                    if len(parts) >= 4:
                        ssid = parts[1].strip()
                        signal = parts[2].strip() + "%"
                        device = parts[3].strip()
                        
                        # Get IP
                        ip_res = subprocess.check_output(['ip', '-4', 'addr', 'show', device], text=True)
                        ip = "N/A"
                        for ip_line in ip_res.split('\n'):
                            if "inet " in ip_line:
                                ip = ip_line.split()[1].split('/')[0]
                                break
                        return {
                            "ssid": ssid,
                            "signal": signal,
                            "ip": ip,
                            "interface": device
                        }
            return {"ssid": "", "signal": "", "ip": "", "interface": ""}
        except Exception as e:
            return {"error": str(e)}

@app.get("/api/wifi/scan")
def scan_wifi():
    import platform
    if platform.system() == "Windows":
        try:
            res = subprocess.check_output(['netsh', 'wlan', 'show', 'networks'], encoding='cp950', errors='ignore')
            ssids = []
            for line in res.split('\n'):
                if "SSID" in line and ":" in line:
                    ssid = line.split(":", 1)[1].strip()
                    if ssid:
                        ssids.append({"ssid": ssid, "signal": "N/A", "security": "WPA2"})
            return ssids
        except:
            return [{"ssid": "Mock_WiFi_1", "signal": "80%", "security": "WPA2"}, {"ssid": "Mock_WiFi_2", "signal": "60%", "security": "WPA3"}]
    else:
        try:
            try:
                subprocess.run(['nmcli', 'dev', 'wifi', 'rescan'], timeout=5)
            except:
                pass
            res = subprocess.check_output(['nmcli', '-t', '-f', 'SSID,SIGNAL,SECURITY', 'dev', 'wifi'], text=True)
            ssids = []
            for line in res.strip().split('\n'):
                if line:
                    parts = line.split(':')
                    if len(parts) >= 3:
                        ssid = parts[0].replace('\\:', ':').strip()
                        if ssid:
                            ssids.append({
                                "ssid": ssid, 
                                "signal": parts[1].strip() + "%",
                                "security": parts[2].strip()
                            })
            # deduplicate by SSID
            unique_ssids = {v['ssid']:v for v in ssids}.values()
            return list(unique_ssids)
        except Exception as e:
            return [{"error": str(e)}]

@app.get("/api/wifi/profiles")
def get_wifi_profiles():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM wifi_profiles ORDER BY last_connected_at DESC")
        profiles = [dict(row) for row in cursor.fetchall()]
    except Exception:
        profiles = []
    finally:
        conn.close()
    return profiles

class WifiConnectRequest(BaseModel):
    ssid: str
    password: str

@app.post("/api/wifi/connect")
def connect_wifi(req: WifiConnectRequest, request: Request):
    if request.cookies.get("session_token") != "admin_session":
        raise HTTPException(status_code=401, detail="Not authenticated")
    import platform
    
    # Save/Update in DB
    conn = get_db_connection()
    cursor = conn.cursor()
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("SELECT id, password FROM wifi_profiles WHERE ssid=?", (req.ssid,))
    row = cursor.fetchone()
    
    actual_password = req.password
    if row:
        if not actual_password and row['password']:
            actual_password = row['password']
            
        if req.password:
            cursor.execute("UPDATE wifi_profiles SET password=?, last_connected_at=? WHERE id=?", (req.password, current_time, row['id']))
        else:
            cursor.execute("UPDATE wifi_profiles SET last_connected_at=? WHERE id=?", (current_time, row['id']))
    else:
        cursor.execute("INSERT INTO wifi_profiles (ssid, password, is_auto_reconnect, last_connected_at) VALUES (?, ?, 1, ?)", 
                       (req.ssid, req.password, current_time))
    conn.commit()
    conn.close()

    if platform.system() == "Windows":
        return {"status": "success", "message": f"Windows 模擬: 已儲存 {req.ssid} 並嘗試連線"}
    else:
        try:
            # Delete old connection profile to avoid conflict (e.g. 'property is missing' error from previous failed attempts)
            try:
                subprocess.run(['nmcli', 'connection', 'delete', req.ssid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except:
                pass

            if actual_password:
                cmd = ['nmcli', 'dev', 'wifi', 'connect', req.ssid, 'password', actual_password]
            else:
                cmd = ['nmcli', 'dev', 'wifi', 'connect', req.ssid]
                
            res = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
            return {"status": "success", "message": "連線成功", "details": res.strip()}
        except subprocess.CalledProcessError as e:
            err_output = e.output.strip()
            if "Secrets were required" in err_output or "802-11-wireless-security.psk" in err_output:
                return JSONResponse(status_code=400, content={"status": "error", "message": "密碼錯誤，或是未提供密碼！請確認密碼是否正確。", "details": err_output})
            return JSONResponse(status_code=400, content={"status": "error", "message": "連線失敗", "details": err_output})
        except Exception as e:
            return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})

class ToggleAutoRequest(BaseModel):
    is_auto_reconnect: bool

@app.post("/api/wifi/profiles/{id}/toggle_auto")
def toggle_wifi_auto(id: int, req: ToggleAutoRequest, request: Request):
    if request.cookies.get("session_token") != "admin_session":
        raise HTTPException(status_code=401, detail="Not authenticated")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE wifi_profiles SET is_auto_reconnect=? WHERE id=?", (req.is_auto_reconnect, id))
    
    # Also attempt to update nmcli connection if Linux
    import platform
    if platform.system() != "Windows":
        cursor.execute("SELECT ssid FROM wifi_profiles WHERE id=?", (id,))
        row = cursor.fetchone()
        if row:
            auto_val = 'yes' if req.is_auto_reconnect else 'no'
            try:
                subprocess.run(['nmcli', 'connection', 'modify', row['ssid'], 'connection.autoconnect', auto_val])
            except:
                pass
                
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.delete("/api/wifi/profiles/{id}")
def delete_wifi_profile(id: int, request: Request):
    if request.cookies.get("session_token") != "admin_session":
        raise HTTPException(status_code=401, detail="Not authenticated")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT ssid FROM wifi_profiles WHERE id=?", (id,))
    row = cursor.fetchone()
    
    if row:
        ssid = row['ssid']
        cursor.execute("DELETE FROM wifi_profiles WHERE id=?", (id,))
        conn.commit()
        
        import platform
        if platform.system() != "Windows":
            try:
                subprocess.run(['nmcli', 'connection', 'delete', ssid])
            except:
                pass
    conn.close()
    return {"status": "success"}

# API to get historical data for a device
@app.get("/api/history/{device_id}")
def get_device_history(device_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT timestamp, value FROM historical_data
        WHERE device_id=? ORDER BY timestamp DESC LIMIT 100
    ''', (device_id,))
    rows = cursor.fetchall()
    conn.close()
    # Return ascending order for charts
    return [{"timestamp": row['timestamp'], "value": row['value']} for row in reversed(rows)]

# API to download CSV
from fastapi.responses import StreamingResponse
@app.get("/api/history/download/{device_id}")
def download_device_history(device_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT timestamp, value FROM historical_data
        WHERE device_id=? ORDER BY timestamp DESC LIMIT 10000
    ''', (device_id,))
    rows = cursor.fetchall()
    conn.close()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Timestamp", "Value"])
    for row in rows:
        writer.writerow([row['timestamp'], row['value']])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=device_{device_id}_history.csv"}
    )

@app.post("/api/system/reboot")
def reboot_system(request: Request):
    if request.cookies.get("session_token") != "admin_session":
        raise HTTPException(status_code=401, detail="Not authenticated")
    import platform
    import subprocess
    import threading
    import time
    
    if platform.system() == "Windows":
        return {"status": "success", "message": "[Windows 模擬環境] 重新開機指令已觸發，但在此環境下不會實際執行。"}
        
    def do_reboot():
        time.sleep(2) # Wait a bit to allow the HTTP response to be sent
        subprocess.run(['reboot'])
        
    threading.Thread(target=do_reboot, daemon=True).start()
    return {"status": "success", "message": "系統即將在幾秒後重新開機，請稍候約 1 分鐘再重新整理網頁。"}

@app.get("/api/ports")
def get_ports(request: Request):
    if request.cookies.get("session_token") != "admin_session":
        raise HTTPException(status_code=401, detail="Not authenticated")
    import serial.tools.list_ports
    ports = serial.tools.list_ports.comports()
    port_list = [{"port": p.device, "description": p.description} for p in ports]
    
    # 為了像 Node-RED 一樣內建支援樹莓派 GPIO Serial，我們手動將常見的實體埠加入清單
    import platform
    import os
    if platform.system() == "Linux":
        pi_ports = [
            {"port": "/dev/serial0", "description": "Raspberry Pi UART (Default)"},
            {"port": "/dev/ttyS0", "description": "Raspberry Pi Mini UART"},
            {"port": "/dev/ttyAMA0", "description": "Raspberry Pi Hardware UART"}
        ]
        existing_ports = [p["port"] for p in port_list]
        for pp in pi_ports:
            if os.path.exists(pp["port"]) and pp["port"] not in existing_ports:
                port_list.append(pp)
                
    return port_list

@app.get("/api/system_logs")
def get_system_logs(request: Request):
    if request.cookies.get("session_token") != "admin_session":
        raise HTTPException(status_code=401, detail="Not authenticated")
    import platform
    import subprocess
    
    if platform.system() == "Windows":
        return {"status": "success", "logs": "[Windows 模擬環境]\n系統記錄功能僅在樹莓派環境 (Linux systemd) 完整支援。\n此為模擬日誌輸出...\nSystem Boot OK\nRS485 Polling Started..."}
        
    try:
        # Fetch the last 200 lines from the systemd service
        res = subprocess.check_output(
            ['journalctl', '-u', 'rs485_dashboard.service', '-n', '200', '--no-pager'],
            text=True, stderr=subprocess.STDOUT
        )
        return {"status": "success", "logs": res.strip()}
    except Exception as e:
        return {"status": "error", "logs": f"無法取得系統日誌: {str(e)}"}

@app.get("/api/configs")
def get_configs(request: Request):
    if request.cookies.get("session_token") != "admin_session":
        raise HTTPException(status_code=401, detail="Not authenticated")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, created_at FROM saved_configs ORDER BY created_at DESC")
    configs = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return configs

@app.post("/api/configs")
def save_config(req: SaveConfigReq, request: Request):
    if request.cookies.get("session_token") != "admin_session":
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 讀取所有設定
    cursor.execute("SELECT * FROM system_settings WHERE id=1")
    sys_settings = dict(cursor.fetchone())
    
    cursor.execute("SELECT * FROM rs485_commands")
    commands = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM rs485_groups")
    groups = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM rs485_devices")
    devices = [dict(r) for r in cursor.fetchall()]
    
    config_data = json.dumps({
        "system_settings": sys_settings,
        "rs485_commands": commands,
        "rs485_groups": groups,
        "rs485_devices": devices
    }, ensure_ascii=False)
    
    cursor.execute("INSERT INTO saved_configs (name, config_data) VALUES (?, ?)", (req.name, config_data))
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.post("/api/configs/{id}/load")
def load_config(id: int, request: Request):
    if request.cookies.get("session_token") != "admin_session":
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT config_data FROM saved_configs WHERE id=?", (id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Config not found")
        
    data = json.loads(row['config_data'])
    
    # 清空現有設定
    cursor.execute("DELETE FROM rs485_devices")
    cursor.execute("DELETE FROM rs485_groups")
    cursor.execute("DELETE FROM rs485_commands")
    
    # 寫入 system_settings
    if 'system_settings' in data:
        ss = data['system_settings']
        fields = ', '.join([f"{k}=?" for k in ss.keys() if k != 'id'])
        values = [ss[k] for k in ss.keys() if k != 'id']
        values.append(1) # id=1
        cursor.execute(f"UPDATE system_settings SET {fields} WHERE id=?", values)
        
    # 寫入 rs485_commands
    if 'rs485_commands' in data:
        for cmd in data['rs485_commands']:
            keys = [k for k in cmd.keys() if k != 'id']
            cols = ', '.join(keys)
            placeholders = ', '.join(['?' for _ in keys])
            vals = [cmd[k] for k in keys]
            cursor.execute(f"INSERT INTO rs485_commands ({cols}) VALUES ({placeholders})", vals)
            
    # 寫入 rs485_groups
    if 'rs485_groups' in data:
        for g in data['rs485_groups']:
            keys = [k for k in g.keys()]
            cols = ', '.join(keys)
            placeholders = ', '.join(['?' for _ in keys])
            vals = [g[k] for k in keys]
            cursor.execute(f"INSERT INTO rs485_groups ({cols}) VALUES ({placeholders})", vals)
            
    # 寫入 rs485_devices
    if 'rs485_devices' in data:
        for d in data['rs485_devices']:
            keys = [k for k in d.keys()]
            cols = ', '.join(keys)
            placeholders = ', '.join(['?' for _ in keys])
            vals = [d[k] for k in keys]
            cursor.execute(f"INSERT INTO rs485_devices ({cols}) VALUES ({placeholders})", vals)

    conn.commit()
    conn.close()
    
    # 重新載入排程器與 polling interval
    scheduler.reschedule_job('poll_job', trigger='interval', seconds=get_polling_interval())
    
    return {"status": "success", "message": "設定檔已成功載入"}

@app.delete("/api/configs/{id}")
def delete_config(id: int, request: Request):
    if request.cookies.get("session_token") != "admin_session":
        raise HTTPException(status_code=401, detail="Not authenticated")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM saved_configs WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return {"status": "success"}

# --- Tailscale Management ---
@app.get("/api/tailscale/status")
def get_tailscale_status():
    import platform, subprocess
    if platform.system() == "Windows":
        return {"installed": False, "status": "Not installed", "ip": ""}
        
    try:
        subprocess.run(['which', 'tailscale'], check=True, stdout=subprocess.DEVNULL)
    except:
        return {"installed": False, "status": "未安裝", "ip": ""}
        
    try:
        res = subprocess.check_output(['tailscale', 'status', '--json'], text=True)
        import json
        ts_data = json.loads(res)
        state = ts_data.get('BackendState', '')
        if state == "Running":
            ip = ""
            try:
                ip = subprocess.check_output(['tailscale', 'ip', '-4'], text=True).strip()
            except:
                pass
            return {"installed": True, "status": "已連線 (Running)", "ip": ip}
        else:
            return {"installed": True, "status": f"未連線 ({state})", "ip": ""}
    except Exception as e:
        return {"installed": True, "status": "無法取得狀態", "ip": ""}

@app.post("/api/tailscale/install")
def install_tailscale(request: Request):
    if request.cookies.get("session_token") != "admin_session":
        raise HTTPException(status_code=401, detail="Not authenticated")
    import platform, subprocess
    if platform.system() == "Windows":
        return {"status": "error", "message": "Windows 環境不支援自動安裝 Tailscale"}
        
    try:
        subprocess.Popen(['bash', '-c', 'curl -fsSL https://tailscale.com/install.sh | sh'])
        return {"status": "success", "message": "Tailscale 安裝腳本已在背景啟動，請稍等 1~3 分鐘後重新整理頁面。"}
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})

class TailscaleUpRequest(BaseModel):
    auth_key: str

@app.post("/api/tailscale/up")
def tailscale_up(req: TailscaleUpRequest, request: Request):
    if request.cookies.get("session_token") != "admin_session":
        raise HTTPException(status_code=401, detail="Not authenticated")
    import subprocess
    try:
        cmd = ['sudo', '-S', 'tailscale', 'up']
        if req.auth_key:
            cmd.extend(['--authkey', req.auth_key])
            
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out, err = process.communicate(input="cyc12345\n")
        
        if process.returncode == 0:
            return {"status": "success", "message": "Tailscale 已啟動連線"}
        else:
            return JSONResponse(status_code=400, content={"status": "error", "message": f"啟動失敗: {err}"})
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})

@app.post("/api/tailscale/down")
def tailscale_down(request: Request):
    if request.cookies.get("session_token") != "admin_session":
        raise HTTPException(status_code=401, detail="Not authenticated")
    import subprocess
    try:
        process = subprocess.Popen(['sudo', '-S', 'tailscale', 'down'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        process.communicate(input="cyc12345\n")
        return {"status": "success", "message": "Tailscale 已斷線"}
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})

@app.post("/api/tailscale/uninstall")
def uninstall_tailscale(request: Request):
    if request.cookies.get("session_token") != "admin_session":
        raise HTTPException(status_code=401, detail="Not authenticated")
    import subprocess
    try:
        process = subprocess.Popen(['sudo', '-S', 'apt-get', 'remove', '--purge', 'tailscale', '-y'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        process.communicate(input="cyc12345\n")
        return {"status": "success", "message": "Tailscale 移除程序已在背景啟動。"}
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
