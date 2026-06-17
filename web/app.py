import logging
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from config import FLASK_HOST, FLASK_PORT, FLASK_DEBUG, SOCKETIO_CORS_ALLOWED_ORIGINS, SECRET_KEY, LOG_LEVEL, LOG_FILE
from core import Genos
import threading
import logging.handlers

app = Flask(__name__, template_folder='web/templates', static_folder='web/static')
app.config['SECRET_KEY'] = SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins=SOCKETIO_CORS_ALLOWED_ORIGINS)

handler = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=10485760, backupCount=5)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(LOG_LEVEL)

genos = None

def init_genos():
    global genos
    genos = Genos()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status', methods=['GET'])
def get_status():
    if genos:
        return jsonify(genos.get_status())
    return jsonify({"error": "Genos not initialized"}), 500

@app.route('/api/models', methods=['GET'])
def get_models():
    if genos:
        return jsonify({"models": genos.llm.list_models(), "current": genos.llm.model})
    return jsonify({"error": "Not initialized"}), 500

@app.route('/api/switch-model/<model_name>', methods=['POST'])
def switch_model(model_name):
    if genos:
        genos.switch_model(model_name)
        return jsonify({"success": True, "model": model_name})
    return jsonify({"error": "Not initialized"}), 500

@socketio.on('connect')
def handle_connect():
    emit('status', {'data': 'Connected'})

@socketio.on('start')
def handle_start():
    if genos:
        genos.start()
        emit('status', {'data': 'Started'})

@socketio.on('stop')
def handle_stop():
    if genos:
        genos.stop()
        emit('status', {'data': 'Stopped'})

@socketio.on('send_message')
def handle_message(data):
    if genos:
        text = data.get('text', '')
        genos.handle_user_input(text)
        emit('message_received', {'text': text})

if __name__ == '__main__':
    init_genos()
    socketio.run(app, host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
