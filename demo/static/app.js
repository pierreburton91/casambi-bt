// Casambi BT Demo - Frontend JavaScript

const API = {
    networks: '/api/networks',
    connect: '/api/connect',
    disconnect: '/api/disconnect',
    status: '/api/status',
    units: '/api/units',
    unitState: (id) => `/api/units/${id}/state`,
    unitControl: (id) => `/api/units/${id}/control`,
    transports: '/api/transports',
    transportDiscover: (type) => `/api/transports/${type}/discover`
};

// State
let state = {
    discoveredNetworks: [],
    connected: false,
    networkName: null,
    networkId: null,
    units: {},
    pollInterval: null,
    availableTransports: {},
    currentTransport: null,
    transportConfigs: JSON.parse(localStorage.getItem('transportConfigs') || '{}')
};

// DOM elements
const elements = {
    status: document.getElementById('status'),
    discoverBtn: document.getElementById('discover-btn'),
    refreshBtn: document.getElementById('refresh-btn'),
    disconnectBtn: document.getElementById('disconnect-btn'),
    networkSelect: document.getElementById('network-select'),
    passwordInput: document.getElementById('password-input'),
    connectBtn: document.getElementById('connect-btn'),
    networksList: document.getElementById('networks-list'),
    unitsSection: document.getElementById('units-section'),
    unitsGrid: document.getElementById('units-grid'),
    log: document.getElementById('log'),
    // Transport elements
    transportSection: document.getElementById('transport-section'),
    transportStatus: document.getElementById('transport-status'),
    transportButtons: document.getElementById('transport-buttons'),
    transportConfig: document.getElementById('transport-config'),
    configFields: document.getElementById('config-fields'),
    testConfigBtn: document.getElementById('test-config-btn')
};

// Storage keys
const STORAGE_KEY = 'casambi-network';

// Log function
function log(message, isError = false) {
    const entry = document.createElement('div');
    entry.className = `log-entry${isError ? ' error' : ''}`;
    entry.textContent = `${new Date().toLocaleTimeString()} - ${message}`;
    elements.log.appendChild(entry);
    elements.log.scrollTop = elements.log.scrollHeight;
    console.log(isError ? 'ERROR: ' + message : message);
}

// API helper
async function apiCall(method, url, data = null) {
    try {
        const options = { method };
        if (data) {
            options.headers = { 'Content-Type': 'application/json' };
            options.body = JSON.stringify(data);
        }
        const response = await fetch(url, options);
        const result = await response.json();
        if (!result.success) {
            throw new Error(result.error || 'API call failed');
        }
        return result.data;
    } catch (error) {
        log(`API Error: ${error.message}`, true);
        throw error;
    }
}

// Update UI based on connection state
function updateUI() {
    // Status
    if (state.connected) {
        elements.status.className = 'status connected';
        elements.status.textContent = `Connected to: ${state.networkName || state.networkId || 'Network'}`;
    } else {
        elements.status.className = 'status disconnected';
        elements.status.textContent = 'Disconnected';
    }

    // Buttons - only show discover/connect if we have a transport selected
    const hasTransport = !!state.currentTransport;
    
    elements.discoverBtn.style.display = (state.connected || !hasTransport) ? 'none' : 'inline-block';
    elements.refreshBtn.style.display = (state.connected && hasTransport) ? 'inline-block' : 'none';
    elements.disconnectBtn.style.display = state.connected ? 'inline-block' : 'none';

    // Connection controls - only show if we have a transport and networks
    const showConnection = state.discoveredNetworks.length > 0 && !state.connected && hasTransport;
    elements.networkSelect.style.display = showConnection ? 'inline-block' : 'none';
    elements.passwordInput.style.display = showConnection ? 'inline-block' : 'none';
    elements.connectBtn.style.display = showConnection ? 'inline-block' : 'none';

    // Units section
    elements.unitsSection.style.display = state.connected ? 'block' : 'none';
}

// Populate network dropdown
function populateNetworks() {
    elements.networkSelect.innerHTML = '<option value="">Select a network...</option>';
    state.discoveredNetworks.forEach(network => {
        const option = document.createElement('option');
        option.value = network.address;
        option.textContent = `${network.name} (${network.address})`;
        elements.networkSelect.appendChild(option);
    });
    updateUI();
}

// Render a single unit card
function renderUnitCard(unit) {
    const card = document.createElement('div');
    card.className = `unit-card ${unit.online ? 'online' : 'offline'}`;
    card.id = `unit-${unit.uuid}`;

    // Header with name and status
    const header = document.createElement('h3');
    header.innerHTML = `${unit.name || 'Unnamed Unit'} <small>(${unit.device_role || 'Unknown'})</small>`;
    card.appendChild(header);

    // Basic info
    const info = document.createElement('div');
    info.className = 'info';
    info.innerHTML = `
        <div><span>UUID:</span> ${unit.uuid}</div>
        <div><span>Address:</span> ${unit.address || 'N/A'}</div>
        <div><span>Device ID:</span> ${unit.deviceId || 'N/A'}</div>
        <div><span>Firmware:</span> ${unit.firmwareVersion || 'N/A'}</div>
        <div><span>Status:</span> ${unit.online ? 'Online' : 'Offline'}</div>
    `;
    card.appendChild(info);

    // State display and controls
    const controls = document.createElement('div');
    controls.className = 'controls';

    if (!unit.controls || unit.controls.length === 0) {
        controls.innerHTML = '<div>No controls available</div>';
    } else {
        // Check if this is primarily a sensor
        const isSensor = unit.controls.includes('SENSOR');
        const hasControls = unit.controls.some(c => !['SENSOR'].includes(c));

        // On/Off control
        if (unit.controls.includes('ONOFF')) {
            const group = document.createElement('div');
            group.className = 'control-group';
            const label = document.createElement('label');
            label.textContent = 'On/Off:';
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.checked = unit.state?.onOff === true || unit.is_on === true;
            checkbox.addEventListener('change', () => {
                sendControl(unit.uuid, 'ONOFF', checkbox.checked ? 1 : 0);
            });
            group.appendChild(label);
            group.appendChild(checkbox);
            controls.appendChild(group);
        }

        // Dimmer control
        if (unit.controls.includes('DIMMER')) {
            const group = document.createElement('div');
            group.className = 'control-group';
            const label = document.createElement('label');
            label.textContent = 'Dimmer:';
            const slider = document.createElement('input');
            slider.type = 'range';
            slider.min = '0';
            slider.max = '255';
            slider.value = unit.state?.dimmer ?? unit.state?.level ?? 0;
            slider.addEventListener('input', () => {
                sendControl(unit.uuid, 'DIMMER', parseInt(slider.value));
            });
            const valueSpan = document.createElement('span');
            valueSpan.textContent = slider.value;
            slider.addEventListener('input', () => {
                valueSpan.textContent = slider.value;
            });
            group.appendChild(label);
            group.appendChild(slider);
            group.appendChild(valueSpan);
            controls.appendChild(group);
        }

        // White control
        if (unit.controls.includes('WHITE')) {
            const group = document.createElement('div');
            group.className = 'control-group';
            const label = document.createElement('label');
            label.textContent = 'White:';
            const slider = document.createElement('input');
            slider.type = 'range';
            slider.min = '0';
            slider.max = '255';
            slider.value = unit.state?.white ?? 0;
            slider.addEventListener('input', () => {
                sendControl(unit.uuid, 'WHITE', parseInt(slider.value));
            });
            const valueSpan = document.createElement('span');
            valueSpan.textContent = slider.value;
            slider.addEventListener('input', () => {
                valueSpan.textContent = slider.value;
            });
            group.appendChild(label);
            group.appendChild(slider);
            group.appendChild(valueSpan);
            controls.appendChild(group);
        }

        // Temperature control
        if (unit.controls.includes('TEMPERATURE')) {
            const group = document.createElement('div');
            group.className = 'control-group';
            const label = document.createElement('label');
            label.textContent = 'Temperature:';
            const slider = document.createElement('input');
            slider.type = 'range';
            slider.min = '0';
            slider.max = '255';
            slider.value = unit.state?.temperature ?? 0;
            slider.addEventListener('input', () => {
                sendControl(unit.uuid, 'TEMPERATURE', parseInt(slider.value));
            });
            const valueSpan = document.createElement('span');
            valueSpan.textContent = slider.value;
            slider.addEventListener('input', () => {
                valueSpan.textContent = slider.value;
            });
            group.appendChild(label);
            group.appendChild(slider);
            group.appendChild(valueSpan);
            controls.appendChild(group);
        }

        // RGB controls
        if (unit.controls.includes('RGB')) {
            const group = document.createElement('div');
            group.className = 'control-group';
            const label = document.createElement('label');
            label.textContent = 'RGB:';
            group.appendChild(label);

            ['red', 'green', 'blue'].forEach(color => {
                const colorLabel = document.createElement('span');
                colorLabel.textContent = color + ':';
                colorLabel.style.marginLeft = '10px';
                const colorInput = document.createElement('input');
                colorInput.type = 'range';
                colorInput.min = '0';
                colorInput.max = '255';
                colorInput.value = unit.state?.[color] ?? 0;
                colorInput.style.width = '80px';
                colorInput.addEventListener('input', () => {
                    const r = parseInt(document.getElementById(`rgb-r-${unit.uuid}`)?.value || 0);
                    const g = parseInt(document.getElementById(`rgb-g-${unit.uuid}`)?.value || 0);
                    const b = parseInt(document.getElementById(`rgb-b-${unit.uuid}`)?.value || 0);
                    sendControl(unit.uuid, 'RGB', [r, g, b]);
                });
                colorInput.id = `rgb-${color}-${unit.uuid}`;
                const valueSpan = document.createElement('span');
                valueSpan.textContent = colorInput.value;
                colorInput.addEventListener('input', () => {
                    valueSpan.textContent = colorInput.value;
                });
                group.appendChild(colorLabel);
                group.appendChild(colorInput);
                group.appendChild(valueSpan);
            });
            controls.appendChild(group);
        }

        // XY controls
        if (unit.controls.includes('XY')) {
            const group = document.createElement('div');
            group.className = 'control-group';
            const label = document.createElement('label');
            label.textContent = 'XY:';
            group.appendChild(label);

            ['x', 'y'].forEach(coord => {
                const coordLabel = document.createElement('span');
                coordLabel.textContent = coord + ':';
                coordLabel.style.marginLeft = '10px';
                const coordInput = document.createElement('input');
                coordInput.type = 'range';
                coordInput.min = '0';
                coordInput.max = '100';
                coordInput.step = '1';
                coordInput.value = Math.round((unit.state?.[coord] ?? 0) * 100);
                coordInput.style.width = '100px';
                coordInput.addEventListener('input', () => {
                    const x = parseFloat(document.getElementById(`xy-x-${unit.uuid}`)?.value || 0) / 100;
                    const y = parseFloat(document.getElementById(`xy-y-${unit.uuid}`)?.value || 0) / 100;
                    sendControl(unit.uuid, 'XY', [x, y]);
                });
                coordInput.id = `xy-${coord}-${unit.uuid}`;
                const valueSpan = document.createElement('span');
                valueSpan.textContent = (parseFloat(coordInput.value) / 100).toFixed(2);
                coordInput.addEventListener('input', () => {
                    valueSpan.textContent = (parseFloat(coordInput.value) / 100).toFixed(2);
                });
                group.appendChild(coordLabel);
                group.appendChild(coordInput);
                group.appendChild(valueSpan);
            });
            controls.appendChild(group);
        }

        // Slider control (generic)
        if (unit.controls.includes('SLIDER')) {
            const group = document.createElement('div');
            group.className = 'control-group';
            const label = document.createElement('label');
            label.textContent = 'Slider:';
            const slider = document.createElement('input');
            slider.type = 'range';
            slider.min = '0';
            slider.max = '255';
            slider.value = unit.state?.slider ?? 0;
            slider.addEventListener('input', () => {
                sendControl(unit.uuid, 'SLIDER', parseInt(slider.value));
            });
            const valueSpan = document.createElement('span');
            valueSpan.textContent = slider.value;
            slider.addEventListener('input', () => {
                valueSpan.textContent = slider.value;
            });
            group.appendChild(label);
            group.appendChild(slider);
            group.appendChild(valueSpan);
            controls.appendChild(group);
        }

        // Vertical control
        if (unit.controls.includes('VERTICAL')) {
            const group = document.createElement('div');
            group.className = 'control-group';
            const label = document.createElement('label');
            label.textContent = 'Vertical:';
            const slider = document.createElement('input');
            slider.type = 'range';
            slider.min = '0';
            slider.max = '255';
            slider.value = unit.state?.vertical ?? 0;
            slider.addEventListener('input', () => {
                sendControl(unit.uuid, 'VERTICAL', parseInt(slider.value));
            });
            const valueSpan = document.createElement('span');
            valueSpan.textContent = slider.value;
            slider.addEventListener('input', () => {
                valueSpan.textContent = slider.value;
            });
            group.appendChild(label);
            group.appendChild(slider);
            group.appendChild(valueSpan);
            controls.appendChild(group);
        }

        // Sensor display (readonly)
        if (isSensor && unit.state?.sensor !== undefined) {
            const group = document.createElement('div');
            group.className = 'control-group';
            group.innerHTML = `<label>Sensor:</label><span class="sensor-value">${unit.state.sensor}</span>`;
            controls.appendChild(group);
        }
    }

    card.appendChild(controls);
    return card;
}

// Render all units
function renderUnits() {
    elements.unitsGrid.innerHTML = '';
    Object.values(state.units).forEach(unit => {
        const card = renderUnitCard(unit);
        elements.unitsGrid.appendChild(card);
    });
}

// Update unit in state and re-render its card
function updateUnit(updatedUnit) {
    state.units[updatedUnit.uuid] = updatedUnit;
    const existingCard = document.getElementById(`unit-${updatedUnit.uuid}`);
    if (existingCard) {
        const newCard = renderUnitCard(updatedUnit);
        existingCard.replaceWith(newCard);
    }
}

// Send control command to a unit
function sendControl(unitId, controlType, value) {
    apiCall('POST', API.unitControl(unitId), { control_type: controlType, value })
        .then(() => {
            log(`Sent ${controlType}=${value} to unit ${unitId}`);
        })
        .catch(error => {
            log(`Failed to send control: ${error.message}`, true);
        });
}

// Discover networks
async function discoverNetworks() {
    if (!state.currentTransport) {
        log('Please select a transport first', true);
        return;
    }
    
    saveCurrentConfig();
    const config = state.transportConfigs[state.currentTransport] || {};
    
    log(`Discovering networks with ${state.currentTransport}...`);
    elements.discoverBtn.disabled = true;
    
    try {
        // Use transport-specific discovery if a transport is selected
        const result = await apiCall('POST', 
            API.transportDiscover(state.currentTransport),
            {config}
        );
        state.discoveredNetworks = result;
        populateNetworks();
        log(`Found ${state.discoveredNetworks.length} network(s)`);
    } catch (error) {
        log(`Discovery failed: ${error.message}`, true);
    } finally {
        elements.discoverBtn.disabled = false;
    }
}

// Connect to network
async function connectNetwork() {
    if (!state.currentTransport) {
        log('Please select a transport first', true);
        return;
    }
    
    saveCurrentConfig();
    const config = state.transportConfigs[state.currentTransport] || {};
    
    const address = elements.networkSelect.value;
    const password = elements.passwordInput.value;
    if (!address) {
        log('Please select a network', true);
        return;
    }

    log(`Connecting to ${address} with ${state.currentTransport}...`);
    elements.connectBtn.disabled = true;
    try {
        await apiCall('POST', API.connect, { 
            address, 
            password,
            transport_type: state.currentTransport,
            transport_config: config
        });
        log('Connected successfully');

        // Save to localStorage for persistence
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ 
            address, 
            password,
            transport_type: state.currentTransport,
            transport_config: config
        }));

        // Fetch initial units
        await fetchUnits();

        // Start polling
        startPolling();

        // Update state and UI
        await updateConnectionStatus();
        updateUI();
    } catch (error) {
        log(`Connection failed: ${error.message}`, true);
    } finally {
        elements.connectBtn.disabled = false;
    }
}

// Disconnect from network
async function disconnectNetwork() {
    log('Disconnecting...');
    try {
        await apiCall('POST', API.disconnect);
        log('Disconnected');

        // Clear from localStorage
        localStorage.removeItem(STORAGE_KEY);

        // Stop polling
        stopPolling();

        // Reset state
        state.connected = false;
        state.networkName = null;
        state.networkId = null;
        state.units = {};

        // Update UI
        updateUI();
        renderUnits();
    } catch (error) {
        log(`Disconnection failed: ${error.message}`, true);
    }
}

// Fetch units from server
async function fetchUnits() {
    try {
        state.units = await apiCall('GET', API.units);
        renderUnits();
        log(`Loaded ${Object.keys(state.units).length} unit(s)`);
    } catch (error) {
        log(`Failed to fetch units: ${error.message}`, true);
    }
}

// Update connection status from server
async function updateConnectionStatus() {
    try {
        const status = await apiCall('GET', API.status);
        state.connected = status.connected || false;
        state.networkName = status.network_name || null;
        state.networkId = status.network_id || null;
        if (status.error) {
            log(`Connection error: ${status.error}`, true);
        }
    } catch (error) {
        log(`Failed to get status: ${error.message}`, true);
        state.connected = false;
    }
}

// Start polling for unit updates
function startPolling() {
    if (state.pollInterval) {
        stopPolling();
    }
    state.pollInterval = setInterval(fetchUnits, 3000);
    log('Started polling for unit updates (every 3s)');
}

// Stop polling
function stopPolling() {
    if (state.pollInterval) {
        clearInterval(state.pollInterval);
        state.pollInterval = null;
        log('Stopped polling');
    }
}

// Try to reconnect on page load if there's a saved network
async function tryReconnect() {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
        try {
            const { address, password, transport_type, transport_config } = JSON.parse(saved);
            
            // If there's a saved transport, select it first
            if (transport_type && state.availableTransports[transport_type]) {
                state.currentTransport = transport_type;
                state.transportConfigs[transport_type] = transport_config || {};
                renderTransportButtons();
                renderTransportConfig();
            }
            
            log(`Attempting to reconnect to saved network: ${address}`);
            await apiCall('POST', API.connect, { 
                address, 
                password,
                transport_type,
                transport_config: transport_config || {}
            });
            await updateConnectionStatus();
            await fetchUnits();
            startPolling();
            updateUI();
            log('Reconnected successfully');
        } catch (error) {
            log(`Auto-reconnect failed: ${error.message}`, true);
            localStorage.removeItem(STORAGE_KEY);
        }
    }
}

// Transport management functions

async function loadTransports() {
    try {
        const transports = await apiCall('GET', API.transports);
        state.availableTransports = transports;
        renderTransportButtons();
        
        // Select first available transport by default
        const firstAvailable = Object.keys(transports).find(t => transports[t].available);
        if (firstAvailable) {
            selectTransport(firstAvailable);
        }
        
        updateTransportStatus();
    } catch (error) {
        log(`Failed to load transports: ${error.message}`, true);
    }
}

function renderTransportButtons() {
    elements.transportButtons.innerHTML = '';
    
    Object.entries(state.availableTransports).forEach(([type, info]) => {
        const btn = document.createElement('button');
        btn.textContent = info.name;
        btn.className = 'transport-button';
        btn.dataset.transportType = type;
        
        if (!info.available) {
            btn.disabled = true;
            btn.title = `Missing dependency: ${info.missing_dependency || 'unknown'}`;
        }
        
        if (state.currentTransport === type) {
            btn.classList.add('selected');
        }
        
        btn.addEventListener('click', () => selectTransport(type));
        elements.transportButtons.appendChild(btn);
    });
}

function selectTransport(type) {
    if (!state.availableTransports[type]) {
        log(`Transport ${type} not available`, true);
        return;
    }
    
    if (!state.availableTransports[type].available) {
        log(`Transport ${type} is not available: missing dependency`, true);
        return;
    }
    
    state.currentTransport = type;
    renderTransportButtons();
    renderTransportConfig();
    updateTransportStatus();
    updateUI();
    log(`Selected transport: ${type}`);
}

function renderTransportConfig() {
    if (!state.currentTransport) {
        elements.transportConfig.style.display = 'none';
        return;
    }
    
    const info = state.availableTransports[state.currentTransport];
    elements.configFields.innerHTML = '';
    
    // Create input fields for each config field
    const config = state.transportConfigs[state.currentTransport] || {};
    
    // Get environment variable defaults if available
    const envDefaults = info.env_defaults || {};
    
    info.config_fields.forEach(field => {
        const configKey = `${state.currentTransport}.${field}`;
        const div = document.createElement('div');
        div.className = 'config-field';
        
        const label = document.createElement('label');
        label.textContent = field + ':';
        
        // Determine input type based on field name
        let inputType = 'text';
        if (field === 'token' || field === 'noise_psk' || field === 'password') {
            inputType = 'password';
        } else if (field === 'ssl') {
            inputType = 'checkbox';
        } else if (field === 'port' || field === 'esphome_port') {
            inputType = 'number';
        }
        
        const input = document.createElement('input');
        input.type = inputType;
        input.id = `config-${field}`;
        
        if (inputType === 'checkbox') {
            // For checkboxes: use config value, or default, or false
            input.checked = config[field] !== false;
        } else {
            // For text inputs: use config value, or env var, or default, or empty string
            // Priority: saved config > env var > hardcoded default > empty
            let value = config[field] || '';
            
            // If no saved config value, try environment variable
            if (!value && envDefaults[field]) {
                value = envDefaults[field];
            }
            
            input.value = value;
        }
        
        // Set default values (hardcoded fallback)
        const defaults = {
            'port': state.currentTransport === 'homeassistant' ? '8123' : '6053',
            'esphome_port': '6053',
            'ssl': true,
        };
        
        if (defaults[field] !== undefined && config[field] === undefined && !envDefaults[field]) {
            if (field === 'ssl') {
                input.checked = defaults[field];
            } else {
                input.value = defaults[field];
            }
        }
        
        div.appendChild(label);
        div.appendChild(input);
        elements.configFields.appendChild(div);
    });
    
    // Show save and test buttons for transports that need config
    const needsConfig = info.config_fields.length > 0;
    elements.testConfigBtn.style.display = needsConfig ? 'inline-block' : 'none';
    elements.transportConfig.style.display = needsConfig ? 'block' : 'none';
}

function saveCurrentConfig() {
    if (!state.currentTransport) return;
    
    const info = state.availableTransports[state.currentTransport];
    const config = {};
    
    info.config_fields.forEach(field => {
        const input = document.getElementById(`config-${field}`);
        if (input) {
            if (input.type === 'checkbox') {
                config[field] = input.checked;
            } else {
                config[field] = input.value;
            }
        }
    });
    
    state.transportConfigs[state.currentTransport] = config;
    localStorage.setItem('transportConfigs', JSON.stringify(state.transportConfigs));
    log(`Saved configuration for ${state.currentTransport}`);
}

async function testTransportConfig() {
    if (!state.currentTransport) return;
    
    saveCurrentConfig();
    const config = state.transportConfigs[state.currentTransport] || {};
    
    log(`Testing ${state.currentTransport} configuration...`);
    elements.testConfigBtn.disabled = true;
    
    try {
        const response = await fetch(
            API.transportDiscover(state.currentTransport),
            {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({config})
            }
        );
        const result = await response.json();
        
        if (result.success) {
            log(`Test successful! Found ${result.data.length} device(s)`);
            // Auto-populate network dropdown if successful
            state.discoveredNetworks = result.data;
            populateNetworks();
        } else {
            log(`Test failed: ${result.error}`, true);
        }
    } catch (error) {
        log(`Test failed: ${error.message}`, true);
    } finally {
        elements.testConfigBtn.disabled = false;
    }
}

function updateTransportStatus() {
    if (state.currentTransport) {
        const info = state.availableTransports[state.currentTransport];
        if (info && info.available) {
            elements.transportStatus.className = 'status connected';
            elements.transportStatus.textContent = `Using: ${info.name}`;
        } else {
            elements.transportStatus.className = 'status error';
            elements.transportStatus.textContent = `Transport ${state.currentTransport} not available`;
        }
    } else {
        elements.transportStatus.className = 'status disconnected';
        elements.transportStatus.textContent = 'Select a transport to begin';
    }
}

// Event listeners
function setupEventListeners() {
    elements.discoverBtn.addEventListener('click', discoverNetworks);
    elements.refreshBtn.addEventListener('click', discoverNetworks);
    elements.connectBtn.addEventListener('click', connectNetwork);
    elements.disconnectBtn.addEventListener('click', disconnectNetwork);
    elements.testConfigBtn.addEventListener('click', testTransportConfig);
}

// Initialize
async function init() {
    log('Initializing...');
    setupEventListeners();
    await loadTransports();
    updateUI();
    await tryReconnect();
    log('Ready');
}

// Start the app
init();
