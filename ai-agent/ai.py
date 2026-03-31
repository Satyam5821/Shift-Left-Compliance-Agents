import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def generate_fix(issue):
    prompt = f"""
    Fix this code issue:

    Issue: {issue['message']}
    Rule: {issue['rule']}

    Provide:
    - Explanation
    - Fixed code
    """

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content