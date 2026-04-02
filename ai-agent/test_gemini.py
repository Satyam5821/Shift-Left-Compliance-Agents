import os
from dotenv import load_dotenv
from google import genai

# Load environment variables
load_dotenv()

# Get API key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("ERROR: GEMINI_API_KEY not found in .env file")
    exit(1)

print(f"API Key found: {GEMINI_API_KEY[:10]}...")

# Create Gemini client
genai_client = genai.Client(api_key=GEMINI_API_KEY)

try:
    response = genai_client.models.generate_content(
        model='gemini-2.5-flash',
        contents='Hello, can you help me fix a Java code issue?'
    )
    print("SUCCESS: Gemini API connection successful!")
    print("Response:", response.text[:100] + "..." if len(response.text) > 100 else response.text)
except Exception as e:
    print(f"ERROR: Gemini API error: {str(e)}")