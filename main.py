#!/usr/bin/env python3
import logging
from web.app import app, socketio, init_genos

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    init_genos()
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
