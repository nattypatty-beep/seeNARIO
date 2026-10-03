from google import genai
from PIL import Image
import os, glob

# Initialize the Gemini API client
client = genai.Client()

# Locate image in Downloads
downloads = os.path.expanduser("~/Downloads")
matches = glob.glob(os.path.join(downloads, "sample.*"))

if not matches:
    raise FileNotFoundError("Could not find any 'sample' image in your Downloads folder!")

image_path = matches[0]
print(f"Using image: {image_path}")

image = Image.open(image_path)

# Prompt for object and horizontal position
prompt = (
    "Identify the main objects in this image and their coarse horizontal positions "
    "(left, center, right). Format your output strictly like this:\n"
    "object_name, position\n\n"
    "Example:\n"
    "chair, center\n"
    "person, center\n"
    "backpack, left"
)

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=[image, prompt]
)

print("\n--- Gemini Output ---")
print(response.text)
