📌 Automated Car Parking System using OCR & Computer Vision
📖 Overview
This project is a smart automated car parking system that uses YOLOv8 for real-time vehicle detection and Tesseract OCR for license plate recognition. It is built with a Flask web application and SQLite database to manage parking slot allocation, vehicle entry/exit tracking, and QR-based payment simulation.
The system updates a real-time dashboard for monitoring parking slots and generates PDF receipts for transactions.

🚀 Features
Automatic Vehicle Detection using YOLOv8

License Plate Recognition using Tesseract OCR

Real-time Dashboard for parking slot status (color-coded)

QR Code Generation for simulated payments

PDF Receipt Generation after exit

Slot Allocation & Deallocation without physical sensors

Lightweight & scalable for malls, campuses, and offices

🛠️ Tech Stack
Languages & Frameworks: Python, Flask, HTML, CSS, JavaScript

Libraries: YOLOv8, OpenCV, Tesseract OCR, SQLite, FPDF, qrcode


⚙️ How It Works
Vehicle Entry: Upload vehicle image → YOLO detects plate → OCR reads number → System assigns slot → Dashboard updates.

Vehicle Exit: Upload exit image → System calculates duration & fee → Generates QR for payment → PDF receipt created → Slot freed.

📊 Results
YOLOv8 Detection Accuracy: 90.2%

Tesseract OCR Accuracy: 88.6%

Slot Assignment Delay: <1 sec

Receipt & QR Generation: <2 sec


🏆 Contributors
Your Name – ML Model Integration, Backend Development

Team Members – Frontend, Testing, Documentation

