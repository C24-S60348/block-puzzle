"""
app.py  —  Standalone Block Puzzle server
-----------------------------------------
Folder structure:

  /home/afwanhaziq/blockpuzzle/
  ├── app.py                   ← this file
  ├── block_puzzle.py
  ├── block_puzzle.db          ← auto-created
  └── static/
      └── block-puzzle/
          ├── block-puzzle.html
          ├── block-puzzle-mp.html
          └── levels.json

Install deps (once):
  source /home/afwanhaziq/quartapp/afwan_cron/venv/bin/activate
  pip install flask-socketio eventlet

Run manually:
  python app.py

Run via systemd:
  sudo systemctl start blockpuzzle
"""

import eventlet
eventlet.monkey_patch()

from flask import Flask, send_from_directory, make_response
from block_puzzle import block_puzzle_bp, init_block_puzzle_db, socketio as bp_socketio
import os
import socket as _socket

app = Flask(__name__)
app.config['SECRET_KEY'] = 'block-puzzle-secret-2024'
app.config['DATABASE']   = os.path.join(os.path.dirname(__file__), 'block_puzzle.db')

STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static', 'block-puzzle')
ASSETS_DIR = os.path.join(os.path.dirname(__file__), 'assets')

# ── Serve HTML/levels ──────────────────────────────────────────────────────
@app.route('/')
@app.route('/block-puzzle/')
def index():
    return send_from_directory(STATIC_DIR, 'block-puzzle.html')

@app.route('/block-puzzle/mp')
def mp():
    return send_from_directory(STATIC_DIR, 'block-puzzle-mp.html')

@app.route('/block-puzzle/levels.json')
def levels():
    resp = make_response(send_from_directory(STATIC_DIR, 'levels.json'))
    resp.headers['Cache-Control'] = 'public, max-age=86400'
    return resp

@app.route('/assets/<path:filename>')
def assets(filename):
    return send_from_directory(ASSETS_DIR, filename)

# ── Blueprint (REST API + SocketIO events) ─────────────────────────────────
app.register_blueprint(block_puzzle_bp)

# ── SocketIO ───────────────────────────────────────────────────────────────
bp_socketio.init_app(app, cors_allowed_origins='*', async_mode='eventlet')

# ── Entry point ────────────────────────────────────────────────────────────
if __name__ == '__main__':
    with app.app_context():
        init_block_puzzle_db(app)

    print('\n=============================================')
    print('  🎮 Block Puzzle server — port 8002')
    try:
        ip = _socket.gethostbyname(_socket.gethostname())
        print(f'  Local:   http://localhost:8002')
        print(f'  Network: http://{ip}:8002')
        print(f'  Domain:  https://afwanhaziq.my/block-puzzle/')
    except:
        pass
    print('=============================================\n')

    bp_socketio.run(app, host='0.0.0.0', port=8002, debug=False)
