# object detection 실행 및 서버 통신
import configparser
import socket
import threading
import time

import cv2
import torch
import RPi.GPIO as GPIO  # Import Raspberry Pi GPIO library


# 설정 가져오기
config = configparser.ConfigParser()
config.read('config.ini')

SERVER_IP = config['server']['ip']
SERVER_PORT = int(config['server']['msg_port'])


# 클라이언트 소켓 생성
client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client_socket.connect((SERVER_IP, SERVER_PORT))

# GPIO 설정
BUZZER_PIN = 12
GPIO.setmode(GPIO.BCM)
GPIO.setup(BUZZER_PIN, GPIO.OUT)
# Create PWM object with frequency 500Hz
buzzer_pwm = GPIO.PWM(BUZZER_PIN, 500)

# Load YOLOv5 model
model = torch.hub.load('ultralytics/yolov5', 'custom', 
                       path='models/barbell_tracking.pt', force_reload=True)
model.eval()

# Set device to CPU
device = torch.device('cpu')

print("<Safety System Online>")
# Initialize webcam
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 360)

# Check if the webcam is opened correctly
if not cap.isOpened():
    raise IOError("Cannot open webcam")

# Define ROI coordinates (x1, y1, x2, y2)
roi_x1, roi_y1 = 0, 180  # Top-left corner of ROI
roi_x2, roi_y2 = 640, 360  # Bottom-right corner of ROI

# Global variable to store the latest frame
latest_frame = None
lock = threading.Lock()

# Flag to control threads
running = True


def send_warning_to_server():
    warning_message = "Warning on Bench Press Zone!"
    client_socket.sendall(warning_message.encode('utf-8'))
    
    
def buzz(duration):
    # Start PWM with duty cycle 50% (half of the period)
    buzzer_pwm.start(50)
    time.sleep(duration)
    # Stop PWM
    buzzer_pwm.stop()
    GPIO.output(BUZZER_PIN, GPIO.LOW)  # Ensure buzzer is off after PWM stops


def capture_frames():
    global latest_frame, running
    while running:
        ret, frame = cap.read()
        if not ret:
            break
        with lock:
            latest_frame = frame.copy()


def process_frames():
    global running
    cooldown_start = time.time()
    
    while running:
        with lock:
            if latest_frame is None:
                continue
            frame = latest_frame.copy()
        
        # Draw ROI rectangle on a copy of the frame with red color (BGR format)
        overlay = frame.copy()
        cv2.rectangle(overlay, (roi_x1, roi_y1), (roi_x2, roi_y2), (0, 0, 255), -1)  # -1 to fill the rectangle
        
        # Add overlay with transparency
        alpha = 0.3  # Transparency factor
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
        
        # Add warning text
        cv2.putText(frame, 'WARNING', (10, 215), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 4, cv2.LINE_AA)
        
        # Crop frame to ROI
        roi_frame = frame[roi_y1:roi_y2, roi_x1:roi_x2]
        
        # Perform inference on ROI
        results = model(roi_frame)
        
        # Extract detections and apply confidence threshold
        detections = results.xyxy[0]
        high_conf_detections = [det for det in detections if det[4] > 0.8]
        
        # Check if any high-confidence objects are detected
        if len(high_conf_detections) > 0:
            # Object detected and not in cooldown
            print("<Warning!>")
            buzz(1)  # Buzz for 1 second
            send_warning_to_server()  # Send message to server
        
        # Draw bounding boxes and labels on the ROI frame for high confidence detections
        for det in high_conf_detections:
            x1, y1, x2, y2, conf, cls = det
            x1, y1, x2, y2 = map(int, [x1, y1, x2, y2])
            label = f'{model.names[int(cls)]} {conf:.2f}'
            cv2.rectangle(roi_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(roi_frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (36, 255, 12), 2)
        
        # Replace the ROI area in the original frame with the annotated ROI frame
        frame[roi_y1:roi_y2, roi_x1:roi_x2] = roi_frame
        
        # Display the frame with detected objects
        cv2.imshow('Bench Press Warning System', frame)
        
        # Check for 'q' key press to exit
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            running = False

    # Release the webcam and close all windows
    cap.release()
    cv2.destroyAllWindows()


# Create threads for capturing and processing frames
capture_thread = threading.Thread(target=capture_frames)
process_thread = threading.Thread(target=process_frames)

# Start the threads
capture_thread.start()
process_thread.start()

# Join the threads
capture_thread.join()
process_thread.join()

# Cleanup GPIO
GPIO.cleanup()

# Close the socket
client_socket.close()

print("<Program ended>")