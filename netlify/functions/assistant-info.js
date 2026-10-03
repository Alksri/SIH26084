/**
 * BUMBLEBLE — /api/assistant/info
 * Returns provider info so the status pill in assistant.html shows correctly.
 */

export default async function handler(req) {
  const hasKey = !!process.env.GEMINI_API_KEY;
  const model  = process.env.GEMINI_MODEL || "gemini-2.5-flash";

  const info = hasKey
    ? { provider: "gemini", model, mode: "serverless", knowledge_docs: 0, embeddings: false }
    : { provider: "demo",   model: null, mode: "demo", knowledge_docs: 0, embeddings: false };

  return new Response(JSON.stringify(info), {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
    },
  });
}
