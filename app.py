from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import json
import os
import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

DATA_FILE = "queue_data.json"

def load_data():
    today = datetime.date.today().strftime("%Y-%m-%d")
    default_data = {
        "date": today, "current_queue": 0, "last_queue": 0, "queues": [],
        "settings": {
            "hospital_name": "โรงพยาบาลส่งเสริมสุขภาพตำบลทับพริก",
            "ticket_title": "บัตรคิวตรวจโรคทั่วไป",
            "ticket_footer": "ขอบคุณที่ใช้บริการ",
            "show_logo": True
        }
    }
    if not os.path.exists(DATA_FILE): return default_data
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if data.get("date") != today:
                data = default_data
            return data
    except: return default_data

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

@app.route('/')
def index(): return render_template('kiosk.html')
@app.route('/tv')
def tv_display(): return render_template('tv.html')
@app.route('/staff')
def staff_control(): return render_template('staff.html')

# 🟢 เพิ่ม Route ใหม่สำหรับหน้า QR Code
@app.route('/ticket')
def ticket_info():
    no = request.args.get('no', '---')
    wait = request.args.get('wait', '0')
    time = request.args.get('time', '--:--')
    return render_template('ticket_info.html', no=no, wait=wait, time=time)

@socketio.on('connect')
def handle_connect():
    data = load_data()
    emit('update_settings', data['settings'])
    emit('update_staff', {'waiting_count': len([q for q in data['queues'] if q['status'] == 'waiting'])})

@socketio.on('get_ticket')
def handle_ticket():
    data = load_data()
    new_num = data['last_queue'] + 1
    data['last_queue'] = new_num
    
    current_time = datetime.datetime.now().strftime("%H:%M")
    data['queues'].append({
        "number": new_num, "status": "waiting", "time": current_time
    })
    save_data(data)
    
    waiting_list = [q for q in data['queues'] if q['status'] == 'waiting']
    queues_ahead = max(0, len(waiting_list) - 1)
    
    emit('ticket_printed', {
        'number': new_num, 
        'settings': data['settings'],
        'queues_ahead': queues_ahead
    })
    emit('update_staff', {'waiting_count': len(waiting_list)}, broadcast=True)

@socketio.on('call_next')
def handle_next():
    data = load_data()
    waiting = [q for q in data['queues'] if q['status'] == 'waiting']
    if waiting:
        next_q = waiting[0]
        next_q['status'] = 'called'
        data['current_queue'] = next_q['number']
        save_data(data)
        emit('update_display', {'number': next_q['number'], 'play_sound': True}, broadcast=True)
        emit('update_staff', {'waiting_count': len(waiting)-1}, broadcast=True)

@socketio.on('repeat_call')
def handle_repeat():
    data = load_data()
    if data['current_queue'] > 0:
        emit('update_display', {'number': data['current_queue'], 'play_sound': True}, broadcast=True)

@socketio.on('save_settings')
def handle_save(settings):
    data = load_data()
    data['settings'] = settings
    save_data(data)
    emit('update_settings', settings, broadcast=True)

@socketio.on('reset_system')
def handle_reset():
    data = load_data()
    data["current_queue"] = 0; data["last_queue"] = 0; data["queues"] = []
    save_data(data)
    emit('update_display', {'number': 0, 'play_sound': False}, broadcast=True)
    emit('update_staff', {'waiting_count': 0}, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5005)
