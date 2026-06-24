"""Chatterbox Turbo client module — drop-in replacement for OllamaClient."""
import requests
import logging

logger = logging.getLogger(__name__)

class ChatterboxClient:
    def __init__(self, base_url="http://127.0.0.1:17493", model="qwen3-0.6b"):
        self.base_url = base_url.rstrip('/')
        self.model = model  # "0.6B", "1.7B", or "4B"

    def is_available(self):
        try:
            response = requests.get(f"{self.base_url}/health", timeout=5)
            return response.status_code == 200
        except requests.RequestException as e:
            logger.error(f"Chatterbox service not available: {e}")
            return False

    SYSTEM_PROMPT = """You are Gemma, a friendly IRC chatbot. You are a knowledgeable assistant that provides information, answers questions, and holds conversations. STRICT RULES: - NEVER write, suggest, or generate shell commands, bash commands, or any executable code - NEVER generate code, scripts, or programming instructions of any kind - If asked for commands or code, politely decline and offer a conceptual explanation instead - Keep responses conversational and helpful - Be concise — aim for 2-4 sentences when possible"""

    def generate_full_response(self, prompt, max_tokens=800):
        if not self.is_available():
            return "Sorry, the AI service is currently unavailable."
        try:
            payload = {
                "prompt": prompt,
                "system": self.SYSTEM_PROMPT,
                "max_tokens": min(max_tokens, 4096),
                "temperature": 0.7,
            }
            response = requests.post(
                f"{self.base_url}/llm/generate",
                json=payload,
                timeout=60
            )
            if response.status_code == 200:
                result = response.json()
                return result.get("text", "Sorry, I couldn't generate a response.")
            else:
                logger.error(f"Chatterbox API error: {response.status_code}")
                return "Sorry, there was an error processing your request."
        except requests.RequestException as e:
            logger.error(f"Error calling Chatterbox API: {e}")
            return "Sorry, I couldn't connect to the AI service."

    def generate_response(self, prompt, max_tokens=500):
        text = self.generate_full_response(prompt, max_tokens)
        # Clean up for IRC
        clean = text.replace('\r\n', ' ').replace('\r', ' ').replace('\n', ' ')
        clean = ' '.join(clean.split())
        if len(clean) > 400:
            clean = clean[:397] + "..."
        return clean

    def list_models(self):
        return ["qwen3-0.6b", "qwen3-1.7b", "qwen3-4b"]

    def generate_full_response_with_context(self, prompt, calling_user, chat_context, max_tokens=800):
        if not self.is_available():
            return "Sorry, the AI service is currently unavailable."
        if chat_context:
            full_prompt = (
                f"Recent channel history:\n{chat_context}\n\n"
                f"Current message from {calling_user}: {prompt}\n\n"
                f"Respond naturally as if in an ongoing conversation."
            )
        else:
            full_prompt = prompt
        return self.generate_full_response(full_prompt, max_tokens)

    def get_available_models(self):
        return self.list_models()
