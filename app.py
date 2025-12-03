from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, emit, join_room
import json
import os
import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'super-secret-key-change-this'
socketio = SocketIO(app, cors_allowed_origins="*")

DATA_FILE = "queue_data.json"
HOSPITALS_FILE = "hospitals.json"
ADMIN_PASSWORD = "admin"

def load_hospitals():
    if not os.path.exists(HOSPITALS_FILE): return {}
    try:
        with open(HOSPITALS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except: return {}

def save_hospitals(data):
    with open(HOSPITALS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def load_all_data():
    if not os.path.exists(DATA_FILE): return {}
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except: return {}

def save_all_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def get_hospital_data(all_data, code):
    today = datetime.date.today().strftime("%Y-%m-%d")
    hospitals = load_hospitals()
    default_name = "โรงพยาบาลส่งเสริมสุขภาพตำบล (แก้ไขได้)"
    if code in hospitals: default_name = hospitals[code]['name']
    
    if code not in all_data:
        all_data[code] = {
            "date": today, "current_queue": 0, "last_queue": 0, "queues": [],
            "settings": { "hospital_name": default_name, "ticket_title": "บัตรคิวตรวจโรคทั่วไป", "ticket_footer": "ขอบคุณที่ใช้บริการ", "show_logo": True }
        }
    
    if all_data[code].get("date") != today:
        all_data[code]["date"] = today
        all_data[code]["current_queue"] = 0
        all_data[code]["last_queue"] = 0
        all_data[code]["queues"] = []
    return all_data

@app.route('/')
def login(): return render_template('login.html')

@app.route('/login', methods=['POST'])
def do_login():
    code = request.form.get('code')
    hospitals = load_hospitals()
    if code in hospitals:
        if hospitals[code].get('active', True): return redirect(url_for('staff_control', code=code))
        else: return "<h1>⛔ รหัสนี้ถูกระงับการใช้งาน</h1><a href='/'>กลับหน้าแรก</a>"
    return "<h1>❌ ไม่พบรหัสสถานพยาบาลนี้</h1><a href='/'>กลับหน้าแรก</a>"

@app.route('/kiosk/<code>')
def kiosk(code): return render_template('kiosk.html', code=code)

@app.route('/tv/<code>')
def tv_display(code): return render_template('tv.html', code=code)

@app.route('/staff/<code>')
def staff_control(code): return render_template('staff.html', code=code)

@app.route('/<code>')
def short_link(code): 
    hospitals = load_hospitals()
    if code in hospitals and hospitals[code].get('active', True): return render_template('kiosk.html', code=code)
    return redirect(url_for('login'))

# 🟢 แก้ไขส่วนนี้: ส่งตัวแปร code ไปที่หน้าเว็บด้วย
@app.route('/check_queue/<code>')
def check_queue(code):
    my_q = request.args.get('q', type=int)
    all_data = load_all_data()
    if code not in all_data: all_data = get_hospital_data(all_data, code)
    
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
                           hospital_name=data['settings']['hospital_name'],
                           code=code) # <-- เพิ่มบรรทัดนี้สำคัญมาก

# --- Admin Routes ---
@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        else: return "<h1>รหัสผ่านผิด</h1><a href='/admin'>ลองใหม่</a>"
    return render_template('admin_login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'): return redirect(url_for('admin_login'))
    hospitals = load_hospitals()
    return render_template('admin_dashboard.html', hospitals=hospitals)

@app.route('/admin/add', methods=['POST'])
def admin_add():
    if not session.get('admin_logged_in'): return redirect(url_for('admin_login'))
    code = request.form.get('code')
    name = request.form.get('name')
    hospitals = load_hospitals()
    if code and name:
        hospitals[code] = {"name": name, "active": True}
        save_hospitals(hospitals)
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/toggle/<code>')
def admin_toggle(code):
    if not session.get('admin_logged_in'): return redirect(url_for('admin_login'))
    hospitals = load_hospitals()
    if code in hospitals:
        hospitals[code]['active'] = not hospitals[code]['active']
        save_hospitals(hospitals)
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete/<code>')
def admin_delete(code):
    if not session.get('admin_logged_in'): return redirect(url_for('admin_login'))
    hospitals = load_hospitals()
    if code in hospitals: del hospitals[code]; save_hospitals(hospitals)
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

# --- Socket Events ---
@socketio.on('join')
def on_join(data):
    code = data['code']
    hospitals = load_hospitals()
    if code not in hospitals or not hospitals[code].get('active', True): return 
    join_room(code)
    all_data = load_all_data()
    all_data = get_hospital_data(all_data, code)
    save_all_data(all_data)
    hospital_data = all_data[code]
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
    emit('ticket_printed', {'number': new_num, 'settings': data['settings'], 'queues_ahead': queues_ahead, 'code': code}, room=code)
    emit('update_staff', {'waiting_count': len(waiting_list)}, room=code)

@socketio.on('call_next')
def handle_next(data_in):
    code = data_in['code']
    all_data = load_all_data()
    if code in all_data:
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
    if code in all_data and all_data[code]['current_queue'] > 0:
        emit('update_display', {'number': all_data[code]['current_queue'], 'play_sound': True}, room=code)

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
        all_data[code]["current_queue"] = 0; all_data[code]["last_queue"] = 0; all_data[code]["queues"] = []
        save_all_data(all_data)
        emit('update_display', {'number': 0, 'play_sound': False}, room=code)
        emit('update_staff', {'waiting_count': 0}, room=code)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5005)
