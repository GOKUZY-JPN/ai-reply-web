const DEFAULT_SETTINGS = {
  model: "gpt-5-mini",
  systemPrompt:
    "You are a concise, friendly assistant. Reply in the same language as the incoming message.",
  referenceGuide: `【前提条件：進化心理学に基づく誠実な魅力向上とコミュニケーションのガイドライン】

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
返信は短めで自然、誠実、知的、安心感があるものにする。相手の話にちゃんと反応し、必要なら軽い共感や自然な質問を1つ入れる。馴れ馴れしすぎず、下心や支配性を感じさせない。`,
  profileAppName: "Tandem",
  profileCountry: "",
  profilePartnerName: "",
  profileSequence: "1",
  conversationDatabases: {},
  temperature: 0.7
};

chrome.runtime.onInstalled.addListener(async () => {
  const current = await chrome.storage.sync.get([
    "openaiApiKey",
    "model",
    "systemPrompt",
    "referenceGuide",
    "profileAppName",
    "profileCountry",
    "profilePartnerName",
    "profileSequence",
    "conversationDatabases",
    "temperature"
  ]);

  await chrome.storage.sync.set({
    model: current.model || DEFAULT_SETTINGS.model,
    systemPrompt: current.systemPrompt || DEFAULT_SETTINGS.systemPrompt,
    referenceGuide: current.referenceGuide || DEFAULT_SETTINGS.referenceGuide,
    profileAppName: current.profileAppName || DEFAULT_SETTINGS.profileAppName,
    profileCountry: current.profileCountry || DEFAULT_SETTINGS.profileCountry,
    profilePartnerName:
      current.profilePartnerName || DEFAULT_SETTINGS.profilePartnerName,
    profileSequence: current.profileSequence || DEFAULT_SETTINGS.profileSequence,
    conversationDatabases:
      current.conversationDatabases || DEFAULT_SETTINGS.conversationDatabases,
    temperature:
      typeof current.temperature === "number"
        ? current.temperature
        : DEFAULT_SETTINGS.temperature
  });
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "generate-reply") {
    handleGenerateReply(message.payload)
      .then((reply) => sendResponse({ ok: true, reply }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message?.type === "load-settings") {
    chrome.storage.sync
      .get([
        "openaiApiKey",
        "model",
        "systemPrompt",
        "referenceGuide",
        "profileAppName",
        "profileCountry",
        "profilePartnerName",
        "profileSequence",
        "conversationDatabases",
        "temperature"
      ])
      .then((settings) => sendResponse({ ok: true, settings }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message?.type === "save-settings") {
    chrome.storage.sync
      .set(message.payload)
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }
});

async function handleGenerateReply(payload) {
  const settings = await chrome.storage.sync.get([
    "openaiApiKey",
    "model",
    "systemPrompt",
    "referenceGuide",
    "profileAppName",
    "profileCountry",
    "profilePartnerName",
    "profileSequence",
    "conversationDatabases",
    "temperature"
  ]);

  if (!settings.openaiApiKey) {
    throw new Error("OpenAI API key が未設定です。拡張機能の設定画面で保存してください。");
  }

  if (!payload?.messageText?.trim()) {
    throw new Error("選択されたメッセージが空です。");
  }

  const profileKey = buildProfileKey(settings);
  const currentDatabase = getConversationDatabase(settings, profileKey);

  const requestBody = {
    model: settings.model || DEFAULT_SETTINGS.model,
    input: [
      {
        role: "system",
        content: [
          {
            type: "input_text",
            text:
              (settings.systemPrompt || DEFAULT_SETTINGS.systemPrompt) +
              "\n\n" +
              (settings.referenceGuide || DEFAULT_SETTINGS.referenceGuide)
          }
        ]
      },
      {
        role: "user",
        content: [
          {
            type: "input_text",
            text:
              buildUserPrompt(currentDatabase, payload.messageText, profileKey)
          }
        ]
      }
    ]
  };

  if (supportsTemperature(requestBody.model)) {
    requestBody.temperature =
      typeof settings.temperature === "number"
        ? settings.temperature
        : DEFAULT_SETTINGS.temperature;
  }

  const response = await fetch("https://api.openai.com/v1/responses", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${settings.openaiApiKey}`
    },
    body: JSON.stringify(requestBody)
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`OpenAI API error: ${errorText}`);
  }

  const data = await response.json();
  const reply = extractReplyPayload(data);
  if (!reply?.reply) {
    throw new Error("返信文を取得できませんでした。");
  }

  const updatedDatabase = appendConversationTurn(
    currentDatabase,
    payload.messageText,
    reply.reply
  );

  const updatedDatabases = {
    ...(settings.conversationDatabases || {}),
    [profileKey]: updatedDatabase
  };

  await chrome.storage.sync.set({
    conversationDatabases: updatedDatabases
  });

  return {
    reply: reply.reply.trim(),
    japaneseTranslation: (reply.japaneseTranslation || "").trim(),
    databasePreview: buildDatabasePreview(updatedDatabase),
    profileKey
  };
}

function buildUserPrompt(conversationDatabase, messageText, profileKey) {
  const historyBlock = conversationDatabase?.trim()
    ? `以下は ${profileKey} との過去会話のデータベースです。これを参照して、同じことを何度も聞かず、話題の連続性を保ってください。\n\n${trimForPrompt(conversationDatabase, 12000)}\n\n`
    : "";

  return (
    historyBlock +
    "以下の新しい相手メッセージに対する自然で短めの返信文を作成してください。" +
              "必ずJSONで返し、keysは reply と japanese_translation の2つだけにしてください。" +
              "reply には相手に実際に送る文、japanese_translation にはその reply の自然な日本語訳を入れてください。" +
    "コードブロックは使わないでください。過去会話にすでに答えがあることを再度質問しないでください。必要なら前回の話題を自然に参照してください。\n\n" +
    `受信メッセージ:\n${messageText}`
  );
}

function buildProfileKey(settings) {
  const appName = sanitizeProfilePart(settings.profileAppName || DEFAULT_SETTINGS.profileAppName);
  const country = sanitizeProfilePart(settings.profileCountry || "unknown-country");
  const partnerName = sanitizeProfilePart(settings.profilePartnerName || "unknown-partner");
  const sequence = sanitizeProfilePart(settings.profileSequence || "1");
  return `${appName}__${country}__${partnerName}__${sequence}`;
}

function sanitizeProfilePart(value) {
  return String(value || "")
    .trim()
    .replace(/\s+/g, "-")
    .replace(/[^\p{L}\p{N}_-]/gu, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "") || "unknown";
}

function getConversationDatabase(settings, profileKey) {
  const databases = settings.conversationDatabases || {};
  return String(databases[profileKey] || "");
}

function appendConversationTurn(existingDatabase, incomingMessage, replyText) {
  let database = String(existingDatabase || "").trim();
  database = appendBlockIfNew(database, "Partner", incomingMessage);
  database = appendBlockIfNew(database, "You", replyText);
  return database.trim();
}

function appendBlockIfNew(database, speaker, text) {
  const normalizedText = normalizeBlock(text);
  if (!normalizedText) return database;

  const block = `[${speaker}]\n${normalizedText}`;
  const normalizedDatabase = String(database || "").trim();
  if (!normalizedDatabase) return block;

  const pieces = normalizedDatabase.split(/\n{2,}/);
  const lastPiece = pieces[pieces.length - 1]?.trim() || "";
  if (lastPiece === block) {
    return normalizedDatabase;
  }

  return `${normalizedDatabase}\n\n${block}`;
}

function normalizeBlock(text) {
  return String(text || "")
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .join("\n")
    .trim();
}

function trimForPrompt(text, maxChars) {
  const normalized = String(text || "").trim();
  if (normalized.length <= maxChars) return normalized;
  return normalized.slice(normalized.length - maxChars);
}

function buildDatabasePreview(text) {
  const trimmed = trimForPrompt(text, 1200);
  return trimmed;
}

function supportsTemperature(model) {
  const normalized = String(model || "").toLowerCase();
  return !normalized.startsWith("gpt-5");
}

function extractOutputText(data) {
  if (typeof data?.output_text === "string" && data.output_text.trim()) {
    return data.output_text;
  }

  if (Array.isArray(data?.output)) {
    const texts = [];
    for (const item of data.output) {
      if (!Array.isArray(item?.content)) continue;
      for (const content of item.content) {
        if (typeof content?.text === "string") {
          texts.push(content.text);
        }
      }
    }
    return texts.join("\n").trim();
  }

  return "";
}

function extractReplyPayload(data) {
  const raw = extractOutputText(data);
  if (!raw) return null;

  try {
    const parsed = JSON.parse(raw);
    return {
      reply: typeof parsed.reply === "string" ? parsed.reply : "",
      japaneseTranslation:
        typeof parsed.japanese_translation === "string"
          ? parsed.japanese_translation
          : typeof parsed.japaneseTranslation === "string"
            ? parsed.japaneseTranslation
            : ""
    };
  } catch (_error) {
    return {
      reply: raw,
      japaneseTranslation: ""
    };
  }
}
