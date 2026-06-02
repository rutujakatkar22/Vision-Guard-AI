from flask import Flask, render_template, request, redirect, url_for, session, Response, jsonify
import cv2
from ultralytics import YOLO
import datetime
import threading
import platform
import mysql.connector

app = Flask(__name__)
app.secret_key = "secret123"

# =========================
# 🔥 LOAD MODELS
# =========================
fire_model = YOLO("fire_model.pt")
person_model = YOLO("yolov8n.pt")
weapon_model = YOLO("yolov8n.pt")

# =========================
# ⚙️ SETTINGS
# =========================
settings = {    
    "fire": True,
    "weapon": True,
    "restricted": False,
    "late": False,
    "lateTime": "09:00"
}

ZONE = (100, 100, 500, 400)

# =========================
# 💾 MYSQL CONNECTION
# =========================
def get_db():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="",   # XAMPP default
        port="3307",
        database="surveillance"
    )

def save_alert(alert_type):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO alerts (type, time) VALUES (%s, %s)",
        (alert_type, datetime.datetime.now())
    )
    conn.commit()
    conn.close()

# =========================
# 🔔 SOUND
# =========================
def play_alarm():
    def beep():
        if platform.system() == "Windows":
            import winsound
            winsound.Beep(1000, 400)
        else:
            print("\a")
    threading.Thread(target=beep).start()

# =========================
# 🚨 ALERT CONTROL
# =========================
latest_alert = {"type": None, "time": None}
last_alert_time = {}
ALERT_COOLDOWN = 5  # seconds

def trigger_alert(alert_type):
    global latest_alert

    now = datetime.datetime.now()
    last_time = last_alert_time.get(alert_type)

    if last_time and (now - last_time).seconds < ALERT_COOLDOWN:
        return

    last_alert_time[alert_type] = now

    latest_alert = {"type": alert_type, "time": str(now)}
    save_alert(alert_type)
    play_alarm()

# =========================
# 🎥 CAMERA STREAM
# =========================
def generate_frames():
    cap = cv2.VideoCapture(0)

    while True:
        success, frame = cap.read()
        if not success:
            break

        # ================= FIRE =================
        if settings["fire"]:
            results = fire_model(frame, conf=0.4)

            for box in results[0].boxes:
                cls = int(box.cls[0])
                label = fire_model.names[cls]

                if "fire" in label.lower():  # ignore smoke
                    x1, y1, x2, y2 = map(int, box.xyxy[0])

                    cv2.rectangle(frame, (x1,y1),(x2,y2),(0,0,255),2)
                    cv2.putText(frame, "FIRE!", (x1,y1-10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,255), 2)

                    trigger_alert("🔥 Fire Detected")

        # ================= WEAPON =================
        if settings["weapon"]:
            results = weapon_model(frame)

            for box in results[0].boxes:
                cls = int(box.cls[0])
                label = weapon_model.names[cls]

                if label in ["knife", "scissors"]:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])

                    cv2.rectangle(frame, (x1,y1),(x2,y2),(0,0,255),2)
                    cv2.putText(frame, "WEAPON!", (x1,y1-10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,255), 2)

                    trigger_alert("🔫 Weapon Detected")

        # ================= PERSON =================
        if settings["restricted"] or settings["late"]:
            results = person_model(frame)

            for box in results[0].boxes:
                cls = int(box.cls[0])

                if person_model.names[cls] == "person":
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    cv2.rectangle(frame, (x1,y1),(x2,y2),(0,255,0),2)

                    # 🚷 Restricted Area (center point logic)
                    if settings["restricted"]:
                        zx1, zy1, zx2, zy2 = ZONE
                        cx = (x1 + x2) // 2
                        cy = (y1 + y2) // 2

                        if zx1 < cx < zx2 and zy1 < cy < zy2:
                            cv2.putText(frame, "RESTRICTED!", (x1,y1-10),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,255), 2)
                            trigger_alert("🚷 Restricted Area")

                    # ⏰ Late Entry (dynamic time)
                    if settings["late"]:
                        now = datetime.datetime.now().strftime("%H:%M")

                        if now > settings["lateTime"]:
                            cv2.putText(frame, "LATE!", (x1,y2+20),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,255), 2)
                            trigger_alert("⏰ Late Entry")

        # Draw Zone
        if settings["restricted"]:
            zx1, zy1, zx2, zy2 = ZONE
            cv2.rectangle(frame, (zx1, zy1), (zx2, zy2), (255,0,0), 2)

        # Encode frame
        ret, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

    cap.release()

# =========================
# 🔐 LOGIN
# =========================
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['username'] == "admin" and request.form['password'] == "admin123":
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        else:
            return "Invalid Credentials"

    return render_template("login.html")

# =========================
# 📊 DASHBOARD
# =========================
@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template("dashboard.html")

# =========================
# 🎥 VIDEO
# =========================
@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

# =========================
# ⚙️ SETTINGS API
# =========================
@app.route('/update_settings', methods=['POST'])
def update_settings():
    data = request.get_json()
    settings.update(data)
    return jsonify({"status": "ok"})

# =========================
# 📊 GET LOGS
# =========================
@app.route('/get_logs')
def get_logs():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT type, time FROM alerts ORDER BY id DESC LIMIT 20")
    rows = cursor.fetchall()
    conn.close()

    return jsonify(rows)

# =========================
# 🚨 REAL-TIME ALERT
# =========================
@app.route('/get_alert')
def get_alert():
    return jsonify(latest_alert)

# =========================
# 🔓 LOGOUT
# =========================
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# =========================
# ▶️ RUN
# =========================
if __name__ == "__main__":
    app.run(debug=True)