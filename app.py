import os
import uuid
import time
from datetime import datetime
from collections import deque
from flask import Flask, render_template, request, jsonify, send_from_directory


import cv2
from PIL import Image
import pytesseract
from ultralytics import YOLO
import qrcode
from fpdf import FPDF

import razorpay

# Replace with your Razorpay Test Mode keys
RAZORPAY_KEY_ID = "rzp_test_amuSbEd1v4Drm4"
RAZORPAY_KEY_SECRET = "4gEt025e0D7J2qVlEfre9EFO"

razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))


app = Flask(__name__, static_url_path='', static_folder='static')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['RECEIPT_FOLDER'] = 'receipts'
app.config['QR_FOLDER'] = 'static/qrcodes'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['RECEIPT_FOLDER'], exist_ok=True)
os.makedirs(app.config['QR_FOLDER'], exist_ok=True)

# Initialize parking slots
SLOTS = {f"P{i+1}": None for i in range(10)}
FREE_SLOT_QUEUE = deque(SLOTS.keys())
import os
from ultralytics import YOLO

# Build path to model relative to app.py
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
model_path = os.path.join(BASE_DIR, "BEST2.pt")

# Load the model
yolo_model = YOLO(model_path)


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

def generate_mock_qr(amount, plate):
    data = f"https://mockpayment.com/pay?plate={plate}&amount={amount}"
    filename = f"{plate}_{int(time.time())}.png"
    qr_path = os.path.join(app.config['QR_FOLDER'], filename)
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(qr_path)
    return f"/static/qrcodes/{filename}"

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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/slots')
def get_slots():
    return jsonify({slot: 'red' if SLOTS[slot] else 'green' for slot in SLOTS})

# Track payment status before allowing receipt generation
PAYMENT_TRACKER = {}

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

    # Check if the vehicle is already parked
    for slot, info in SLOTS.items():
        if info and info['plate'].upper() == plate.upper():
            return jsonify({
                "message": f"Vehicle with plate {plate} is already parked in slot {slot}",
                "slot": slot,
                "plate": plate
            })

    # If no match, assign a new slot
    if not FREE_SLOT_QUEUE:
        return jsonify({"message": "All slots are full"}), 200

    slot = FREE_SLOT_QUEUE.popleft()
    SLOTS[slot] = {"plate": plate, "entry_time": time_now}

    return jsonify({
        "message": f"Slot {slot} assigned",
        "slot": slot,
        "plate": plate
    })

@app.route('/process_exit', methods=['POST'])
def process_exit():
    try:
        file = request.files.get('image')
        if not file:
            return jsonify({'error': 'No file uploaded'}), 400

        filename = f"{uuid.uuid4()}.jpg"
        path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(path)

        exit_plate = extract_plate_number(path)
        matched_slot = None

        for slot, info in SLOTS.items():
            if info and info['plate'].upper() == exit_plate.upper():
                matched_slot = slot
                break

        if not matched_slot:
            return jsonify({'error': f"No match found for plate {exit_plate}"}), 404

        entry_time = SLOTS[matched_slot]['entry_time']
        duration_seconds = (datetime.now() - entry_time).total_seconds()
        cost = int(duration_seconds)

        # Create Razorpay order (in test mode or real as needed)
        order = razorpay_client.order.create({
            "amount": cost * 100,  # amount in paise
            "currency": "INR",
            "payment_capture": 1,
            "receipt": f"receipt_{exit_plate}_{int(time.time())}"
        })

        # Store temporary data until payment is completed
        PAYMENT_TRACKER[order['id']] = {
            'plate': exit_plate,
            'slot': matched_slot,
            'entry_time': entry_time,
            'cost': cost,
            'duration': duration_seconds / 60  # in minutes
        }

        return jsonify({
            "message": "Payment required",
            "order_id": order['id'],
            "amount": cost,
            "razorpay_key": "rzp_test_amuSbEd1v4Drm4",  # Replace with actual test key
            "slot_freed": matched_slot,
            "plate": exit_plate
        })

    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Internal server error'}), 500


@app.route('/verify_payment', methods=['POST'])
def verify_payment():
    try:
        data = request.json
        order_id = data.get('order_id')
        payment_id = data.get('payment_id')
        signature = data.get('signature')

        params_dict = {
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': signature
        }

        razorpay_client.utility.verify_payment_signature(params_dict)

        # Get transaction details
        payment_info = PAYMENT_TRACKER.pop(order_id, None)
        if not payment_info:
            return jsonify({"error": "Payment info not found"}), 404

        receipt_id = generate_pdf_receipt(
            payment_info['plate'],
            payment_info['duration'],
            payment_info['cost']
        )

        # Free the slot
        SLOTS[payment_info['slot']] = None
        FREE_SLOT_QUEUE.append(payment_info['slot'])

        return jsonify({
            "message": "Payment verified",
            "receipt_url": f"/receipt/{receipt_id}"
        })

    except razorpay.errors.SignatureVerificationError:
        return jsonify({"error": "Signature verification failed"}), 400
    except Exception as e:
        print(f"[ERROR in verify_payment]: {e}")
        return jsonify({"error": "Internal server error"}), 500


@app.route('/receipt/<receipt_id>')
def download_receipt(receipt_id):
    try:
        filename = f"{receipt_id}.pdf"
        filepath = os.path.join(app.config['RECEIPT_FOLDER'], filename)
        if not os.path.exists(filepath):
            return jsonify({"error": "Receipt not found"}), 404
        return send_from_directory(
            os.path.abspath(app.config['RECEIPT_FOLDER']),
            filename,
            as_attachment=True,
            mimetype='application/pdf'
        )
    except Exception as e:
        print(f"[ERROR in /receipt/<receipt_id>]: {e}")
        return jsonify({"error": "Internal server error"}), 500



if __name__ == '__main__':
    app.run(debug=True)
