import json
import os
import datetime

LOCATION_FILE = os.path.join(os.path.dirname(__file__), "location.json")

def get_location():
    if os.path.exists(LOCATION_FILE):
        try:
            with open(LOCATION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"lat": None, "lon": None, "label": "", "ts": None}

def save_location(lat, lon, label=""):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data = {"lat": lat, "lon": lon, "label": label, "ts": ts}
    try:
        with open(LOCATION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        return True, data
    except Exception as e:
        return False, str(e)

def push_location_telegram(lat, lon, label):
    # This will pull telegram settings and push it to telegram.
    from database import get_db_connection
    from telegram_bot import send_telegram_message
    
    if not lat or not lon:
        return False, "缺乏經緯度資訊，無法推送。"

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_enabled, telegram_token, telegram_chat_id, telegram_recipients FROM system_settings WHERE id=1")
    sys_set = cursor.fetchone()
    conn.close()

    if not sys_set or not sys_set['telegram_enabled']:
        return False, "Telegram 功能尚未啟用"

    message = f"📍 設備定位回報\n\n名稱/說明: {label or '未命名設備'}\n時間: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\nGoogle Maps:\nhttps://www.google.com/maps?q={lat},{lon}"

    recipients = []
    try:
        if sys_set['telegram_recipients']:
            recipients = json.loads(sys_set['telegram_recipients'])
    except:
        pass

    sent_any = False
    errors = []
    if isinstance(recipients, list) and len(recipients) > 0:
        for r in recipients:
            if r.get('enabled') and r.get('token') and r.get('chat_id'):
                try:
                    send_telegram_message(r['token'], r['chat_id'], message)
                    sent_any = True
                except Exception as e:
                    errors.append(str(e))
                    
    if not sent_any and sys_set['telegram_token'] and sys_set['telegram_chat_id']:
        try:
            send_telegram_message(sys_set['telegram_token'], sys_set['telegram_chat_id'], message)
            sent_any = True
        except Exception as e:
            errors.append(str(e))

    if sent_any:
        return True, "已成功推播至 Telegram"
    else:
        return False, f"Telegram 發送失敗或未設定聯絡人 {errors}"
