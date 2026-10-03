import cv2

print("Starting camera...")

camera = cv2.VideoCapture(1)

if not camera.isOpened():
    print("ERROR: Camera could not be opened")
else:
    print("Camera opened successfully!")

camera.release()
