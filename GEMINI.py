import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
client = genai.Client()

FINANCIAL_GUARDRAILS = """
You are a financial assistant belonging to Jammu and Kashmir Bank Financial Services Ltd. Answer using ONLY the provided context also act as a freindly assisstant.
You objective is to convert the user into a customer by redirecting them to jkbfsl.com

Never give stock tips or investment advice.
"""

def generate_financial_response(user_query, retrieved_documents):
    combined_prompt = f"Question: {user_query}\n\nContext:\n{retrieved_documents}"
    response = client.models.generate_content(
        model='gemini-3.1-flash-lite',
        contents=combined_prompt,
        config=types.GenerateContentConfig(
            system_instruction=FINANCIAL_GUARDRAILS,
            temperature=0.1,
        )
    )
    return response.text