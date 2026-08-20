// Worker 侧 DeepSeek 客户端：解释划线句子（fetch 直调 api.deepseek.com）。
export async function explainText(text: string, key: string): Promise<string> {
  const res = await fetch("https://api.deepseek.com/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer " + key,
    },
    body: JSON.stringify({
      model: "deepseek-chat",
      messages: [
        {
          role: "system",
          content:
            "你是申论/时政辅导老师。用简洁的中文解释用户划线的句子：先说字面含义，再说它的考点或政策背景。100 字左右。",
        },
        { role: "user", content: text },
      ],
      temperature: 0.3,
      max_tokens: 600,
    }),
  });
  if (!res.ok) throw new Error("deepseek api error: " + res.status);
  const data = (await res.json()) as { choices: { message: { content: string } }[] };
  return data.choices[0]?.message.content.trim() ?? "";
}

async function chatOnce(
  system: string,
  user: string,
  key: string,
  temperature: number,
  maxTokens: number,
): Promise<string> {
  const res = await fetch("https://api.deepseek.com/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer " + key,
    },
    body: JSON.stringify({
      model: "deepseek-chat",
      messages: [
        { role: "system", content: system },
        { role: "user", content: user },
      ],
      temperature,
      max_tokens: maxTokens,
    }),
  });
  if (!res.ok) throw new Error("deepseek api error: " + res.status);
  const data = (await res.json()) as { choices: { message: { content: string } }[] };
  return data.choices[0]?.message.content.trim() ?? "";
}

/** 为政策术语生成 3 个紧扣考点的建议追问问题；解析失败返回空数组（前端回退通用模板）。 */
export async function suggestTermQuestions(term: string, explanation: string, key: string): Promise<string[]> {
  const raw = await chatOnce(
    '你是公务员考试申论辅导老师。针对政策术语给出 3 个紧扣考点、适合追问的问题，覆盖「是什么 / 为什么 / 怎么做」角度。只返回 JSON：{"suggestions":["问题1","问题2","问题3"]}，每个问题 15-40 字。',
    `术语：${term}${explanation ? `\n释义：${explanation}` : ""}`,
    key,
    0.4,
    400,
  );
  try {
    const text = raw.replace(/^```(?:json)?\s*|\s*```$/g, "").trim();
    const parsed = JSON.parse(text) as { suggestions?: unknown };
    const list = Array.isArray(parsed.suggestions)
      ? parsed.suggestions.filter((s): s is string => typeof s === "string" && s.trim().length > 0).slice(0, 3)
      : [];
    return list;
  } catch {
    return [];
  }
}

/** 回答用户对政策术语的追问（Markdown 输出）。 */
export async function answerTermQuestion(term: string, explanation: string, question: string, key: string): Promise<string> {
  return chatOnce(
    "你是公务员考试申论辅导老师。用 Markdown 回答关于政策术语的追问，紧扣考点（是什么/为什么/怎么办），100-200 字，可用小标题或列表。",
    `术语：${term}${explanation ? `\n释义：${explanation}` : ""}\n追问：${question}`,
    key,
    0.4,
    800,
  );
}
