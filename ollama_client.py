"""
Ollama client module for AI model communication
"""
import requests
import json
import logging

logger = logging.getLogger(__name__)

class OllamaClient:
    def __init__(self, base_url="http://localhost:11434", model="llama2"):
        self.base_url = base_url.rstrip('/')
        self.model = model

    def is_available(self):
        """Check if Ollama service is available"""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except requests.RequestException as e:
            logger.error(f"Ollama service not available: {e}")
            return False

    SYSTEM_PROMPT = """You are Gemma, a friendly IRC chatbot. You are a knowledgeable assistant that provides information, answers questions, and holds conversations.

STRICT RULES:
- NEVER write, suggest, or generate shell commands, bash commands, or any executable code
- NEVER generate code, scripts, or programming instructions of any kind
- If asked for commands or code, politely decline and offer a conceptual explanation instead
- Keep responses conversational and helpful
- Be concise — aim for 2-4 sentences when possible"""

    @staticmethod
    def _strip_thought_prefix(text):
        """Remove model-internal thought markers like <|channel>thought<channel|>"""
        import re
        # Remove patterns like <|channel>thought\n<channel|> or similar variations
        cleaned = re.sub(r'<\|?\w+>\s*\w*\s*<\w+\|?>\s*', '', text, count=1)
        # Also remove any remaining standalone tags
        cleaned = re.sub(r'<\|?\w+\|?>', '', cleaned)
        return cleaned.strip()

    def generate_full_response(self, prompt, max_tokens=800):
        """Generate full response from Ollama model without truncation"""
        if not self.is_available():
            return "Sorry, the AI service is currently unavailable."

        try:
            payload = {
                "model": self.model,
                "prompt": f"{self.SYSTEM_PROMPT}\n\nUser: {prompt}\n\nGemma:",
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": 0.7
                }
            }

            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=60
            )

            if response.status_code == 200:
                result = response.json()
                raw = result.get("response", "Sorry, I couldn't generate a response.")
                return self._strip_thought_prefix(raw)
            else:
                logger.error(f"Ollama API error: {response.status_code}")
                return "Sorry, there was an error processing your request."

        except requests.RequestException as e:
            logger.error(f"Error calling Ollama API: {e}")
            return "Sorry, I couldn't connect to the AI service."
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing Ollama response: {e}")
            return "Sorry, there was an error processing the AI response."

    def generate_response(self, prompt, max_tokens=500):
        """Generate response from Ollama model"""
        if not self.is_available():
            return "Sorry, the AI service is currently unavailable."

        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": 0.7
                }
            }

            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                raw_response = result.get("response", "Sorry, I couldn't generate a response.")
                # Clean up the response for IRC compatibility
                clean_response = raw_response.replace('\r\n', ' ').replace('\r', ' ').replace('\n', ' ')
                # Remove extra spaces
                clean_response = ' '.join(clean_response.split())
                # Truncate if too long for IRC (max ~400 chars to be safe)
                if len(clean_response) > 400:
                    clean_response = clean_response[:397] + "..."
                return clean_response
            else:
                logger.error(f"Ollama API error: {response.status_code}")
                return "Sorry, there was an error processing your request."

        except requests.RequestException as e:
            logger.error(f"Error calling Ollama API: {e}")
            return "Sorry, I couldn't connect to the AI service."
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing Ollama response: {e}")
            return "Sorry, there was an error processing the AI response."

    def list_models(self):
        """List available models"""
        if not self.is_available():
            return []

        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=10)
            if response.status_code == 200:
                data = response.json()
                return [model['name'] for model in data.get('models', [])]
            return []
        except requests.RequestException:
            return []

    def generate_full_response_with_context(self, prompt, calling_user, chat_context, max_tokens=800):
        """Generate response with chat history context"""
        if not self.is_available():
            return "Sorry, the AI service is currently unavailable."

        # Build prompt with context
        if chat_context:
            full_prompt = (
                f"{self.SYSTEM_PROMPT}\n\n"
                f"Recent channel history:\n{chat_context}\n\n"
                f"Current message from {calling_user}: {prompt}\n\n"
                f"Gemma (respond naturally as if in an ongoing conversation):"
            )
        else:
            full_prompt = f"{self.SYSTEM_PROMPT}\n\nUser: {prompt}\n\nGemma:"

        try:
            payload = {
                "model": self.model,
                "prompt": full_prompt,
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": 0.7
                }
            }

            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=60
            )

            if response.status_code == 200:
                result = response.json()
                raw = result.get("response", "Sorry, I couldn't generate a response.")
                return self._strip_thought_prefix(raw)
            else:
                logger.error(f"Ollama API error: {response.status_code}")
                return "Sorry, there was an error processing your request."

        except requests.RequestException as e:
            logger.error(f"Error calling Ollama API: {e}")
            return "Sorry, I couldn't connect to the AI service."
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing Ollama response: {e}")
            return "Sorry, there was an error processing the AI response."

    def get_available_models(self):
        """Alias for list_models() - returns list of available models"""
        return self.list_models()