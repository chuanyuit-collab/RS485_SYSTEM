import os
import json
import hashlib
import paramiko

CONFIG_FILE = 'deploy_config.json'

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def get_local_hashes(local_dir):
    hashes = {}
    for root, dirs, files in os.walk(local_dir):
        if '__pycache__' in root or '.git' in root or '.venv' in root:
            continue
        for file in files:
            if file.endswith('.pyc') or file == 'compare_code.py':
                continue
            filepath = os.path.join(root, file)
            rel_path = os.path.relpath(filepath, local_dir).replace('\\', '/')
            with open(filepath, 'rb') as f:
                hashes[rel_path] = hashlib.md5(f.read()).hexdigest()
    return hashes

def get_remote_hashes(ssh, remote_dir):
    # We use md5sum on the remote
    cmd = f"cd {remote_dir} && find . -type f -not -path '*/__pycache__/*' -not -path '*/.git/*' -not -path '*/.venv/*' -not -name '*.pyc' -exec md5sum {{}} +"
    stdin, stdout, stderr = ssh.exec_command(cmd)
    out = stdout.read().decode('utf-8')
    
    hashes = {}
    for line in out.strip().split('\n'):
        if not line:
            continue
        parts = line.split('  ')
        if len(parts) == 2:
            md5 = parts[0]
            rel_path = parts[1].lstrip('./')
            hashes[rel_path] = md5
    return hashes

def main():
    config = load_config()
    host = config['pi_host']
    user = config['pi_user']
    target = config['target_dir']
    password = config.get('pi_pass', "")

    print(f"Connecting to {user}@{host}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, password=password, timeout=10)

    print("Fetching remote file hashes...")
    remote_hashes = get_remote_hashes(ssh, target)
    ssh.close()

    print("Fetching local file hashes...")
    local_hashes = get_local_hashes('.')

    print("\n--- Comparison Results ---")
    all_files = set(local_hashes.keys()).union(set(remote_hashes.keys()))
    
    differ = []
    missing_remote = []
    missing_local = []
    
    for f in all_files:
        if f not in remote_hashes:
            missing_remote.append(f)
        elif f not in local_hashes:
            missing_local.append(f)
        elif local_hashes[f] != remote_hashes[f]:
            differ.append(f)

    if not differ and not missing_remote and not missing_local:
        print("[OK] The code on the Pi is exactly the same as the local computer.")
    else:
        if differ:
            print("\n[WARNING] Files with different content:")
            for f in differ:
                print(f"  - {f}")
        if missing_remote:
            print("\n[WARNING] Files missing on the Raspberry Pi (Only on local):")
            for f in missing_remote:
                print(f"  - {f}")
        if missing_local:
            print("\n[WARNING] Files missing on the local computer (Only on Pi):")
            for f in missing_local:
                print(f"  - {f}")

if __name__ == '__main__':
    main()
