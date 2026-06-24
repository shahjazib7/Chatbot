import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
client = genai.Client()

FINANCIAL_GUARDRAILS = """
You are a knowledgeable financial assistant for a banking subsidiary.
Your role is to explain financial concepts (like Demat accounts, ETFs, Trading) using ONLY the provided knowledge base context.

CRITICAL RULES:
1. You must NEVER provide personalized investment advice or recommend specific stocks.
2. If a user asks what to buy or sell, politely refuse and state you can only provide definitions.
3. If the answer to the user's question is not found in the provided Knowledge Base Context, you must say "I do not have that information in my repository." Do not hallucinate external facts.
4. EXCEPTION TO RULE 3: If the user sends a greeting, you must respond politely and ask how you can help. HOWEVER, do not repeat your introduction if you have already greeted the user in the Previous Conversation history.
"""

def generate_financial_response(user_query, retrieved_documents, chat_history=None):
    # Fix for mutable default argument
    if chat_history is None:
        chat_history = []

    # 1. Format the past messages into a readable chat transcript
    history_transcript = ""
    for msg in chat_history:
        role = "User" if msg["sender"] == "user" else "Bank Assistant"
        history_transcript += f"{role}: {msg['text']}\n"

    # 2. Inject the history into the final prompt sent to the model
    # (Combined your two prompt fragments into one clean structure)
    prompt = f"""
You are a professional financial assistant for JKB Financial Services.

Previous Conversation:
{history_transcript}

User Question:
{user_query}

Knowledge Base Context:
{retrieved_documents}

Rules:
1. Give short and direct answers.
2. If explaining a process, ALWAYS use numbered steps.
3. If listing information, ALWAYS use bullet points.
4. Never return long paragraphs.
5. Keep URLs unchanged.
6. Keep responses concise and easy to read.
"""

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=FINANCIAL_GUARDRAILS,
            temperature=0.8,
        )
    )

    return response.text