from flask import Flask, render_template, request, jsonify, url_for
import sqlite3
import json
import os
import ssl
import uuid
import random
import html
import re
from pathlib import Path

import truststore

truststore.inject_into_ssl()

from dotenv import load_dotenv
from google import genai
from google.genai import types


# =========================================================
# PATH
# =========================================================

BASE_DIR = Path(__file__).resolve().parent

DB_FILE = BASE_DIR / "database.db"
QUESTIONS_FILE = BASE_DIR / "questions.json"
ENV_FILE = BASE_DIR / ".env"


# =========================================================
# FLASK
# =========================================================

app = Flask(__name__)


# =========================================================
# ENV
# =========================================================

load_dotenv(ENV_FILE)

GEMINI_API_KEY = os.getenv(
    "GEMINI_API_KEY",
    ""
).strip()

GEMINI_MODEL = "gemini-3.1-flash-lite"


# =========================================================
# GEMINI CLIENT
# =========================================================

gemini_client = None

if GEMINI_API_KEY:

    try:

        ssl_context = truststore.SSLContext(
            ssl.PROTOCOL_TLS_CLIENT
        )

        gemini_client = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options=types.HttpOptions(
                client_args={
                    "verify": ssl_context
                },
                async_client_args={
                    "verify": ssl_context
                }
            )
        )

        print()
        print("✅ Gemini API кілті табылды.")
        print("✅ Gemini:", GEMINI_MODEL)
        print("✅ SSL дайын.")
        print()

    except Exception as error:

        print()
        print("❌ Gemini клиентін іске қосу қатесі:")
        print(error)
        print()

else:

    print()
    print("⚠️ GEMINI_API_KEY табылмады.")
    print()


# =========================================================
# HELPER
# =========================================================

def escape_html(value):

    return html.escape(
        str(value)
    )


def format_ai_text(text):

    if not text:
        return ""

    text = escape_html(text)

    # **мәтін**
    text = re.sub(
        r"\*\*(.+?)\*\*",
        r"<strong>\1</strong>",
        text
    )

    # `код`
    text = re.sub(
        r"`(.+?)`",
        r"<code>\1</code>",
        text
    )

    # Жолдарды HTML-ға ауыстыру
    text = text.replace(
        "\n",
        "<br>"
    )

    return text


# =========================================================
# AI SYSTEM PROMPT
# =========================================================

AI_SYSTEM_PROMPT = """

Сен INFO ҰБТ AI платформасындағы
11-сынып оқушыларына информатикадан
ҰБТ-ға дайындық жүргізетін AI мұғалімсің.

Негізгі жауап тілі — қазақ тілі.

Егер есеп болса:

1. БЕРІЛГЕНІ
2. ТАБУ КЕРЕК
3. ҚАЖЕТТІ ФОРМУЛА НЕМЕСЕ ЕРЕЖЕ
4. ҚАДАМДЫҚ ШЕШУ ЖОЛЫ
5. ДҰРЫС ЖАУАП
6. НЕГЕ ДӘЛ ОСЫ ЖАУАП
7. ТАҚЫРЫПТЫ ТҮСІНДІРУ
8. ҰҚСАС ҰБТ ЕСЕБІ

Python болса:

- айнымалыларды түсіндір;
- циклдерді талда;
- шарттарды талда;
- кодтың орындалуын қадамдап көрсет;
- соңғы нәтижені есепте.

Теориялық сұрақ болса:

- анықтама;
- толық түсіндірме;
- мысал;
- ҰБТ-да кездесетін түрі;
- жиі қате;
- есте сақтау тәсілі;
- ұқсас сұрақ.

Нақты жабық немесе рұқсатсыз
таратылған тест сұрақтарын көшірме.

Сол тақырып пен форматқа ұқсас
жаңа авторлық тапсырма жаса.

"""


# =========================================================
# JSON QUESTIONS
# =========================================================

def load_questions():

    try:

        with open(
            QUESTIONS_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if not isinstance(
            data,
            list
        ):

            print(
                "❌ questions.json массив болуы керек."
            )

            return []

        return data

    except FileNotFoundError:

        print(
            "❌ questions.json табылмады."
        )

        return []

    except json.JSONDecodeError as error:

        print(
            "❌ questions.json ішінде қате:"
        )

        print(error)

        return []


# =========================================================
# DATABASE
# =========================================================

def init_database():

    connection = sqlite3.connect(
        DB_FILE,
        timeout=30
    )

    connection.execute(
        "PRAGMA journal_mode=WAL"
    )

    connection.execute(
        "PRAGMA busy_timeout=30000"
    )

    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS results (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            score INTEGER NOT NULL DEFAULT 0,

            max_score INTEGER NOT NULL DEFAULT 0,

            answered INTEGER NOT NULL DEFAULT 0,

            total INTEGER NOT NULL DEFAULT 40,

            created_at
            TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        )
        """
    )

    cursor.execute(
        "PRAGMA table_info(results)"
    )

    columns = {
        row[1]
        for row in cursor.fetchall()
    }

    if "max_score" not in columns:

        cursor.execute(
            """
            ALTER TABLE results
            ADD COLUMN max_score INTEGER DEFAULT 0
            """
        )

    if "answered" not in columns:

        cursor.execute(
            """
            ALTER TABLE results
            ADD COLUMN answered INTEGER DEFAULT 0
            """
        )

    if "total" not in columns:

        cursor.execute(
            """
            ALTER TABLE results
            ADD COLUMN total INTEGER DEFAULT 40
            """
        )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS generated_tests (

            id TEXT PRIMARY KEY,

            title TEXT NOT NULL,

            questions TEXT NOT NULL,

            created_at
            TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        )
        """
    )

    connection.commit()

    connection.close()


# =========================================================
# SAVE RESULT
# =========================================================

def save_result(
    score,
    max_score,
    answered,
    total
):

    connection = sqlite3.connect(
        DB_FILE,
        timeout=30
    )

    connection.execute(
        "PRAGMA busy_timeout=30000"
    )

    connection.execute(
        """
        INSERT INTO results
        (
            score,
            max_score,
            answered,
            total
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            score,
            max_score,
            answered,
            total
        )
    )

    connection.commit()

    connection.close()


# =========================================================
# STATIC UBT
# =========================================================

def get_ubt_questions():

    questions = load_questions()

    questions.sort(
        key=lambda question:
        question.get(
            "id",
            0
        )
    )

    return questions[:40]


# =========================================================
# MAX SCORE
# =========================================================

def get_max_score(
    questions
):

    total = 0

    for question in questions:

        qtype = question.get(
            "type"
        )

        if qtype in (
            "single",
            "context_single"
        ):

            total += 1

        elif qtype in (
            "multiple",
            "match"
        ):

            total += 2

    return total


# =========================================================
# CALCULATE SCORE
# =========================================================

def calculate_score(
    question,
    user_answer
):

    qtype = question.get(
        "type"
    )

    correct = question.get(
        "answer"
    )

    if user_answer is None:

        return 0

    if qtype in (
        "single",
        "context_single"
    ):

        try:

            if (
                int(user_answer)
                ==
                int(correct)
            ):

                return 1

        except (
            ValueError,
            TypeError
        ):

            pass

        return 0

    if qtype in (
        "multiple",
        "match"
    ):

        if not isinstance(
            user_answer,
            list
        ):

            return 0

        try:

            user_values = sorted([
                int(value)
                for value
                in user_answer
            ])

            correct_values = sorted([
                int(value)
                for value
                in correct
            ])

            if (
                user_values
                ==
                correct_values
            ):

                return 2

        except (
            ValueError,
            TypeError
        ):

            pass

        return 0

    return 0


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    questions = load_questions()

    topics = sorted(
        {
            q.get(
                "topic",
                ""
            )
            for q in questions
            if q.get(
                "topic"
            )
        }
    )

    return render_template(
        "index.html",
        topics=topics,
        question_count=len(questions)
    )


# =========================================================
# STATIC TEST
# =========================================================

@app.route("/test")
def test():

    questions = get_ubt_questions()

    if len(questions) < 40:

        return f"""
        <h2>❌ Базада 40 сұрақ жоқ</h2>
        <p>Қазір: {len(questions)} сұрақ.</p>
        """

    return render_template(
        "test.html",
        questions=questions,
        generated=False,
        test_id="",
        test_title="Информатика ҰБТ"
    )


# =========================================================
# STATIC CHECK
# =========================================================

@app.route(
    "/api/check",
    methods=["POST"]
)
def check_test():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        answers = data.get(
            "answers",
            {}
        )

        questions = get_ubt_questions()

        if len(questions) < 40:

            return jsonify({
                "error":
                    "40 сұрақ табылмады."
            }), 400

        score = 0
        answered = 0
        details = []

        for question in questions:

            question_id = str(
                question.get("id")
            )

            user_answer = answers.get(
                question_id
            )

            if user_answer is not None:

                answered += 1

            points = calculate_score(
                question,
                user_answer
            )

            score += points

            details.append({

                "id":
                    question.get("id"),

                "type":
                    question.get("type"),

                "topic":
                    question.get("topic"),

                "question":
                    question.get("question"),

                "user":
                    user_answer,

                "correct":
                    question.get("answer"),

                "points":
                    points,

                "explanation":
                    question.get(
                        "explanation",
                        ""
                    ),

                "theory":
                    question.get(
                        "theory",
                        ""
                    )

            })

        max_score = get_max_score(
            questions
        )

        save_result(
            score,
            max_score,
            answered,
            len(questions)
        )

        return jsonify({

            "score":
                score,

            "max_score":
                max_score,

            "answered":
                answered,

            "total":
                len(questions),

            "details":
                details

        })

    except Exception as error:

        print(
            "❌ /api/check қатесі:"
        )

        print(error)

        return jsonify({
            "error":
                str(error)
        }), 500


# =========================================================
# AI PAGE
# =========================================================

@app.route("/ai")
def ai_teacher():

    return render_template(
        "ai_teacher.html"
    )


# =========================================================
# AI CHAT
# =========================================================

@app.route(
    "/api/ai",
    methods=["POST"]
)
def ai():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        user_message = str(
            data.get(
                "message",
                ""
            )
        ).strip()

        if not user_message:

            return jsonify({
                "answer":
                    "Сұрағыңызды жазыңыз."
            })

        if gemini_client is None:

            return jsonify({
                "answer":
                    "❌ Gemini іске қосылмаған."
            })

        prompt = f"""
Оқушының сұрағы:

{user_message}

Осы сұраққа INFO ҰБТ AI
мұғалімі ретінде толық жауап бер.

Жауапты қазақ тілінде бер.
"""

        response = (
            gemini_client
            .models
            .generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=
                        AI_SYSTEM_PROMPT,
                    temperature=0.3,
                    max_output_tokens=5000
                )
            )
        )

        answer = (
            response.text
            or
            "Gemini бос жауап қайтарды."
        )

        return jsonify({
            "answer":
                format_ai_text(
                    answer
                )
        })

    except Exception as error:

        print(
            "❌ Gemini қатесі:"
        )

        print(error)

        return jsonify({

            "answer":
                f"""
                <b>❌ Gemini қатесі</b>
                <br><br>
                <code>
                {escape_html(error)}
                </code>
                """

        }), 500


# =========================================================
# GENERATOR PAGE
# =========================================================

@app.route("/generate")
def generate_page():

    return render_template(
        "generate.html"
    )


# =========================================================
# DIFFICULTY
# =========================================================

def make_difficulty_pattern():

    pattern = (
        ["A"] * 20
        +
        ["B"] * 12
        +
        ["C"] * 8
    )

    random.shuffle(
        pattern
    )

    return pattern


# =========================================================
# GENERATOR PROMPT
# =========================================================

def build_generator_prompt(
    difficulty_pattern
):

    difficulty_text = ", ".join(

        f"{index + 1}:{level}"

        for index, level
        in enumerate(
            difficulty_pattern
        )

    )

    return f"""

Сен Қазақстандағы
11-сынып оқушыларына арналған
информатика ҰБТ тапсырмаларын
құрастырушысысың.

СЕНІҢ МІНДЕТІҢ:

ДӘЛ 40 жаңа авторлық тапсырма жаса.

Тек JSON қайтар.

JSON құрылымы:

{{
  "questions": [
    {{
      "id": 1,
      "type": "single",
      "topic": "...",
      "difficulty": "A",
      "question": "...",
      "context": "",
      "options": ["...", "...", "...", "..."],
      "answer_index": 0,
      "answer_indices": [],
      "left": [],
      "right": [],
      "explanation": "...",
      "theory": "..."
    }}
  ]
}}


==================================================
СҰРАҚ ҚҰРЫЛЫМЫ
==================================================

1–25:

type = "single"

Дәл 4 жауап нұсқасы.

Бір ғана дұрыс жауап.

answer_index = 0, 1, 2 немесе 3.


26–30:

type = "context_single"

БІР ортақ контекст.

Дәл 4 жауап нұсқасы.

Бір ғана дұрыс жауап.

answer_index = 0, 1, 2 немесе 3.

26, 27, 28, 29, 30 сұрақтарының
"context" мәні ДӘЛ БІРДЕЙ болуы керек.


31–35:

type = "multiple"

Дәл 6 жауап нұсқасы.

1, 2 немесе 3 дұрыс жауап.

answer_indices ішінде
дұрыс жауаптардың индекстерін бер.

Индекстер 0–5 аралығында.


36–40:

type = "match"

left = ДӘЛ 2 элемент.

right = ДӘЛ 4 элемент.

answer_indices = ДӘЛ 2 элемент.

Индекстер 0–3 аралығында.

Мысалы:

answer_indices: [1, 3]

деген:

1-элемент → B
2-элемент → D

дегенді білдіреді.

answer_indices ешқашан бос болмауы керек.


==================================================
АРТЫҚ ӨРІСТЕР
==================================================

Барлық сұрақта мына өрістер болуы керек:

id
type
topic
difficulty
question
context
options
answer_index
answer_indices
left
right
explanation
theory

Қолданылмайтын өрістерге:

context = ""

options = []

answer_index = -1

answer_indices = []

left = []

right = []

деп беруге болады.


==================================================
DIFFICULTY
==================================================

Төмендегі нақты ретпен бер:

{difficulty_text}

Бұл тізбекті өзгертпе.

Сервер кейін difficulty мәнін
қайта тексереді.


==================================================
ТАҚЫРЫПТАР
==================================================

Тақырыптарды араластыр:

Python

алгоритмдер

санау жүйелері

логика

ақпаратты өлшеу

ақпаратты кодтау

компьютерлік желілер

ақпараттық қауіпсіздік

SQL

деректер қоры

графтар

файлдар

жолдар

массивтер

функциялар

рекурсия

сұрыптау

компьютер құрылғылары

бағдарламалық қамтамасыз ету

Web

3D модельдеу


==================================================
САПА
==================================================

Python есептері міндетті.

Санау жүйелерінен есептер міндетті.

Логикалық есептер міндетті.

SQL тапсырмалары міндетті.

Алгоритмдер міндетті.

Массивтер міндетті.

Функциялар міндетті.

Компьютерлік желілер міндетті.

Ақпараттық қауіпсіздік міндетті.

C деңгейіндегі есептер
бірнеше білімді бірге қолдануды талап етсін.

Жай жаттанды анықтамаларды көп қолданба.

Есептер нақты есептеуге негізделсін.

Әр сұрақта:

explanation

және

theory

міндетті.

explanation ішінде
дұрыс жауаптың неге дұрыс екенін түсіндір.

Есеп болса есептеу қадамдарын көрсет.

theory ішінде осы сұраққа қатысты
тақырыпты түсіндір.


==================================================
МАҢЫЗДЫ
==================================================

Нақты жабық немесе рұқсатсыз
таратылған ҰБТ сұрақтарын көшірме.

Сол тақырыпқа, форматқа және
қиындық деңгейіне ұқсас
жаңа авторлық тапсырмалар жаса.

ТЕК JSON ҚАЙТАР.

Markdown қолданба.

```json қолданба.

JSON алдында ешқандай мәтін жазба.

JSON соңынан ешқандай мәтін жазба.
"""


# =========================================================
# GENERATOR VALIDATION
# =========================================================

def validate_generated_questions(
    questions,
    difficulty_pattern
):

    if not isinstance(
        questions,
        list
    ):

        raise ValueError(
            "questions массив емес."
        )

    if len(questions) != 40:

        raise ValueError(
            f"40 сұрақ қажет. "
            f"Келгені: {len(questions)}."
        )

    expected_types = (
        ["single"] * 25
        +
        ["context_single"] * 5
        +
        ["multiple"] * 5
        +
        ["match"] * 5
    )

    result = []

    for index, item in enumerate(
        questions,
        start=1
    ):

        if not isinstance(
            item,
            dict
        ):

            raise ValueError(
                f"{index}-сұрақ объект емес."
            )

        q = dict(item)

        expected_type = (
            expected_types[
                index - 1
            ]
        )

        actual_type = q.get(
            "type"
        )

        if actual_type != expected_type:

            raise ValueError(
                f"{index}-сұрақтың type қате. "
                f"Керегі: {expected_type}. "
                f"Келгені: {actual_type}."
            )

        # -------------------------------------------------
        # ID
        # -------------------------------------------------

        q["id"] = index

        # -------------------------------------------------
        # COMMON FIELDS
        # -------------------------------------------------

        q["topic"] = str(
            q.get(
                "topic",
                "Информатика"
            )
        ).strip()

        q["question"] = str(
            q.get(
                "question",
                ""
            )
        ).strip()

        q["explanation"] = str(
            q.get(
                "explanation",
                ""
            )
        ).strip()

        q["theory"] = str(
            q.get(
                "theory",
                ""
            )
        ).strip()

        q["context"] = str(
            q.get(
                "context",
                ""
            )
        ).strip()

        if not q["question"]:

            raise ValueError(
                f"{index}-сұрақ бос."
            )

        if not q["explanation"]:

            raise ValueError(
                f"{index}-сұрақта explanation жоқ."
            )

        if not q["theory"]:

            raise ValueError(
                f"{index}-сұрақта theory жоқ."
            )

        # Сервер difficulty-ді өзі бекітеді.

        q["difficulty"] = (
            difficulty_pattern[
                index - 1
            ]
        )

        # -------------------------------------------------
        # SINGLE
        # -------------------------------------------------

        if actual_type in (
            "single",
            "context_single"
        ):

            options = q.get(
                "options",
                []
            )

            if not isinstance(
                options,
                list
            ):

                raise ValueError(
                    f"{index}-сұрақ options массив емес."
                )

            if len(options) != 4:

                raise ValueError(
                    f"{index}-сұрақта "
                    f"дәл 4 жауап болуы керек."
                )

            options = [
                str(x).strip()
                for x in options
            ]

            if any(
                not x
                for x in options
            ):

                raise ValueError(
                    f"{index}-сұрақта бос жауап бар."
                )

            q["options"] = options

            try:

                answer_index = int(
                    q.get(
                        "answer_index",
                        -1
                    )
                )

            except (
                ValueError,
                TypeError
            ):

                raise ValueError(
                    f"{index}-сұрақтың "
                    f"answer_index қате."
                )

            if not (
                0
                <=
                answer_index
                <=
                3
            ):

                raise ValueError(
                    f"{index}-сұрақтың "
                    f"answer_index 0–3 болуы керек."
                )

            q["answer_index"] = (
                answer_index
            )

            q["answer"] = (
                answer_index
            )

            q["answer_indices"] = []
            q["left"] = []
            q["right"] = []

        # -------------------------------------------------
        # MULTIPLE
        # -------------------------------------------------

        elif actual_type == "multiple":

            options = q.get(
                "options",
                []
            )

            if not isinstance(
                options,
                list
            ):

                raise ValueError(
                    f"{index}-multiple options массив емес."
                )

            if len(options) != 6:

                raise ValueError(
                    f"{index}-multiple "
                    f"сұрағында дәл 6 жауап болуы керек."
                )

            q["options"] = [
                str(x).strip()
                for x in options
            ]

            try:

                answers = [
                    int(x)
                    for x
                    in q.get(
                        "answer_indices",
                        []
                    )
                ]

            except (
                ValueError,
                TypeError
            ):

                raise ValueError(
                    f"{index}-multiple "
                    f"answer_indices қате."
                )

            if not (
                1
                <=
                len(answers)
                <=
                3
            ):

                raise ValueError(
                    f"{index}-multiple "
                    f"сұрағында 1–3 дұрыс жауап болуы керек."
                )

            if len(
                set(answers)
            ) != len(answers):

                raise ValueError(
                    f"{index}-multiple "
                    f"жауаптары қайталанған."
                )

            if any(
                x < 0 or x > 5
                for x in answers
            ):

                raise ValueError(
                    f"{index}-multiple "
                    f"жауап индексі 0–5 болуы керек."
                )

            answers = sorted(
                answers
            )

            q["answer_indices"] = answers
            q["answer"] = answers

            q["answer_index"] = -1
            q["left"] = []
            q["right"] = []

        # -------------------------------------------------
        # MATCH
        # -------------------------------------------------

        elif actual_type == "match":

            left = q.get(
                "left",
                []
            )

            right = q.get(
                "right",
                []
            )

            if not isinstance(
                left,
                list
            ):

                raise ValueError(
                    f"{index}-match left массив емес."
                )

            if not isinstance(
                right,
                list
            ):

                raise ValueError(
                    f"{index}-match right массив емес."
                )

            if len(left) != 2:

                raise ValueError(
                    f"{index}-match "
                    f"left = дәл 2 болуы керек."
                )

            if len(right) != 4:

                raise ValueError(
                    f"{index}-match "
                    f"right = дәл 4 болуы керек."
                )

            try:

                answers = [
                    int(x)
                    for x
                    in q.get(
                        "answer_indices",
                        []
                    )
                ]

            except (
                ValueError,
                TypeError
            ):

                raise ValueError(
                    f"{index}-match "
                    f"answer_indices қате."
                )

            if len(answers) != 2:

                raise ValueError(
                    f"{index}-match "
                    f"answer_indices = дәл 2 болуы керек."
                )

            if any(
                x < 0 or x > 3
                for x in answers
            ):

                raise ValueError(
                    f"{index}-match "
                    f"answer_indices 0–3 болуы керек."
                )

            q["left"] = [
                str(x).strip()
                for x in left
            ]

            q["right"] = [
                str(x).strip()
                for x in right
            ]

            q["answer_indices"] = answers
            q["answer"] = answers

            q["options"] = []
            q["answer_index"] = -1

        result.append(
            q
        )

    # =====================================================
    # CONTEXT CHECK
    # =====================================================

    contexts = [
        q.get(
            "context",
            ""
        )
        for q
        in result[25:30]
    ]

    if not contexts[0]:

        raise ValueError(
            "26–30 контексті бос."
        )

    if any(
        not context
        for context
        in contexts
    ):

        raise ValueError(
            "26–30 сұрақтарының бірінде "
            "context бос."
        )

    if any(
        context != contexts[0]
        for context
        in contexts
    ):

        raise ValueError(
            "26–30 сұрақтарында "
            "бірдей ортақ контекст болуы керек."
        )

    # =====================================================
    # DIFFICULTY CHECK
    # =====================================================

    actual_difficulties = [
        q["difficulty"]
        for q
        in result
    ]

    if actual_difficulties != difficulty_pattern:

        raise ValueError(
            "Difficulty pattern сәйкес емес."
        )

    # =====================================================
    # COUNT
    # =====================================================

    counts = {
        "A": actual_difficulties.count("A"),
        "B": actual_difficulties.count("B"),
        "C": actual_difficulties.count("C")
    }

    if counts != {
        "A": 20,
        "B": 12,
        "C": 8
    }:

        raise ValueError(
            f"Difficulty саны қате: {counts}"
        )

    return result


# =========================================================
# CLEAN GEMINI JSON
# =========================================================

def clean_json_response(
    raw
):

    if not raw:

        raise ValueError(
            "Gemini бос жауап қайтарды."
        )

    raw = raw.strip()

    # ```json ... ``` болса алып тастау

    if raw.startswith(
        "```"
    ):

        raw = re.sub(
            r"^```(?:json)?\s*",
            "",
            raw,
            flags=re.IGNORECASE
        )

        raw = re.sub(
            r"\s*```$",
            "",
            raw
        )

        raw = raw.strip()

    # JSON басталғанға дейінгі
    # артық мәтінді алып тастау

    start = raw.find(
        "{"
    )

    end = raw.rfind(
        "}"
    )

    if start >= 0 and end > start:

        raw = raw[
            start:end + 1
        ]

    return raw


# =========================================================
# GENERATE UBT
# =========================================================

def generate_ubt_questions():

    if gemini_client is None:

        raise RuntimeError(
            "Gemini іске қосылмаған."
        )

    last_error = ""

    for attempt in range(
        1,
        6
    ):

        difficulty_pattern = (
            make_difficulty_pattern()
        )

        try:

            print()
            print(
                f"🤖 ҰБТ генерациясы: "
                f"{attempt}/5"
            )

            response = (

                gemini_client
                .models
                .generate_content(

                    model=GEMINI_MODEL,

                    contents=
                        build_generator_prompt(
                            difficulty_pattern
                        ),

                    config=
                    types.GenerateContentConfig(

                        response_mime_type=
                            "application/json",

                        temperature=1.0,

                        max_output_tokens=
                            30000

                    )

                )

            )

            raw = response.text

            print(
                f"📦 Gemini жауабы: "
                f"{len(raw or '')} таңба"
            )

            raw = clean_json_response(
                raw
            )

            data = json.loads(
                raw
            )

            if not isinstance(
                data,
                dict
            ):

                raise ValueError(
                    "Gemini JSON объект қайтармады."
                )

            questions = data.get(
                "questions",
                []
            )

            questions = (
                validate_generated_questions(
                    questions,
                    difficulty_pattern
                )
            )

            print(
                "✅ 40/40 сұрақ дұрыс."
            )

            print(
                "✅ Difficulty тексерілді."
            )

            print(
                "✅ A=20, B=12, C=8"
            )

            return questions

        except json.JSONDecodeError as error:

            last_error = (
                f"JSON қатесі: {error}"
            )

            print(
                "⚠️ JSON дұрыс емес:"
            )

            print(
                last_error
            )

        except Exception as error:

            last_error = str(
                error
            )

            print(
                f"⚠️ {attempt}/5 қате:"
            )

            print(
                last_error
            )

        if attempt < 5:

            print(
                "🔄 Қайта генерация..."
            )

    raise RuntimeError(

        "5 әрекеттен кейін "
        "дұрыс ҰБТ нұсқасы жасалмады.\n"
        +
        last_error

    )


# =========================================================
# GENERATOR API
# =========================================================

@app.route(
    "/api/generate-test",
    methods=["POST"]
)
def api_generate_test():

    try:

        questions = (
            generate_ubt_questions()
        )

        test_id = str(
            uuid.uuid4()
        )

        title = (
            "AI жасаған "
            "Информатика ҰБТ нұсқасы"
        )

        connection = sqlite3.connect(
            DB_FILE,
            timeout=30
        )

        connection.execute(
            "PRAGMA busy_timeout=30000"
        )

        connection.execute(

            """
            INSERT INTO generated_tests
            (
                id,
                title,
                questions
            )
            VALUES (?, ?, ?)
            """,

            (
                test_id,
                title,
                json.dumps(
                    questions,
                    ensure_ascii=False
                )
            )

        )

        connection.commit()

        connection.close()

        print(
            "✅ AI ҰБТ нұсқасы сақталды."
        )

        return jsonify({

            "success":
                True,

            "test_id":
                test_id,

            "url":
                url_for(
                    "generated_test",
                    test_id=test_id
                )

        })

    except Exception as error:

        print()
        print(
            "❌ AI TEST GENERATION ҚАТЕСІ:"
        )
        print(error)
        print()

        return jsonify({

            "success":
                False,

            "error":
                str(error)

        }), 500


# =========================================================
# GENERATED TEST
# =========================================================

@app.route(
    "/generated-test/<test_id>"
)
def generated_test(
    test_id
):

    connection = sqlite3.connect(
        DB_FILE,
        timeout=30
    )

    row = connection.execute(

        """
        SELECT
            title,
            questions
        FROM generated_tests
        WHERE id = ?
        """,

        (
            test_id,
        )

    ).fetchone()

    connection.close()

    if not row:

        return """

        <h2>
            ❌ Тест табылмады.
        </h2>

        <a href="/generate">
            Жаңа тест жасау
        </a>

        """

    try:

        questions = json.loads(
            row[1]
        )

    except json.JSONDecodeError:

        return """

        <h2>
            ❌ Тест деректері бұзылған.
        </h2>

        <a href="/generate">
            Жаңа тест жасау
        </a>

        """

    return render_template(

        "test.html",

        questions=questions,

        generated=True,

        test_id=test_id,

        test_title=row[0]

    )


# =========================================================
# GENERATED TEST CHECK
# =========================================================

@app.route(
    "/api/check-generated",
    methods=["POST"]
)
def check_generated():

    try:

        data = request.get_json(
            silent=True
        ) or {}

        test_id = data.get(
            "test_id"
        )

        answers = data.get(
            "answers",
            {}
        )

        if not test_id:

            return jsonify({

                "error":
                    "test_id жоқ."

            }), 400

        connection = sqlite3.connect(
            DB_FILE,
            timeout=30
        )

        row = connection.execute(

            """
            SELECT questions
            FROM generated_tests
            WHERE id = ?
            """,

            (
                test_id,
            )

        ).fetchone()

        connection.close()

        if not row:

            return jsonify({

                "error":
                    "Тест табылмады."

            }), 404

        questions = json.loads(
            row[0]
        )

        score = 0
        answered = 0
        details = []

        for question in questions:

            question_id = str(
                question["id"]
            )

            user_answer = answers.get(
                question_id
            )

            if user_answer is not None:

                answered += 1

            points = calculate_score(
                question,
                user_answer
            )

            score += points

            details.append({

                "id":
                    question["id"],

                "type":
                    question["type"],

                "topic":
                    question["topic"],

                "question":
                    question["question"],

                "user":
                    user_answer,

                "correct":
                    question["answer"],

                "points":
                    points,

                "explanation":
                    question.get(
                        "explanation",
                        ""
                    ),

                "theory":
                    question.get(
                        "theory",
                        ""
                    )

            })

        max_score = get_max_score(
            questions
        )

        save_result(
            score,
            max_score,
            answered,
            len(questions)
        )

        return jsonify({

            "score":
                score,

            "max_score":
                max_score,

            "answered":
                answered,

            "total":
                len(questions),

            "details":
                details

        })

    except Exception as error:

        print(
            "❌ /api/check-generated:",
            error
        )

        return jsonify({

            "error":
                str(error)

        }), 500


# =========================================================
# RESULTS
# =========================================================

@app.route(
    "/results"
)
def results():

    connection = sqlite3.connect(
        DB_FILE,
        timeout=30
    )

    rows = connection.execute(

        """
        SELECT
            score,
            max_score,
            answered,
            total,
            created_at

        FROM results

        ORDER BY id DESC

        LIMIT 50

        """

    ).fetchall()

    connection.close()

    html_page = """

    <!DOCTYPE html>

    <html lang="kk">

    <head>

        <meta charset="UTF-8">

        <meta name="viewport"
              content="width=device-width,
                       initial-scale=1.0">

        <title>
            Нәтижелер
        </title>

        <style>

            body {
                font-family: Arial;
                background: #07111f;
                color: white;
                padding: 30px;
            }

            .box {
                max-width: 1000px;
                margin: auto;
            }

            table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }

            th,
            td {
                border-bottom:
                    1px solid #20394f;
                padding: 12px;
                text-align: left;
            }

            th {
                color: #4fd8ff;
            }

            a {
                color: #4fd8ff;
            }

        </style>

    </head>

    <body>

        <div class="box">

            <h1>
                📊 Нәтижелер
            </h1>

            <a href="/">
                ← Басты бет
            </a>

            <table>

                <tr>

                    <th>
                        Балл
                    </th>

                    <th>
                        Жауап
                    </th>

                    <th>
                        Сұрақ
                    </th>

                    <th>
                        Уақыты
                    </th>

                </tr>

    """

    for row in rows:

        score = row[0]

        max_score = row[1]

        answered = row[2]

        total = row[3]

        created = row[4]

        html_page += f"""

                <tr>

                    <td>
                        {score} / {max_score}
                    </td>

                    <td>
                        {answered}
                    </td>

                    <td>
                        {total}
                    </td>

                    <td>
                        {created}
                    </td>

                </tr>

        """

    html_page += """

            </table>

        </div>

    </body>

    </html>

    """

    return html_page


# =========================================================
# SERVER
# =========================================================

if __name__ == "__main__":

    init_database()

    questions = load_questions()

    print()

    print("=" * 65)

    print(
        "                    INFO ҰБТ AI"
    )

    print("=" * 65)

    print()

    print(
        f"📚 Базада: {len(questions)} сұрақ"
    )

    print(
        f"🤖 Gemini: {GEMINI_MODEL}"
    )

    print(
        "🧠 AI мұғалім: ҚОСУЛЫ"
    )

    print(
        "🎯 AI ҰБТ генераторы: ҚОСУЛЫ"
    )

    print()

    print(
        "🌐 http://127.0.0.1:5000"
    )

    print()

    app.run(
        debug=True
    )
