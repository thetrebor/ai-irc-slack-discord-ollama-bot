"""
IRC message context manager - stores recent channel history for AI context
"""
import time
import json
import logging
import os
from collections import deque

logger = logging.getLogger(__name__)

class ContextManager:
    def __init__(self, max_tokens=4000, max_age_hours=24, storage_path=None):
        self.max_tokens = max_tokens
        self.max_age_seconds = max_age_hours * 3600
        # Store messages as deque of dicts: {timestamp, sender, channel, message}
        self.messages = deque()
        self.storage_path = storage_path

        # Load persisted history if available
        if storage_path and os.path.exists(storage_path):
            self._load()

    def _load(self):
        try:
            with open(self.storage_path, 'r') as f:
                data = json.load(f)
                for msg in data:
                    self.messages.append(msg)
            logger.info(f"Loaded {len(self.messages)} messages from {self.storage_path}")
        except Exception as e:
            logger.warning(f"Could not load message history: {e}")

    def _save(self):
        if not self.storage_path:
            return
        try:
            # Only save last 1000 messages to keep file small
            recent = list(self.messages)[-1000:]
            with open(self.storage_path, 'w') as f:
                json.dump(recent, f)
        except Exception as e:
            logger.warning(f"Could not save message history: {e}")

    def add_message(self, sender, channel, message, is_action=False):
        """Log a message into the context buffer"""
        now = time.time()
        self.messages.append({
            "timestamp": now,
            "sender": sender,
            "channel": channel,
            "message": message,
            "is_action": is_action
        })
        # Trim old messages
        self._trim()

    def add_bot_message(self, channel, message):
        """Log the bot's own response"""
        self.add_message("gemmabot", channel, message)

    def _trim(self):
        """Remove messages older than max_age or exceeding rough token budget"""
        cutoff = time.time() - self.max_age_seconds
        # Remove expired messages
        while self.messages and self.messages[0]["timestamp"] < cutoff:
            self.messages.popleft()

        # Estimate token count (rough: ~4 chars per token)
        total_chars = sum(len(m["message"]) for m in self.messages)
        est_tokens = total_chars / 4

        # Trim oldest if over budget (leave some room for system prompt + current query)
        budget = self.max_tokens * 4  # chars
        while self.messages and total_chars > budget:
            oldest = self.messages.popleft()
            total_chars -= len(oldest["message"])

    def get_context(self, channel=None, max_messages=100):
        """Get recent chat context, optionally filtered to a channel.
        Returns formatted string suitable for inclusion in the AI prompt."""
        self._trim()

        # Filter by channel if specified
        if channel:
            relevant = [m for m in self.messages if m["channel"] == channel]
        else:
            relevant = list(self.messages)

        # Take most recent messages up to limit
        recent = relevant[-max_messages:]

        if not recent:
            return ""

        # Format as IRC-style chat log
        lines = []
        for m in recent:
            sender = m["sender"]
            msg = m["message"]
            if m.get("is_action"):
                lines.append(f"* {sender} {msg}")
            else:
                lines.append(f"<{sender}> {msg}")

        return "\n".join(lines)

    def get_context_for_prompt(self, calling_user, channel, max_context_messages=50):
        """Build a context string for the AI prompt.
        Includes recent channel history and highlights the calling user's messages."""
        context = self.get_context(channel=channel, max_messages=max_context_messages)

        if not context:
            return ""

        # Build a preamble
        result = (
            f"Recent chat history in {channel}:\n"
            f"```\n"
            f"{context}\n"
            f"```"
        )
        return result

    def save(self):
        """Persist history to disk"""
        self._save()
