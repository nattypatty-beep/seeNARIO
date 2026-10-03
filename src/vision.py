import cv2
import time

print("Starting camera...")

camera = cv2.VideoCapture(1)

if not camera.isOpened():
    print("ERROR: Camera could not be opened")

else:
    print("Camera opened successfully!")

    # Give the camera a moment to adjust
    time.sleep(2)

    # Take a picture
    success, frame = camera.read()

    if success:
        cv2.imwrite("scene.jpg", frame)
        print("Picture taken! Saved as scene.jpg")
    else:
        print("ERROR: Could not take picture")

camera.release()
