import os
from flask import Flask, render_template, request, session, redirect, url_for
import mysql.connector
import re
from rapidfuzz import fuzz
from dotenv import load_dotenv

##### NEW CODE IMPORT #####
# Import the response generator function from your new file
from GEMINI import generate_financial_response

###########################

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY")


def normalize(text):
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def linkify(text):
    url_pattern = re.compile(r'(https?://[^\s]+)')
    return url_pattern.sub(
        r'<a href="\1" target="_blank" style="color: #003366; text-decoration: underline; font-weight: bold;">\1</a>',
        text)


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
    # We change this default return string to None so app.py knows nothing was found locally
    return None


@app.route("/", methods=["GET", "POST"])
def home():
    if 'history' not in session:
        session['history'] = []

    minimized = False
    show_form = False

    if request.method == "POST":

        # 1. Handle Explicit Button Shutdown
        if "end_chat" in request.form:
            session.clear()
            return render_template("index.html", history=[], minimized=True)

        # 2. Handle Lead Form Submission
        if "customer_form" in request.form:
            name = request.form.get("name")
            phone = request.form.get("phone")
            email = request.form.get("email")

            db = mysql.connector.connect(
                host=os.getenv("DB_HOST"), user=os.getenv("DB_USER"),
                password=os.getenv("DB_PASSWORD"), database="chatbot"
            )
            cursor = db.cursor()
            try:
                cursor.execute("INSERT INTO leads (name, phone, email) VALUES (%s, %s, %s)", (name, phone, email))
                db.commit()
            finally:
                cursor.close()
                db.close()

            bot_reply = f"Thank you, {name}. Your contact details have been saved. A representative will reach out shortly."
            chat_history = session['history']
            chat_history.append({"sender": "bot", "text": bot_reply})
            session['history'] = chat_history

            return render_template("index.html", history=session['history'], minimized=False)

        ## 3. Standard Text Input Handling
        user_msg = request.form.get("question", "")
        clean_msg = normalize(user_msg)

        if clean_msg == "chat is closed":
            session.clear()
            return render_template("index.html", history=[], minimized=True)

        ##### UPDATED CODE: DETECT CONVERSATION END/THANK YOU #####
        # Define a list of natural closing or gratitude phrases
        closing_phrases = {
            "thank you", "thanks", "thankyou", "bye", "goodbye",
            "that is all", "thats all", "no more questions", "clear"
        }

        # Check if the user is asking for the form OR signaling the end of the chat
        is_form_requested = "contact form" in clean_msg or "share details" in clean_msg or "call me" in clean_msg
        is_closing_sentiment = any(phrase in clean_msg for phrase in closing_phrases)

        if is_form_requested or is_closing_sentiment:
            # Set a polite contextual response based on what they said
            if is_closing_sentiment and not is_form_requested:
                bot_reply = "You're welcome! If you have any further requirements or want our team to reach out, please fill out this quick contact form."
            else:
                bot_reply = "Please fill out the form below, and a banking representative will contact you."

            show_form = True
            chat_history = session['history']
            chat_history.append({"sender": "user", "text": user_msg})
            chat_history.append({"sender": "bot", "text": bot_reply})
            session['history'] = chat_history
            return render_template("index.html", history=session['history'], minimized=False, show_form=show_form)
        ###########################################################

        # Standard Query Logic (Context Bridge)
        search_query = user_msg
        words = clean_msg.split()
        pronouns = {"it", "they", "them", "this", "that", "these", "those"}

        if any(word in pronouns for word in words):
            history_list = session.get('history', [])
            if len(history_list) >= 2:
                last_user_msg = history_list[-2]['text']
                search_query = f"{last_user_msg} {user_msg}"

        db = mysql.connector.connect(
            host=os.getenv("DB_HOST"), user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"), database="chatbot"
        )
        cursor = db.cursor()
        try:
            cursor.execute("SELECT question, answer FROM knowledge")
            data = cursor.fetchall()
        finally:
            cursor.close()
            db.close()

        ##### CHANGED CODE: INTELLIGENT RAG FALLBACK #####
        # 1. Use your existing matching logic to search the database
        db_match = find_best_match(search_query, data)

        # 2. If the database found a document context, send it to Gemini
        if db_match:
            bot_reply = db_match
        else:
            # If the database score was under 60, tell Gemini there is no context
            try:
                # ADD session.get('history', []) HERE
                bot_reply = generate_financial_response(user_msg, retrieved_documents="",
                                                        chat_history=session.get('history', []))
            except Exception as e:
                print(f"Gemini API Error: {e}")
                bot_reply = "I'm sorry, I couldn't find an answer to that in my current records."

        bot_reply = linkify(bot_reply)

        chat_history = session['history']
        chat_history.append({"sender": "user", "text": user_msg})
        chat_history.append({"sender": "bot", "text": bot_reply})
        session['history'] = chat_history

    return render_template("index.html", history=session.get('history', []), minimized=minimized)


if __name__ == "__main__":
    app.run(debug=True)