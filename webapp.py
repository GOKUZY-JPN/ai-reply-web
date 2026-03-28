import json
import os
import sqlite3
import base64
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, url_for
from openai import OpenAI


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "reply_site.db"
REFERENCE_GUIDE_PATH = BASE_DIR / "prompts" / "reply_policy.txt"

DEFAULT_SYSTEM_PROMPT = (
    "You are a concise, friendly assistant. Reply in the same language as the incoming message."
)

DEFAULT_REFERENCE_GUIDE = """【前提条件：進化心理学に基づく誠実な魅力向上とコミュニケーションのガイドライン】

あなたは以下の価値観と原則を完全に身につけた、誠実で魅力的な人物です。このガイドラインに従って、相手に安心感を与え、Win-Winの関係を築くための返信やコミュニケーションを行ってください。"""


load_dotenv(BASE_DIR / ".env")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key")


def get_settings() -> dict:
    return {
        "api_key": os.getenv("OPENAI_API_KEY", "").strip(),
        "model": os.getenv("OPENAI_MODEL", "gpt-5-mini").strip(),
        "vision_model": os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini").strip(),
        "temperature": float(os.getenv("OPENAI_TEMPERATURE", "0.7")),
    }


def load_reference_guide() -> str:
    try:
        text = REFERENCE_GUIDE_PATH.read_text(encoding="utf-8").strip()
        return text or DEFAULT_REFERENCE_GUIDE
    except FileNotFoundError:
        return DEFAULT_REFERENCE_GUIDE


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_name TEXT NOT NULL,
                country TEXT NOT NULL,
                partner_name TEXT NOT NULL,
                sequence TEXT NOT NULL,
                conversation_db TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(app_name, country, partner_name, sequence)
            )
            """
        )
        conn.commit()


def db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def profile_key(profile: sqlite3.Row | dict) -> str:
    return "__".join(
        [
            sanitize_part(profile["app_name"]),
            sanitize_part(profile["country"]),
            sanitize_part(profile["partner_name"]),
            sanitize_part(profile["sequence"]),
        ]
    )


def sanitize_part(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "unknown"
    cleaned = []
    last_dash = False
    for char in text:
        if char.isalnum() or char in {"_", "-"}:
            cleaned.append(char)
            last_dash = False
        elif char.isspace() or char in {"/", ".", ","}:
            if not last_dash:
                cleaned.append("-")
                last_dash = True
        else:
            if not last_dash:
                cleaned.append("-")
                last_dash = True
    return "".join(cleaned).strip("-") or "unknown"


def supports_temperature(model: str) -> bool:
    return not model.lower().startswith("gpt-5")


def trim_for_prompt(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def normalize_block(text: str) -> str:
    return "\n".join(line.strip() for line in str(text or "").splitlines() if line.strip()).strip()


def append_block_if_new(database: str, speaker: str, text: str) -> str:
    normalized_text = normalize_block(text)
    if not normalized_text:
        return database
    block = f"[{speaker}]\n{normalized_text}"
    database = (database or "").strip()
    if not database:
        return block
    pieces = database.split("\n\n")
    if pieces and pieces[-1].strip() == block:
        return database
    return f"{database}\n\n{block}"


def append_conversation_turn(database: str, incoming_message: str, reply_text: str) -> str:
    updated = append_block_if_new(database, "Partner", incoming_message)
    updated = append_block_if_new(updated, "You", reply_text)
    return updated.strip()


def build_user_prompt(profile: sqlite3.Row, incoming_message: str) -> str:
    history = trim_for_prompt(profile["conversation_db"], 12000)
    history_block = ""
    if history:
        history_block = (
            f"以下は {profile_key(profile)} との過去会話のデータベースです。"
            "これを参照して、同じことを何度も聞かず、話題の連続性を保ってください。\n\n"
            f"{history}\n\n"
        )
    return (
        history_block
        + "以下の新しい相手メッセージに対する自然で短めの返信文を作成してください。"
        + "必ずJSONで返し、keysは reply と japanese_translation の2つだけにしてください。"
        + "reply には相手に実際に送る文、japanese_translation にはその reply の自然な日本語訳を入れてください。"
        + "コードブロックは使わないでください。過去会話にすでに答えがあることを再度質問しないでください。"
        + "必要なら前回の話題を自然に参照してください。\n\n"
        + f"受信メッセージ:\n{incoming_message}"
    )


def generate_reply(profile: sqlite3.Row, incoming_message: str) -> dict:
    settings = get_settings()
    if not settings["api_key"]:
        raise RuntimeError("OPENAI_API_KEY が未設定です。.env を確認してください。")

    reference_guide = load_reference_guide()
    client = OpenAI(api_key=settings["api_key"])
    request_payload = {
        "model": settings["model"],
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": DEFAULT_SYSTEM_PROMPT + "\n\n" + reference_guide,
                    }
                ],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": build_user_prompt(profile, incoming_message)}],
            },
        ],
    }
    if supports_temperature(settings["model"]):
        request_payload["temperature"] = settings["temperature"]

    response = client.responses.create(**request_payload)
    raw_text = response.output_text.strip()
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return {"reply": raw_text, "japanese_translation": ""}
    return {
        "reply": str(parsed.get("reply", "")).strip(),
        "japanese_translation": str(parsed.get("japanese_translation", "")).strip(),
    }


def extract_profile_from_image(image_bytes: bytes, filename: str) -> dict:
    settings = get_settings()
    if not settings["api_key"]:
        raise RuntimeError("OPENAI_API_KEY が未設定です。.env を確認してください。")

    suffix = Path(filename or "upload.png").suffix.lower()
    mime_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(suffix, "image/png")

    image_data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('utf-8')}"
    client = OpenAI(api_key=settings["api_key"])
    request_payload = {
        "model": settings["vision_model"],
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "このプロフィールスクリーンショットから、プロフィール入力に必要な情報を抽出してください。"
                            "必ずJSONで返し、keysは app_name, country, partner_name, sequence, profile_notes のみ。"
                            "sequence は見えなければ '1'。country や app_name が推定でも分かるなら入れる。"
                            "profile_notes には、自己紹介、言語、趣味など保存に役立つ内容を短く整理して入れる。"
                            "分からない項目は空文字にしてください。コードブロックは禁止。"
                        ),
                    },
                    {
                        "type": "input_image",
                        "image_url": image_data_url,
                        "detail": "high",
                    },
                ],
            }
        ],
    }
    response = client.responses.create(**request_payload)
    raw_text = response.output_text.strip()
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"画像からプロフィール抽出に失敗しました: {raw_text}") from exc

    return {
        "app_name": str(parsed.get("app_name", "")).strip() or "Tandem",
        "country": str(parsed.get("country", "")).strip(),
        "partner_name": str(parsed.get("partner_name", "")).strip(),
        "sequence": str(parsed.get("sequence", "")).strip() or "1",
        "profile_notes": str(parsed.get("profile_notes", "")).strip(),
    }


def fetch_profiles() -> list[sqlite3.Row]:
    with db_connection() as conn:
        return conn.execute(
            "SELECT * FROM profiles ORDER BY app_name, country, partner_name, sequence"
        ).fetchall()


def fetch_profile(profile_id: int | None) -> sqlite3.Row | None:
    if not profile_id:
        return None
    with db_connection() as conn:
        return conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()


@app.get("/")
def index():
    init_db()
    profiles = fetch_profiles()
    selected_id = request.args.get("profile_id", type=int)
    selected_profile = fetch_profile(selected_id) if selected_id else (profiles[0] if profiles else None)
    return render_template(
        "index.html",
        profiles=profiles,
        selected_profile=selected_profile,
        result=None,
        incoming_message="",
        current_profile_key=profile_key(selected_profile) if selected_profile else "",
        profile_key_fn=profile_key,
        imported_profile=None,
    )


@app.post("/profiles/import-image")
def import_profile_image():
    init_db()
    profiles = fetch_profiles()
    selected_id = request.form.get("selected_profile_id", type=int)
    selected_profile = fetch_profile(selected_id) if selected_id else (profiles[0] if profiles else None)
    uploaded_file = request.files.get("profile_image")

    if not uploaded_file or not uploaded_file.filename:
        flash("プロフィール画像のスクショを選んでください。", "error")
        return render_template(
            "index.html",
            profiles=profiles,
            selected_profile=selected_profile,
            result=None,
            incoming_message="",
            current_profile_key=profile_key(selected_profile) if selected_profile else "",
            profile_key_fn=profile_key,
            imported_profile=None,
        )

    image_bytes = uploaded_file.read()
    if not image_bytes:
        flash("画像を読み込めませんでした。", "error")
        return render_template(
            "index.html",
            profiles=profiles,
            selected_profile=selected_profile,
            result=None,
            incoming_message="",
            current_profile_key=profile_key(selected_profile) if selected_profile else "",
            profile_key_fn=profile_key,
            imported_profile=None,
        )

    try:
        extracted = extract_profile_from_image(image_bytes, uploaded_file.filename)
    except Exception as exc:
        flash(str(exc), "error")
        return render_template(
            "index.html",
            profiles=profiles,
            selected_profile=selected_profile,
            result=None,
            incoming_message="",
            current_profile_key=profile_key(selected_profile) if selected_profile else "",
            profile_key_fn=profile_key,
            imported_profile=None,
        )

    imported_profile = {
        "id": None,
        "app_name": extracted["app_name"],
        "country": extracted["country"],
        "partner_name": extracted["partner_name"],
        "sequence": extracted["sequence"],
        "conversation_db": f"[Profile Notes]\n{extracted['profile_notes']}".strip()
        if extracted["profile_notes"]
        else "",
    }
    flash("画像からプロフィール候補を抽出しました。内容を確認してから保存してください。", "success")
    return render_template(
        "index.html",
        profiles=profiles,
        selected_profile=selected_profile,
        result=None,
        incoming_message="",
        current_profile_key=profile_key(selected_profile) if selected_profile else "",
        profile_key_fn=profile_key,
        imported_profile=imported_profile,
    )


@app.post("/profiles/save")
def save_profile():
    init_db()
    profile_id = request.form.get("profile_id", type=int)
    app_name = request.form.get("app_name", "").strip() or "Tandem"
    country = request.form.get("country", "").strip()
    partner_name = request.form.get("partner_name", "").strip()
    sequence = request.form.get("sequence", "").strip() or "1"
    conversation_db = request.form.get("conversation_db", "").strip()

    if not country or not partner_name:
        flash("Country と Partner Name は必須です。", "error")
        return redirect(url_for("index", profile_id=profile_id or ""))

    try:
        with db_connection() as conn:
            if profile_id:
                conn.execute(
                    """
                    UPDATE profiles
                    SET app_name = ?, country = ?, partner_name = ?, sequence = ?, conversation_db = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (app_name, country, partner_name, sequence, conversation_db, profile_id),
                )
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO profiles (app_name, country, partner_name, sequence, conversation_db)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (app_name, country, partner_name, sequence, conversation_db),
                )
                profile_id = cursor.lastrowid
            conn.commit()
    except sqlite3.IntegrityError:
        flash(
            "同じ App Name / Country / Partner Name / Sequence のプロフィールがすでにあります。Sequence を変えるか、既存プロフィールを編集してください。",
            "error",
        )
        return redirect(url_for("index", profile_id=profile_id or ""))
    except Exception:
        app.logger.exception("Failed to save profile")
        flash("プロフィール保存中にエラーが発生しました。Railway のログも確認してください。", "error")
        return redirect(url_for("index", profile_id=profile_id or ""))

    flash("プロフィールを保存しました。", "success")
    return redirect(url_for("index", profile_id=profile_id))


@app.post("/generate")
def generate():
    init_db()
    profile_id = request.form.get("profile_id", type=int)
    incoming_message = request.form.get("incoming_message", "").strip()
    selected_profile = fetch_profile(profile_id)
    profiles = fetch_profiles()

    if not selected_profile:
        flash("先にプロフィールを作成または選択してください。", "error")
        return render_template(
            "index.html",
            profiles=profiles,
        selected_profile=None,
        result=None,
        incoming_message=incoming_message,
        current_profile_key="",
        profile_key_fn=profile_key,
        imported_profile=None,
    )

    if not incoming_message:
        flash("相手の新しいメッセージを入力してください。", "error")
        return render_template(
            "index.html",
            profiles=profiles,
            selected_profile=selected_profile,
            result=None,
            incoming_message="",
            current_profile_key=profile_key(selected_profile),
            profile_key_fn=profile_key,
            imported_profile=None,
        )

    try:
        result = generate_reply(selected_profile, incoming_message)
    except Exception as exc:
        flash(str(exc), "error")
        return render_template(
            "index.html",
            profiles=profiles,
            selected_profile=selected_profile,
            result=None,
            incoming_message=incoming_message,
            current_profile_key=profile_key(selected_profile),
            profile_key_fn=profile_key,
            imported_profile=None,
        )

    updated_db = append_conversation_turn(
        selected_profile["conversation_db"],
        incoming_message,
        result["reply"],
    )

    with db_connection() as conn:
        conn.execute(
            """
            UPDATE profiles
            SET conversation_db = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (updated_db, profile_id),
        )
        conn.commit()

    selected_profile = fetch_profile(profile_id)
    flash("返信を生成し、会話DBに追記しました。", "success")
    return render_template(
        "index.html",
        profiles=fetch_profiles(),
        selected_profile=selected_profile,
        result=result,
        incoming_message=incoming_message,
        current_profile_key=profile_key(selected_profile),
        profile_key_fn=profile_key,
        imported_profile=None,
    )


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5050, debug=True)
