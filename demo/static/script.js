// Global variables
let pollingInterval = null;
let isPollingEnabled = false;
let unitsCache = {};

// DOM elements
const discoverySection = document.getElementById('discovery-section');
const connectionSection = document.getElementById('connection-section');
const dashboardSection = document.getElementById('dashboard-section');
const networksList = document.getElementById('networks-list');
const networkSelect = document.getElementById('network-select');
const passwordInput = document.getElementById('password-input');
const connectionForm = document.getElementById('connection-form');
const discoveryError = document.getElementById('discovery-error');
const connectionError = document.getElementById('connection-error');
const globalStatus = document.getElementById('global-status');
const statusMessage = document.getElementById('status-message');
const disconnectBtn = document.getElementById('disconnect-btn');
const pollingToggle = document.getElementById('polling-toggle');
const unitsContainer = document.getElementById('units-container');
const refreshNetworksBtn = document.getElementById('refresh-networks-btn');

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    fetchNetworks();
    setupEventListeners();
});

// Setup event listeners
function setupEventListeners() {
    refreshNetworksBtn.addEventListener('click', fetchNetworks);
    connectionForm.addEventListener('submit', handleConnect);
    disconnectBtn.addEventListener('click', handleDisconnect);
    pollingToggle.addEventListener('change', togglePolling);
}

// Discovery Flow
async function fetchNetworks() {
    try {
        showLoading(refreshNetworksBtn, 'Refreshing...');
        const response = await fetch('/api/networks');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await response.json();
        if (data.success) {
            populateNetworks(data.data);
            hideError(discoveryError);
        } else {
            throw new Error(data.error || 'Failed to fetch networks');
        }
    } catch (error) {
        console.error('Error fetching networks:', error);
        showError(discoveryError, `Failed to discover networks: ${error.message}`);
        hideElement(connectionSection);
    } finally {
        hideLoading(refreshNetworksBtn, 'Refresh Networks');
    }
}

function populateNetworks(networks) {
    // Clear existing options except the placeholder
    networkSelect.innerHTML = '<option value="">Choose a network...</option>';

    if (networks.length === 0) {
        showError(discoveryError, 'No networks found. Make sure Bluetooth is enabled and Casambi devices are in range.');
        hideElement(connectionSection);
        return;
    }

    // Populate dropdown
    networks.forEach(network => {
        const option = document.createElement('option');
        option.value = network.address;
        option.textContent = network.name || `Network ${network.address}`;
        networkSelect.appendChild(option);
    });

    // Show connection section
    showElement(connectionSection);
    hideError(discoveryError);
}

// Connection Flow
async function handleConnect(event) {
    event.preventDefault();
    const address = networkSelect.value;
    const password = passwordInput.value;

    if (!address || !password) {
        showError(connectionError, 'Please select a network and enter a password.');
        return;
    }

    try {
        showLoading(connectionForm.querySelector('button'), 'Connecting...');
        const response = await fetch('/api/connect', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ address, password }),
        });

        const data = await response.json();
        if (data.success) {
            hideElement(discoverySection);
            hideElement(connectionSection);
            hideError(connectionError);
            showElement(dashboardSection);
            showStatus(`Connected to network: ${networkSelect.value} (${ address})`);
            loadUnits();
        } else {
            throw new Error(data.error || 'Connection failed');
        }
    } catch (error) {
        console.error('Connection error:', error);
        showError(connectionError, `Connection failed: ${error.message}`);
    } finally {
        hideLoading(connectionForm.querySelector('button'), 'Connect');
    }
}

async function handleDisconnect() {
    try {
        const response = await fetch('/api/disconnect', {
            method: 'POST',
        });
        const data = await response.json();
        if (data.success) {
            resetUI();
        } else {
            console.error('Disconnect error:', data.error);
        }
    } catch (error) {
        console.error('Disconnect error:', error);
        resetUI(); // Reset UI anyway
    }
}

function resetUI() {
    hideElement(dashboardSection);
    showElement(discoverySection);
    hideElement(connectionSection);
    unitsContainer.innerHTML = '';
    unitsCache = {};
    stopPolling();
    pollingToggle.checked = false;
    hideError(connectionError);
    hideStatus();
}

// Dashboard Rendering
async function loadUnits() {
    try {
        const response = await fetch('/api/units');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await response.json();
        if (data.success) {
            unitsCache = {};
            unitsContainer.innerHTML = '';
            data.data.forEach(unit => {
                unitsCache[unit.id] = unit;
                const unitCard = createUnitCard(unit);
                unitsContainer.appendChild(unitCard);
            });
        } else {
            throw new Error(data.error || 'Failed to load units');
        }
    } catch (error) {
        console.error('Error loading units:', error);
        showGlobalError(`Failed to load units: ${error.message}`);
    }
}

function createUnitCard(unit) {
    const card = document.createElement('section');
    card.className = 'unit-card';
    card.setAttribute('data-unit-id', unit.id);
    if (unit.device_role === 'SENSOR') {
        card.classList.add('readonly');
    }

    const heading = document.createElement('h3');
    heading.textContent = `${unit.name} (${unit.device_role})`;
    card.appendChild(heading);

    // State display
    const stateDiv = document.createElement('div');
    stateDiv.className = 'unit-state';
    stateDiv.innerHTML = `<strong>State:</strong> ${formatUnitState(unit.state)}`;
    card.appendChild(stateDiv);

    // Controls
    if (unit.controls && unit.controls.length > 0) {
        const controlsDiv = document.createElement('div');
        controlsDiv.className = 'unit-controls';
        unit.controls.forEach(controlType => {
            const controlElement = createControlElement(unit.id, controlType, unit.state);
            if (controlElement) {
                controlsDiv.appendChild(controlElement);
            }
        });
        card.appendChild(controlsDiv);
    }

    return card;
}

function formatUnitState(state) {
    // Simple formatting, can be expanded
    return Object.entries(state).map(([key, value]) => `${key}: ${value}`).join(', ');
}

// Control Mapping
function createControlElement(unitId, controlType, currentState) {
    const controlItem = document.createElement('div');
    controlItem.className = 'control-item';

    let label, input;
    switch (controlType) {
        case 'DIMMER':
            label = document.createElement('label');
            label.textContent = 'Brightness';
            input = document.createElement('input');
            input.type = 'range';
            input.min = '0';
            input.max = '255';
            input.value = currentState.level || 0;
            input.addEventListener('input', (e) => sendControl(unitId, 'DIMMER', parseInt(e.target.value)));
            break;
        case 'ONOFF':
            input = document.createElement('button');
            input.className = 'toggle-btn';
            input.textContent = (currentState.onOff || false) ? 'On' : 'Off';
            if (currentState.onOff) input.classList.add('on');
            input.addEventListener('click', () => {
                const newValue = !currentState.onOff;
                sendControl(unitId, 'ONOFF', newValue);
                // Optimistic update
                input.textContent = newValue ? 'On' : 'Off';
                if (newValue) input.classList.add('on'); else input.classList.remove('on');
                currentState.onOff = newValue;
            });
            break;
        case 'TEMPERATURE':
            label = document.createElement('label');
            label.textContent = 'Temperature (K)';
            input = document.createElement('input');
            input.type = 'number';
            input.min = '2700';
            input.max = '6500';
            input.value = currentState.temperature || 2700;
            input.addEventListener('change', (e) => sendControl(unitId, 'TEMPERATURE', parseInt(e.target.value)));
            break;
        case 'RGB':
            // Simplified: three sliders
            const rgbContainer = document.createElement('div');
            rgbContainer.innerHTML = `
                <label>R: <input type="range" min="0" max="255" value="${currentState.red || 0}" class="rgb-slider" data-color="red"></label>
                <label>G: <input type="range" min="0" max="255" value="${currentState.green || 0}" class="rgb-slider" data-color="green"></label>
                <label>B: <input type="range" min="0" max="255" value="${currentState.blue || 0}" class="rgb-slider" data-color="blue"></label>
            `;
            rgbContainer.querySelectorAll('.rgb-slider').forEach(slider => {
                slider.addEventListener('input', () => {
                    const r = parseInt(rgbContainer.querySelector('[data-color="red"]').value);
                    const g = parseInt(rgbContainer.querySelector('[data-color="green"]').value);
                    const b = parseInt(rgbContainer.querySelector('[data-color="blue"]').value);
                    sendControl(unitId, 'RGB', { red: r, green: g, blue: b });
                });
            });
            return rgbContainer; // Return the container directly
        case 'WHITE':
            label = document.createElement('label');
            label.textContent = 'White';
            input = document.createElement('input');
            input.type = 'range';
            input.min = '0';
            input.max = '255';
            input.value = currentState.white || 0;
            input.addEventListener('input', (e) => sendControl(unitId, 'WHITE', parseInt(e.target.value)));
            break;
        case 'VERTICAL':
            label = document.createElement('label');
            label.textContent = 'Vertical';
            input = document.createElement('input');
            input.type = 'range';
            input.min = '0';
            input.max = '255';
            input.value = currentState.vertical || 0;
            input.addEventListener('input', (e) => sendControl(unitId, 'VERTICAL', parseInt(e.target.value)));
            break;
        case 'SLIDER':
            label = document.createElement('label');
            label.textContent = 'Slider';
            input = document.createElement('input');
            input.type = 'range';
            input.min = '0'; // Assume min/max from unit data, placeholder
            input.max = '255';
            input.value = currentState.slider || 0;
            input.addEventListener('input', (e) => sendControl(unitId, 'SLIDER', parseInt(e.target.value)));
            break;
        case 'COLORSOURCE':
            label = document.createElement('label');
            label.textContent = 'Color Source';
            input = document.createElement('select');
            ['TEMPERATURE', 'RGB', 'XY'].forEach(option => {
                const opt = document.createElement('option');
                opt.value = option;
                opt.textContent = option;
                input.appendChild(opt);
            });
            input.value = currentState.colorSource || 'TEMPERATURE';
            input.addEventListener('change', (e) => sendControl(unitId, 'COLORSOURCE', e.target.value));
            break;
        case 'XY':
            // Read-only for now
            const xyDisplay = document.createElement('div');
            xyDisplay.innerHTML = `<strong>XY:</strong> ${currentState.x || 0}, ${currentState.y || 0}`;
            return xyDisplay;
        case 'SENSOR':
            // Read-only display
            const sensorDisplay = document.createElement('div');
            sensorDisplay.innerHTML = `<strong>Sensor:</strong> ${currentState.value || 'N/A'}`;
            return sensorDisplay;
        default:
            return null; // Unknown control type
    }

    if (label) controlItem.appendChild(label);
    if (input) controlItem.appendChild(input);
    return controlItem;
}

// Polling System
function togglePolling() {
    isPollingEnabled = pollingToggle.checked;
    if (isPollingEnabled) {
        startPolling();
    } else {
        stopPolling();
    }
}

function startPolling() {
    if (pollingInterval) return;
    pollingInterval = setInterval(pollState, 3000); // Poll every 3 seconds
}

function stopPolling() {
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}

async function pollState() {
    try {
        const response = await fetch('/api/poll-state');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await response.json();
        if (data.success) {
            updateUnitsState(data.data);
        } else {
            console.error('Polling error:', data.error);
            stopPolling();
            pollingToggle.checked = false;
            showGlobalError('Polling failed, disabled auto-updates');
        }
    } catch (error) {
        console.error('Polling error:', error);
        stopPolling();
        pollingToggle.checked = false;
        showGlobalError('Polling failed, disabled auto-updates');
    }
}

function updateUnitsState(unitsState) {
    Object.entries(unitsState).forEach(([unitId, state]) => {
        if (unitsCache[unitId]) {
            unitsCache[unitId].state = state;
            // Update the displayed state in the card
            const card = unitsContainer.querySelector(`[data-unit-id="${unitId}"]`);
            if (card) {
                const stateDiv = card.querySelector('.unit-state');
                if (stateDiv) {
                    stateDiv.innerHTML = `<strong>State:</strong> ${formatUnitState(state)}`;
                }
                // Update control values if needed
                updateControlValues(card, state);
            }
        }
    });
}

function updateControlValues(card, state) {
    // Update specific controls based on state
    const dimmer = card.querySelector('input[type="range"][max="255"]'); // Assuming dimmer
    if (dimmer && state.level !== undefined) {
        dimmer.value = state.level;
    }
    // Add more updates as needed for other controls
}

// Control Interaction
async function sendControl(unitId, controlType, value) {
    try {
        const response = await fetch(`/api/units/${unitId}/control`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ controlType, value }),
        });

        const data = await response.json();
        if (data.success) {
            // Update cache
            if (unitsCache[unitId]) {
                unitsCache[unitId].state[controlType.toLowerCase()] = value;
            }
        } else {
            throw new Error(data.error || 'Control failed');
        }
    } catch (error) {
        console.error('Control error:', error);
        showGlobalError(`Failed to send control: ${error.message}`);
        // Revert optimistic update if needed
        // For now, just log; could implement revert logic
    }
}

// Additional Error Handling and Feedback
function showStatus(message) {
    statusMessage.textContent = message;
    showElement(statusMessage);
}

function hideStatus() {
    hideElement(statusMessage);
    statusMessage.textContent = '';
}

// UI Utility Functions
function showElement(element) {
    element.style.display = '';
}

function hideElement(element) {
    element.style.display = 'none';
}

function showError(element, message) {
    element.textContent = message;
    showElement(element);
}

function hideError(element) {
    hideElement(element);
    element.textContent = '';
}

function showLoading(button, text) {
    button.textContent = text;
    button.disabled = true;
}

function hideLoading(button, text) {
    button.textContent = text;
    button.disabled = false;
}

function showGlobalError(message) {
    globalStatus.textContent = message;
    showElement(globalStatus);
    setTimeout(() => hideElement(globalStatus), 5000); // Auto-hide after 5s
}