from flask import Flask, render_template, request, redirect, url_for
from flask_socketio import SocketIO, emit, join_room
import json
import os
import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

DATA_FILE = "queue_data.json"

# โหลดข้อมูลทั้งหมด (รวมทุกโรงพยาบาล)
def load_all_data():
    if not os.path.exists(DATA_FILE): return {}
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except: return {}

def save_all_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# ดึงข้อมูลเฉพาะโรงพยาบาลนั้นๆ (ตาม code)
def get_hospital_data(all_data, code):
    today = datetime.date.today().strftime("%Y-%m-%d")
    
    # ถ้ายังไม่มีข้อมูลของรหัสนี้ ให้สร้างใหม่
    if code not in all_data:
        all_data[code] = {
            "date": today,
            "current_queue": 0,
            "last_queue": 0,
            "queues": [],
            "settings": {
                "hospital_name": "ชื่อโรงพยาบาล (แก้ไขได้)",
                "ticket_title": "บัตรคิวตรวจโรคทั่วไป",
                "ticket_footer": "ขอบคุณที่ใช้บริการ",
                "show_logo": True
            }
        }
    
    # รีเซ็ตคิวถ้าข้ามวัน (เฉพาะรหัสนั้น)
    if all_data[code].get("date") != today:
        all_data[code]["date"] = today
        all_data[code]["current_queue"] = 0
        all_data[code]["last_queue"] = 0
        all_data[code]["queues"] = []
    
    return all_data

# --- Routes ---

# หน้าแรก: ล็อกอินใส่รหัส
@app.route('/')
def login():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def do_login():
    code = request.form.get('code')
    if code:
        return redirect(url_for('staff_control', code=code))
    return redirect(url_for('login'))

# หน้าใช้งานต่างๆ (ต้องมี code กำกับ)
@app.route('/kiosk/<code>')
def kiosk(code):
    return render_template('kiosk.html', code=code)

@app.route('/tv/<code>')
def tv_display(code):
    return render_template('tv.html', code=code)

@app.route('/staff/<code>')
def staff_control(code):
    return render_template('staff.html', code=code)

@app.route('/check_queue/<code>')
def check_queue(code):
    my_q = request.args.get('q', type=int)
    all_data = load_all_data()
    
    if code not in all_data: return "ไม่พบข้อมูลสถานพยาบาล"
    data = all_data[code]
    
    current_q = data['current_queue']
    status = "waiting"
    wait_count = 0
    
    if my_q == current_q: status = "called"
    elif my_q < current_q: status = "passed"
    else:
        waiting_list = [q for q in data['queues'] if q['status'] == 'waiting' and q['number'] < my_q]
        wait_count = len(waiting_list)
    
    return render_template('ticket_info.html', 
                           my_queue=f"{my_q:03d}", 
                           current_queue=f"{current_q:03d}",
                           wait_count=wait_count,
                           status=status,
                           date=datetime.date.today().strftime("%d/%m/%Y"),
                           hospital_name=data['settings']['hospital_name'])

# --- Socket Events (แยกห้องตาม code) ---

@socketio.on('join')
def on_join(data):
    code = data['code']
    join_room(code) # เข้าห้องเฉพาะรหัสนั้น
    
    all_data = load_all_data()
    all_data = get_hospital_data(all_data, code) # เตรียมข้อมูล
    save_all_data(all_data) # บันทึกเผื่อเป็น user ใหม่
    
    hospital_data = all_data[code]
    
    # ส่งข้อมูลเฉพาะห้องนั้น
    emit('update_settings', hospital_data['settings'], room=code)
    emit('update_display', {'number': hospital_data['current_queue'], 'play_sound': False}, room=code)
    emit('update_staff', {'waiting_count': len([q for q in hospital_data['queues'] if q['status'] == 'waiting'])}, room=code)

@socketio.on('get_ticket')
def handle_ticket(data_in):
    code = data_in['code']
    all_data = load_all_data()
    all_data = get_hospital_data(all_data, code)
    data = all_data[code]
    
    new_num = data['last_queue'] + 1
    data['last_queue'] = new_num
    current_time = datetime.datetime.now().strftime("%H:%M")
    
    data['queues'].append({"number": new_num, "status": "waiting", "time": current_time})
    save_all_data(all_data)
    
    waiting_list = [q for q in data['queues'] if q['status'] == 'waiting']
    queues_ahead = max(0, len(waiting_list) - 1)
    
    # ส่งกลับเฉพาะห้อง code นี้
    emit('ticket_printed', {
        'number': new_num, 
        'settings': data['settings'],
        'queues_ahead': queues_ahead,
        'code': code
    }, room=code)
    
    emit('update_staff', {'waiting_count': len(waiting_list)}, room=code)

@socketio.on('call_next')
def handle_next(data_in):
    code = data_in['code']
    all_data = load_all_data()
    if code not in all_data: return
    data = all_data[code]
    
    waiting = [q for q in data['queues'] if q['status'] == 'waiting']
    if waiting:
        next_q = waiting[0]
        next_q['status'] = 'called'
        data['current_queue'] = next_q['number']
        save_all_data(all_data)
        
        emit('update_display', {'number': next_q['number'], 'play_sound': True}, room=code)
        emit('update_staff', {'waiting_count': len(waiting)-1}, room=code)

@socketio.on('repeat_call')
def handle_repeat(data_in):
    code = data_in['code']
    all_data = load_all_data()
    if code not in all_data: return
    data = all_data[code]
    
    if data['current_queue'] > 0:
        emit('update_display', {'number': data['current_queue'], 'play_sound': True}, room=code)

@socketio.on('save_settings')
def handle_save(data_in):
    code = data_in['code']
    settings = data_in['settings']
    
    all_data = load_all_data()
    all_data = get_hospital_data(all_data, code)
    all_data[code]['settings'] = settings
    save_all_data(all_data)
    
    emit('update_settings', settings, room=code)

@socketio.on('reset_system')
def handle_reset(data_in):
    code = data_in['code']
    all_data = load_all_data()
    if code in all_data:
        all_data[code]["current_queue"] = 0
        all_data[code]["last_queue"] = 0
        all_data[code]["queues"] = []
        save_all_data(all_data)
        
        emit('update_display', {'number': 0, 'play_sound': False}, room=code)
        emit('update_staff', {'waiting_count': 0}, room=code)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5005)
