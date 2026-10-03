import time
import os, glob
from google import genai
from google.genai import errors
from PIL import Image

# Initialize Gemini client
client = genai.Client()

# Target your sample image in Downloads
downloads = os.path.expanduser("~/Downloads")
matches = glob.glob(os.path.join(downloads, "sample.*"))

if not matches:
    raise FileNotFoundError("Could not find 'sample.png' or 'sample.jpg' in Downloads!")

image_path = matches[0]
print(f"Loading image from: {image_path}")
image = Image.open(image_path)

# Strict prompt demanding the 3-value output format
prompt = (
    "Analyze the image and identify the single most important object directly in front of the camera. "
    "Your response MUST consist ONLY of three comma-separated values: OBJECT, POSITION, HAZARD.\n"
    "- OBJECT: Name of the object (e.g., CHAIR, PERSON, WALL, TREE).\n"
    "- POSITION: Must be strictly one of: LEFT, CENTER, RIGHT.\n"
    "- HAZARD: Must be strictly one of: YES, NO. (Output YES if it is an obstacle blocking the path, NO if it is just in the background).\n"
    "Do not include any intro, explanation, markdown formatting, or extra text.\n"
    "Example exactly like this: TREE, CENTER, NO"
)

# Call Gemini 3.8 Flash with retry logic for 503 stability
for attempt in range(3):
    try:
        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=[image, prompt]
        )
        print("\n--- Raw Output for Pi Parsing ---")
        print(response.text.strip())
        break
    except errors.ServerError:
        print(f"Server busy (503), retrying... (Attempt {attempt + 1}/3)")
        time.sleep(3)
