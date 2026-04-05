"""
block_puzzle.py  —  /home/afwanhaziq/blockpuzzle/block_puzzle.py
"""
import sqlite3, random, string, json, time, os
from flask import Blueprint, request, jsonify, g
from flask_socketio import SocketIO, join_room, leave_room, emit

block_puzzle_bp = Blueprint('block_puzzle', __name__, url_prefix='/block-puzzle')
socketio = SocketIO()

DB_PATH = os.path.join(os.path.dirname(__file__), 'block_puzzle.db')

# ── DB ─────────────────────────────────────────────────────────────────────

def init_block_puzzle_db(app):
    db = sqlite3.connect(DB_PATH)
    db.executescript('''
        CREATE TABLE IF NOT EXISTS bp_rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_code TEXT UNIQUE NOT NULL,
            created_at INTEGER NOT NULL,
            status TEXT DEFAULT 'waiting',
            p1_name TEXT, p2_name TEXT,
            p1_sid TEXT,  p2_sid TEXT,
            p1_level INTEGER DEFAULT 0, p2_level INTEGER DEFAULT 0,
            p1_moves INTEGER DEFAULT 0, p2_moves INTEGER DEFAULT 0,
            p1_time_ms INTEGER DEFAULT 0, p2_time_ms INTEGER DEFAULT 0,
            winner_id INTEGER DEFAULT NULL,
            p1_vote TEXT DEFAULT NULL, p2_vote TEXT DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS bp_state_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_code TEXT NOT NULL, player_id INTEGER NOT NULL,
            level_index INTEGER NOT NULL, blocks_json TEXT NOT NULL,
            moves INTEGER DEFAULT 0, time_ms INTEGER DEFAULT 0,
            updated_at INTEGER NOT NULL
        );
    ''')
    db.commit(); db.close()
    print(f'[block_puzzle] DB ready at {DB_PATH}')

def get_bp_db():
    db = getattr(g, '_bp_db', None)
    if db is None:
        db = g._bp_db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
    return db

def bp_query(sql, args=(), one=False):
    db = get_bp_db(); cur = db.execute(sql, args); rv = cur.fetchall(); db.commit()
    return (rv[0] if rv else None) if one else rv

def bp_mutate(sql, args=()):
    db = get_bp_db(); cur = db.execute(sql, args); db.commit(); return cur.lastrowid

def gen_room_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

@block_puzzle_bp.teardown_request
def close_bp_db(error):
    db = getattr(g, '_bp_db', None)
    if db: db.close()

def _get_room(room_code):
    db = sqlite3.connect(DB_PATH); db.row_factory = sqlite3.Row
    row = db.execute('SELECT * FROM bp_rooms WHERE room_code=?', (room_code,)).fetchone()
    db.close(); return row

def _update_room(room_code, **kwargs):
    sets = ', '.join(f'{k}=?' for k in kwargs)
    vals = list(kwargs.values()) + [room_code]
    db = sqlite3.connect(DB_PATH)
    db.execute(f'UPDATE bp_rooms SET {sets} WHERE room_code=?', vals)
    db.commit(); db.close()

def _save_state(room_code, player_id, level_index, blocks, moves, time_ms):
    db = sqlite3.connect(DB_PATH)
    db.execute('DELETE FROM bp_state_snapshots WHERE room_code=? AND player_id=? AND level_index=?',
               (room_code, player_id, level_index))
    db.execute('INSERT INTO bp_state_snapshots '
               '(room_code,player_id,level_index,blocks_json,moves,time_ms,updated_at) '
               'VALUES (?,?,?,?,?,?,?)',
               (room_code, player_id, level_index, json.dumps(blocks), moves, time_ms, int(time.time())))
    db.commit(); db.close()

# ── REST ───────────────────────────────────────────────────────────────────

@block_puzzle_bp.route('/api/game/create', methods=['POST'])
def create_game():
    data = request.get_json() or {}
    name = data.get('display_name', 'Player 1')[:20]
    for _ in range(10):
        code = gen_room_code()
        if not bp_query('SELECT id FROM bp_rooms WHERE room_code=?', (code,), one=True):
            break
    bp_mutate('INSERT INTO bp_rooms (room_code,created_at,status,p1_name) VALUES (?,?,?,?)',
              (code, int(time.time()), 'waiting', name))
    return jsonify({'room_code': code, 'player_id': 1})

@block_puzzle_bp.route('/api/game/join', methods=['POST'])
def join_game():
    data = request.get_json() or {}
    code = data.get('room_code', '').strip().upper()
    name = data.get('display_name', 'Player 2')[:20]
    room = bp_query('SELECT * FROM bp_rooms WHERE room_code=?', (code,), one=True)
    if not room:
        return jsonify({'error': 'Room not found'}), 404
    if room['status'] != 'waiting':
        return jsonify({'error': 'Room is full or already started'}), 400
    bp_mutate('UPDATE bp_rooms SET p2_name=?, status=? WHERE room_code=?', (name, 'playing', code))
    return jsonify({'room_code': code, 'player_id': 2, 'opponent_name': room['p1_name']})

@block_puzzle_bp.route('/api/game/<room_code>', methods=['GET'])
def get_game(room_code):
    room = bp_query('SELECT * FROM bp_rooms WHERE room_code=?', (room_code.upper(),), one=True)
    if not room: return jsonify({'error': 'Not found'}), 404
    return jsonify(dict(room))

# ── SOCKETIO ───────────────────────────────────────────────────────────────

@socketio.on('join_room')
def handle_join_room(data):
    room_code    = data.get('room_code','').upper()
    player_id    = int(data.get('player_id',1))
    display_name = data.get('display_name', f'Player {player_id}')[:20]
    sid = request.sid
    room = _get_room(room_code)
    if not room: emit('error',{'message':'Room not found'}); return
    if player_id == 1:
        _update_room(room_code, p1_sid=sid, p1_name=display_name)
        opponent_name = room['p2_name'] or ''
    else:
        _update_room(room_code, p2_sid=sid, p2_name=display_name)
        opponent_name = room['p1_name'] or ''
    join_room(room_code)
    emit('room_joined', {'room_code':room_code,'player_id':player_id,'opponent_name':opponent_name})
    emit('opponent_joined', {'opponent_name':display_name}, to=room_code, skip_sid=sid)

@socketio.on('section_chosen')
def handle_section_chosen(data):
    room_code = data.get('room_code','').upper()
    section   = int(data.get('section', 0))
    _update_room(room_code, p1_level=section*10)
    emit('section_chosen', {'section':section}, to=room_code, skip_sid=request.sid)

@socketio.on('state_update')
def handle_state_update(data):
    room_code   = data.get('room_code','').upper()
    player_id   = int(data.get('player_id',1))
    level_index = int(data.get('level_index',0))
    blocks      = data.get('blocks',[])
    moves       = int(data.get('moves',0))
    time_ms     = int(data.get('time_ms',0))
    _save_state(room_code, player_id, level_index, blocks, moves, time_ms)
    if player_id==1: _update_room(room_code, p1_level=level_index, p1_moves=moves)
    else:            _update_room(room_code, p2_level=level_index, p2_moves=moves)
    emit('opponent_state', {'level_index':level_index,'blocks':blocks,'moves':moves,'time_ms':time_ms},
         to=room_code, skip_sid=request.sid)

@socketio.on('level_clear')
def handle_level_clear(data):
    room_code   = data.get('room_code','').upper()
    player_id   = int(data.get('player_id',1))
    level_index = int(data.get('level_index',0))
    total_moves = int(data.get('total_moves',0))
    total_time  = int(data.get('total_time_ms',0))
    if player_id==1: _update_room(room_code, p1_level=level_index+1, p1_moves=total_moves, p1_time_ms=total_time)
    else:            _update_room(room_code, p2_level=level_index+1, p2_moves=total_moves, p2_time_ms=total_time)
    emit('opponent_cleared', {'level_index':level_index,'total_moves':total_moves},
         to=room_code, skip_sid=request.sid)

@socketio.on('match_win')
def handle_match_win(data):
    room_code   = data.get('room_code','').upper()
    player_id   = int(data.get('player_id',1))
    total_moves = int(data.get('total_moves',0))
    total_time  = int(data.get('total_time_ms',0))
    _update_room(room_code, winner_id=player_id, status='finished')
    room = _get_room(room_code)
    if not room: return
    if player_id==1:
        winner_name=room['p1_name'] or 'Player 1'; w_moves,w_time=total_moves,total_time; o_moves,o_time=room['p2_moves'],room['p2_time_ms']
    else:
        winner_name=room['p2_name'] or 'Player 2'; w_moves,w_time=total_moves,total_time; o_moves,o_time=room['p1_moves'],room['p1_time_ms']
    emit('match_result', {'winner_id':player_id,'winner_name':winner_name,
         'w_moves':w_moves,'w_time_ms':w_time,'o_moves':o_moves,'o_time_ms':o_time}, to=room_code)

@socketio.on('replay_vote')
def handle_replay_vote(data):
    room_code = data.get('room_code','').upper()
    player_id = int(data.get('player_id',1))
    vote      = data.get('vote','no')
    if player_id==1: _update_room(room_code, p1_vote=vote)
    else:            _update_room(room_code, p2_vote=vote)
    room = _get_room(room_code)
    if not room: return
    p1v, p2v = room['p1_vote'], room['p2_vote']
    emit('replay_status', {'votes':{'1':p1v or 'waiting','2':p2v or 'waiting'}}, to=room_code)
    if p1v and p2v:
        if p1v=='yes' and p2v=='yes':
            _update_room(room_code, status='playing', p1_level=0, p2_level=0,
                         p1_moves=0, p2_moves=0, p1_time_ms=0, p2_time_ms=0,
                         winner_id=None, p1_vote=None, p2_vote=None)
            emit('game_restart', {}, to=room_code)
        else:
            emit('opponent_quit', {}, to=room_code)

@socketio.on('quit_game')
def handle_quit_game(data):
    room_code = data.get('room_code','').upper()
    _update_room(room_code, status='abandoned')
    emit('opponent_quit', {}, to=room_code, skip_sid=request.sid)
    leave_room(room_code)

@socketio.on('disconnect')
def handle_disconnect():
    pass
