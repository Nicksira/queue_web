from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import json
import os
import datetime
from gtts import gTTS # <-- เพิ่ม gTTS
import threading

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

DATA_FILE = "queue_data.json"
TTS_FOLDER = "static/announcements" # <-- โฟลเดอร์สำหรับเก็บไฟล์เสียง MP3 ที่สร้างขึ้น

# --- TTS Function (Server Side) ---
def generate_speech_file(number):
    """แปลงข้อความเป็นไฟล์ MP3 และส่งคืนชื่อไฟล์"""
    if not os.path.exists(TTS_FOLDER):
        os.makedirs(TTS_FOLDER)
        
    text = f"เชิญคิวที่ {number} ค่ะ"
    filename = f"queue_{number}.mp3"
    filepath = os.path.join(TTS_FOLDER, filename)
    
    # ถ้าไฟล์มีอยู่แล้ว ไม่ต้องสร้างซ้ำ
    if os.path.exists(filepath):
        print(f"✅ TTS file for Q{number} already exists.")
        return filename
    
    try:
        # 🟢 ใช้ gTTS สร้างไฟล์เสียงภาษาไทย
        tts = gTTS(text=text, lang='th')
        tts.save(filepath)
        print(f"✅ Generated TTS file: {filename}")
        return filename
    except Exception as e:
        print(f"❌ Error generating TTS: {e}")
        return None

# --- Printer Function (Server Side) ---
def print_server_side(ticket_num, settings, time_str):
    """ฟังก์ชันสั่งปริ้นที่เครื่อง Server (Mac)"""
    # ... (โค้ดสั่งปริ้นเหมือนเดิม) ...
    try:
        content = f"""
   {settings['hospital_name']}
 --------------------------------
   {settings['ticket_title']}
          QUEUE NO.
          {str(ticket_num).zfill(3)}
 --------------------------------
   Time: {time_str}
   {settings['ticket_footer']}
 --------------------------------
   .
   """
        filename = "temp_ticket.txt"
        with open(filename, "w", encoding="utf-8") as f: f.write(content)
        os.system(f"lp {filename}")
        print(f"🖨️ Printing Queue {ticket_num} at Server...")
    except Exception as e:
        print(f"❌ Print Error: {e}")

# --- Database Logic (เหมือนเดิม) ---
def load_data():
    today = datetime.date.today().strftime("%Y-%m-%d")
    default_data = {
        "date": today,
        "current_queue": 0,
        "last_queue": 0,
        "queues": [],
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
                data["date"] = today
                data["current_queue"] = 0
                data["last_queue"] = 0
                data["queues"] = []
            if "settings" not in data: data["settings"] = default_data["settings"]
            return data
    except: return default_data

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# --- Routes (เหมือนเดิม) ---
@app.route('/')
def index(): return render_template('kiosk.html')
@app.route('/tv')
def tv_display(): return render_template('tv.html')
@app.route('/staff')
def staff_control(): return render_template('staff.html')

# --- Socket Events ---
@socketio.on('connect')
def handle_connect():
    data = load_data()
    emit('update_display', {'number': data['current_queue'], 'play_sound': False})
    emit('update_staff', {'waiting_count': len([q for q in data['queues'] if q['status'] == 'waiting'])})
    emit('update_settings', data['settings'])

@socketio.on('save_settings')
def handle_save_settings(settings):
    data = load_data()
    data['settings'] = settings
    save_data(data)
    emit('update_settings', settings, broadcast=True)

@socketio.on('call_next')
def handle_next():
    data = load_data()
    waiting = [q for q in data['queues'] if q['status'] == 'waiting']
    if waiting:
        next_q = waiting[0]
        next_q['status'] = 'called'
        data['current_queue'] = next_q['number']
        save_data(data)
        
        # 1. สร้างไฟล์เสียงสำหรับคิวนี้ (ทำใน thread เพื่อไม่ให้โปรแกรมค้าง)
        tts_filename = generate_speech_file(next_q['number'])
        
        # 2. ส่งชื่อไฟล์ MP3 ไปให้ TrueID Box
        emit('update_display', {'number': next_q['number'], 'sound_file': tts_filename}, broadcast=True)
        emit('update_staff', {'waiting_count': len(waiting)-1}, broadcast=True)

@socketio.on('repeat_call')
def handle_repeat():
    data = load_data()
    if data['current_queue'] > 0:
        # สร้างไฟล์เสียงซ้ำ
        tts_filename = generate_speech_file(data['current_queue'])
        # ส่งชื่อไฟล์ MP3 ไปให้ TrueID Box
        emit('update_display', {'number': data['current_queue'], 'sound_file': tts_filename}, broadcast=True)

@socketio.on('reset_system')
def handle_reset():
    data = load_data()
    data["current_queue"] = 0
    data["last_queue"] = 0
    data["queues"] = []
    save_data(data)
    emit('update_display', {'number': 0, 'sound_file': None}, broadcast=True)
    emit('update_staff', {'waiting_count': 0}, broadcast=True)

@socketio.on('get_ticket')
def handle_ticket():
    data = load_data()
    new_num = data['last_queue'] + 1
    data['last_queue'] = new_num
    current_time = datetime.datetime.now().strftime("%H:%M")
    data['queues'].append({"number": new_num, "status": "waiting", "time": current_time})
    save_data(data)
    # เราไม่จำเป็นต้อง generate speech file ตอนออกบัตรคิว เพราะจะไป generate ตอนเรียก
    print_server_side(new_num, data['settings'], current_time)
    emit('ticket_printed', {'number': new_num, 'settings': data['settings']})
    waiting_count = len([q for q in data['queues'] if q['status'] == 'waiting'])
    emit('update_staff', {'waiting_count': waiting_count}, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5005, debug=True)