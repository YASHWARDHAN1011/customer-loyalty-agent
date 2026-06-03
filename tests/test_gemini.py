import google.generativeai as genai
from dotenv import load_dotenv
import os

# Load the .env file
load_dotenv()

# Configure Gemini with your key
genai.configure(api_key=os.getenv("GEMINI_KEY_1"))

# Create a model
model = genai.GenerativeModel("gemini-2.5-flash")

# Send a message
response = model.generate_content("Say hello and tell me you are working correctly.")

print(response.text)