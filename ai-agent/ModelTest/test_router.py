#test_router.py
import os
from dotenv import load_dotenv
load_dotenv()
import requests
import json

response = requests.post(
  url="https://openrouter.ai/api/v1/chat/completions",
  headers={
    "Authorization": "Bearer " + os.getenv("OPENROUTER_API_KEY"),
  },
  data=json.dumps({
    "model": "openai/gpt-4o-mini", 
    "messages": [
      {
        "role": "user",
        "content": "What is the meaning of life?"
      }
    ]
  })
)
print(response.json())