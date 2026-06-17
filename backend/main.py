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

# Initialize database on startup
@app.on_event("startup")
def startup_event():
    init_db()
    
    # Try to send boot notification if enabled
    try:
        from telegram_bot import send_boot_notification
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT telegram_enabled, telegram_boot_notify, telegram_token, telegram_chat_id FROM system_settings WHERE id=1")
        sys_set = cursor.fetchone()
        conn.close()
        
        if sys_set and sys_set['telegram_enabled'] and sys_set['telegram_boot_notify'] and sys_set['telegram_token'] and sys_set['telegram_chat_id']:
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
    polling_interval: int
    serial_port: str
    simulation_mode: bool
    mqtt_upload_on_change: bool
    mqtt_upload_change_percent: float
    mqtt_upload_on_timer: bool
    mqtt_upload_interval: int

@app.post("/api/system_settings")
def update_system_settings(settings: SystemSettingsUpdate, request: Request):
    if request.cookies.get("session_token") != "admin_session":
        raise HTTPException(status_code=401, detail="Not authenticated")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE system_settings SET
            mqtt_enabled=?, mqtt_host=?, mqtt_port=?, mqtt_user=?, mqtt_pass=?, mqtt_topic=?,
            telegram_enabled=?, telegram_boot_notify=?, telegram_token=?, telegram_chat_id=?,
            polling_interval=?, serial_port=?, simulation_mode=?,
            mqtt_upload_on_change=?, mqtt_upload_change_percent=?, mqtt_upload_on_timer=?, mqtt_upload_interval=?
        WHERE id=1
    ''', (
        settings.mqtt_enabled, settings.mqtt_host, settings.mqtt_port, settings.mqtt_user, settings.mqtt_pass, settings.mqtt_topic,
        settings.telegram_enabled, settings.telegram_boot_notify, settings.telegram_token, settings.telegram_chat_id,
        settings.polling_interval, settings.serial_port, settings.simulation_mode,
        settings.mqtt_upload_on_change, settings.mqtt_upload_change_percent, settings.mqtt_upload_on_timer, settings.mqtt_upload_interval
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
            s = serial.Serial(settings.serial_port, 9600, timeout=1)
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
                client.tls_set(tls_version=ssl.PROTOCOL_TLS)
            
            # Simple synchronous connect to test
            client.connect(settings.mqtt_host, settings.mqtt_port, 5)
            client.loop_start()
            
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            payload = f'{{"status": "test_ok", "time": "{timestamp}"}}'
            msg_info = client.publish(settings.mqtt_topic + "/test", payload)
            msg_info.wait_for_publish(timeout=2)
            
            client.disconnect()
            client.loop_stop()
            return {"status": "success", "message": "MQTT connected and test message sent."}
        except Exception as e:
            return JSONResponse(status_code=400, content={"status": "error", "message": f"MQTT Error: {str(e)}"})
            
    elif test_type == "telegram":
        try:
            import requests
            url = f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage"
            payload = {
                "chat_id": settings.telegram_chat_id,
                "text": "🔔 系統通訊測試成功！\n\n您的 RS485 儀表板已經可以正常發送推播通知。"
            }
            resp = requests.post(url, json=payload, timeout=5)
            if resp.status_code == 200:
                return {"status": "success", "message": "Telegram message sent successfully."}
            else:
                return JSONResponse(status_code=400, content={"status": "error", "message": f"Telegram API Error: {resp.text}"})
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

# API to scan Wi-Fi
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
                        ssids.append({"ssid": ssid, "signal": "N/A"})
            return ssids
        except:
            return [{"ssid": "Mock_WiFi_1", "signal": "80%"}, {"ssid": "Mock_WiFi_2", "signal": "60%"}]
    else:
        try:
            # Try to force rescan if possible (might fail without sudo, but we try anyway)
            try:
                subprocess.run(['nmcli', 'dev', 'wifi', 'rescan'], timeout=5)
            except:
                pass

            res = subprocess.check_output(['nmcli', '-t', '-f', 'SSID,SIGNAL', 'dev', 'wifi'], text=True)
            ssids = []
            for line in res.strip().split('\n'):
                if line:
                    parts = line.rsplit(':', 1)
                    if len(parts) == 2:
                        ssid = parts[0].replace('\\:', ':').strip()
                        if ssid:
                            ssids.append({"ssid": ssid, "signal": parts[1].strip() + "%"})
            unique_ssids = {v['ssid']:v for v in ssids}.values()
            return list(unique_ssids)
        except Exception as e:
            return [{"error": str(e)}]

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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
