const state = {
  rememberedInput: null
};

document.addEventListener(
  "focusin",
  (event) => {
    const target = event.target;
    if (isEditable(target)) {
      state.rememberedInput = buildElementPath(target);
      showToast("返信欄を記憶しました");
    }
  },
  true
);

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "remember-active-input") {
    const active = document.activeElement;
    if (!isEditable(active)) {
      sendResponse({
        ok: false,
        error: "先に返信欄をクリックしてカーソルを置いてください。"
      });
      return;
    }

    state.rememberedInput = buildElementPath(active);
    showToast("返信欄を記憶しました");
    sendResponse({ ok: true });
    return;
  }

  if (message?.type === "get-selected-text") {
    const text = window.getSelection()?.toString().trim() || "";
    sendResponse({ ok: true, text });
    return;
  }

  if (message?.type === "insert-generated-reply") {
    const target = resolveRememberedInput();
    if (!target) {
      sendResponse({
        ok: false,
        error: "記憶した入力欄が見つかりません。もう一度返信欄をクリックしてください。"
      });
      return;
    }

    insertText(target, message.payload?.replyText || "");
    showToast("返信文を入力しました");
    sendResponse({ ok: true });
  }
});

function isEditable(node) {
  if (!(node instanceof HTMLElement)) return false;
  if (node.isContentEditable) return true;
  const tag = node.tagName?.toLowerCase();
  return tag === "textarea" || (tag === "input" && node.type === "text");
}

function buildElementPath(element) {
  if (!(element instanceof Element)) return null;

  if (element.id) {
    return { selector: `#${cssEscape(element.id)}` };
  }

  const parts = [];
  let current = element;
  while (current && current !== document.body) {
    let part = current.tagName.toLowerCase();
    const siblings = current.parentElement
      ? Array.from(current.parentElement.children).filter(
          (child) => child.tagName === current.tagName
        )
      : [];
    if (siblings.length > 1) {
      part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
    }
    parts.unshift(part);
    current = current.parentElement;
  }
  return { selector: parts.join(" > ") };
}

function resolveRememberedInput() {
  if (!state.rememberedInput?.selector) return null;
  const element = document.querySelector(state.rememberedInput.selector);
  return isEditable(element) ? element : null;
}

function insertText(target, text) {
  target.focus();

  if (target instanceof HTMLTextAreaElement || target instanceof HTMLInputElement) {
    target.value = text;
    target.dispatchEvent(new Event("input", { bubbles: true }));
    target.dispatchEvent(new Event("change", { bubbles: true }));
    return;
  }

  if (target instanceof HTMLElement && target.isContentEditable) {
    target.textContent = text;
    target.dispatchEvent(new InputEvent("input", { bubbles: true, data: text }));
  }
}

function showToast(message) {
  const existing = document.querySelector("[data-ai-reply-toast]");
  if (existing) existing.remove();

  const toast = document.createElement("div");
  toast.setAttribute("data-ai-reply-toast", "true");
  toast.textContent = message;
  toast.style.position = "fixed";
  toast.style.right = "20px";
  toast.style.bottom = "20px";
  toast.style.zIndex = "2147483647";
  toast.style.background = "rgba(17, 24, 39, 0.95)";
  toast.style.color = "#fff";
  toast.style.padding = "10px 14px";
  toast.style.borderRadius = "999px";
  toast.style.fontSize = "13px";
  toast.style.fontFamily = "system-ui, sans-serif";
  toast.style.boxShadow = "0 10px 30px rgba(0, 0, 0, 0.25)";
  document.documentElement.appendChild(toast);

  window.setTimeout(() => toast.remove(), 1800);
}

function cssEscape(value) {
  if (window.CSS?.escape) return window.CSS.escape(value);
  return value.replace(/([^a-zA-Z0-9_-])/g, "\\$1");
}
