const statusEl = document.querySelector("#status");
const messageTextEl = document.querySelector("#messageText");
const replyTextEl = document.querySelector("#replyText");
const translationTextEl = document.querySelector("#translationText");
const databasePreviewEl = document.querySelector("#databasePreview");
const profileKeyEl = document.querySelector("#profileKey");

loadSettings();

document.querySelector("#rememberInput").addEventListener("click", async () => {
  setStatus("入力欄を記憶中...");
  const tab = await getCurrentTab();
  const response = await chrome.tabs.sendMessage(tab.id, {
    type: "remember-active-input"
  });
  setStatus(response?.ok ? "入力欄を記憶しました" : response?.error || "失敗しました");
});

document.querySelector("#captureSelection").addEventListener("click", async () => {
  setStatus("選択文を取得中...");
  const tab = await getCurrentTab();
  const response = await chrome.tabs.sendMessage(tab.id, {
    type: "get-selected-text"
  });
  const text = response?.text?.trim() || "";
  messageTextEl.value = text;
  setStatus(text ? "選択文を取得しました" : "選択テキストが見つかりません");
});

document.querySelector("#generateReply").addEventListener("click", async () => {
  setStatus("返信を生成中...");
  const messageText = messageTextEl.value.trim();
  if (!messageText) {
    setStatus("先に選択文を取得するか、手入力してください");
    return;
  }

  const response = await chrome.runtime.sendMessage({
    type: "generate-reply",
    payload: { messageText }
  });

  if (!response?.ok) {
    setStatus(response?.error || "返信生成に失敗しました");
    return;
  }

  replyTextEl.value = response.reply?.reply || "";
  translationTextEl.value = response.reply?.japaneseTranslation || "";
  databasePreviewEl.value = response.reply?.databasePreview || databasePreviewEl.value;
  profileKeyEl.value = response.reply?.profileKey || profileKeyEl.value;
  setStatus("返信を生成しました");
});

document.querySelector("#insertReply").addEventListener("click", async () => {
  setStatus("入力欄へ挿入中...");
  const replyText = replyTextEl.value.trim();
  if (!replyText) {
    setStatus("先に返信を生成してください");
    return;
  }

  const tab = await getCurrentTab();
  const response = await chrome.tabs.sendMessage(tab.id, {
    type: "insert-generated-reply",
    payload: { replyText }
  });
  setStatus(response?.ok ? "入力欄に入れました" : response?.error || "挿入に失敗しました");
});

document.querySelector("#openOptions").addEventListener("click", () => {
  chrome.runtime.openOptionsPage();
});

async function getCurrentTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

function setStatus(text) {
  statusEl.textContent = text;
}

async function loadSettings() {
  const response = await chrome.runtime.sendMessage({ type: "load-settings" });
  if (!response?.ok) {
    setStatus(response?.error || "設定を読み込めませんでした");
    return;
  }

  profileKeyEl.value = buildProfileKey(response.settings || {});
  databasePreviewEl.value = trimPreview(getCurrentDatabase(response.settings || {}));
}

function trimPreview(text) {
  const normalized = String(text || "").trim();
  if (normalized.length <= 1200) return normalized;
  return normalized.slice(normalized.length - 1200);
}

function buildProfileKey(settings) {
  const appName = sanitizePart(settings.profileAppName || "Tandem");
  const country = sanitizePart(settings.profileCountry || "unknown-country");
  const partnerName = sanitizePart(settings.profilePartnerName || "unknown-partner");
  const sequence = sanitizePart(settings.profileSequence || "1");
  return `${appName}__${country}__${partnerName}__${sequence}`;
}

function getCurrentDatabase(settings) {
  const key = buildProfileKey(settings);
  return settings?.conversationDatabases?.[key] || "";
}

function sanitizePart(value) {
  return String(value || "")
    .trim()
    .replace(/\s+/g, "-")
    .replace(/[^\p{L}\p{N}_-]/gu, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "") || "unknown";
}
