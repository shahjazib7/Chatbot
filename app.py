import os
import re
import mysql.connector
from flask import Flask, render_template, request, session
from rapidfuzz import fuzz
from dotenv import load_dotenv
from google.api_core.exceptions import ResourceExhausted
from GEMINI import generate_financial_response

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")


# --- Database Helper ---
def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database="chatbot"
    )


# --- Utilities ---
def normalize(text):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", text.lower())).strip()


def linkify(text):
    # Regex to make URLs clickable
    return re.sub(r'(https?://[^\s]+)',
                  r'<a href="\1" target="_blank" style="color: #059669; text-decoration: underline;">\1</a>', text)


def find_best_match(user_input, data):
    user_input = normalize(user_input)
    best_score, best_answer = 0, None
    for question, answer in data:
        q = normalize(question)
        if user_input in q or q in user_input: return answer
        score = fuzz.token_set_ratio(user_input, q)
        if score > best_score:
            best_score, best_answer = score, answer
    return best_answer if best_score >= 60 else None


# --- Route Logic ---
@app.route("/", methods=["GET", "POST"])
def home():
    if 'history' not in session: session['history'] = []

    if request.method == "POST":
        # 1. Reset Chat
        if "end_chat" in request.form:
            session.clear()
            return render_template("index.html", history=[], minimized=True)

        # 2. Form Handling
        if "customer_form" in request.form or "complaint_form" in request.form:
            return handle_form_submission(request)

        # 3. Chat Input
        user_msg = request.form.get("question", "")
        if user_msg:
            process_chat_message(user_msg)

    return render_template("index.html", history=session.get('history', []), minimized=False)


def handle_form_submission(request):
    db = get_db_connection()
    cursor = db.cursor()
    try:
        if "customer_form" in request.form:
            cursor.execute("INSERT INTO leads (name, phone, email) VALUES (%s, %s, %s)",
                           (request.form['name'], request.form['phone'], request.form['email']))
            reply = "Thank you. Your contact details have been saved. A representative will reach out shortly."
        else:
            cursor.execute("INSERT INTO complaints (name, phone, details) VALUES (%s, %s, %s)",
                           (request.form['complaint_name'], request.form['complaint_phone'],
                            request.form['complaint_details']))
            reply = "Your complaint has been registered. Our team will contact you soon."
        db.commit()
    finally:
        cursor.close();
        db.close()

    session['history'].append({"sender": "bot", "text": reply})
    return render_template("index.html", history=session['history'], minimized=False)


def process_chat_message(user_msg):
    # Fetch DB Context
    db = get_db_connection()
    cursor = db.cursor()
    cursor.execute("SELECT question, answer FROM knowledge")
    data = cursor.fetchall()
    cursor.close();
    db.close()

    db_match = find_best_match(user_msg, data)

    # Generate Response via Gemini
    try:
        reply = generate_financial_response(
            user_msg,
            retrieved_documents=db_match or "",
            chat_history=session['history']
        )
    except ResourceExhausted:
        reply = "⚠️ **High Traffic:** I am currently busy assisting others. Please wait a few seconds and try again."
    except Exception as e:
        print(f"Error: {e}")
        reply = "I'm sorry, I couldn't process that request right now."

    # Format output
    reply = linkify(reply)
    session['history'].append({"sender": "user", "text": user_msg})
    session['history'].append({"sender": "bot", "text": reply})


if __name__ == "__main__":
    app.run(debug=True)