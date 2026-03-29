import json
import os
import base64
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, url_for
from openai import OpenAI
from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


BASE_DIR = Path(__file__).resolve().parent
REFERENCE_GUIDE_PATH = BASE_DIR / "prompts" / "reply_policy.txt"
SELF_PROFILE_PATH = BASE_DIR / "prompts" / "self_profile.txt"

DEFAULT_SYSTEM_PROMPT = (
    "You are a concise, friendly assistant. Reply in the same language as the incoming message."
)

DEFAULT_REFERENCE_GUIDE = """【前提条件：進化心理学に基づく誠実な魅力向上とコミュニケーションのガイドライン】

あなたは以下の価値観と原則を完全に身につけた、誠実で魅力的な人物です。このガイドラインに従って、相手に安心感を与え、Win-Winの関係を築くための返信やコミュニケーションを行ってください。"""


load_dotenv(BASE_DIR / ".env")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key")


def resolve_database_url() -> str:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        if database_url.startswith("postgres://"):
            return "postgresql+psycopg://" + database_url[len("postgres://") :]
        if database_url.startswith("postgresql://"):
            return "postgresql+psycopg://" + database_url[len("postgresql://") :]
        return database_url

    explicit = os.getenv("DATABASE_PATH", "").strip()
    if explicit:
        return f"sqlite:///{Path(explicit)}"

    railway_mount = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    if railway_mount:
        return f"sqlite:///{Path(railway_mount) / 'reply_site.db'}"

    return f"sqlite:///{BASE_DIR / 'data' / 'reply_site.db'}"


DATABASE_URL = resolve_database_url()
engine = create_engine(DATABASE_URL, future=True)


class Base(DeclarativeBase):
    pass


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = (
        UniqueConstraint("app_name", "country", "partner_name", "sequence", name="uq_profile_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    app_name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str] = mapped_column(String(255), nullable=False)
    partner_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sequence: Mapped[str] = mapped_column(String(255), nullable=False)
    conversation_db: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


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


def load_self_profile() -> str:
    try:
        return SELF_PROFILE_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def init_db() -> None:
    if DATABASE_URL.startswith("sqlite:///"):
        db_file = Path(DATABASE_URL.replace("sqlite:///", "", 1))
        db_file.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)


def db_session() -> Session:
    return Session(engine)


def profile_to_dict(profile: Profile) -> dict:
    return {
        "id": profile.id,
        "app_name": profile.app_name,
        "country": profile.country,
        "partner_name": profile.partner_name,
        "sequence": profile.sequence,
        "conversation_db": profile.conversation_db,
    }


def profile_key(profile: dict) -> str:
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


def replace_last_you_block(database: str, old_reply: str, new_reply: str) -> str:
    database = (database or "").strip()
    old_block = f"[You]\n{normalize_block(old_reply)}".strip()
    new_block = f"[You]\n{normalize_block(new_reply)}".strip()
    if not database or not old_block or not new_block:
        return database
    if database.endswith(old_block):
        return (database[: -len(old_block)] + new_block).strip()
    return database


def build_user_prompt(profile: dict, incoming_message: str) -> str:
    history = trim_for_prompt(profile["conversation_db"], 12000)
    self_profile = load_self_profile()
    history_block = ""
    if history:
        history_block = (
            f"以下は {profile_key(profile)} との過去会話のデータベースです。"
            "これを参照して、同じことを何度も聞かず、話題の連続性を保ってください。\n\n"
            f"{history}\n\n"
        )
    self_profile_block = ""
    if self_profile:
        self_profile_block = (
            "以下は自分のプロフィール情報です。自己開示が自然に役立つ場合だけ、この範囲から正確に使ってください。"
            "書かれていない経歴や価値観を作らないでください。自己開示は短く、相手中心の会話を優先してください。\n\n"
            f"{self_profile}\n\n"
        )
    return (
        history_block
        + self_profile_block
        + "以下の新しい相手メッセージに対する自然で短めの返信文を作成してください。"
        + "必ずJSONで返し、keysは reply と japanese_translation の2つだけにしてください。"
        + "reply には相手に実際に送る文、japanese_translation にはその reply の自然な日本語訳を入れてください。"
        + "コードブロックは使わないでください。過去会話にすでに答えがあることを再度質問しないでください。"
        + "必要なら前回の話題を自然に参照してください。自己開示する場合は、相手の話に関連する範囲だけを短く自然に入れてください。"
        + "質問を入れる場合は最大1つまでにしてください。複数の質問を並べないでください。\n\n"
        + f"受信メッセージ:\n{incoming_message}"
    )


def generate_reply(profile: dict, incoming_message: str) -> dict:
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


def translate_message_to_japanese(incoming_message: str) -> str:
    settings = get_settings()
    if not settings["api_key"]:
        raise RuntimeError("OPENAI_API_KEY が未設定です。.env を確認してください。")

    client = OpenAI(api_key=settings["api_key"])
    request_payload = {
        "model": settings["model"],
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "次のメッセージを自然な日本語に翻訳してください。"
                            "説明は不要で、翻訳文だけを返してください。\n\n"
                            f"{incoming_message}"
                        ),
                    }
                ],
            }
        ],
    }
    if supports_temperature(settings["model"]):
        request_payload["temperature"] = settings["temperature"]

    response = client.responses.create(**request_payload)
    return response.output_text.strip()


def retranslate_from_japanese(profile: dict, incoming_message: str, edited_japanese: str) -> dict:
    settings = get_settings()
    if not settings["api_key"]:
        raise RuntimeError("OPENAI_API_KEY が未設定です。.env を確認してください。")

    reference_guide = load_reference_guide()
    self_profile = load_self_profile()
    history = trim_for_prompt(profile["conversation_db"], 12000)
    history_block = (
        f"以下は {profile_key(profile)} との過去会話のデータベースです。\n\n{history}\n\n" if history else ""
    )
    self_profile_block = (
        "以下は自分のプロフィール情報です。自己開示が必要なときだけ、この範囲から正確に使ってください。\n\n"
        f"{self_profile}\n\n"
        if self_profile
        else ""
    )

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
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            history_block
                            + self_profile_block
                            + "以下の incoming message に対する返信として、edited Japanese draft の意味を保ったまま、"
                            + "incoming message と同じ言語で自然な返信文へ再翻訳してください。"
                            + "必ずJSONで返し、keysは reply と japanese_translation の2つだけ。"
                            + "reply は相手に送る文、japanese_translation は編集後の日本語文をそのまま自然に整えたものにしてください。"
                            + "コードブロックは禁止。質問を入れる場合は最大1つまでにしてください。複数の質問を並べないでください。\n\n"
                            + f"incoming message:\n{incoming_message}\n\n"
                            + f"edited Japanese draft:\n{edited_japanese}"
                        ),
                    }
                ],
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
        return {"reply": raw_text, "japanese_translation": edited_japanese.strip()}
    return {
        "reply": str(parsed.get("reply", "")).strip(),
        "japanese_translation": str(parsed.get("japanese_translation", "")).strip()
        or edited_japanese.strip(),
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


def fetch_profiles() -> list[dict]:
    with db_session() as session:
        profiles = session.execute(
            select(Profile).order_by(Profile.app_name, Profile.country, Profile.partner_name, Profile.sequence)
        ).scalars().all()
        return [profile_to_dict(profile) for profile in profiles]


def fetch_profile(profile_id: int | None) -> dict | None:
    if not profile_id:
        return None
    with db_session() as session:
        profile = session.get(Profile, profile_id)
        return profile_to_dict(profile) if profile else None


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
        translated_message="",
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
            translated_message="",
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
            translated_message="",
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
            translated_message="",
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
        translated_message="",
        current_profile_key=profile_key(selected_profile) if selected_profile else "",
        profile_key_fn=profile_key,
        imported_profile=imported_profile,
    )


@app.post("/translate-message")
def translate_message():
    init_db()
    profile_id = request.form.get("profile_id", type=int)
    incoming_message = request.form.get("incoming_message", "").strip()
    selected_profile = fetch_profile(profile_id)
    profiles = fetch_profiles()

    if not incoming_message:
        flash("翻訳したい相手メッセージを入力してください。", "error")
        return render_template(
            "index.html",
            profiles=profiles,
            selected_profile=selected_profile,
            result=None,
            incoming_message="",
            translated_message="",
            current_profile_key=profile_key(selected_profile) if selected_profile else "",
            profile_key_fn=profile_key,
            imported_profile=None,
        )

    try:
        translated_message = translate_message_to_japanese(incoming_message)
    except Exception as exc:
        flash(str(exc), "error")
        translated_message = ""

    return render_template(
        "index.html",
        profiles=profiles,
        selected_profile=selected_profile,
        result=None,
        incoming_message=incoming_message,
        translated_message=translated_message,
        current_profile_key=profile_key(selected_profile) if selected_profile else "",
        profile_key_fn=profile_key,
        imported_profile=None,
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
        with db_session() as session:
            if profile_id:
                profile = session.get(Profile, profile_id)
                if not profile:
                    flash("プロフィールが見つかりません。", "error")
                    return redirect(url_for("index"))
            else:
                profile = Profile()
                session.add(profile)

            profile.app_name = app_name
            profile.country = country
            profile.partner_name = partner_name
            profile.sequence = sequence
            profile.conversation_db = conversation_db
            session.commit()
            profile_id = profile.id
    except IntegrityError:
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
            translated_message="",
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
            translated_message="",
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
            translated_message="",
            current_profile_key=profile_key(selected_profile),
            profile_key_fn=profile_key,
            imported_profile=None,
        )

    updated_db = append_conversation_turn(
        selected_profile["conversation_db"],
        incoming_message,
        result["reply"],
    )

    with db_session() as session:
        profile = session.get(Profile, profile_id)
        if profile:
            profile.conversation_db = updated_db
            session.commit()

    selected_profile = fetch_profile(profile_id)
    flash("返信を生成し、会話DBに追記しました。", "success")
    return render_template(
        "index.html",
        profiles=fetch_profiles(),
        selected_profile=selected_profile,
        result=result,
        incoming_message=incoming_message,
        translated_message="",
        current_profile_key=profile_key(selected_profile),
        profile_key_fn=profile_key,
        imported_profile=None,
    )


@app.post("/retranslate")
def retranslate():
    init_db()
    profile_id = request.form.get("profile_id", type=int)
    incoming_message = request.form.get("incoming_message", "").strip()
    edited_japanese = request.form.get("edited_japanese", "").strip()
    previous_reply = request.form.get("previous_reply", "").strip()
    selected_profile = fetch_profile(profile_id)
    profiles = fetch_profiles()

    if not selected_profile:
        flash("先にプロフィールを選択してください。", "error")
        return render_template(
            "index.html",
            profiles=profiles,
            selected_profile=None,
            result=None,
            incoming_message=incoming_message,
            translated_message="",
            current_profile_key="",
            profile_key_fn=profile_key,
            imported_profile=None,
        )

    if not edited_japanese:
        flash("編集後の日本語文を入力してください。", "error")
        return render_template(
            "index.html",
            profiles=profiles,
            selected_profile=selected_profile,
            result=None,
            incoming_message=incoming_message,
            translated_message="",
            current_profile_key=profile_key(selected_profile),
            profile_key_fn=profile_key,
            imported_profile=None,
        )

    try:
        result = retranslate_from_japanese(selected_profile, incoming_message, edited_japanese)
    except Exception as exc:
        flash(str(exc), "error")
        return render_template(
            "index.html",
            profiles=profiles,
            selected_profile=selected_profile,
            result=None,
            incoming_message=incoming_message,
            translated_message="",
            current_profile_key=profile_key(selected_profile),
            profile_key_fn=profile_key,
            imported_profile=None,
        )

    updated_db = replace_last_you_block(selected_profile["conversation_db"], previous_reply, result["reply"])
    if updated_db != selected_profile["conversation_db"]:
        with db_session() as session:
            profile = session.get(Profile, profile_id)
            if profile:
                profile.conversation_db = updated_db
                session.commit()
        selected_profile = fetch_profile(profile_id)

    flash("日本語の微調整内容を相手の言語へ再翻訳しました。", "success")
    return render_template(
        "index.html",
        profiles=fetch_profiles(),
        selected_profile=selected_profile,
        result=result,
        incoming_message=incoming_message,
        translated_message="",
        current_profile_key=profile_key(selected_profile),
        profile_key_fn=profile_key,
        imported_profile=None,
    )


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5050, debug=True)
