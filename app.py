import os
from flask import Flask, render_template, request, session, redirect, url_for
import mysql.connector
import re
from rapidfuzz import fuzz
from dotenv import load_dotenv

# Load the variables from the .env file
load_dotenv()

app = Flask(__name__)

# Fetch the secret key from the environment
app.secret_key = os.getenv("FLASK_SECRET_KEY")

def linkify(text):
    # Regex to find standard URLs
    url_pattern = re.compile(r'(https?://[^\s]+)')
    # Replace the URL with an HTML anchor tag that opens in a new tab
    # We also add an inline style so the link matches your JKB blue theme
    return url_pattern.sub(r'<a href="\1" target="_blank" style="color: #003366; text-decoration: underline; font-weight: bold;">\1</a>', text)

def normalize(text):
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def is_closing_sentiment(text):
    # Detect typical phrases that indicate a user wants to finish
    closing_words = {"thanks", "thank you", "bye", "goodbye", "exit", "close", "chat is closed", "done"}
    return any(word in text for word in closing_words)


def is_affirmative(text):
    # Detect confirmation to close
    return text in {"yes", "yeah", "y", "close it", "end chat", "sure"}


def find_best_match(user_input, data):
    user_input = normalize(user_input)
    best_score = 0
    best_answer = None

    for question, answer in data:
        q = normalize(question)
        if user_input in q or q in user_input:
            return answer
        score = fuzz.token_set_ratio(user_input, q)
        if score > best_score:
            best_score = score
            best_answer = answer

    if best_score >= 60:
        return best_answer
    return "I am sorry, I couldn't find an answer to that in my current records."


@app.route("/", methods=["GET", "POST"])
def home():
    if 'history' not in session:
        session['history'] = []
    if 'awaiting_closure' not in session:
        session['awaiting_closure'] = False

    minimized = False

    if request.method == "POST":
        user_msg = request.form["question"]
        clean_msg = normalize(user_msg)

        # 1. Handle explicit immediate shutdown
        if clean_msg == "chat is closed":
            session.clear()
            return render_template("index.html", history=[], minimized=True)

        # 2. Handle confirmation tracking state
        if session.get('awaiting_closure'):
            if is_affirmative(clean_msg):
                session.clear()
                return render_template("index.html", history=[], minimized=True)
            else:
                # User changed their mind
                session['awaiting_closure'] = False
                bot_reply = "Understood. Let's keep going. How else can I assist you today?"

                chat_history = session['history']
                chat_history.append({"sender": "user", "text": user_msg})
                chat_history.append({"sender": "bot", "text": bot_reply})
                session['history'] = chat_history
                return render_template("index.html", history=session['history'], minimized=False)

        # 3. Detect initial closing sentiment
        if is_closing_sentiment(clean_msg):
            session['awaiting_closure'] = True
            bot_reply = "You're welcome! Would you like to securely end and close this chat session?"

            chat_history = session['history']
            chat_history.append({"sender": "user", "text": user_msg})
            chat_history.append({"sender": "bot", "text": bot_reply})
            session['history'] = chat_history
            return render_template("index.html", history=session['history'], minimized=False)

        # 4. Standard Database Query logic
        db = mysql.connector.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database="chatbot"
        )
        cursor = db.cursor()
        try:
            cursor.execute("SELECT question, answer FROM knowledge")
            data = cursor.fetchall()
        finally:
            cursor.close()
            db.close()

            # ... (Inside your POST route) ...

            bot_reply = find_best_match(user_msg, data)

            # FIX: Convert raw URLs in the reply into clickable HTML links
            bot_reply = linkify(bot_reply)

            chat_history = session['history']
            chat_history.append({"sender": "user", "text": user_msg})
            chat_history.append({"sender": "bot", "text": bot_reply})
            session['history'] = chat_history

    return render_template("index.html", history=session.get('history', []), minimized=minimized)


if __name__ == "__main__":
    app.run(debug=True)