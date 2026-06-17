import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.234.145', username='cys', password='cyc12345', timeout=5)

stdin, stdout, stderr = ssh.exec_command('journalctl -u rs485_dashboard.service --no-pager -n 500')
lines = stdout.read().decode('utf-8', errors='ignore').split('\\n')
errs = [l for l in lines if 'File "/home/cys/prog/' in l or 'Traceback' in l or 'Exception' in l or '500' in l or 'FastAPI' in l]
print('\\n'.join(errs[-50:]))
ssh.close()
