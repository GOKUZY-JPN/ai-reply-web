const openaiApiKeyEl = document.querySelector("#openaiApiKey");
const modelEl = document.querySelector("#model");
const temperatureEl = document.querySelector("#temperature");
const systemPromptEl = document.querySelector("#systemPrompt");
const referenceGuideEl = document.querySelector("#referenceGuide");
const profileAppNameEl = document.querySelector("#profileAppName");
const profileCountryEl = document.querySelector("#profileCountry");
const profilePartnerNameEl = document.querySelector("#profilePartnerName");
const profileSequenceEl = document.querySelector("#profileSequence");
const conversationDatabaseEl = document.querySelector("#conversationDatabase");
const statusEl = document.querySelector("#status");

const DEFAULT_REFERENCE_GUIDE = `【前提条件：進化心理学に基づく誠実な魅力向上とコミュニケーションのガイドライン】

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
返信は短めで自然、誠実、知的、安心感があるものにする。相手の話にちゃんと反応し、必要なら軽い共感や自然な質問を1つ入れる。馴れ馴れしすぎず、下心や支配性を感じさせない。`;

document.querySelector("#save").addEventListener("click", async () => {
  const payload = {
    openaiApiKey: openaiApiKeyEl.value.trim(),
    model: modelEl.value.trim() || "gpt-5-mini",
    temperature: Number(temperatureEl.value || "0.7"),
    systemPrompt:
      systemPromptEl.value.trim() ||
      "You are a concise, friendly assistant. Reply in the same language as the incoming message.",
    referenceGuide: referenceGuideEl.value.trim() || DEFAULT_REFERENCE_GUIDE,
    profileAppName: profileAppNameEl.value.trim() || "Tandem",
    profileCountry: profileCountryEl.value.trim(),
    profilePartnerName: profilePartnerNameEl.value.trim(),
    profileSequence: profileSequenceEl.value.trim() || "1",
    conversationDatabases: buildUpdatedDatabases()
  };

  const response = await chrome.runtime.sendMessage({
    type: "save-settings",
    payload
  });

  statusEl.textContent = response?.ok ? "保存しました" : response?.error || "保存に失敗しました";
});

loadSettings();

async function loadSettings() {
  const response = await chrome.runtime.sendMessage({ type: "load-settings" });
  if (!response?.ok) {
    statusEl.textContent = response?.error || "設定を読み込めませんでした";
    return;
  }

  const settings = response.settings || {};
  window.__currentSettings = settings;
  openaiApiKeyEl.value = settings.openaiApiKey || "";
  modelEl.value = settings.model || "gpt-5-mini";
  temperatureEl.value = String(settings.temperature ?? 0.7);
  systemPromptEl.value =
    settings.systemPrompt ||
    "You are a concise, friendly assistant. Reply in the same language as the incoming message.";
  referenceGuideEl.value = settings.referenceGuide || DEFAULT_REFERENCE_GUIDE;
  profileAppNameEl.value = settings.profileAppName || "Tandem";
  profileCountryEl.value = settings.profileCountry || "";
  profilePartnerNameEl.value = settings.profilePartnerName || "";
  profileSequenceEl.value = settings.profileSequence || "1";
  conversationDatabaseEl.value = getCurrentDatabase(settings);
}

function buildUpdatedDatabases() {
  const existing = window.__currentSettings?.conversationDatabases || {};
  const key = buildProfileKey({
    profileAppName: profileAppNameEl.value.trim() || "Tandem",
    profileCountry: profileCountryEl.value.trim(),
    profilePartnerName: profilePartnerNameEl.value.trim(),
    profileSequence: profileSequenceEl.value.trim() || "1"
  });
  return {
    ...existing,
    [key]: conversationDatabaseEl.value.trim()
  };
}

function getCurrentDatabase(settings) {
  const key = buildProfileKey(settings);
  return settings.conversationDatabases?.[key] || "";
}

function buildProfileKey(settings) {
  const appName = sanitizePart(settings.profileAppName || "Tandem");
  const country = sanitizePart(settings.profileCountry || "unknown-country");
  const partnerName = sanitizePart(settings.profilePartnerName || "unknown-partner");
  const sequence = sanitizePart(settings.profileSequence || "1");
  return `${appName}__${country}__${partnerName}__${sequence}`;
}

function sanitizePart(value) {
  return String(value || "")
    .trim()
    .replace(/\s+/g, "-")
    .replace(/[^\p{L}\p{N}_-]/gu, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "") || "unknown";
}
