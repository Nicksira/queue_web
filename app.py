from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, emit, join_room
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'super-secret-key-change-this'

# 🟢 เชื่อมต่อ Database (ถ้ามี URL จาก Render ให้ใช้ ถ้าไม่มีให้ใช้ไฟล์ในเครื่อง)
db_url = os.environ.get('DATABASE_URL')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url or 'sqlite:///queue.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

ADMIN_PASSWORD = "admin"

# --- 📝 สร้างตารางฐานข้อมูล (Database Models) ---
class Hospital(db.Model):
    code = db.Column(db.String(10), primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    active = db.Column(db.Boolean, default=True)
    ticket_title = db.Column(db.String(200), default="บัตรคิวตรวจโรคทั่วไป")
    ticket_footer = db.Column(db.String(200), default="ขอบคุณที่ใช้บริการ")
    show_logo = db.Column(db.Boolean, default=True)
    
    # เก็บสถานะคิวปัจจุบัน
    current_queue = db.Column(db.Integer, default=0)
    last_queue = db.Column(db.Integer, default=0)
    last_reset_date = db.Column(db.String(20), default="")

class QueueItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    hospital_code = db.Column(db.String(10), db.ForeignKey('hospital.code'), nullable=False)
    number = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default="waiting") # waiting, called
    time = db.Column(db.String(20), nullable=False)
    date = db.Column(db.String(20), nullable=False)

# --- ฟังก์ชันช่วยโหลดข้อมูล ---
def get_or_create_hospital(code):
    hospital = Hospital.query.get(code)
    
    # ถ้าไม่มีในฐานข้อมูล ให้ลองดูจากค่า Default (เผื่อเป็นรหัสเริ่มต้น)
    if not hospital:
        default_names = {
            "02500": "โรงพยาบาลส่งเสริมสุขภาพตำบลเมืองไผ่",
            "02506": "โรงพยาบาลส่งเสริมสุขภาพตำบลทับพริก"
            # ... (ใส่เพิ่มได้)
        }
        name = default_names.get(code, "โรงพยาบาลส่งเสริมสุขภาพตำบล")
        hospital = Hospital(code=code, name=name, last_reset_date=datetime.now().strftime("%Y-%m-%d"))
        db.session.add(hospital)
        db.session.commit()
    
    # เช็คข้ามวัน (Auto Reset)
    today = datetime.now().strftime("%Y-%m-%d")
    if hospital.last_reset_date != today:
        hospital.current_queue = 0
        hospital.last_queue = 0
        hospital.last_reset_date = today
        # ลบคิวเก่าทิ้ง
        QueueItem.query.filter_by(hospital_code=code).delete()
        db.session.commit()
        
    return hospital

# --- Routes ---

@app.route('/')
def login(): return render_template('login.html')

@app.route('/login', methods=['POST'])
def do_login():
    code = request.form.get('code')
    hospital = Hospital.query.get(code)
    if hospital and hospital.active:
        return redirect(url_for('staff_control', code=code))
    elif not hospital:
         # อนุญาตให้เข้าได้และสร้าง record ใหม่เลย (Auto Register)
         get_or_create_hospital(code)
         return redirect(url_for('staff_control', code=code))
    else:
        return "<h1>⛔ รหัสนี้ถูกระงับการใช้งาน</h1><a href='/'>กลับ</a>"

@app.route('/kiosk/<code>')
def kiosk(code): return render_template('kiosk.html', code=code)
@app.route('/tv/<code>')
def tv_display(code): return render_template('tv.html', code=code)
@app.route('/staff/<code>')
def staff_control(code): return render_template('staff.html', code=code)
@app.route('/<code>')
def short_link(code): return render_template('kiosk.html', code=code)

@app.route('/check_queue/<code>')
def check_queue(code):
    my_q = request.args.get('q', type=int)
    hospital = get_or_create_hospital(code)
    
    status = "waiting"
    wait_count = 0
    
    if my_q == hospital.current_queue: status = "called"
    elif my_q < hospital.current_queue: status = "passed"
    else:
        # นับคิวที่รออยู่
        wait_count = QueueItem.query.filter(
            QueueItem.hospital_code == code,
            QueueItem.status == 'waiting',
            QueueItem.number < my_q
        ).count()
    
    return render_template('ticket_info.html', 
                           my_queue=f"{my_q:03d}", 
                           current_queue=f"{hospital.current_queue:03d}",
                           wait_count=wait_count,
                           status=status,
                           date=datetime.now().strftime("%d/%m/%Y"),
                           hospital_name=hospital.name,
                           code=code)

# --- Admin Routes ---
@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
    return render_template('admin_login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'): return redirect(url_for('admin_login'))
    hospitals = Hospital.query.all()
    return render_template('admin_dashboard.html', hospitals={h.code: h for h in hospitals}) # แปลง format ให้เข้ากับ template เดิม

@app.route('/admin/add', methods=['POST'])
def admin_add():
    if not session.get('admin_logged_in'): return redirect(url_for('admin_login'))
    code = request.form.get('code')
    name = request.form.get('name')
    if code and name:
        if not Hospital.query.get(code):
            db.session.add(Hospital(code=code, name=name))
            db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/toggle/<code>')
def admin_toggle(code):
    if not session.get('admin_logged_in'): return redirect(url_for('admin_login'))
    hospital = Hospital.query.get(code)
    if hospital:
        hospital.active = not hospital.active
        db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/delete/<code>')
def admin_delete(code):
    if not session.get('admin_logged_in'): return redirect(url_for('admin_login'))
    hospital = Hospital.query.get(code)
    if hospital:
        # ลบคิวที่เกี่ยวข้องด้วย
        QueueItem.query.filter_by(hospital_code=code).delete()
        db.session.delete(hospital)
        db.session.commit()
    return redirect(url_for('admin_dashboard'))

# --- Socket Events ---
@socketio.on('join')
def on_join(data):
    code = data['code']
    join_room(code)
    hospital = get_or_create_hospital(code)
    
    # ส่งข้อมูลกลับไป
    wait_count = QueueItem.query.filter_by(hospital_code=code, status='waiting').count()
    settings = {
        "hospital_name": hospital.name,
        "ticket_title": hospital.ticket_title,
        "ticket_footer": hospital.ticket_footer,
        "show_logo": hospital.show_logo
    }
    emit('update_settings', settings, room=code)
    emit('update_display', {'number': hospital.current_queue, 'play_sound': False}, room=code)
    emit('update_staff', {'waiting_count': wait_count}, room=code)

@socketio.on('get_ticket')
def handle_ticket(data_in):
    code = data_in['code']
    hospital = get_or_create_hospital(code)
    
    new_num = hospital.last_queue + 1
    hospital.last_queue = new_num
    
    current_time = datetime.now().strftime("%H:%M")
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    new_q = QueueItem(hospital_code=code, number=new_num, time=current_time, date=today_str)
    db.session.add(new_q)
    db.session.commit()
    
    wait_count = QueueItem.query.filter_by(hospital_code=code, status='waiting').count()
    queues_ahead = max(0, wait_count - 1)
    
    settings = {
        "hospital_name": hospital.name,
        "ticket_title": hospital.ticket_title,
        "ticket_footer": hospital.ticket_footer,
        "show_logo": hospital.show_logo
    }
    
    emit('ticket_printed', {'number': new_num, 'settings': settings, 'queues_ahead': queues_ahead, 'code': code}, room=code)
    emit('update_staff', {'waiting_count': wait_count}, room=code)

@socketio.on('call_next')
def handle_next(data_in):
    code = data_in['code']
    hospital = get_or_create_hospital(code)
    
    # หาคิวที่รออยู่ (คิวแรกสุด)
    next_q = QueueItem.query.filter_by(hospital_code=code, status='waiting').order_by(QueueItem.id).first()
    
    if next_q:
        next_q.status = 'called'
        hospital.current_queue = next_q.number
        db.session.commit()
        
        wait_count = QueueItem.query.filter_by(hospital_code=code, status='waiting').count()
        
        emit('update_display', {'number': next_q.number, 'play_sound': True}, room=code)
        emit('update_staff', {'waiting_count': wait_count}, room=code)

@socketio.on('repeat_call')
def handle_repeat(data_in):
    code = data_in['code']
    hospital = get_or_create_hospital(code)
    # ส่งเลขปัจจุบันกลับไปหาหน้าจอ TV และสั่งให้เล่นเสียง
    emit('update_display', {'number': hospital.current_queue, 'play_sound': True}, room=code)
    
@socketio.on('save_settings')
def handle_save(data_in):
    code = data_in['code']
    s = data_in['settings']
    hospital = get_or_create_hospital(code)
    
    hospital.name = s['hospital_name']
    hospital.ticket_title = s['ticket_title']
    hospital.ticket_footer = s['ticket_footer']
    hospital.show_logo = s['show_logo']
    db.session.commit()
    
    emit('update_settings', s, room=code)

@socketio.on('reset_system')
def handle_reset(data_in):
    code = data_in['code']
    hospital = get_or_create_hospital(code)
    
    hospital.current_queue = 0
    hospital.last_queue = 0
    QueueItem.query.filter_by(hospital_code=code).delete()
    db.session.commit()
    
    emit('update_display', {'number': 0, 'play_sound': False}, room=code)
    emit('update_staff', {'waiting_count': 0}, room=code)

# สร้างตารางใน Database ถ้ายังไม่มี
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5005)
