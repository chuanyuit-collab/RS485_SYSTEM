import os
import re
import json
import shutil
import subprocess
import urllib.request
import tarfile

SERVICE = "Npc"
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "npc_config.json")
# GitHub release URL for nps client (linux_arm64 as typical for pi, but could also be linux_arm or linux_amd64 depending on OS)
# We will just try to download linux_arm64 as a default, or detect it.
# Actually, since it's a python backend, we can use `platform.machine()`
import platform

def get_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}

def save_config(server, vkey, type_):
    with open(CONFIG_FILE, 'w') as f:
        json.dump({"server": server, "vkey": vkey, "type": type_}, f)

def run(cmd):
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        return res.returncode, res.stdout, res.stderr
    except Exception as e:
        return -1, "", str(e)

def ok(cmd):
    rc, out, err = run(cmd)
    if rc == 0:
        return True, out
    return False, err or out

def _npc_bin():
    for c in ("npc", "/usr/bin/npc", "/usr/local/bin/npc", "/opt/npc/npc"):
        p = shutil.which(c) if "/" not in c else (c if os.path.exists(c) else None)
        if p:
            return p
    return None

def parse_command(text):
    if not text:
        return None
    server = re.search(r"-server=(\S+)", text)
    vkey = re.search(r"-vkey=(\S+)", text)
    typ = re.search(r"-type=(\S+)", text)
    if not server or not vkey:
        return None
    return {
        "server": server.group(1),
        "vkey": vkey.group(1),
        "type": typ.group(1) if typ else "tcp",
    }

def status():
    binp = _npc_bin()
    saved = get_config()
    info = {
        "installed": binp is not None,
        "binary": binp or "",
        "server": saved.get("server", ""),
        "vkey": saved.get("vkey", ""),
        "type": saved.get("type", "tcp"),
        "active": False,
        "service_state": "",
    }
    rc, out, _ = run(["systemctl", "is-active", SERVICE])
    info["service_state"] = out.strip() or "unknown"
    info["active"] = out.strip() == "active"
    return info

def install(server, vkey, type_="tcp"):
    binp = _npc_bin()
    if not binp:
        return False, "找不到 npc 執行檔,請先安裝或下載 npc"
    
    # Stop and uninstall old service if any
    run([binp, "stop"])
    run([binp, "uninstall"])
    
    # Install new service
    s, m = ok([binp, "install", "-server=%s" % server, "-vkey=%s" % vkey, "-type=%s" % type_])
    if not s:
        return False, "npc install 失敗: " + m
        
    save_config(server, vkey, type_)
    
    # Start service
    ok([binp, "start"])
    ok(["systemctl", "enable", SERVICE])
    s2, m2 = ok(["systemctl", "start", SERVICE])
    return True, "NPC 已安裝並啟動 (%s)" % server

def control(action):
    if action not in ("start", "stop", "restart"):
        return False, "不支援的動作"
    s, m = ok(["systemctl", action, SERVICE])
    return s, m

def uninstall():
    binp = _npc_bin()
    if binp:
        run([binp, "stop"])
        run([binp, "uninstall"])
    run(["systemctl", "disable", SERVICE])
    return True, "已移除 NPC 服務"

def download_npc():
    arch = platform.machine().lower()
    if "aarch64" in arch or "arm64" in arch:
        url = "https://github.com/ehang-io/nps/releases/download/v0.26.10/linux_arm64_client.tar.gz"
    elif "arm" in arch:
        url = "https://github.com/ehang-io/nps/releases/download/v0.26.10/linux_arm_v7_client.tar.gz"
    elif "x86_64" in arch or "amd64" in arch:
        url = "https://github.com/ehang-io/nps/releases/download/v0.26.10/linux_amd64_client.tar.gz"
    else:
        # fallback to arm for pi
        url = "https://github.com/ehang-io/nps/releases/download/v0.26.10/linux_arm_v7_client.tar.gz"
        
    tmp_tar = "/tmp/npc_client.tar.gz"
    try:
        # Note: If SSL errors occur, urllib might fail. We assume basic functionality or use wget.
        rc, out, err = run(["wget", "-qO", tmp_tar, url])
        if rc != 0:
             return False, f"下載失敗: {err}"
             
        with tarfile.open(tmp_tar, "r:gz") as tar:
            tar.extract("npc", path="/usr/bin/")
        
        os.chmod("/usr/bin/npc", 0o755)
        os.remove(tmp_tar)
        return True, "NPC 已成功下載並放置於 /usr/bin/npc"
    except Exception as e:
        return False, f"下載或解壓縮時發生錯誤: {e}"
