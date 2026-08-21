import paho.mqtt.client as mqtt
import json
import ssl

def get_mqtt_client(host, port, user, password):
    try:
        client = mqtt.Client()
        if user and password:
            client.username_pw_set(user, password)
        
        # Use TLS for common secure ports
        if port in [8883, 8884]:
            import certifi
            client.tls_set(ca_certs=certifi.where(), tls_version=ssl.PROTOCOL_TLS)
            
        client.connect(host, port, 5)
        return client
    except Exception as e:
        print(f"MQTT Connect Error: {e}")
        return None

def publish_with_client(client, topic, data):
    if not client:
        return
    try:
        msg_info = client.publish(topic, json.dumps(data, ensure_ascii=False))
        msg_info.wait_for_publish(timeout=2)
    except Exception as e:
        print(f"MQTT Publish Error: {e}")
