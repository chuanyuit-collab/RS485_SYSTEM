import os
import json
import paramiko
from stat import S_ISDIR

CONFIG_FILE = 'deploy_config.json'

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def download_file(sftp, remote_path, local_path):
    print(f"Downloading {remote_path} to {local_path}...")
    try:
        sftp.get(remote_path, local_path)
    except Exception as e:
        print(f"Failed to download {remote_path}: {e}")

def main():
    config = load_config()
    host = config['pi_host']
    user = config['pi_user']
    password = config.get('pi_pass', "")
    remote_dir = config['target_dir']

    print(f"Connecting to {user}@{host}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, password=password, timeout=10)
    sftp = ssh.open_sftp()

    files_to_download = [
        'frontend/styles.css',
        'database/rs485_system.db',
        'frontend/login.html',
        'requirements.txt',
        'backend/mqtt_client.py',
        'backend/telegram_bot.py'
    ]

    for rel_path in files_to_download:
        remote_path = f"{remote_dir}/{rel_path}"
        local_path = rel_path
        
        dirname = os.path.dirname(local_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        
        download_file(sftp, remote_path, local_path)

    print("Download completed.")
    sftp.close()
    ssh.close()

if __name__ == '__main__':
    main()
