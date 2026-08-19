import time
import random
import sqlite3
import struct
import json
from pymodbus.client import ModbusSerialClient
from database import get_db_connection
from telegram_bot import send_telegram_message

import threading

# Global lock to prevent concurrent Modbus access
rs485_lock = threading.Lock()

# Global cache for MQTT advanced upload logic
last_mqtt_upload_time = {}
last_mqtt_upload_value = {}

def generate_mock_registers(parse_method, count):
    if parse_method == 'ph_sensor': 
        return [random.randint(600, 800)]
    if parse_method == 'ec_sensor': 
        return [random.randint(100, 500), random.randint(200, 300)]
    if parse_method == 'orp_sensor': 
        return [random.randint(100, 300)]
    if parse_method == 'do_sensor':
        b = struct.pack('<ff', random.uniform(5.0, 8.0), random.uniform(20.0, 30.0))
        return list(struct.unpack('>HHHH', b))
    if parse_method == 'flowmeter_net_flow':
        b = struct.pack('>f', random.uniform(10.0, 1000.0))
        return list(struct.unpack('>HH', b))
    if parse_method == 'flowmeter_temps':
        b = struct.pack('>ff', random.uniform(20.0, 30.0), random.uniform(15.0, 25.0))
        return list(struct.unpack('>HHHH', b))
    if parse_method and parse_method.startswith('pd666_'):
        n_floats = max(1, count // 2)
        b = struct.pack('>' + 'f'*n_floats, *[random.uniform(50.0, 250.0) for _ in range(n_floats)])
        return list(struct.unpack('>' + 'H'*count, b))
    if parse_method and 'float32' in parse_method:
        b = struct.pack('>f', random.uniform(10.0, 100.0))
        return list(struct.unpack('>HH', b))
    return [random.randint(100, 999) for _ in range(count)]

def parse_payload(registers, parse_method, irat=1.0, urat=1.0):
    import json
    try:
        if not registers:
            return None
        
        # Simple int16 (1 register)
        if parse_method == 'int16':
            val = registers[0]
            if val > 32767:
                val -= 65536
            return val
            
        # Int16 divided by 10 (for Temperature sensors)
        elif parse_method == 'int16_div10':
            val = registers[0]
            if val > 32767:
                val -= 65536
            return val / 10.0
            
        # Unsigned int16 (1 register)
        elif parse_method == 'uint16':
            return registers[0]
            
        # Float32 (2 registers, big endian)
        elif parse_method == 'float32_be':
            if len(registers) < 2: return None
            b = struct.pack('>HH', registers[0], registers[1])
            return struct.unpack('>f', b)[0]
            
        # Float32 (2 registers, little endian byte swap)
        elif parse_method == 'float32_le':
            if len(registers) < 2: return None
            b = struct.pack('<HH', registers[0], registers[1])
            return struct.unpack('<f', b)[0]
            
        # Float32 CDAB (Word Swap), convert to L/min (for flow meters)
        elif parse_method == 'float32_cdab_lmin':
            if len(registers) < 2: return None
            b = struct.pack('>HH', registers[1], registers[0])
            q = struct.unpack('>f', b)[0]
            if q < 0 or q > 1000:
                return None
            l_min = q * 1000.0 / 60.0
            return round(l_min, 4)
            
        # PD666 3-Phase Voltage
        elif parse_method == 'pd666_voltage':
            if len(registers) < 6: return None
            b = struct.pack('>HHHHHH', *registers[0:6])
            v1, v2, v3 = struct.unpack('>fff', b)
            return {"type": "Voltage", "Va": round(v1 * urat * 0.1, 1), "Vb": round(v2 * urat * 0.1, 1), "Vc": round(v3 * urat * 0.1, 1)}

        # PD666 3-Phase Current
        elif parse_method == 'pd666_current':
            if len(registers) < 6: return None
            b = struct.pack('>HHHHHH', *registers[0:6])
            i1, i2, i3 = struct.unpack('>fff', b)
            return {"type": "Current", "Ia": round(i1 * irat * 0.01, 3), "Ib": round(i2 * irat * 0.01, 3), "Ic": round(i3 * irat * 0.01, 3)}

        # PD666 3-Phase Active Power
        elif parse_method == 'pd666_active_power':
            if len(registers) < 6: return None
            b = struct.pack('>HHHHHH', *registers[0:6])
            p1, p2, p3 = struct.unpack('>fff', b)
            return {"type": "Active_Power", "Pa": round(p1 * urat * irat * 0.001, 2), "Pb": round(p2 * urat * irat * 0.001, 2), "Pc": round(p3 * urat * irat * 0.001, 2)}

        # PD666 3-Phase Reactive Power
        elif parse_method == 'pd666_reactive_power':
            if len(registers) < 6: return None
            b = struct.pack('>HHHHHH', *registers[0:6])
            q1, q2, q3 = struct.unpack('>fff', b)
            return {"type": "Reactive_Power", "Qa": round(q1 * urat * irat * 0.001, 2), "Qb": round(q2 * urat * irat * 0.001, 2), "Qc": round(q3 * urat * irat * 0.001, 2)}

        # PD666 Power Factor
        elif parse_method == 'pd666_power_factor':
            if len(registers) < 2: return None
            b = struct.pack('>HH', *registers[0:2])
            pf = struct.unpack('>f', b)[0]
            return {"type": "Power_Factor", "PF": round(pf * 0.001, 4)}

        # PD666 Frequency
        elif parse_method == 'pd666_frequency':
            if len(registers) < 2: return None
            b = struct.pack('>HH', *registers[0:2])
            hz = struct.unpack('>f', b)[0]
            return {"type": "Frequency", "Hz": round(hz * 0.01, 2)}

        # PD666 Demand
        elif parse_method == 'pd666_demand':
            if len(registers) < 2: return None
            b = struct.pack('>HH', *registers[0:2])
            dm = struct.unpack('>f', b)[0]
            return {"type": "Demand", "DmPt": round(dm * 0.01, 2)}

        # PD666 EPI
        elif parse_method == 'pd666_epi':
            if len(registers) < 2: return None
            b = struct.pack('>HH', *registers[0:2])
            val = struct.unpack('>f', b)[0]
            return {"type": "EPI", "ImpEp": round(val * urat * irat * 0.01, 2)}

        # PD666 EPE
        elif parse_method == 'pd666_epe':
            if len(registers) < 2: return None
            b = struct.pack('>HH', *registers[0:2])
            val = struct.unpack('>f', b)[0]
            return {"type": "EPE", "ExpEp": round(val * urat * irat * 0.01, 2)}
            
        # Int32 (2 registers, big endian)
        elif parse_method == 'int32_be':
            if len(registers) < 2: return None
            b = struct.pack('>HH', registers[0], registers[1])
            return struct.unpack('>i', b)[0]

        # Flowmeter Net Flow (1x Float32 REAL4 CDAB)
        elif parse_method == 'flowmeter_net_flow':
            if len(registers) < 2: return None
            b = struct.pack('>HH', registers[1], registers[0])
            val = struct.unpack('>f', b)[0]
            return {"type": "FlowMeter", "NetFlow": round(val, 2)}

        # Flowmeter Temps (2x Float32 REAL4 CDAB)
        elif parse_method == 'flowmeter_temps':
            if len(registers) < 4: return None
            b1 = struct.pack('>HH', registers[1], registers[0])
            b2 = struct.pack('>HH', registers[3], registers[2])
            t1 = struct.unpack('>f', b1)[0]
            t2 = struct.unpack('>f', b2)[0]
            return {"type": "WaterTemp", "supply": round(t1, 2), "return": round(t2, 2)}
            
        # PH Sensor (UInt16 * 0.01)
        elif parse_method == 'ph_sensor':
            if len(registers) < 1: return None
            val = struct.unpack('>H', struct.pack('>H', registers[0]))[0]
            return {"type": "PH", "ph": round(val * 0.01, 2)}

        # EC Sensor (2x UInt16: EC / 100, Temp / 10)
        elif parse_method == 'ec_sensor':
            if len(registers) < 2: return None
            b = struct.pack('>HH', *registers[0:2])
            ec_raw, temp_raw = struct.unpack('>HH', b)
            return {"type": "EC", "ec": round(ec_raw / 100.0, 2), "temp": round(temp_raw / 10.0, 1)}

        # ORP Sensor (Int16)
        elif parse_method == 'orp_sensor':
            if len(registers) < 1: return None
            b = struct.pack('>H', registers[0])
            val = struct.unpack('>h', b)[0]  # signed short
            return {"type": "ORP", "orp": val}

        # DO Sensor (2x Float32 Little Endian: DO, Temp)
        elif parse_method == 'do_sensor':
            if len(registers) < 4: return None
            # DO is in 4 bytes (little endian float). 
            # Modbus holding registers are 16-bit. 4 registers = 8 bytes.
            b = struct.pack('>HHHH', *registers[0:4])
            do_val, temp_val = struct.unpack('<ff', b) # '<ff' for 2 little-endian floats
            return {"type": "DO", "do": round(do_val, 3), "temp": round(temp_val, 1)}

        else:
            return {"type": "Unknown", "value": registers[0]}
            
    except Exception as e:
        print(f"Parse error for method {parse_method}: {e}")
        return None

def poll_devices():
    lock_acquired = False
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get system settings
        cursor.execute("SELECT * FROM system_settings WHERE id=1")
        sys_set = cursor.fetchone()
        if not sys_set:
            conn.close()
            return
        sys_set = dict(sys_set)
        
        simulation_mode = sys_set['simulation_mode'] if 'simulation_mode' in sys_set.keys() else 0
    
        # Initialize MQTT client once per polling cycle
        mqtt_client = None
        if sys_set['mqtt_enabled'] and sys_set['mqtt_host']:
            from mqtt_client import get_mqtt_client
            mqtt_client = get_mqtt_client(sys_set['mqtt_host'], sys_set['mqtt_port'], sys_set['mqtt_user'], sys_set['mqtt_pass'])
            if mqtt_client:
                mqtt_client.loop_start()

        client = None
        if not simulation_mode:
            port = sys_set['serial_port']
            if not port:
                if mqtt_client:
                    mqtt_client.disconnect()
                    mqtt_client.loop_stop()
                conn.close()
                return
            
            baud = sys_set.get('serial_baudrate', 9600)
            bsize = sys_set.get('serial_bytesize', 8)
            parity = sys_set.get('serial_parity', 'N')
            stopb = sys_set.get('serial_stopbits', 1)

            try:
                client = ModbusSerialClient(
                    port=port, 
                    baudrate=baud, 
                    bytesize=bsize, 
                    parity=parity, 
                    stopbits=stopb, 
                    timeout=1
                )
            except TypeError:
                # Fallback for older pymodbus versions
                client = ModbusSerialClient(
                    method='rtu', 
                    port=port, 
                    baudrate=baud, 
                    bytesize=bsize, 
                    parity=parity, 
                    stopbits=stopb, 
                    timeout=1
                )

            rs485_lock.acquire()
            lock_acquired = True
            
            if not client.connect():
                if mqtt_client:
                    mqtt_client.disconnect()
                    mqtt_client.loop_stop()
                conn.close()
                rs485_lock.release()
                lock_acquired = False
                return
            
        # Get active groups
        cursor.execute("SELECT * FROM rs485_groups")
        groups = cursor.fetchall()
    
        for group in groups:
            if not group['is_enabled']:
                continue
            cursor.execute("SELECT * FROM rs485_devices WHERE group_id=?", (group['id'],))
            devices = cursor.fetchall()
        
            for dev in devices:
                try:
                    # Simulation mode: generate mock result
                    if simulation_mode:
                        mock_registers = generate_mock_registers(group['parse_method'], dev['register_count'])
                        class MockResult:
                            def isError(self): return False
                            @property
                            def registers(self): return mock_registers
                        result = MockResult()
                    else:
                        # Read holding registers (0x03)
                        if True:
                            if group['command'] == 'read_holding_registers':
                                try:
                                    result = client.read_holding_registers(
                                        address=dev['register_address'],
                                        count=dev['register_count'],
                                        device_id=dev['slave_id']
                                    )
                                except TypeError:
                                    try:
                                        result = client.read_holding_registers(
                                            address=dev['register_address'],
                                            count=dev['register_count'],
                                            slave=dev['slave_id']
                                        )
                                    except TypeError:
                                        result = client.read_holding_registers(
                                            address=dev['register_address'],
                                            count=dev['register_count'],
                                            unit=dev['slave_id']
                                        )
                            # Read input registers (0x04)
                            elif group['command'] == 'read_input_registers':
                                try:
                                    result = client.read_input_registers(
                                        address=dev['register_address'],
                                        count=dev['register_count'],
                                        device_id=dev['slave_id']
                                    )
                                except TypeError:
                                    try:
                                        result = client.read_input_registers(
                                            address=dev['register_address'],
                                            count=dev['register_count'],
                                            slave=dev['slave_id']
                                        )
                                    except TypeError:
                                        result = client.read_input_registers(
                                            address=dev['register_address'],
                                            count=dev['register_count'],
                                            unit=dev['slave_id']
                                        )
                            else:
                                continue
                        
                    if not result.isError():
                        irat = dev['irat'] if 'irat' in dev.keys() else 1.0
                        urat = dev['urat'] if 'urat' in dev.keys() else 1.0
                        val = parse_payload(result.registers, group['parse_method'], irat, urat)
                        if val is not None:
                            import json
                            
                            # Determine if we should publish to MQTT
                            should_publish = True
                            if mqtt_client:
                                upload_on_timer = sys_set.get('mqtt_upload_on_timer', 1)
                                upload_interval = sys_set.get('mqtt_upload_interval', 60)
                                upload_on_change = sys_set.get('mqtt_upload_on_change', 1)
                                change_percent = sys_set.get('mqtt_upload_change_percent', 5.0)
                                
                                dev_id_str = str(dev['id'])
                                current_time = time.time()
                                last_time = last_mqtt_upload_time.get(dev_id_str, 0)
                                last_val = last_mqtt_upload_value.get(dev_id_str, None)
                                
                                publish_reason_timer = upload_on_timer and (current_time - last_time >= upload_interval)
                                
                                publish_reason_change = False
                                if upload_on_change:
                                    if last_val is None:
                                        publish_reason_change = True
                                    elif isinstance(val, dict) and isinstance(last_val, dict):
                                        # For dicts, check if any numeric value changed by more than threshold
                                        for k, v in val.items():
                                            if isinstance(v, (int, float)) and k in last_val and isinstance(last_val[k], (int, float)):
                                                old_v = last_val[k]
                                                if old_v == 0:
                                                    if v != 0: publish_reason_change = True
                                                else:
                                                    diff = abs((v - old_v) / old_v) * 100.0
                                                    if diff >= change_percent:
                                                        publish_reason_change = True
                                                        break
                                    elif isinstance(val, (int, float)) and isinstance(last_val, (int, float)):
                                        if last_val == 0:
                                            if val != 0: publish_reason_change = True
                                        else:
                                            diff = abs((val - last_val) / last_val) * 100.0
                                            if diff >= change_percent:
                                                publish_reason_change = True
                                
                                should_publish = publish_reason_timer or publish_reason_change
                                if should_publish:
                                    last_mqtt_upload_time[dev_id_str] = current_time
                                    last_mqtt_upload_value[dev_id_str] = val
                            
                            if isinstance(val, dict):
                                # Save to history as JSON
                                from datetime import datetime
                                current_local_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                cursor.execute('''
                                    INSERT INTO historical_data (device_id, value, timestamp)
                                    VALUES (?, ?, ?)
                                ''', (dev['id'], json.dumps(val), current_local_time))
                            
                                # Publish to MQTT
                                if mqtt_client and should_publish:
                                    from mqtt_client import publish_with_client
                                    
                                    topic_prefix = sys_set.get('mqtt_topic', '')
                                    if sys_set.get('mqtt_use_mac_prefix', 0):
                                        import uuid
                                        mac = hex(uuid.getnode())[2:].upper()
                                        if topic_prefix:
                                            topic_prefix = f"{mac}/{topic_prefix}"
                                        else:
                                            topic_prefix = mac
                                            
                                    topic = f"{topic_prefix}/{group['name']}/{dev['slave_id']}" if topic_prefix else f"{group['name']}/{dev['slave_id']}"
                                    
                                    payload = {
                                        "device_id": dev['id'],
                                        "slave_id": dev['slave_id'],
                                        "group": group['name'],
                                        "data": val
                                    }
                                    publish_with_client(mqtt_client, topic, payload)
                            else:
                                # Normal single float/int value
                                # Save to history
                                from datetime import datetime
                                current_local_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                cursor.execute('''
                                    INSERT INTO historical_data (device_id, value, timestamp)
                                    VALUES (?, ?, ?)
                                ''', (dev['id'], val, current_local_time))
                            
                                # Check limits for alerts
                                if dev.get('alarm_enabled', 0):
                                    limit_min = dev.get('limit_min', 0)
                                    limit_max = dev.get('limit_max', 100)
                                    if val < limit_min or val > limit_max:
                                        msg = f"⚠️ ALERT: Device {dev['id']} (Group: {group['name']}) value {val} out of bounds ({limit_min} - {limit_max})"
                                        print(msg)
                                        if sys_set.get('telegram_enabled'):
                                            recipients = []
                                            try:
                                                recipients = json.loads(sys_set.get('telegram_recipients', '[]'))
                                            except:
                                                pass
                                            
                                            sent_any = False
                                            if isinstance(recipients, list) and len(recipients) > 0:
                                                for r in recipients:
                                                    if r.get('enabled') and r.get('token') and r.get('chat_id'):
                                                        send_telegram_message(r['token'], r['chat_id'], msg)
                                                        sent_any = True
                                                        
                                            if not sent_any:
                                                if sys_set.get('telegram_token') and sys_set.get('telegram_chat_id'):
                                                    send_telegram_message(sys_set['telegram_token'], sys_set['telegram_chat_id'], msg)
                                
                                # Publish to MQTT
                                if mqtt_client and should_publish:
                                    from mqtt_client import publish_with_client
                                    
                                    topic_prefix = sys_set.get('mqtt_topic', '')
                                    if sys_set.get('mqtt_use_mac_prefix', 0):
                                        import uuid
                                        mac = hex(uuid.getnode())[2:].upper()
                                        if topic_prefix:
                                            topic_prefix = f"{mac}/{topic_prefix}"
                                        else:
                                            topic_prefix = mac
                                            
                                    topic = f"{topic_prefix}/{group['name']}/{dev['slave_id']}" if topic_prefix else f"{group['name']}/{dev['slave_id']}"
                                    
                                    payload = {
                                        "device_id": dev['id'],
                                        "slave_id": dev['slave_id'],
                                        "group": group['name'],
                                        "value": val
                                    }
                                    publish_with_client(mqtt_client, topic, payload)
                    else:
                        print(f"Modbus error reading slave {dev['slave_id']}")
                except Exception as e:
                    print(f"Error polling device {dev['id']}: {e}")
                
        if mqtt_client:
            mqtt_client.disconnect()
            mqtt_client.loop_stop()
            
        conn.commit()
    except Exception as e:
        print(f"Polling error: {e}")
    finally:
        if 'client' in locals() and client:
            client.close()
        if lock_acquired:
            rs485_lock.release()
        if 'conn' in locals() and conn:
            conn.close()
