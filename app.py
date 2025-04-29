# # app.py
# from flask import Flask, request, jsonify,render_template, send_from_directory
# import os
# from flask import Flask, request, jsonify
# import sqlite3
# from datetime import datetime

# from ultralytics import YOLO
# import cv2

# # Load the YOLO model
# model = YOLO(r'C:\Users\mohdf\OneDrive\Desktop\ASEP\project\BEST2.pt')

# app = Flask(__name__)
 
# # Create or connect to SQLite database
# def get_db_connection():
#     conn = sqlite3.connect('parking_system.db')
#     conn.row_factory = sqlite3.Row
#     return conn

# @app.route('/dashboard')
# def serve_dashboard():
#     return render_template('index.html')

# @app.route('/detect', methods=['POST'])
# def detect_vehicle():
#     if 'image' not in request.files:
#         return "No image uploaded", 400
    
#     image_file = request.files['image']
#     image_path = f"uploads/{image_file.filename}"
#     image_file.save(image_path)

#     # Run detection
#     results = model.predict(source=image_path, save=False)

#     # Get predicted labels (you can print results[0].boxes.cls to check class predictions)
#     classes = results[0].boxes.cls.cpu().numpy()
    
#     # For now just return detected classes
#     return {"detected_classes": classes.tolist()}

# # # Home Route
# # @app.route('/')
# # def index():
# #     return "Parking System Backend Running!"

# # Insert new vehicle entry
# @app.route('/entry', methods=['POST'])
# def vehicle_entry():
#     data = request.json
#     number_plate = data['number_plate']
#     vehicle_type = data['vehicle_type']
#     slot_number = data['slot_number']
#     entry_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

#     conn = get_db_connection()
#     conn.execute('INSERT INTO vehicles (number_plate, vehicle_type, slot_number, entry_time) VALUES (?, ?, ?, ?)',
#                  (number_plate, vehicle_type, slot_number, entry_time))
#     conn.commit()
#     conn.close()

#     return jsonify({'message': 'Vehicle entry recorded successfully'}), 200

# # Show all current parked vehicles
# @app.route('/current', methods=['GET'])
# def get_current_vehicles():
#     conn = get_db_connection()
#     vehicles = conn.execute('SELECT * FROM vehicles').fetchall()
#     conn.close()

#     vehicles_list = [dict(vehicle) for vehicle in vehicles]
#     return jsonify(vehicles_list)

# # Vehicle Exit and Payment
# @app.route('/exit', methods=['POST'])
# def vehicle_exit():
#     data = request.json
#     number_plate = data['number_plate']
#     exit_time = datetime.now()

#     conn = get_db_connection()
#     vehicle = conn.execute('SELECT * FROM vehicles WHERE number_plate = ?', (number_plate,)).fetchone()

#     if vehicle is None:
#         return jsonify({'message': 'Vehicle not found'}), 404

#     entry_time = datetime.strptime(vehicle['entry_time'], "%Y-%m-%d %H:%M:%S")
#     parked_minutes = (exit_time - entry_time).total_seconds() / 60
#     payment_amount = round(parked_minutes * 1, 2)  # Example: ₹1 per minute

#     # Insert into history
#     conn.execute('INSERT INTO history (number_plate, vehicle_type, slot_number, entry_time, exit_time, payment_amount) VALUES (?, ?, ?, ?, ?, ?)',
#                  (vehicle['number_plate'], vehicle['vehicle_type'], vehicle['slot_number'], vehicle['entry_time'], exit_time.strftime("%Y-%m-%d %H:%M:%S"), payment_amount))

#     # Remove from current vehicles
#     conn.execute('DELETE FROM vehicles WHERE number_plate = ?', (number_plate,))
#     conn.commit()
#     conn.close()

#     return jsonify({'payment_amount': payment_amount}), 200

# # Show history
# @app.route('/history', methods=['GET'])
# def get_history():
#     conn = get_db_connection()
#     history = conn.execute('SELECT * FROM history ORDER BY exit_time DESC').fetchall()
#     conn.close()

#     history_list = [dict(record) for record in history]
#     return jsonify(history_list)

# if __name__ == '__main__':
#     app.run(debug=True)


# app.py
from flask import Flask, request, jsonify, render_template
import os
import sqlite3
from datetime import datetime

from ultralytics import YOLO
import cv2
import easyocr
import numpy as np

# Load the YOLO model
model = YOLO('C:/Users/mohdf/OneDrive/Desktop/ASEP/project/BEST2.pt') # Ensure this path is correct

# Initialize OCR reader
reader = easyocr.Reader(['en'])

# Flask app initialization
app = Flask(__name__)

# Database connection
def get_db_connection():
    conn = sqlite3.connect('parking_system.db')
    conn.row_factory = sqlite3.Row
    return conn

# Route to serve dashboard (HTML)
@app.route('/dashboard')
def serve_dashboard():
    return render_template('index.html')

# ----------- OCR + YOLO Helper Functions -----------

def crop_plate(image_path, results):
    boxes = results[0].boxes.xyxy.cpu().numpy()
    labels = results[0].boxes.cls.cpu().numpy()
    img = cv2.imread(image_path)

    for i, label in enumerate(labels):
        if int(label) == 0:  # Assuming label 0 = license plate
            x1, y1, x2, y2 = map(int, boxes[i])
            cropped = img[y1:y2, x1:x2]
            return cropped
    return None

def ocr_plate(cropped_img):
    gray = cv2.cvtColor(cropped_img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    result = reader.readtext(binary)
    return ' '.join([text[1] for text in result]) if result else None

# ----------- Detection Route -----------

@app.route('/detect', methods=['POST'])
def detect_vehicle():
    if 'image' not in request.files:
        return "No image uploaded", 400

    image_file = request.files['image']
    os.makedirs("uploads", exist_ok=True)
    image_path = f"uploads/{image_file.filename}"
    image_file.save(image_path)

    results = model(image_path)

    cropped = crop_plate(image_path, results)
    if cropped is None:
        return jsonify({"error": "No license plate detected"}), 404

    plate_number = ocr_plate(cropped)
    if not plate_number:
        return jsonify({"error": "OCR failed to extract text"}), 500

    return jsonify({"plate_number": plate_number}), 200

# ----------- Vehicle Entry -----------

@app.route('/entry', methods=['POST'])
def vehicle_entry():
    data = request.json
    number_plate = data['number_plate']
    vehicle_type = data['vehicle_type']
    slot_number = data['slot_number']
    entry_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    conn.execute(
        'INSERT INTO vehicles (number_plate, vehicle_type, slot_number, entry_time) VALUES (?, ?, ?, ?)',
        (number_plate, vehicle_type, slot_number, entry_time)
    )
    conn.commit()
    conn.close()

    return jsonify({'message': 'Vehicle entry recorded successfully'}), 200

# ----------- Get Current Parked Vehicles -----------

@app.route('/current', methods=['GET'])
def get_current_vehicles():
    conn = get_db_connection()
    vehicles = conn.execute('SELECT * FROM vehicles').fetchall()
    conn.close()

    vehicles_list = [dict(vehicle) for vehicle in vehicles]
    return jsonify(vehicles_list)

# ----------- Vehicle Exit and Payment -----------

@app.route('/exit', methods=['POST'])
def vehicle_exit():
    data = request.json
    number_plate = data['number_plate']
    exit_time = datetime.now()

    conn = get_db_connection()
    vehicle = conn.execute('SELECT * FROM vehicles WHERE number_plate = ?', (number_plate,)).fetchone()

    if vehicle is None:
        return jsonify({'message': 'Vehicle not found'}), 404

    entry_time = datetime.strptime(vehicle['entry_time'], "%Y-%m-%d %H:%M:%S")
    parked_minutes = (exit_time - entry_time).total_seconds() / 60
    payment_amount = round(parked_minutes * 1, 2)  # ₹1 per minute

    # Insert into history
    conn.execute('INSERT INTO history (number_plate, vehicle_type, slot_number, entry_time, exit_time, payment_amount) VALUES (?, ?, ?, ?, ?, ?)',
                 (vehicle['number_plate'], vehicle['vehicle_type'], vehicle['slot_number'], vehicle['entry_time'],
                  exit_time.strftime("%Y-%m-%d %H:%M:%S"), payment_amount))

    # Remove from current parking
    conn.execute('DELETE FROM vehicles WHERE number_plate = ?', (number_plate,))
    conn.commit()
    conn.close()

    return jsonify({'payment_amount': payment_amount}), 200

# ----------- Get Parking History -----------

@app.route('/history', methods=['GET'])
def get_history():
    conn = get_db_connection()
    history = conn.execute('SELECT * FROM history ORDER BY exit_time DESC').fetchall()
    conn.close()

    history_list = [dict(record) for record in history]
    return jsonify(history_list)

# ----------- Run Server -----------

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)