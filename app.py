import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from playwright.sync_api import BrowserContext, Page, sync_playwright


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "site_config.json"
PROFILE_DIR = BASE_DIR / "browser-profile"


def load_settings() -> dict:
    load_dotenv(BASE_DIR / ".env")
    return {
        "api_key": os.getenv("OPENAI_API_KEY", "").strip(),
        "model": os.getenv("OPENAI_MODEL", "gpt-5-mini").strip(),
        "system_prompt": os.getenv(
            "SYSTEM_PROMPT",
            "You are a concise, friendly assistant. Reply in the same language as the incoming message.",
        ).strip(),
        "temperature": float(os.getenv("OPENAI_TEMPERATURE", "0.7")),
        "target_url": os.getenv("TARGET_URL", "").strip(),
        "headless": os.getenv("HEADLESS", "false").strip().lower() == "true",
    }


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise SystemExit(
            "config/site_config.json がありません。先に `python3 app.py setup` を実行してください。"
        )
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def launch_context(headless: bool) -> BrowserContext:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    playwright = sync_playwright().start()
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
        viewport={"width": 1440, "height": 960},
    )
    context._codex_playwright = playwright
    return context


def close_context(context: BrowserContext) -> None:
    playwright = getattr(context, "_codex_playwright", None)
    context.close()
    if playwright:
        playwright.stop()


def get_active_page(context: BrowserContext, target_url: str) -> Page:
    page = context.pages[0] if context.pages else context.new_page()
    if target_url and page.url in ("about:blank", ""):
        page.goto(target_url)
    return page


def prompt_enter(message: str) -> None:
    input(f"\n{message}\nEnter を押して続けてください...")


def capture_selector(page: Page, label: str) -> dict:
    print(f"\n[{label}] ブラウザ上で対象要素を1回クリックしてください。")
    return page.evaluate(
        """
        (label) => new Promise((resolve) => {
          const overlay = document.createElement("div");
          overlay.setAttribute("data-ai-reply-overlay", "true");
          overlay.style.position = "fixed";
          overlay.style.top = "16px";
          overlay.style.left = "50%";
          overlay.style.transform = "translateX(-50%)";
          overlay.style.zIndex = "2147483647";
          overlay.style.background = "rgba(17, 24, 39, 0.94)";
          overlay.style.color = "#fff";
          overlay.style.padding = "10px 14px";
          overlay.style.borderRadius = "999px";
          overlay.style.fontFamily = "ui-monospace, SFMono-Regular, Menlo, monospace";
          overlay.style.fontSize = "13px";
          overlay.style.boxShadow = "0 8px 30px rgba(0,0,0,0.2)";
          overlay.textContent = `AI Reply MVP: ${label} をクリック`;
          document.body.appendChild(overlay);

          const highlight = document.createElement("div");
          highlight.style.position = "fixed";
          highlight.style.pointerEvents = "none";
          highlight.style.zIndex = "2147483646";
          highlight.style.border = "2px solid #22c55e";
          highlight.style.background = "rgba(34, 197, 94, 0.12)";
          highlight.style.display = "none";
          document.body.appendChild(highlight);

          const escape = (value) => {
            if (window.CSS && CSS.escape) return CSS.escape(value);
            return value.replace(/([^a-zA-Z0-9_-])/g, "\\\\$1");
          };

          const uniqueSelector = (el) => {
            if (!el || el.nodeType !== Node.ELEMENT_NODE) return null;

            const attrCandidates = [
              "data-testid",
              "data-test",
              "data-qa",
              "name",
              "aria-label",
              "placeholder",
              "title",
              "role"
            ];

            if (el.id) {
              const byId = `#${escape(el.id)}`;
              if (document.querySelectorAll(byId).length === 1) return byId;
            }

            for (const attr of attrCandidates) {
              const value = el.getAttribute(attr);
              if (!value) continue;
              const selector = `${el.tagName.toLowerCase()}[${attr}="${value.replaceAll('"', '\\"')}"]`;
              if (document.querySelectorAll(selector).length === 1) return selector;
            }

            const parts = [];
            let current = el;
            while (current && current.nodeType === Node.ELEMENT_NODE && current !== document.body) {
              let part = current.tagName.toLowerCase();
              if (current.id) {
                part = `#${escape(current.id)}`;
                parts.unshift(part);
                const joined = parts.join(" > ");
                if (document.querySelectorAll(joined).length === 1) return joined;
                break;
              }

              const siblings = current.parentElement
                ? Array.from(current.parentElement.children).filter((child) => child.tagName === current.tagName)
                : [];
              if (siblings.length > 1) {
                const index = siblings.indexOf(current) + 1;
                part += `:nth-of-type(${index})`;
              }
              parts.unshift(part);
              const joined = parts.join(" > ");
              if (document.querySelectorAll(joined).length === 1) return joined;
              current = current.parentElement;
            }

            return parts.join(" > ");
          };

          const onMove = (event) => {
            const target = event.target;
            if (!(target instanceof Element)) return;
            const rect = target.getBoundingClientRect();
            highlight.style.display = "block";
            highlight.style.top = `${rect.top}px`;
            highlight.style.left = `${rect.left}px`;
            highlight.style.width = `${rect.width}px`;
            highlight.style.height = `${rect.height}px`;
          };

          const cleanup = () => {
            overlay.remove();
            highlight.remove();
            document.removeEventListener("mousemove", onMove, true);
            document.removeEventListener("click", onClick, true);
          };

          const onClick = (event) => {
            event.preventDefault();
            event.stopPropagation();
            event.stopImmediatePropagation();
            const target = event.target;
            if (!(target instanceof Element)) return;
            const selector = uniqueSelector(target);
            const text = (target.innerText || target.textContent || "").trim().slice(0, 200);
            cleanup();
            resolve({
              selector,
              preview: text,
              tag: target.tagName.toLowerCase()
            });
          };

          document.addEventListener("mousemove", onMove, true);
          document.addEventListener("click", onClick, true);
        })
        """,
        label,
    )


def generate_reply(settings: dict, message_text: str) -> str:
    if not settings["api_key"]:
        raise SystemExit(".env に OPENAI_API_KEY を設定してください。")

    client = OpenAI(api_key=settings["api_key"])
    request = {
        "model": settings["model"],
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": settings["system_prompt"]}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "以下のメッセージに対する自然で短めの返信文を作成してください。"
                            "返答文だけを出力してください。\n\n"
                            f"受信メッセージ:\n{message_text}"
                        ),
                    }
                ],
            },
        ],
    }
    if supports_temperature(settings["model"]):
        request["temperature"] = settings["temperature"]
    response = client.responses.create(**request)
    return response.output_text.strip()


def supports_temperature(model: str) -> bool:
    return not model.strip().lower().startswith("gpt-5")


def setup_command(settings: dict) -> None:
    context = launch_context(settings["headless"])
    try:
        page = get_active_page(context, settings["target_url"])
        page.bring_to_front()
        prompt_enter("ログインして、返信したいページを開いてください。")
        config = {
            "page_url": page.url,
            "message": capture_selector(page, "最新メッセージ"),
            "reply_box": capture_selector(page, "返信入力欄"),
            "send_button": capture_selector(page, "送信ボタン"),
        }
        save_config(config)
        print("\nセレクタを保存しました。")
        print(json.dumps(config, indent=2, ensure_ascii=False))
    finally:
        close_context(context)


def run_command(settings: dict, dry_run: bool) -> None:
    config = load_config()
    context = launch_context(settings["headless"])
    try:
        page = get_active_page(context, settings["target_url"] or config.get("page_url", ""))
        page.bring_to_front()
        prompt_enter("ログイン済み状態を確認し、返信対象の画面を開いてください。")

        message_locator = page.locator(config["message"]["selector"]).first
        reply_box = page.locator(config["reply_box"]["selector"]).first
        send_button = page.locator(config["send_button"]["selector"]).first

        message_locator.wait_for(state="visible", timeout=15000)
        reply_box.wait_for(state="visible", timeout=15000)
        send_button.wait_for(state="visible", timeout=15000)

        message_text = message_locator.inner_text().strip()
        if not message_text:
            raise SystemExit("メッセージ本文が空でした。セレクタを見直してください。")

        print("\n取得したメッセージ:")
        print(message_text)

        reply_text = generate_reply(settings, message_text)
        print("\n生成した返信:")
        print(reply_text)

        reply_box.click()
        reply_box.fill(reply_text)

        if dry_run:
            print("\n--dry-run のため送信せず終了します。")
            return

        send_button.click()
        print("\n送信しました。")
    finally:
        close_context(context)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Reply MVP")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("setup", help="セレクタを登録する")

    run_parser = subparsers.add_parser("run", help="返信を生成して送信する")
    run_parser.add_argument("--dry-run", action="store_true", help="送信しない")

    return parser


def main() -> None:
    settings = load_settings()
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "setup":
            setup_command(settings)
        elif args.command == "run":
            run_command(settings, dry_run=args.dry_run)
    except KeyboardInterrupt:
        print("\n中断しました。")
        sys.exit(1)


if __name__ == "__main__":
    main()
