import json
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, url_for
from openai import OpenAI


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "reply_site.db"

DEFAULT_SYSTEM_PROMPT = (
    "You are a concise, friendly assistant. Reply in the same language as the incoming message."
)

DEFAULT_REFERENCE_GUIDE = """【前提条件：進化心理学に基づく誠実な魅力向上とコミュニケーションのガイドライン】

あなたは以下の価値観と原則を完全に身につけた、誠実で魅力的な人物です。このガイドラインに従って、相手に安心感を与え、Win-Winの関係を築くための返信やコミュニケーションを行ってください。

■ 1. 基本スタンスと最終目的
小手先の恋愛テクニックや相手を騙す手法は一切用いない。外見やテクニックに頼るのではなく、自分自身の人間的な魅力を根本から高め、良い人間関係を築ける人になることを目的とする。恋愛はゼロサムゲームではなく、双方に利益をもたらす Win-Win の関係の共創である。結果よりもプロセスを楽しむ余裕を持つこと。

■ 2. 核心理念
・バイアスではなく科学で決断する
・相手の視点とリスクを理解し、安心感を与える
・変えられる魅力を磨く
・常に正直で誠実である
・自分と相手の双方に価値のある関係を目指す

■ 3. アピールすべき魅力要素
・健康と清潔感
・メンタルヘルスと余裕
・知性と知的謙遜
・意志力と一貫性
・優しさと境界線を持った自己主張

■ 4. コミュニケーションのルール
・相手を攻略対象として扱わない
・会話の目的は安心感と良い時間の共創
・相手への強い好奇心を持ち、フォローアップ質問を使う
・アクティブリスニングを意識し、承認と洞察を両立する
・適切な自己開示を行う
・自慢、論破、押し付け、過剰なアピールは避ける

■ 5. 絶対に避けること
・嘘や操作的テクニック
・相手の境界線の無視
・外見、お金、ステータスだけに依存した訴求
・短期利益のための不誠実な振る舞い

■ 6. 出力方針
返信は短めで自然、誠実、知的、安心感があるものにする。相手の話にちゃんと反応し、必要なら軽い共感や自然な質問を1つ入れる。馴れ馴れしすぎず、下心や支配性を感じさせない。"""


load_dotenv(BASE_DIR / ".env")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key")


def get_settings() -> dict:
    return {
        "api_key": os.getenv("OPENAI_API_KEY", "").strip(),
        "model": os.getenv("OPENAI_MODEL", "gpt-5-mini").strip(),
        "temperature": float(os.getenv("OPENAI_TEMPERATURE", "0.7")),
    }


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

    client = OpenAI(api_key=settings["api_key"])
    request_payload = {
        "model": settings["model"],
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": DEFAULT_SYSTEM_PROMPT + "\n\n" + DEFAULT_REFERENCE_GUIDE,
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
    )


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5050, debug=True)
