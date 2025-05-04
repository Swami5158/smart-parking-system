import os
import uuid
import time
from datetime import datetime
from collections import deque

from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy

import cv2
from PIL import Image
import pytesseract
from ultralytics import YOLO
import razorpay
from fpdf import FPDF

# --- CONFIGURATION ---
RAZORPAY_KEY_ID = "rzp_test_amuSbEd1v4Drm4"
RAZORPAY_KEY_SECRET = "4gEt025e0D7J2qVlEfre9EFO"

app = Flask(__name__, static_url_path='', static_folder='static')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'uploads')
app.config['RECEIPT_FOLDER'] = os.path.join(BASE_DIR, 'receipts')
app.config['QR_FOLDER'] = os.path.join(BASE_DIR, 'static/qrcodes')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'parking.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['RECEIPT_FOLDER'], exist_ok=True)
os.makedirs(app.config['QR_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

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
    order_id = db.Column(db.String(100))
    payment_id = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# --- LOAD YOLO MODEL ---
model_path = os.path.join(BASE_DIR, "BEST2.pt")
yolo_model = YOLO(model_path)

# --- INITIALIZE SLOTS ---
@app.before_request
def setup():
    db.create_all()  # Ensure that the database schema is created
    # Check if there are no slots in the database, then add them
    if Slot.query.count() == 0:
        for i in range(10):
            db.session.add(Slot(name=f"P{i+1}"))
        db.session.commit()

# --- UTILITY FUNCTIONS ---
def extract_plate_number(image_path):
    img = cv2.imread(image_path)
    results = yolo_model(img)[0]
    for box in results.boxes:
        cls_id = int(box.cls[0])
        if cls_id == 0:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            plate_crop = img[y1:y2, x1:x2]
            gray = cv2.cvtColor(plate_crop, cv2.COLOR_BGR2GRAY)
            text = pytesseract.image_to_string(
                gray, config='--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
            )
            return text.strip().replace(" ", "").replace("\n", "")
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
    return receipt_id

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

    filename = f"{uuid.uuid4()}.jpg"
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(path)

    plate = extract_plate_number(path)
    time_now = datetime.now()

    # Check if vehicle already parked
    existing = Slot.query.filter_by(plate=plate, is_occupied=True).first()
    if existing:
        return jsonify({"message": f"Vehicle with plate {plate} is already parked in slot {existing.name}", "slot": existing.name, "plate": plate})

    # Assign free slot
    free_slot = Slot.query.filter_by(is_occupied=False).first()
    if not free_slot:
        return jsonify({"message": "All slots are full"})

    free_slot.plate = plate
    free_slot.entry_time = time_now
    free_slot.is_occupied = True
    db.session.commit()

    return jsonify({"message": f"Slot {free_slot.name} assigned", "slot": free_slot.name, "plate": plate})

@app.route('/process_exit', methods=['POST'])
def process_exit():
    file = request.files.get('image')
    if not file:
        return jsonify({'error': 'No file uploaded'}), 400

    filename = f"{uuid.uuid4()}.jpg"
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(path)

    exit_plate = extract_plate_number(path)
    matched = Slot.query.filter_by(plate=exit_plate, is_occupied=True).first()
    if not matched:
        return jsonify({'error': f"No match found for plate {exit_plate}"}), 404

    entry_time = matched.entry_time
    duration_seconds = (datetime.now() - entry_time).total_seconds()
    cost = int(duration_seconds)

    order = razorpay_client.order.create({
        "amount": cost * 100,
        "currency": "INR",
        "payment_capture": 1,
        "receipt": f"receipt_{exit_plate}_{int(time.time())}"
    })

    payment = Payment(
        plate=exit_plate,
        slot=matched.name,
        entry_time=entry_time,
        duration=duration_seconds / 60,
        amount=cost,
        order_id=order['id']
    )
    db.session.add(payment)
    db.session.commit()

    return jsonify({
        "message": "Payment required",
        "order_id": order['id'],
        "amount": cost,
        "razorpay_key": RAZORPAY_KEY_ID,
        "slot_freed": matched.name,
        "plate": exit_plate
    })

@app.route('/verify_payment', methods=['POST'])
def verify_payment():
    data = request.json
    order_id = data.get('order_id')
    payment_id = data.get('payment_id')
    signature = data.get('signature')

    try:
        razorpay_client.utility.verify_payment_signature({
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': signature
        })

        payment = Payment.query.filter_by(order_id=order_id).first()
        if not payment:
            return jsonify({"error": "Payment info not found"}), 404

        receipt_id = generate_pdf_receipt(payment.plate, payment.duration, payment.amount)
        payment.receipt_id = receipt_id
        payment.payment_id = payment_id

        slot = Slot.query.filter_by(name=payment.slot).first()
        slot.is_occupied = False
        slot.plate = None
        slot.entry_time = None

        db.session.commit()

        return jsonify({"message": "Payment verified", "receipt_url": f"/receipt/{receipt_id}"})

    except razorpay.errors.SignatureVerificationError:
        return jsonify({"error": "Signature verification failed"}), 400
    except Exception as e:
        print(f"[ERROR verify_payment] {e}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/receipt/<receipt_id>')
def download_receipt(receipt_id):
    filename = f"{receipt_id}.pdf"
    filepath = os.path.join(app.config['RECEIPT_FOLDER'], filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "Receipt not found"}), 404
    return send_from_directory(app.config['RECEIPT_FOLDER'], filename, as_attachment=True, mimetype='application/pdf')

if __name__ == '__main__':
    app.run(debug=True)
