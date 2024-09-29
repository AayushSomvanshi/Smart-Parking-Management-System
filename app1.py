import cv2
import pickle
import cvzone
import numpy as np
from flask import Flask, render_template, request, jsonify
import base64
from flask_socketio import SocketIO, emit

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")  # Allow cross-origin requests

# Video feed
cap = cv2.VideoCapture('carPark.mp4')

# Load parking positions or initialize an empty list
try:
    with open('CarParkPos', 'rb') as f:
        posList = pickle.load(f)
except FileNotFoundError:
    posList = []

# Add zone labels
zones = ['A', 'B', 'C']
width, height = 107, 48

# Global variable to track occupied slots
occupied_slots = []

# Mouse callback function to select parking slots manually
def mouseClick(events, x, y, flags, params):
    if events == cv2.EVENT_LBUTTONDOWN:  # Left click to add positions
        posList.append((x, y))
    elif events == cv2.EVENT_RBUTTONDOWN:  # Right click to remove positions
        for i, pos in enumerate(posList):
            x1, y1 = pos
            if x1 < x < x1 + width and y1 < y < y1 + height:
                posList.pop(i)

# Function to check parking space
def checkParkingSpace(imgProcess, img):
    spaceCounter = 0
    global occupied_slots
    occupied_slots = []  # Reset the list for each frame
    
    zone_count = len(zones)  # Number of zones
    slots_per_zone = 23       # Number of slots per zone (you can change this as needed)
    
    for idx, pos in enumerate(posList):
        x, y = pos
        imgCrop = imgProcess[y:y + height, x:x + width]
        count = cv2.countNonZero(imgCrop)
        
        # Determine the zone and slot number dynamically
        zone_index = idx // slots_per_zone  # Determine which zone
        if zone_index >= zone_count:
            continue  # Skip if zone index is out of bounds
        
        zone_number = zones[zone_index]  # Get the zone letter
        slot_number = (idx % slots_per_zone) + 1  # Slot numbers start from 1
        
        full_slot_number = f"{zone_number}-{slot_number}"

        if count < 900:
            color = (0, 255, 0)  # Green for free
            spaceCounter += 1
        else:
            color = (0, 0, 255)  # Red for occupied
            occupied_slots.append(full_slot_number)

        # Annotate the slot number and draw rectangle on the image
        cvzone.putTextRect(img, full_slot_number, (x, y + height - 20), scale=1.5, thickness=2, offset=0)
        cv2.rectangle(img, pos, (pos[0] + width, pos[1] + height), color, 2)
    total_slots = 69
    cvzone.putTextRect(img, f'Free: {spaceCounter}/{total_slots}', (100, 50),
                       scale=3, thickness=5, offset=20, colorR=(0, 200, 0))
    
    return occupied_slots, spaceCounter


# Function to update parking status
def update_parking_status():
    while True:
        success, img = cap.read()
        if not success:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            continue
            
        imgGray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        imgBlur = cv2.GaussianBlur(imgGray, (3, 3), 1)
        imgThreshold = cv2.adaptiveThreshold(imgBlur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 25, 16)
        imgMedian = cv2.medianBlur(imgThreshold, 5)
        kernel = np.ones((3, 3), np.uint8)
        imgDil = cv2.dilate(imgMedian, kernel, iterations=1)

        occupied_slots, free_count = checkParkingSpace(imgDil, img)

        is_full = len(occupied_slots) == len(posList)
        
        # Encode the image in base64 format for display on the frontend
        _, buffer = cv2.imencode('.jpg', img)
        image_base64 = base64.b64encode(buffer).decode('utf-8')

        parking_status = {
            'free_slots': free_count,
            'occupied_slots': occupied_slots,
            'is_full': is_full,
            'image': image_base64
        }
        
        # Emit the parking status to all connected clients
        socketio.emit('update', parking_status)

# Route for the index page
@app.route('/')
def index():
    return render_template('livecar.html')

# Route to find car location
@app.route('/find_car_location', methods=['POST'])
def find_car_location():
    car_slot = request.form.get('slot_number')
    if car_slot in [f"{zone}-{slot}" for zone in zones for slot in range(1, 6)]:
        # Extract the zone and slot number
        zone, slot = car_slot.split('-')
        zone_index = zones.index(zone)
        slot_index = int(slot) - 1  # Convert to zero-indexed
        
        if zone_index * 5 + slot_index < len(posList):
            return jsonify({"slot": car_slot, "position": posList[zone_index * 5 + slot_index]})
    return jsonify({"error": "Invalid slot number."}), 400

# Route to manually add or remove parking positions
@app.route('/edit_positions')
def edit_positions():
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    while True:
        success, img = cap.read()
        if not success:
            break
        
        # Display all parking spaces
        for pos in posList:
            cv2.rectangle(img, pos, (pos[0] + width, pos[1] + height), (0, 255, 0), 2)
        
        cv2.imshow("Image", img)
        cv2.setMouseCallback("Image", mouseClick)

        # Press 's' to save, 'q' to quit
        key = cv2.waitKey(1)
        if key == ord('s'):  # Save the positions
            with open('CarParkPos', 'wb') as f:
                pickle.dump(posList, f)
            print("Positions saved.")
        elif key == ord('q'):  # Quit the position editor
            break

    cv2.destroyAllWindows()
    return "Positions updated."

# Updated route to handle booking a parking slot
@app.route('/book_slot', methods=['POST'])
def book_slot():
    slot = request.form.get('slot_number')
    
    if slot in [f"{zone}-{i}" for zone in zones for i in range(1, 6)]:
        # Check if the slot is occupied
        if slot in occupied_slots:
            return jsonify({"status": "error", "message": f"Slot {slot} is already occupied."}), 400
        else:
            # Logic to book the slot (e.g., mark it as occupied)
            return jsonify({"status": "success", "message": f"Slot {slot} booked successfully."})
    return jsonify({"status": "error", "message": "Slot not available."}), 400

# Main function to run the app
if __name__ == "__main__":  # Fixed here
    # Start the parking status update in a separate thread
    socketio.start_background_task(update_parking_status)
    socketio.run(app, debug=True)


import cv2
import pickle
import cvzone
import numpy as np
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
from flask_sqlalchemy import SQLAlchemy
import base64
import re

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///parking_lot.db'
db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Video feed
cap = cv2.VideoCapture('carPark.mp4')

# Load parking positions or initialize an empty list
try:
    with open('CarParkPos', 'rb') as f:
        posList = pickle.load(f)
except FileNotFoundError:
    posList = []

# Add zone labels
zones = ['A', 'B', 'C']
width, height = 107, 48

class ParkingSlot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slot_id = db.Column(db.String(10), unique=True, nullable=False)
    status = db.Column(db.String(10), default='vacant')  # 'occupied' or 'vacant'
    reg_number = db.Column(db.String(15), nullable=True)
    mob = db.Column(db.String(15), nullable=True)

def create_tables():
    db.create_all()
    if ParkingSlot.query.count() == 0:
        initial_slots = []
        for i in range(30):
            zone = chr(65 + (i // 10))
            slot_id = f"{zone}-{(i % 10) + 1}"
            initial_slots.append(ParkingSlot(slot_id=slot_id, status='vacant'))

        db.session.bulk_save_objects(initial_slots)
        db.session.commit()

# Mouse callback function for manual parking slot editing
def mouseClick(events, x, y, flags, params):
    if events == cv2.EVENT_LBUTTONDOWN:
        posList.append((x, y))
    elif events == cv2.EVENT_RBUTTONDOWN:
        for i, pos in enumerate(posList):
            x1, y1 = pos
            if x1 < x < x1 + width and y1 < y < y1 + height:
                posList.pop(i)

# Function to check parking space
def checkParkingSpace(imgProcess, img):
    spaceCounter = 0
    occupied_slots = []
    
    for idx, pos in enumerate(posList):
        x, y = pos
        imgCrop = imgProcess[y:y + height, x:x + width]
        count = cv2.countNonZero(imgCrop)
        
        zone_number = zones[idx // 10]
        slot_number = (idx % 10) + 1
        full_slot_number = f"{zone_number}-{slot_number}"

        if count < 900:
            color = (0, 255, 0)  # Green for free
            spaceCounter += 1
        else:
            color = (0, 0, 255)  # Red for occupied
            occupied_slots.append(full_slot_number)

        cvzone.putTextRect(img, full_slot_number, (x, y + height - 20), scale=1.5, thickness=2, offset=0)
        cv2.rectangle(img, pos, (pos[0] + width, pos[1] + height), color, 2)
    total_slots = 69
    cvzone.putTextRect(img, f'Free: {spaceCounter}/{total_slots}', (100, 50),
                       scale=3, thickness=5, offset=20, colorR=(0, 200, 0))
    
    return occupied_slots, spaceCounter

# Function to update parking status
def update_parking_status():
    while True:
        success, img = cap.read()
        if not success:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            continue
            
        imgGray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        imgBlur = cv2.GaussianBlur(imgGray, (3, 3), 1)
        imgThreshold = cv2.adaptiveThreshold(imgBlur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 25, 16)
        imgMedian = cv2.medianBlur(imgThreshold, 5)
        kernel = np.ones((3, 3), np.uint8)
        imgDil = cv2.dilate(imgMedian, kernel, iterations=1)

        occupied_slots, free_count = checkParkingSpace(imgDil, img)

        is_full = len(occupied_slots) == len(posList)
        
        _, buffer = cv2.imencode('.jpg', img)
        image_base64 = base64.b64encode(buffer).decode('utf-8')

        parking_status = {
            'free_slots': free_count,
            'occupied_slots': occupied_slots,
            'is_full': is_full,
            'image': image_base64
        }
        
        socketio.emit('update', parking_status)

@app.route('/')
def index():
    spots = ParkingSlot.query.all()
    vacant_count = ParkingSlot.query.filter_by(status='vacant').count()
    occupied_count = ParkingSlot.query.filter_by(status='occupied').count()
    return render_template('index.html', spots=spots, vacant_count=vacant_count, occupied_count=occupied_count)

@app.route('/book', methods=['POST'])
def book_slot():
    slot_id = request.form.get('slot_id')
    reg_number = request.form.get('reg_number')
    mob = request.form.get('mob')

    if not re.match(r'^[A-Z]{2}\d{2} \d{5}$', reg_number):
        return jsonify({'status': 'error', 'message': 'Invalid registration number format!'}), 400

    if not re.match(r'^\d{10}$', mob):
        return jsonify({'status': 'error', 'message': 'Invalid mobile number! Must be 10 digits.'}), 400

    spot = ParkingSlot.query.filter_by(slot_id=slot_id, status='vacant').first()
    if spot:
        spot.status = 'occupied'
        spot.reg_number = reg_number
        spot.mob = mob
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Slot booked successfully!'})
    
    return jsonify({'status': 'error', 'message': 'Slot is already occupied!'}), 409

@app.route('/unbook', methods=['POST'])
def unbook_slot():
    slot_id = request.form['slot_id']
    spot = ParkingSlot.query.filter_by(slot_id=slot_id, status='occupied').first()
    
    if spot:
        spot.status = 'vacant'
        spot.reg_number = None
        spot.mob = None
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Slot unbooked successfully!'})
    
    return jsonify({'status': 'error', 'message': 'Slot is already vacant!'}), 409

@app.route('/find_car', methods=['POST'])
def find_car():
    reg_number = request.form['reg_number']
    spot = ParkingSlot.query.filter_by(reg_number=reg_number).first()
    if spot:
        return jsonify({'status': 'found', 'slot_id': spot.slot_id, 'mob': spot.mob})
    return jsonify({'status': 'not_found', 'message': 'Vehicle not found!'}), 404

@app.route('/refresh', methods=['GET'])
def refresh_slots():
    spots = ParkingSlot.query.all()
    vacant_count = ParkingSlot.query.filter_by(status='vacant').count()
    occupied_count = ParkingSlot.query.filter_by(status='occupied').count()
    
    return jsonify({
        'spots': [{ 
            'slot_id': spot.slot_id, 
            'status': spot.status, 
            'reg_number': spot.reg_number, 
            'mob': spot.mob 
        } for spot in spots],
        'vacant_count': vacant_count,
        'occupied_count': occupied_count
    })

if __name__ == '__main__':
    with app.app_context():
        create_tables()  # Create tables when the application starts
    socketio.start_background_task(update_parking_status)  # Start background task
    socketio.run(app, debug=True, port=5501)  # Change 5001 to your desired port number
