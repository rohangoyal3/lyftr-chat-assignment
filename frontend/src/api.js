export const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '');

export async function checkHealth(signal) {
  const response = await fetch(`${apiBase}/health`, { signal });
  if (!response.ok) throw new Error('The chat API is unavailable.');
  return response.json();
}

export async function sendChat(sessionId, message, systemPrompt) {
  let response;
  try {
    response = await fetch(`${apiBase}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, message, system_prompt: systemPrompt }),
    });
  } catch {
    throw new Error('Couldn’t reach the chat server. Check your connection and try again.');
  }

  if (response.status === 503) {
    throw new Error('All model providers are temporarily unavailable. Try again in a moment.');
  }
  if (response.status === 422) {
    throw new Error('Your message couldn’t be accepted. Enter 1 to 4,000 characters and try again.');
  }
  if (!response.ok) throw new Error('The chat server couldn’t respond. Please try again.');
  return response.json();
}
