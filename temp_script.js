
        const { createApp, ref, onMounted } = Vue;

        createApp({
            setup() {
                const loading = ref(true);
                const activeTab = ref('system');
                const sysSettings = ref({});
                const groups = ref([]);
                const commandsList = ref([]);
                const setupCommandsList = ref([]);
                const setupCommandExec = ref({ slave_id: 1, selected_cmd_id: 'null', command: '', register_address: 0, write_value: '', read_count: 1 });
                const execModal = ref({ show: false, success: false, message: '' });
                const ports = ref([]);
                const wifiList = ref([]);
                const wifiScanned = ref(false);
                const tsStatus = ref({ installed: false, status: 'Ê™¢Êü•‰∏?..', ip: '' });
                const tsAuthKey = ref('');
                
                const systemLogs = ref("");
                const autoRefreshLogs = ref(false);
                let logInterval = null;
                
                const savedConfigs = ref([]);
                const newConfigName = ref("");
                
                const telegramRecipientsList = ref([]);
                
                const rawLogs = ref([]);
                const logViewModal = ref({ show: false, filename: '', content: '' });

                const fetchSysSettings = async () => {
                    const res = await fetch('/api/system_settings');
                    const data = await res.json();
                    if (data) {
                        data.mqtt_enabled = !!data.mqtt_enabled;
                        data.telegram_enabled = !!data.telegram_enabled;
                        data.telegram_boot_notify = !!data.telegram_boot_notify;
                        data.simulation_mode = !!data.simulation_mode;
                        data.mqtt_upload_on_change = !!data.mqtt_upload_on_change;
                        data.mqtt_upload_on_timer = !!data.mqtt_upload_on_timer;
                        data.mqtt_use_mac_prefix = !!data.mqtt_use_mac_prefix;
                        data.serial_baudrate = data.serial_baudrate || 9600;
                        data.serial_bytesize = data.serial_bytesize || 8;
                        data.serial_parity = data.serial_parity || 'N';
                        data.serial_stopbits = data.serial_stopbits || 1;
                        sysSettings.value = data;
                        
                        // Parse recipients
                        let list = [];
                        try {
                            list = JSON.parse(data.telegram_recipients || '[]');
                        } catch (e) {}
                        
                        // Migrate legacy to first slot if empty
                        if (list.length === 0 && data.telegram_token) {
                            list.push({
                                name: '?êË®≠?ØÁµ°‰∫?,
                                token: data.telegram_token,
                                chat_id: data.telegram_chat_id,
                                enabled: true
                            });
                        }
                        
                        // Pad to 10 items
                        while (list.length < 10) {
                            list.push({ name: '', token: '', chat_id: '', enabled: false });
                        }
                        telegramRecipientsList.value = list;
                    }
                };

                const fetchRawLogs = async () => {
                    try {
                        const res = await fetch('/api/logs');
                        if(res.ok) {
                            rawLogs.value = await res.json();
                        }
                    } catch (e) {
                        console.error('Failed to fetch raw logs', e);
                    }
                };

                const viewRawLog = async (filename) => {
                    logViewModal.value = { show: true, filename: filename, content: 'ËÆÄ?ñ‰∏≠...' };
                    try {
                        const res = await fetch(`/api/logs/${filename}`);
                        if(res.ok) {
                            const data = await res.json();
                            logViewModal.value.content = data.content;
                        } else {
                            logViewModal.value.content = 'ËÆÄ?ñÂ§±?ó„Ä?;
                        }
                    } catch (e) {
                        logViewModal.value.content = '?°Ê?ËÆÄ?ñÊó•Ë™åÂÖßÂÆπ„Ä?;
                    }
                };

                const formatBytes = (bytes) => {
                    if(bytes === 0) return '0 Bytes';
                    const k = 1024, dm = 2, sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
                    const i = Math.floor(Math.log(bytes) / Math.log(k));
                    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
                };

                const fetchCommands = async () => {
                    const res = await fetch('/api/rs485_commands');
                    const data = await res.json();
                    commandsList.value = data.map(cmd => ({
                        ...cmd,
                        register_address_hex: (cmd.register_address || 0).toString(16).toUpperCase()
                    }));
                };

                const fetchSetupCommands = async () => {
                    const res = await fetch('/api/rs485_setup_commands');
                    const data = await res.json();
                    setupCommandsList.value = data.map(cmd => ({
                        ...cmd,
                        register_address_hex: (cmd.register_address || 0).toString(16).toUpperCase(),
                        read_count: cmd.read_count || 1
                    }));
                };

                const fetchGroups = async () => {
                    const res = await fetch('/api/rs485_groups');
                    const data = await res.json();
                    if (data) {
                        data.forEach(g => {
                            g.is_enabled = !!g.is_enabled;
                        });
                        groups.value = data;
                    }
                };

                const fetchPorts = async () => {
                    const res = await fetch('/api/ports');
                    ports.value = await res.json();
                };

                const saveSysSettings = async () => {
                    try {
                        sysSettings.value.mqtt_upload_change_percent = parseFloat(sysSettings.value.mqtt_upload_change_percent) || 5.0;
                        sysSettings.value.mqtt_upload_interval = parseInt(sysSettings.value.mqtt_upload_interval) || 60;
                        
                        // Set the stringified recipients
                        sysSettings.value.telegram_recipients = JSON.stringify(telegramRecipientsList.value);
                        
                        // Set legacy fields to first recipient's info to maintain backwards compatibility
                        const firstActive = telegramRecipientsList.value.find(r => r.enabled && r.token && r.chat_id);
                        if (firstActive) {
                            sysSettings.value.telegram_token = firstActive.token;
                            sysSettings.value.telegram_chat_id = firstActive.chat_id;
                        } else {
                            sysSettings.value.telegram_token = '';
                            sysSettings.value.telegram_chat_id = '';
                        }
                        
                        const res = await fetch('/api/system_settings', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(sysSettings.value)
                        });
                        if (res.ok) alert('Á≥ªÁµ±Ë®≠Â?Â∑≤ÂÑ≤Â≠òÔ?');
                    } catch (e) {
                        alert('?≤Â?Â§±Ê?');
                    }
                };

                const saveGroup = async (groupToSave) => {
                    try {
                        groupToSave.limit_min = parseFloat(groupToSave.limit_min) || 0;
                        groupToSave.limit_max = parseFloat(groupToSave.limit_max) || 0;
                        groupToSave.is_enabled = Boolean(groupToSave.is_enabled);
                        if (groupToSave.devices) {
                            groupToSave.devices.forEach(d => {
                                d.irat = parseFloat(d.irat) || 1.0;
                                d.urat = parseFloat(d.urat) || 1.0;
                            });
                        }
                        const res = await fetch('/api/rs485_groups', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(groupToSave)
                        });
                        if (res.ok) alert(`Áæ§Á? ${groupToSave.id} Ë®≠Â?Â∑≤ÂÑ≤Â≠òÔ?`);
                        else alert('?≤Â?Â§±Ê? (?Ä?ãÁ¢º: ' + res.status + ')');
                    } catch (e) {
                        alert('?≤Â??ºÁ??ØË™§: ' + e.message);
                    }
                };

                const saveCommands = async () => {
                    try {
                        const payload = commandsList.value.map(cmd => ({
                            ...cmd,
                            register_address: parseInt(cmd.register_address_hex, 16) || 0
                        }));
                        const res = await fetch('/api/rs485_commands', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(payload)
                        });
                        if (res.ok) {
                            alert('?™Ë??á‰ª§Â∑≤ÂÑ≤Â≠òÔ?');
                            fetchCommands();
                        }
                    } catch (e) {
                        alert('?≤Â?Â§±Ê?');
                    }
                };

                const saveSetupCommands = async () => {
                    try {
                        const payload = setupCommandsList.value.map(cmd => ({
                            ...cmd,
                            register_address: parseInt(cmd.register_address_hex, 16) || 0,
                            read_count: cmd.read_count || 1
                        }));
                        const res = await fetch('/api/rs485_setup_commands', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(payload)
                        });
                        if (res.ok) {
                            alert('Ë®≠Â??á‰ª§Â∑≤ÂÑ≤Â≠òÔ?');
                            fetchSetupCommands();
                        } else {
                            alert('?≤Â?Â§±Ê?');
                        }
                    } catch (e) {
                        alert('?≤Â??ºÁ??ØË™§: ' + e.message);
                    }
                };

                const addSetupCommand = () => {
                    setupCommandsList.value.push({ name: '', command: 'write_single_register', register_address_hex: '0', write_value: '', read_count: 1 });
                };

                const removeSetupCommand = (index) => {
                    setupCommandsList.value.splice(index, 1);
                };

                const onSetupCommandSelect = () => {
                    const selectedId = setupCommandExec.value.selected_cmd_id;
                    if (selectedId !== 'null') {
                        const cmd = setupCommandsList.value.find(c => c.id === selectedId || c.name === selectedId);
                        if (cmd) {
                            setupCommandExec.value.command = cmd.command;
                            setupCommandExec.value.register_address_hex = cmd.register_address_hex;
                            setupCommandExec.value.write_value = cmd.write_value;
                            setupCommandExec.value.read_count = cmd.read_count || 1;
                        }
                    }
                };

                const setupCommandPreviewHex = () => {
                    if (setupCommandExec.value.selected_cmd_id === 'null') return '';
                    try {
                        const slaveId = parseInt(setupCommandExec.value.slave_id) || 1;
                        const cmdType = setupCommandExec.value.command;
                        const startAddr = parseInt(setupCommandExec.value.register_address_hex, 16) || 0;
                        const valStr = setupCommandExec.value.write_value || '';
                        
                        let buf = [];
                        buf.push(slaveId);
                        
                        if (cmdType === 'read_holding_registers' || cmdType === 'read_input_registers') {
                            const func = cmdType === 'read_holding_registers' ? 3 : 4;
                            const count = setupCommandExec.value.read_count || 1;
                            buf.push(func);
                            buf.push((startAddr >> 8) & 0xFF);
                            buf.push(startAddr & 0xFF);
                            buf.push((count >> 8) & 0xFF);
                            buf.push(count & 0xFF);
                        } else if (cmdType === 'write_single_register') {
                            buf.push(0x06);
                            buf.push((startAddr >> 8) & 0xFF);
                            buf.push(startAddr & 0xFF);
                            const val = parseInt(valStr, 16) || 0;
                            buf.push((val >> 8) & 0xFF);
                            buf.push(val & 0xFF);
                        } else if (cmdType === 'write_multiple_registers') {
                            buf.push(0x10);
                            buf.push((startAddr >> 8) & 0xFF);
                            buf.push(startAddr & 0xFF);
                            const vals = valStr.split(',').filter(v => v.trim()).map(v => parseInt(v.trim(), 16) || 0);
                            const len = vals.length || 1;
                            buf.push((len >> 8) & 0xFF);
                            buf.push(len & 0xFF);
                            buf.push(len * 2);
                            const fillVals = vals.length ? vals : [0];
                            for (let v of fillVals) {
                                buf.push((v >> 8) & 0xFF);
                                buf.push(v & 0xFF);
                            }
                        } else {
                            return 'Unknown Command Type';
                        }
                        
                        let crc = 0xFFFF;
                        for (let pos = 0; pos < buf.length; pos++) {
                            crc ^= buf[pos];
                            for (let i = 0; i < 8; i++) {
                                if ((crc & 1) !== 0) {
                                    crc >>= 1;
                                    crc ^= 0xA001;
                                } else {
                                    crc >>= 1;
                                }
                            }
                        }
                        buf.push(crc & 0xFF);
                        buf.push((crc >> 8) & 0xFF);
                        
                        return buf.map(b => b.toString(16).padStart(2, '0').toUpperCase()).join(' ');
                    } catch (e) {
                        return 'Invalid Input';
                    }
                };

                const executeSetupCommand = async () => {
                    if (setupCommandExec.value.selected_cmd_id === 'null') {
                        alert('Ë´ãÂ??∏Ê??á‰ª§');
                        return;
                    }
                    if (!confirm(`Á¢∫Â?Ë¶ÅÂ? Slave ID: ${setupCommandExec.value.slave_id} ?∑Ë?ÂØ´ÂÖ•?á‰ª§?éÔ?`)) {
                        return;
                    }
                    try {
                        const res = await fetch('/api/execute_setup_command', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(setupCommandExec.value)
                        });
                        const result = await res.json();
                        if (res.ok) {
                            execModal.value = { show: true, success: true, message: result.message };
                        } else {
                            execModal.value = { show: true, success: false, message: result.message };
                        }
                    } catch (e) {
                        execModal.value = { show: true, success: false, message: e.message };
                    }
                };

                const testConnection = async (testType) => {
                    try {
                        sysSettings.value.telegram_recipients = JSON.stringify(telegramRecipientsList.value);
                        const res = await fetch('/api/test_connection', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                test_type: testType,
                                settings: sysSettings.value
                            })
                        });
                        const result = await res.json();
                        if (res.ok) {
                            alert('??' + result.message);
                        } else {
                            alert('??Ê∏¨Ë©¶Â§±Ê?: \n' + result.message);
                        }
                    } catch (e) {
                        alert('??Ê∏¨Ë©¶?ºÁ??ØË™§: \n' + e.message);
                    }
                };

                const testGroupConnection = async (group) => {
                    try {
                        const res = await fetch('/api/test_rs485_group', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(group)
                        });
                        const result = await res.json();
                        if (res.ok) {
                            const parsedStr = typeof result.data === 'object' ? JSON.stringify(result.data) : result.data;
                            alert('??' + result.message + '\n\nËß??ÁµêÊ?: ' + parsedStr + '\n?üÂ?Ë≥áÊ?: ' + JSON.stringify(result.raw));
                        } else {
                            alert('??Ê∏¨Ë©¶Â§±Ê?: \n' + result.message);
                        }
                    } catch (e) {
                        alert('??Ê∏¨Ë©¶?ºÁ??ØË™§: \n' + e.message);
                    }
                };

                const testSingleDevice = async (group, dev) => {
                    const tempGroup = JSON.parse(JSON.stringify(group));
                    tempGroup.devices = [dev];
                    
                    try {
                        const res = await fetch('/api/test_rs485_group', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(tempGroup)
                        });
                        const result = await res.json();
                        if (res.ok) {
                            const parsedStr = typeof result.data === 'object' ? JSON.stringify(result.data) : result.data;
                            alert('??' + result.message + '\n\nËß??ÁµêÊ?: ' + parsedStr + '\n?üÂ?Ë≥áÊ?: ' + JSON.stringify(result.raw));
                        } else {
                            alert('??Ê∏¨Ë©¶Â§±Ê?: \n' + result.message);
                        }
                    } catch (e) {
                        alert('??Ê∏¨Ë©¶?ºÁ??ØË™§: \n' + e.message);
                    }
                };

                const addCommand = (category = '?∂Â?') => {
                    commandsList.value.push({ name: '', category: category, command: 'read_holding_registers', parse_method: 'int16', register_address: 0, register_address_hex: '0', register_count: 1 });
                };

                const removeCommand = (index) => {
                    commandsList.value.splice(index, 1);
                };

                const isPowerMeterGroup = (group) => {
                    if (group.parse_method && group.parse_method.startsWith('pd666_')) return true;
                    if (group.command_name) {
                        const cmd = commandsList.value.find(c => c.name === group.command_name);
                        return cmd && cmd.category === '?ªÈå∂';
                    }
                    return false;
                };

                const applyCommandTemplate = (group, commandName) => {
                    if (!commandName) return;
                    const c = commandsList.value.find(cmd => cmd.name === commandName);
                    if (c) {
                        group.command = c.command;
                        group.parse_method = c.parse_method;
                        if (group.devices && group.devices.length > 0) {
                            group.devices.forEach(d => {
                                d.register_address = c.register_address || 0;
                                d.register_address_hex = (c.register_address || 0).toString(16).toUpperCase();
                                d.register_count = c.register_count || 1;
                            });
                        }
                    }
                };

                const addDevice = (group) => {
                    if (!group.devices) group.devices = [];
                    let defaultAddr = 0;
                    let defaultCount = 1;
                    if (group.command_name) {
                        const c = commandsList.value.find(cmd => cmd.name === group.command_name);
                        if (c) {
                            defaultAddr = c.register_address || 0;
                            defaultCount = c.register_count || 1;
                        }
                    }
                    group.devices.push({
                        slave_id: 1,
                        register_address: defaultAddr,
                        register_address_hex: defaultAddr.toString(16).toUpperCase(),
                        register_count: defaultCount,
                        irat: 1.0,
                        urat: 1.0,
                        alarm_enabled: false,
                        limit_min: 0,
                        limit_max: 100
                    });
                };

                const removeDevice = (group, index) => {
                    group.devices.splice(index, 1);
                };

                const getModbusHex = (slaveId, funcCodeStr, startAddr, length) => {
                    if (slaveId == null || startAddr == null || length == null) return 'N/A';
                    const buf = new Uint8Array(6);
                    buf[0] = slaveId;
                    buf[1] = funcCodeStr === 'read_holding_registers' ? 0x03 : (funcCodeStr === 'read_input_registers' ? 0x04 : 0x03);
                    buf[2] = (startAddr >> 8) & 0xFF;
                    buf[3] = startAddr & 0xFF;
                    buf[4] = (length >> 8) & 0xFF;
                    buf[5] = length & 0xFF;

                    let crc = 0xFFFF;
                    for (let pos = 0; pos < 6; pos++) {
                        crc ^= buf[pos];
                        for (let i = 0; i < 8; i++) {
                            if ((crc & 1) !== 0) {
                                crc >>= 1;
                                crc ^= 0xA001;
                            } else {
                                crc >>= 1;
                            }
                        }
                    }
                    
                    const toHex = (n) => n.toString(16).padStart(2, '0').toUpperCase();
                    let hexArr = [];
                    for(let i=0; i<6; i++) hexArr.push(toHex(buf[i]));
                    hexArr.push(toHex(crc & 0xFF));
                    hexArr.push(toHex((crc >> 8) & 0xFF));
                    return hexArr.join(' ');
                };

                const wifiStatus = ref({});
                const wifiProfiles = ref([]);

                const fetchWifiStatus = async () => {
                    const res = await fetch('/api/wifi/status');
                    wifiStatus.value = await res.json();
                };

                const fetchWifiProfiles = async () => {
                    const res = await fetch('/api/wifi/profiles');
                    wifiProfiles.value = await res.json();
                };

                const scanWifi = async () => {
                    wifiList.value = [];
                    wifiScanned.value = false;
                    const res = await fetch('/api/wifi/scan');
                    wifiList.value = await res.json();
                    wifiScanned.value = true;
                };

                const hasProfile = (ssid) => {
                    return wifiProfiles.value.some(p => p.ssid === ssid);
                };

                const connectWifi = async (ssid, hasSavedProfile = false) => {
                    let password = "";
                    if (!hasSavedProfile) {
                        password = prompt(`Ë´ãËº∏??${ssid} ?ÑÂ?Á¢?(?•ÁÑ°ÂØÜÁ¢ºË´ãÁõ¥?•Ê?Á¢∫Â?):`);
                        if (password === null) return; // Cancelled
                    }
                    
                    const res = await fetch('/api/wifi/connect', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ ssid, password })
                    });
                    const data = await res.json();
                    if (res.ok) {
                        alert(data.message);
                        fetchWifiStatus();
                        fetchWifiProfiles();
                    } else {
                        alert(`???Â§±Ê?: ${data.message}\n${data.details || ''}`);
                    }
                };
                
                const deleteProfile = async (id) => {
                    if (confirm("Á¢∫Â?Ë¶ÅÂ?Ë®òÊ≠§Á∂≤Ë∑Ø‰∏¶Âà™?§Â?Á¢ºÂ?Ôº?)) {
                        const res = await fetch(`/api/wifi/profiles/${id}`, { method: 'DELETE' });
                        if (res.ok) {
                            fetchWifiProfiles();
                        }
                    }
                };
                
                const toggleAuto = async (profile) => {
                    const res = await fetch(`/api/wifi/profiles/${profile.id}/toggle_auto`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ is_auto_reconnect: !profile.is_auto_reconnect })
                    });
                    if (res.ok) {
                        fetchWifiProfiles();
                    }
                };
                
                const editProfile = (profile) => {
                    const password = prompt(`?çÊñ∞Ëº∏ÂÖ• ${profile.ssid} ?ÑÂ?Á¢?`);
                    if (password) {
                        connectWifi(profile.ssid, false); // reuse connect to update password
                    }
                };
                
                const fetchSystemLogs = async () => {
                    try {
                        const res = await fetch('/api/system_logs');
                        const data = await res.json();
                        if (data && data.status === 'success') {
                            systemLogs.value = data.logs;
                            // auto scroll to bottom
                            setTimeout(() => {
                                const container = document.getElementById('logContainer');
                                if (container) container.scrollTop = container.scrollHeight;
                            }, 100);
                        } else {
                            systemLogs.value = data.logs || "?°Ê??ñÂ?Á¥Ä?Ñ„Ä?;
                        }
                    } catch (e) {
                        systemLogs.value = "???Â§±Ê?: " + e.message;
                    }
                };

                const toggleAutoRefreshLogs = () => {
                    if (autoRefreshLogs.value) {
                        logInterval = setInterval(fetchSystemLogs, 3000);
                        fetchSystemLogs();
                    } else {
                        if (logInterval) clearInterval(logInterval);
                    }
                };
                
                // Watch for tab change to start/stop auto refresh
                Vue.watch(activeTab, (newTab) => {
                    if (newTab === 'logs') {
                        fetchSystemLogs();
                        if (autoRefreshLogs.value && !logInterval) {
                            logInterval = setInterval(fetchSystemLogs, 3000);
                        }
                    } else {
                        if (logInterval) {
                            clearInterval(logInterval);
                            logInterval = null;
                        }
                    }
                });

                const fetchTailscaleStatus = async () => {
                    tsStatus.value.status = 'Ê™¢Êü•‰∏?..';
                    try {
                        const res = await fetch('/api/tailscale/status');
                        tsStatus.value = await res.json();
                    } catch (e) {
                        tsStatus.value.status = '???Â§±Ê?';
                    }
                };
                
                const installTailscale = async () => {
                    if (confirm('?≥Â??®Ë??ØÂü∑Ë°?Tailscale ÂÆâË??≥Êú¨ÔºåÂèØ?ΩÈ?Ë¶?1~3 ?ÜÈ??ÇË?Á¢∫Â?Ê®πË?Ê¥æÂ∑≤???Â§ñÁ∂≤ÔºåË?ÁπºÁ??éÔ?')) {
                        tsStatus.value.status = 'ÂÆâË?‰∏?.. Ë´ãÁ??ôÂπæ?ÜÈ?ÂæåÈ??∞Êï¥??;
                        try {
                            const res = await fetch('/api/tailscale/install', { method: 'POST' });
                            const data = await res.json();
                            alert(data.message);
                        } catch (e) {
                            alert('?ºÈÄÅÂ?Ë£ùÊ?‰ª§Â§±??);
                        }
                    }
                };
                
                const uninstallTailscale = async () => {
                    if (confirm('Ë≠¶Â?ÔºöËß£?§Â?Ë£ùÂ?Ê∏ÖÈô§?Ä??Tailscale Ë®≠Â??ÇÁ¢∫ÂÆöË?ÁπºÁ??éÔ?')) {
                        try {
                            const res = await fetch('/api/tailscale/uninstall', { method: 'POST' });
                            const data = await res.json();
                            alert(data.message);
                            tsStatus.value.installed = false;
                            tsStatus.value.ip = '';
                            tsStatus.value.status = 'Ëß?ô§ÂÆâË?‰∏?..';
                        } catch (e) {
                            alert('?ºÈÄÅËß£?§Â?Ë£ùÊ?‰ª§Â§±??);
                        }
                    }
                };
                
                const tailscaleUp = async () => {
                    if (!tsAuthKey.value) {
                        alert('Ë´ãËº∏??Auth Key');
                        return;
                    }
                    tsStatus.value.status = '???‰∏?..';
                    try {
                        const res = await fetch('/api/tailscale/up', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ auth_key: tsAuthKey.value })
                        });
                        const data = await res.json();
                        alert(data.message);
                        fetchTailscaleStatus();
                        tsAuthKey.value = '';
                    } catch (e) {
                        alert('???Ë´ãÊ?Â§±Ê?');
                    }
                };
                
                const tailscaleDown = async () => {
                    if (confirm('Á¢∫Â?Ë¶ÅÊñ∑?ãÈ?Á´ØÈÄ???éÔ??∑È?ÂæåÊÇ®Â∞áÁÑ°Ê≥ïÈÄèÈ? Tailscale IP Â≠òÂ??¨Ê???)) {
                        try {
                            const res = await fetch('/api/tailscale/down', { method: 'POST' });
                            const data = await res.json();
                            alert(data.message);
                            fetchTailscaleStatus();
                        } catch (e) {
                            alert('?∑Á?Ë´ãÊ?Â§±Ê?');
                        }
                    }
                };

                onMounted(async () => {
                    await fetchSysSettings();
                    await fetchCommands();
                    await fetchSetupCommands();
                    await fetchGroups();
                    await fetchPorts();
                    await fetchWifiStatus();
                    await fetchWifiProfiles();
                    await fetchConfigs();
                    await fetchTailscaleStatus();
                    await fetchRawLogs();
                    loading.value = false;
                });

                const logout = async () => {
                    if (confirm('Á¢∫Â?Ë¶ÅÁôª?∫Â?Ôº?)) {
                        document.cookie = 'session_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;';
                        window.location.href = '/login';
                    }
                };
                
                const rebootSystem = async () => {
                    if (confirm('?†Ô? Á¢∫Â?Ë¶ÅÂ?Ê®πË?Ê¥æÈ??∞È?Ê©üÂ?Ôºü\n\n?çÊñ∞?ãÊ?Á¥ÑÈ? 1 ?ÜÈ?ÔºåÊ??ìÁ≥ªÁµ±Â??´Ê?‰∏≠Êñ∑?çÂ???)) {
                        try {
                            const res = await fetch('/api/system/reboot', { method: 'POST' });
                            const data = await res.json();
                            alert(data.message || 'Â∑≤ÈÄÅÂá∫?çÊñ∞?ãÊ??á‰ª§Ôº?);
                        } catch (e) {
                            alert('?á‰ª§?ÅÂá∫Â§±Ê?: ' + e.message);
                        }
                    }
                };
                
                const fetchConfigs = async () => {
                    try {
                        const res = await fetch('/api/configs');
                        savedConfigs.value = await res.json();
                    } catch (e) {
                        console.error("Failed to fetch configs", e);
                    }
                };

                const saveConfig = async () => {
                    if (!newConfigName.value.trim()) {
                        alert("Ë´ãËº∏?•Ë®≠ÂÆöÊ??çÁ®±");
                        return;
                    }
                    try {
                        const res = await fetch('/api/configs', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ name: newConfigName.value.trim() })
                        });
                        if (res.ok) {
                            alert("Ë®≠Â?Ê™îÂÑ≤Â≠òÊ??üÔ?");
                            newConfigName.value = "";
                            await fetchConfigs();
                        } else {
                            alert("?≤Â?Â§±Ê?");
                        }
                    } catch (e) {
                        alert("?ØË™§: " + e.message);
                    }
                };

                const loadConfig = async (cfg) => {
                    if (confirm(`?†Ô? Ë≠¶Â?ÔºöÂç≥Â∞áË??•Ë®≠ÂÆöÊ???{cfg.name}?ç„ÄÇ\n?ôÂ??ÉÂ??®Ë??ãÁõÆ?çÁ? RS485 Áæ§Á??ÅË®≠?ô„ÄÅÊ?‰ª§Ë??öË?Ë®≠Â??Ç\nÁ¢∫Â?Ë¶ÅÁπºÁ∫åÂ?Ôºü`)) {
                        try {
                            const res = await fetch(`/api/configs/${cfg.id}/load`, { method: 'POST' });
                            if (res.ok) {
                                alert("Ë®≠Â?Ê™îÂ∑≤?êÂ?ËºâÂÖ•?ÑÂ?ÔºÅÁ∂≤?ÅÂç≥Â∞áÈ??∞Êï¥?Ü‰ª•Â•óÁî®?∞Ë®≠ÂÆö„Ä?);
                                window.location.reload();
                            } else {
                                alert("ËºâÂÖ•Â§±Ê?");
                            }
                        } catch (e) {
                            alert("?ØË™§: " + e.message);
                        }
                    }
                };

                const deleteConfig = async (cfg) => {
                    if (confirm(`Á¢∫Â?Ë¶ÅÂà™?§Ë®≠ÂÆöÊ???{cfg.name}?çÂ?Ôºü`)) {
                        try {
                            const res = await fetch(`/api/configs/${cfg.id}`, { method: 'DELETE' });
                            if (res.ok) {
                                await fetchConfigs();
                            }
                        } catch (e) {
                            alert("?™Èô§?ØË™§: " + e.message);
                        }
                    }
                };

                return {
                    loading, activeTab, sysSettings, groups, ports, wifiList, wifiScanned, commandsList, setupCommandsList, setupCommandExec, execModal, wifiStatus, wifiProfiles,
                    systemLogs, autoRefreshLogs, fetchSystemLogs, toggleAutoRefreshLogs,
                    savedConfigs, newConfigName, saveConfig, loadConfig, deleteConfig, telegramRecipientsList,
                    fetchPorts, saveSysSettings, saveGroup, addDevice, removeDevice, getModbusHex,
                    saveCommands, saveSetupCommands, addSetupCommand, removeSetupCommand, onSetupCommandSelect, setupCommandPreviewHex, executeSetupCommand, testConnection, testGroupConnection, testSingleDevice, addCommand, removeCommand, applyCommandTemplate, isPowerMeterGroup,
                    scanWifi, connectWifi, fetchWifiStatus, hasProfile, deleteProfile, toggleAuto, editProfile, logout, rebootSystem,
                    tsStatus, tsAuthKey,
                    fetchTailscaleStatus,
                    installTailscale,
                    uninstallTailscale,
                    tailscaleUp,
                    tailscaleDown
                };
            }
        }).mount('#app');
    
