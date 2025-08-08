# Your updated and corrected app.py file

import os
import uuid
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from ultralytics import YOLO
import cv2
import pytesseract
import qrcode
from fpdf import FPDF
from PIL import Image

# --- CONFIGURATION ---
app = Flask(__name__, static_url_path='', static_folder='static')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'uploads')
app.config['RECEIPT_FOLDER'] = os.path.join(BASE_DIR, 'static/receipts')
app.config['QR_FOLDER'] = os.path.join(BASE_DIR, 'static/qrcodes')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'parking.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['RECEIPT_FOLDER'], exist_ok=True)
os.makedirs(app.config['QR_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# --- DATABASE MODELS ---
class Slot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(10), unique=True, nullable=False)
    is_occupied = db.Column(db.Boolean, default=False)
    plate = db.Column(db.String(20), nullable=True)
    entry_time = db.Column(db.DateTime, nullable=True)

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    plate = db.Column(db.String(20))
    slot = db.Column(db.String(10))
    entry_time = db.Column(db.DateTime)
    duration = db.Column(db.Float)
    amount = db.Column(db.Integer)
    receipt_id = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# --- LOAD YOLO MODEL ---
model_path = os.path.join(BASE_DIR, "BEST2.pt")
yolo_model = YOLO(model_path)

# --- INITIALIZE SLOTS ---
initialized = False
@app.before_request
def setup_once():
    global initialized
    if not initialized:
        db.drop_all()
        db.create_all()
        for i in range(10):
            db.session.add(Slot(name=f"P{i+1}"))
        db.session.commit()
        initialized = True

# --- UTILITY FUNCTIONS ---
def extract_plate_number(image_path):
    try:
        img = cv2.imread(image_path)
        results = yolo_model(img)[0]
        for box in results.boxes:
            if int(box.cls[0]) == 0:
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                plate_crop = img[y1:y2, x1:x2]
                gray = cv2.cvtColor(plate_crop, cv2.COLOR_BGR2GRAY)
                text = pytesseract.image_to_string(
                    gray, config='--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
                )
                return text.strip().replace(" ", "").replace("\n", "")
        return "UNKNOWN"
    except Exception as e:
        app.logger.error(f"Plate extraction error: {e}")
        return "UNKNOWN"

def generate_pdf_receipt(plate, duration, amount):
    receipt_id = str(uuid.uuid4())
    receipt_path = os.path.join(app.config['RECEIPT_FOLDER'], f"{receipt_id}.pdf")
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, f"Receipt for vehicle {plate}", ln=True)
    pdf.cell(200, 10, f"Duration: {duration:.2f} minutes", ln=True)
    pdf.cell(200, 10, f"Amount: Rs. {amount}", ln=True)
    pdf.output(receipt_path)

    receipt_url = url_for('download_receipt', receipt_id=receipt_id)
    return receipt_id, receipt_url

def generate_mock_qr(text):
    qr_filename = f"{uuid.uuid4()}.png"
    output_path = os.path.join(app.config['QR_FOLDER'], qr_filename)
    img = qrcode.make(text)
    img.save(output_path)
    app.logger.info(f"QR code saved to: {output_path}")
    return qr_filename

# --- ROUTES ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/slots')
def get_slots():
    slots = Slot.query.all()
    return jsonify({slot.name: 'red' if slot.is_occupied else 'green' for slot in slots})

@app.route('/process_entry', methods=['POST'])
def process_entry():
    file = request.files.get('image')
    if not file:
        return jsonify({'error': 'No file uploaded'}), 400

    filename = secure_filename(f"{uuid.uuid4()}.jpg")
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(path)

    plate = extract_plate_number(path)
    if plate == "UNKNOWN":
        return jsonify({'error': 'Plate number could not be recognized'}), 422

    time_now = datetime.now()
    existing = Slot.query.filter_by(plate=plate, is_occupied=True).first()
    if existing:
        return jsonify({
            "message": f"Vehicle with plate {plate} is already parked in slot {existing.name}",
            "slot": existing.name, "plate": plate
        }), 200

    free_slot = Slot.query.filter_by(is_occupied=False).first()
    if not free_slot:
        return jsonify({"message": "All slots are full"}), 503

    free_slot.plate = plate
    free_slot.entry_time = time_now
    free_slot.is_occupied = True
    db.session.commit()

    return jsonify({"message": f"Slot {free_slot.name} assigned", "slot": free_slot.name, "plate": plate}), 200

@app.route('/process_exit', methods=['POST'])
def process_exit():
    file = request.files.get('image')
    if not file:
        return jsonify({'error': 'No file uploaded'}), 400

    filename = secure_filename(f"{uuid.uuid4()}.jpg")
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(path)

    exit_plate = extract_plate_number(path)
    if exit_plate == "UNKNOWN":
        return jsonify({'error': 'Unable to recognize plate'}), 422

    matched = Slot.query.filter_by(plate=exit_plate, is_occupied=True).first()
    if not matched:
        return jsonify({'error': f"No active parking found for plate {exit_plate}"}), 404

    entry_time = matched.entry_time
    exit_time = datetime.now()
    duration_seconds = (exit_time - entry_time).total_seconds()
    cost = max(10, int(duration_seconds // 60 * 2))

    receipt_id, receipt_url = generate_pdf_receipt(exit_plate, duration_seconds / 60, cost)
    qr_filename = generate_mock_qr(f"Amount: Rs.{cost} | Plate: {exit_plate}")

    # Immediately free slot
    matched.is_occupied = False
    matched.plate = None
    matched.entry_time = None
    db.session.commit()

    payment = Payment(
        plate=exit_plate,
        slot=matched.name,
        entry_time=entry_time,
        duration=duration_seconds / 60,
        amount=cost,
        receipt_id=receipt_id
    )
    db.session.add(payment)
    db.session.commit()

    return jsonify({
        'status': 'success',
        'qr_path': url_for('static', filename=f'qrcodes/{qr_filename}'),
        'slot_freed': matched.name,
        'vehicle_number': exit_plate,
        'receipt_url': receipt_url
    }), 200

@app.route('/receipt/<receipt_id>')
def download_receipt(receipt_id):
    filename = f"{receipt_id}.pdf"
    filepath = os.path.join(app.config['RECEIPT_FOLDER'], filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "Receipt not found"}), 404
    return send_from_directory(app.config['RECEIPT_FOLDER'], filename, as_attachment=True, mimetype='application/pdf')

if __name__ == '__main__':
    app.run(debug=True)
