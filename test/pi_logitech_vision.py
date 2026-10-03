import os
import time
from google import genai
from google.genai import errors
from PIL import Image

try:
    import cv2
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

client = genai.Client()

def capture_image(filename="scene.jpg"):
    print("📸 Capturing image from webcam...")
    if not HAS_OPENCV:
        print("❌ Error: OpenCV is not installed. Run: python -m pip install opencv-python")
        return None
        
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("❌ Error: Could not open webcam. Check if another app is using it.")
        return None
    
    ret, frame = cap.read()
    cap.release()
    
    if ret:
        cv2.imwrite(filename, frame)
        return filename
    else:
        print("❌ Error: Failed to grab frame from webcam.")
        return None

def main():
    image_path = capture_image("scene.jpg")
    if not image_path or not os.path.exists(image_path):
        return

    print(f"✅ Image saved to {image_path}. Loading for Gemini...")
    image = Image.open(image_path)

    prompt = (
        "Analyze the image and identify the single most important obstacle directly in front of the camera. "
        "Your response MUST consist ONLY of three values separated by the pipe symbol (|): OBJECT | POSITION | DANGER.\n"
        "- OBJECT: Name of the object (e.g., CHAIR, PERSON, WALL).\n"
        "- POSITION: Must be strictly one of: LEFT, CENTER, RIGHT.\n"
        "- DANGER: Must be strictly one of: YES, NO. (Output YES if it is an obstacle blocking the path).\n"
        "Do not include any intro, explanation, markdown formatting, or extra text.\n"
        "Example exactly like this: CHAIR | CENTER | YES"
    )

    print("🧠 Sending to Gemini 3.8 Flash...")
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=[image, prompt]
            )
            raw_output = response.text.strip()
            print(f"\n--- Raw Gemini Output ---\n{raw_output}\n")
            
            object_name, position, danger = [item.strip() for item in raw_output.split("|")]
            print("🎯 Successfully parsed data:")
            print(f"   -> Object:   {object_name}")
            print(f"   -> Position: {position}")
            print(f"   -> Danger:   {danger}")
            break
        except errors.ServerError:
            print(f"Server busy (503), retrying... (Attempt {attempt + 1}/3)")
            time.sleep(3)
        except ValueError:
            print("⚠️ Could not parse the output. Make sure Gemini used the '|' separators.")
            break

if __name__ == "__main__":
    main()
