import threading
import time
import json
import uuid
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    print("WARNING: RPi.GPIO module not found. GPIO functionality will be mocked (running on non-Pi OS).")
    GPIO_AVAILABLE = False

import paho.mqtt.client as mqtt

# Default Pins (BCM mode)
INPUT_PINS = [5, 6, 13, 19]
OUTPUT_PINS = [26, 16, 20, 21]

# Global state
gpio_state = {
    "inputs": {str(pin): 0 for pin in INPUT_PINS},
    "outputs": {str(pin): 0 for pin in OUTPUT_PINS}
}

mqtt_client = None

def init_gpio():
    if not GPIO_AVAILABLE:
        return
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    
    for pin in INPUT_PINS:
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    for pin in OUTPUT_PINS:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW) # default off

def read_inputs():
    changed = False
    if GPIO_AVAILABLE:
        for pin in INPUT_PINS:
            # PUD_UP implies inverted logic if active low. We will just read raw state.
            val = GPIO.input(pin)
            if gpio_state["inputs"].get(str(pin)) != val:
                gpio_state["inputs"][str(pin)] = val
                changed = True
    return changed

def write_output(pin: int, state: int):
    str_pin = str(pin)
    if str_pin in gpio_state["outputs"]:
        if GPIO_AVAILABLE:
            GPIO.output(pin, GPIO.HIGH if state else GPIO.LOW)
        gpio_state["outputs"][str_pin] = state
        publish_status()

def on_mqtt_connect(client, userdata, flags, rc):
    if rc == 0:
        mac = hex(uuid.getnode())[2:].upper()
        client.subscribe(f"{mac}/CTRL/#")
        # Also keep old topic for backward compatibility during transition
        client.subscribe("rs485_sys/gpio/set/#")
        publish_status()

def on_mqtt_message(client, userdata, msg):
    # Topic format: MAC/CTRL/26 or rs485_sys/gpio/set/26
    # Payload: "1" or "0"
    topic_parts = msg.topic.split('/')
    pin = None
    if len(topic_parts) >= 3 and topic_parts[1] == 'CTRL':
        pin = int(topic_parts[2])
    elif len(topic_parts) >= 4 and topic_parts[2] == 'set':
        pin = int(topic_parts[3])
        
    if pin is not None:
        try:
            val_str = msg.payload.decode('utf-8').strip().lower()
            if val_str in ['1', 'true', 'on']:
                val = 1
            else:
                val = 0
            write_output(pin, val)
        except Exception as e:
            print(f"GPIO MQTT Msg Error: {e}")

def publish_status():
    if mqtt_client:
        try:
            mac = hex(uuid.getnode())[2:].upper()
            payload = json.dumps(gpio_state, ensure_ascii=False)
            mqtt_client.publish(f"{mac}/STATUS", payload)
            # Old topic
            mqtt_client.publish("rs485_sys/gpio/status", payload)
        except Exception as e:
            pass

def gpio_polling_thread():
    init_gpio()
    last_publish = 0
    while True:
        changed = read_inputs()
        now = time.time()
        # Publish if state changed or every 5 seconds
        if changed or (now - last_publish > 5):
            publish_status()
            last_publish = now
        time.sleep(0.1)

def start_gpio_service(db_conn):
    # Fetch MQTT config from DB
    cursor = db_conn.cursor()
    cursor.execute("SELECT mqtt_host, mqtt_port, mqtt_user, mqtt_pass FROM system_settings LIMIT 1")
    row = cursor.fetchone()
    if not row:
        return
        
    host, port, user, password = row
    if not host:
        return
        
    global mqtt_client
    mqtt_client = mqtt.Client()
    if user and password:
        mqtt_client.username_pw_set(user, password)
        
    if port in [8883, 8884]:
        import certifi
        import ssl
        mqtt_client.tls_set(ca_certs=certifi.where(), tls_version=ssl.PROTOCOL_TLS)
    
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_message = on_mqtt_message
    
    try:
        mqtt_client.connect(host, port, 60)
        mqtt_client.loop_start()
    except Exception as e:
        print(f"GPIO MQTT Connect Error: {e}")
        
    t = threading.Thread(target=gpio_polling_thread, daemon=True)
    t.start()
