import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'backend', 'database', 'rs485_system.db')

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE rs485_commands ADD COLUMN register_address INTEGER DEFAULT 0")
        cursor.execute("ALTER TABLE rs485_commands ADD COLUMN register_count INTEGER DEFAULT 1")
        conn.commit()
        print("Migration successful")
    except sqlite3.OperationalError as e:
        print("Migration skipped or failed:", e)
    conn.close()

if __name__ == '__main__':
    migrate()
