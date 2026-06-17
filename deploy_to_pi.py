import os
import json
import sys
import getpass
try:
    import paramiko
except ImportError:
    print("Missing paramiko library. Please install it first: pip install paramiko")
    sys.exit(1)

CONFIG_FILE = 'deploy_config.json'

def load_config():
    if not os.path.exists(CONFIG_FILE):
        default_config = {
            "pi_host": "192.168.1.100",
            "pi_user": "cys",
            "pi_pass": "",
            "target_dir": "/home/cys/prog/RS485_SYSTEM"
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(default_config, f, indent=4)
        print(f"已建立 {CONFIG_FILE}！請打開它設定您的樹莓派 IP。")
        print("您可以在裡面設定密碼 (pi_pass)，或者留空以便在執行時手動輸入。")
        sys.exit(1)
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def run_ssh_cmd(ssh_client, cmd):
    print(f"Running: {cmd}")
    stdin, stdout, stderr = ssh_client.exec_command(cmd)
    
    # 讀取輸出
    exit_status = stdout.channel.recv_exit_status()
    out = stdout.read().decode('utf-8', errors='ignore')
    err = stderr.read().decode('utf-8', errors='ignore')
    
    if out:
        try:
            print(out.strip())
        except UnicodeEncodeError:
            print(out.strip().encode('ascii', 'replace').decode('ascii'))
    if err:
        try:
            print(f"Error: {err.strip()}")
        except UnicodeEncodeError:
            print(f"Error: {err.strip().encode('ascii', 'replace').decode('ascii')}")
        
    return exit_status

def upload_dir_sftp(sftp, local_dir, remote_dir):
    try:
        sftp.mkdir(remote_dir)
    except IOError:
        pass # Directory might already exist

    for item in os.listdir(local_dir):
        if item == '__pycache__':
            continue
        local_path = os.path.join(local_dir, item)
        remote_path = f"{remote_dir}/{item}"
        
        if os.path.isfile(local_path):
            print(f"Uploading {local_path} -> {remote_path}")
            sftp.put(local_path, remote_path)
        elif os.path.isdir(local_path):
            upload_dir_sftp(sftp, local_path, remote_path)

def main():
    config = load_config()
    host = config['pi_host']
    user = config['pi_user']
    target = config['target_dir']
    password = config.get('pi_pass', "")

    if not password:
        password = getpass.getpass(f"請輸入 {user}@{host} 的 SSH 密碼: ")

    print(f"\n連線至 {user}@{host} ...")
    
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        ssh.connect(host, username=user, password=password, timeout=10)
    except Exception as e:
        print(f"連線失敗: {e}")
        sys.exit(1)

    print("SSH 連線成功！準備部署...")

    # 1. 建立遠端目錄
    run_ssh_cmd(ssh, f"mkdir -p {target}/backend {target}/frontend {target}/database")

    # 2. SFTP 上傳檔案
    print("\n--- 開始上傳檔案 ---")
    sftp = ssh.open_sftp()
    
    # 上傳 backend
    if os.path.exists('backend'):
        upload_dir_sftp(sftp, 'backend', f"{target}/backend")
    
    # 上傳 frontend
    if os.path.exists('frontend'):
        upload_dir_sftp(sftp, 'frontend', f"{target}/frontend")
        
    # 上傳設定檔
    files_to_upload = ['requirements.txt', 'rs485_dashboard.service', 'setup_pi.sh']
    for f in files_to_upload:
        if os.path.exists(f):
            print(f"Uploading {f}...")
            sftp.put(f, f"{target}/{f}")
            
    sftp.close()

    # 3. 執行遠端 setup_pi.sh，由於會用到 sudo，如果需要密碼這裡可以透過 echo 傳入
    print("\n--- 執行遠端設定腳本 (setup_pi.sh) ---")
    
    # 將密碼自動傳入 sudo 以防跳出密碼詢問 (這是一個常見的自動部署技巧)
    sudo_setup_cmd = f"cd {target} && chmod +x setup_pi.sh && echo '{password}' | sudo -S bash setup_pi.sh"
    run_ssh_cmd(ssh, sudo_setup_cmd)

    ssh.close()
    print("\n [Deployment Complete] 部署完成！系統服務已在樹莓派上啟動。")

if __name__ == '__main__':
    main()
