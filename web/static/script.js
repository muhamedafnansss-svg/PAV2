const socket = io();

let genos_status = {
    is_running: false,
    is_listening: false,
    current_state: 'IDLE',
    current_model: 'llama2',
};

const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');
const sendBtn = document.getElementById('sendBtn');
const switchBtn = document.getElementById('switchBtn');
const messageInput = document.getElementById('messageInput');
const modelSelect = document.getElementById('modelSelect');
const chatHistory = document.getElementById('chatHistory');
const stateSpan = document.getElementById('state');
const modelSpan = document.getElementById('model');
const listeningSpan = document.getElementById('listening');

startBtn.addEventListener('click', () => socket.emit('start'));
stopBtn.addEventListener('click', () => socket.emit('stop'));
sendBtn.addEventListener('click', sendMessage);
switchBtn.addEventListener('click', switchModel);

function sendMessage() {
    const text = messageInput.value.trim();
    if (text) {
        socket.emit('send_message', {text: text});
        addChatMessage('user', text);
        messageInput.value = '';
    }
}

function switchModel() {
    const model = modelSelect.value;
    fetch(`/api/switch-model/${model}`, {method: 'POST'})
        .then(r => r.json())
        .then(d => console.log('Model switched:', d));
}

function addChatMessage(role, text) {
    const div = document.createElement('div');
    div.className = `chat-message ${role}-message`;
    div.textContent = text;
    chatHistory.appendChild(div);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

function updateStatus() {
    fetch('/api/status')
        .then(r => r.json())
        .then(data => {
            stateSpan.textContent = data.current_state || 'IDLE';
            modelSpan.textContent = data.current_model || 'llama2';
            listeningSpan.textContent = data.is_listening ? 'Yes' : 'No';
            genos_status = data;
        });
}

function loadModels() {
    fetch('/api/models')
        .then(r => r.json())
        .then(data => {
            modelSelect.innerHTML = '';
            data.models.forEach(model => {
                const opt = document.createElement('option');
                opt.value = model;
                opt.textContent = model;
                if (model === data.current) opt.selected = true;
                modelSelect.appendChild(opt);
            });
        });
}

socket.on('status', (data) => {
    console.log('Status:', data);
    updateStatus();
});

socket.on('message_received', (data) => {
    addChatMessage('assistant', data.text);
});

socket.on('connect', () => {
    console.log('Connected to server');
    updateStatus();
    loadModels();
});

setInterval(updateStatus, 2000);
