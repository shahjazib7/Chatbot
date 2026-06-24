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
        if user_input in q or q in user_input:
            return answer
        score = fuzz.token_set_ratio(user_input, q)
        if score > best_score:
            best_score, best_answer = score, answer
    return best_answer if best_score >= 60 else None


def format_long_reply(reply):
    """Break long, unformatted replies into a numbered list for readability."""
    if len(reply) > 150 and '\n' not in reply:
        sentences = reply.split('. ')
        formatted = []
        for i, sentence in enumerate(sentences, 1):
            sentence = sentence.strip()
            if sentence:
                formatted.append(f"{i}. {sentence}")
        return "<br>".join(formatted)
    return reply


# --- Route Logic ---
@app.route("/", methods=["GET", "POST"])
def home():
    if 'history' not in session:
        session['history'] = []

    minimized = False
    show_form = False
    show_support_form = False

    if request.method == "POST":

        # 1. Reset Chat
        if "end_chat" in request.form:
            session.clear()
            return render_template("index.html", history=[], minimized=True)

        # 2. Form Handling (lead form or support/complaint form)
        if "customer_form" in request.form or "complaint_form" in request.form:
            return handle_form_submission(request)

        # 3. Standard Chat Input
        user_msg = request.form.get("question", "")
        if user_msg:
            clean_msg = normalize(user_msg)

            # 3a. Explicit "chat is closed" phrase
            if clean_msg == "chat is closed":
                session.clear()
                return render_template("index.html", history=[], minimized=True)

            # 3b. Detect requests for the contact form OR closing/thank-you sentiment
            closing_phrases = {
                "thank you", "thanks", "thankyou", "bye", "goodbye",
                "that is all", "thats all", "no more questions", "clear"
            }
            is_form_requested = (
                "contact form" in clean_msg
                or "share details" in clean_msg
                or "call me" in clean_msg
            )
            is_closing_sentiment = any(phrase in clean_msg for phrase in closing_phrases)

            if is_form_requested or is_closing_sentiment:
                if is_closing_sentiment and not is_form_requested:
                    bot_reply = (
                        "You're welcome! If you have any further requirements or want our team "
                        "to reach out, please fill out this quick contact form."
                    )
                else:
                    bot_reply = "Please fill out the form below, and a banking representative will contact you."

                show_form = True
                session['history'].append({"sender": "user", "text": user_msg})
                session['history'].append({"sender": "bot", "text": bot_reply})
                session.modified = True
                return render_template("index.html", history=session['history'], minimized=False, show_form=show_form)

            # 3c. Standard query — process via DB match / Gemini fallback
            process_chat_message(user_msg, clean_msg)

    return render_template(
        "index.html",
        history=session.get('history', []),
        minimized=minimized,
        show_form=show_form,
        show_support_form=show_support_form,
    )


def handle_form_submission(request):
    db = get_db_connection()
    cursor = db.cursor()
    try:
        if "customer_form" in request.form:
            name = request.form['name']
            cursor.execute(
                "INSERT INTO leads (name, phone, email) VALUES (%s, %s, %s)",
                (name, request.form['phone'], request.form['email'])
            )
            reply = f"Thank you, {name}. Your contact details have been saved. A representative will reach out shortly."
        else:
            name = request.form['complaint_name']
            cursor.execute(
                "INSERT INTO complaints (name, phone, details) VALUES (%s, %s, %s)",
                (name, request.form['complaint_phone'], request.form['complaint_details'])
            )
            reply = f"Thank you, {name}. Your request has been registered. Our team will contact you soon."
        db.commit()
    finally:
        cursor.close()
        db.close()

    session['history'].append({"sender": "bot", "text": reply})
    session.modified = True
    return render_template("index.html", history=session['history'], minimized=False)


def process_chat_message(user_msg, clean_msg=None):
    if clean_msg is None:
        clean_msg = normalize(user_msg)

    # --- Context Bridge: resolve pronouns using the previous user message ---
    search_query = user_msg
    pronouns = {"it", "they", "them", "this", "that", "these", "those"}
    words = clean_msg.split()

    if any(word in pronouns for word in words):
        history_list = session.get('history', [])
        if len(history_list) >= 2:
            last_user_msg = history_list[-2]['text']
            search_query = f"{last_user_msg} {user_msg}"

    # --- Fetch DB Context ---
    db = get_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute("SELECT question, answer FROM knowledge")
        data = cursor.fetchall()
    finally:
        cursor.close()
        db.close()

    db_match = find_best_match(search_query, data)

    # --- Generate Response ---
    if db_match:
        bot_reply = db_match
    else:
        try:
            bot_reply = generate_financial_response(
                user_msg,
                retrieved_documents="",
                chat_history=session.get('history', [])
            )
        except ResourceExhausted:
            print("Gemini API Error: Rate Limit Exceeded (429)")
            bot_reply = (
                "⚠️ **High Traffic Alert:** I am currently assisting many customers. "
                "Please wait about 30 seconds and try your message again."
            )
        except Exception as e:
            print(f"Gemini API Error: {e}")
            bot_reply = "I'm sorry, I couldn't find an answer to that in my current records right now."

    # --- Format & Linkify ---
    bot_reply = format_long_reply(bot_reply)
    bot_reply = linkify(bot_reply)

    session['history'].append({"sender": "user", "text": user_msg})
    session['history'].append({"sender": "bot", "text": bot_reply})
    session.modified = True


if __name__ == "__main__":
    app.run(debug=True)