import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'database', 'rs485_system.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # System Settings Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS system_settings (
        id INTEGER PRIMARY KEY,
        mqtt_enabled BOOLEAN DEFAULT 0,
        mqtt_host TEXT DEFAULT '',
        mqtt_port INTEGER DEFAULT 1883,
        mqtt_user TEXT DEFAULT '',
        mqtt_pass TEXT DEFAULT '',
        mqtt_topic TEXT DEFAULT 'rs485/data',
        telegram_enabled BOOLEAN DEFAULT 0,
        telegram_boot_notify BOOLEAN DEFAULT 1,
        telegram_token TEXT DEFAULT '',
        telegram_chat_id TEXT DEFAULT '',
        telegram_recipients TEXT DEFAULT '[]',
        polling_interval INTEGER DEFAULT 5,
        serial_port TEXT DEFAULT '',
        simulation_mode INTEGER DEFAULT 0,
        mqtt_upload_on_change BOOLEAN DEFAULT 1,
        mqtt_upload_change_percent REAL DEFAULT 5.0,
        mqtt_upload_on_timer BOOLEAN DEFAULT 1,
        mqtt_upload_interval INTEGER DEFAULT 60,
        mqtt_use_mac_prefix INTEGER DEFAULT 0,
        serial_baudrate INTEGER DEFAULT 9600,
        serial_bytesize INTEGER DEFAULT 8,
        serial_parity TEXT DEFAULT 'N',
        serial_stopbits INTEGER DEFAULT 1
    )
    ''')

    # Ensure at least one row exists
    cursor.execute('SELECT COUNT(*) FROM system_settings')
    if cursor.fetchone()[0] == 0:
        cursor.execute('INSERT INTO system_settings (id) VALUES (1)')

    # Migration: add columns if they don't exist
    try:
        cursor.execute('ALTER TABLE system_settings ADD COLUMN telegram_boot_notify BOOLEAN DEFAULT 1')
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute('ALTER TABLE system_settings ADD COLUMN simulation_mode INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass
        
    try:
        cursor.execute('ALTER TABLE system_settings ADD COLUMN mqtt_upload_on_change BOOLEAN DEFAULT 1')
        cursor.execute('ALTER TABLE system_settings ADD COLUMN mqtt_upload_change_percent REAL DEFAULT 5.0')
        cursor.execute('ALTER TABLE system_settings ADD COLUMN mqtt_upload_on_timer BOOLEAN DEFAULT 1')
        cursor.execute('ALTER TABLE system_settings ADD COLUMN mqtt_upload_interval INTEGER DEFAULT 60')
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute('ALTER TABLE system_settings ADD COLUMN mqtt_use_mac_prefix INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE system_settings ADD COLUMN telegram_recipients TEXT DEFAULT '[]'")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE system_settings ADD COLUMN serial_baudrate INTEGER DEFAULT 9600")
        cursor.execute("ALTER TABLE system_settings ADD COLUMN serial_bytesize INTEGER DEFAULT 8")
        cursor.execute("ALTER TABLE system_settings ADD COLUMN serial_parity TEXT DEFAULT 'N'")
        cursor.execute("ALTER TABLE system_settings ADD COLUMN serial_stopbits INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass

    # RS485 Groups Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS rs485_groups (
        id INTEGER PRIMARY KEY,
        name TEXT DEFAULT '裝置群組',
        is_enabled BOOLEAN DEFAULT 1,
        start_id INTEGER DEFAULT 1,
        id_count INTEGER DEFAULT 1,
        command_name TEXT DEFAULT '',
        parse_type TEXT DEFAULT 'int16',
        lower_limit REAL DEFAULT 0,
        upper_limit REAL DEFAULT 100
    )
    ''')

    # Migration: add is_enabled if it doesn't exist
    try:
        cursor.execute('ALTER TABLE rs485_groups ADD COLUMN is_enabled BOOLEAN DEFAULT 1')
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE rs485_groups ADD COLUMN command_name TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
        
    try:
        cursor.execute("ALTER TABLE rs485_groups ADD COLUMN command TEXT DEFAULT 'read_holding_registers'")
        cursor.execute("ALTER TABLE rs485_groups ADD COLUMN parse_method TEXT DEFAULT 'int16'")
        cursor.execute("ALTER TABLE rs485_groups ADD COLUMN limit_min REAL DEFAULT 0")
        cursor.execute("ALTER TABLE rs485_groups ADD COLUMN limit_max REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # Initialize 10 groups if not exist
    cursor.execute('SELECT COUNT(*) FROM rs485_groups')
    if cursor.fetchone()[0] < 10:
        for i in range(1, 11):
            cursor.execute('INSERT OR IGNORE INTO rs485_groups (id, name) VALUES (?, ?)', (i, f'Device Group {i}'))

    # RS485 Commands Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS rs485_commands (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        command TEXT,
        parse_method TEXT,
        register_address INTEGER DEFAULT 0,
        register_count INTEGER DEFAULT 1
    )
    ''')

    try:
        cursor.execute("ALTER TABLE rs485_commands ADD COLUMN register_address INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE rs485_commands ADD COLUMN register_count INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass

    # Seed default commands if missing
    default_commands = [
        ('讀取數值 (Holding Int16)', 'read_holding_registers', 'int16', 0, 1),
        ('讀取狀態 (Input UInt16)', 'read_input_registers', 'uint16', 0, 1),
        ('流量計-瞬時流量', 'read_holding_registers', 'float32_cdab_lmin', 4, 2),
        ('流量計-净累積流量(浮點形式)', 'read_holding_registers', 'flowmeter_net_flow', 114, 2),
        ('流量計-供水温度/回水温度', 'read_holding_registers', 'flowmeter_temps', 32, 4),
        ('三相線電壓 (Va, Vb, Vc)', 'read_holding_registers', 'pd666_voltage', 8192, 6),
        ('三相線電流 (Ia, Ib, Ic)', 'read_holding_registers', 'pd666_current', 8204, 6),
        ('三相線有功功率 (Pa, Pb, Pc)', 'read_holding_registers', 'pd666_active_power', 8212, 6),
        ('三相線無功功率 (Qa, Qb, Qc)', 'read_holding_registers', 'pd666_reactive_power', 8220, 6),
        ('功率因數', 'read_holding_registers', 'pd666_power_factor', 8234, 2),
        ('頻率', 'read_holding_registers', 'pd666_frequency', 8260, 2),
        ('總有功功率需量', 'read_holding_registers', 'pd666_demand', 8272, 2),
        ('正向有功總電能', 'read_holding_registers', 'pd666_epi', 4126, 2),
        ('反向有功總電能', 'read_holding_registers', 'pd666_epe', 4136, 2),
        ('PH 讀值', 'read_holding_registers', 'ph_sensor', 0, 1),
        ('EC 讀值 (含溫度)', 'read_holding_registers', 'ec_sensor', 0, 2),
        ('ORP 讀值', 'read_holding_registers', 'orp_sensor', 0, 1),
        ('DO 讀值 (含溫度)', 'read_holding_registers', 'do_sensor', 0, 4)
    ]
    for cmd in default_commands:
        cursor.execute('SELECT COUNT(*) FROM rs485_commands WHERE name = ?', (cmd[0],))
        if cursor.fetchone()[0] == 0:
            cursor.execute('INSERT INTO rs485_commands (name, command, parse_method, register_address, register_count) VALUES (?, ?, ?, ?, ?)', cmd)

    # RS485 Devices Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS rs485_devices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER,
        slave_id INTEGER,
        register_address INTEGER,
        register_count INTEGER,
        irat REAL DEFAULT 1.0,
        urat REAL DEFAULT 1.0,
        FOREIGN KEY(group_id) REFERENCES rs485_groups(id) ON DELETE CASCADE
    )
    ''')

    try:
        cursor.execute("ALTER TABLE rs485_devices ADD COLUMN irat REAL DEFAULT 1.0")
        cursor.execute("ALTER TABLE rs485_devices ADD COLUMN urat REAL DEFAULT 1.0")
    except sqlite3.OperationalError:
        pass

    # Historical Data Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS historical_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        device_id INTEGER,
        value REAL,
        FOREIGN KEY (device_id) REFERENCES rs485_devices(id)
    )
    ''')

    # WiFi Profiles Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS wifi_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ssid TEXT UNIQUE NOT NULL,
        password TEXT,
        is_auto_reconnect BOOLEAN DEFAULT 1,
        last_connected_at DATETIME
    )
    ''')

    # Saved Configs Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS saved_configs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        config_data TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_db()
    print("Database initialized successfully.")
