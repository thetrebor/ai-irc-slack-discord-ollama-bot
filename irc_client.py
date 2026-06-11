"""
IRC client implementation for the AI bot
"""
import ssl
import irc.bot
import irc.connection
import irc.strings
import threading
import logging
import time
import random
from ollama_client import OllamaClient


class NoReconnect:
    """Reconnect strategy that does nothing — prevents SingleServerIRCBot from auto-reconnecting"""
    def run(self, bot):
        pass

logger = logging.getLogger(__name__)

class IRCBot(irc.bot.SingleServerIRCBot):
    def __init__(self, config):
        self.config = config
        irc_config = config['irc']

        # Initialize IRC connection
        self.server = irc_config['server']
        self.port = irc_config['port']
        self.nickname = irc_config['nickname']

        # Use SSL if port is 6697
        use_ssl = irc_config.get('use_ssl', self.port == 6697)
        if use_ssl:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            connect_factory = irc.connection.Factory(wrapper=ssl_context.wrap_socket)
        else:
            connect_factory = irc.connection.Factory()

        # SASL authentication
        nickserv_password = irc_config.get('nickserv_password', '')
        sasl_username = irc_config.get('sasl_username', '')
        sasl_password = irc_config.get('sasl_password', '')
        if sasl_username and sasl_password:
            # Pass SASL credentials via extra args
            super().__init__([(self.server, self.port)], self.nickname, self.nickname,
                connect_factory=connect_factory,
                sasl_username=sasl_username,
                sasl_password=sasl_password,
                recon=NoReconnect())
            logger.info(f"Configured SASL authentication for {sasl_username}")
        else:
            super().__init__([(self.server, self.port)], self.nickname, self.nickname, connect_factory=connect_factory,
                recon=NoReconnect())

        self.channel_list = irc_config['channels']
        self.bot_name = config['bot_name']
        self.ollama_client = OllamaClient(
            base_url=config['ollama']['base_url'],
            model=config['ollama']['model']
        )

        # Store full responses for continuation
        self.stored_responses = {}  # key: "user@channel", value: {"full_text": str, "position": int}

        # Reconnection settings
        self.reconnect_enabled = True
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.base_reconnect_delay = 5  # Base delay in seconds
        self.max_reconnect_delay = 300  # Max delay in seconds (5 minutes)
        self.is_connected = False
        self.should_stop = False

        logger.info(f"IRC Bot initialized for {self.server}:{self.port} as {self.nickname}")

    _nick_retries = 0

    def on_nicknameinuse(self, connection, event):
        """Handle nick in use: fallback with rate limit"""
        self._nick_retries += 1
        desired = self.nickname
        current = connection.get_nickname()
        logger.info(f"on_nicknameinuse: desired={desired}, current={current}, args={event.arguments}, retry=#{self._nick_retries}")
        if self._nick_retries > 5:
            logger.error("Nick retry limit reached, using whatever nick we have")
            return
        # Always generate a fresh fallback with random suffix
        fallback = f"{desired}{random.randint(10, 999)}"
        connection.nick(fallback)
        # Identify so we can speak
        nickserv_password = self.config['irc'].get('nickserv_password', '')
        if nickserv_password:
            connection.privmsg('NickServ', f'IDENTIFY {nickserv_password}')

    def on_welcome(self, connection, event):
        """Called when bot successfully connects to IRC server"""
        logger.info("Connected to IRC server")
        self.is_connected = True
        # Identify with NickServ for registered accounts
        nickserv_password = self.config['irc'].get('nickserv_password', '')
        if nickserv_password:
            connection.privmsg('NickServ', f'IDENTIFY {nickserv_password}')
        for channel in self.channel_list:
            connection.join(channel)
            logger.info(f"Joined channel: {channel}")

    def on_privmsg(self, connection, event):
        """Handle private messages"""
        sender = event.source.nick
        message = event.arguments[0].strip() if event.arguments else ""

        logger.info(f"Private message from {sender}: {message}")

        # Check for continue command
        if message.lower() in ['continue', 'cont', 'more']:
            self.handle_continue(connection, sender, sender)  # DM context
            return

        # Generate AI response
        full_response = self.ollama_client.generate_full_response(message)
        chunked_response = self.get_first_chunk(full_response, sender, sender)

        # Send response back as private message
        connection.privmsg(sender, chunked_response)
        logger.info(f"Sent private response to {sender}")

    def on_pubmsg(self, connection, event):
        """Handle public channel messages"""
        sender = event.source.nick
        channel = event.target
        message = event.arguments[0].strip() if event.arguments else ""

        # Check for simple continue command (no mention)
        if message.lower() in ['continue', 'cont', 'more']:
            self.handle_continue(connection, sender, channel)
            return

        # Check if bot is mentioned
        if self.is_mentioned(message):
            # Remove bot name from message
            clean_message = self.clean_message(message)

            # Check if the cleaned message is a continue command
            if clean_message.lower().strip() in ['continue', 'cont', 'more']:
                logger.info(f"Continue command from {sender} in {channel}")
                self.handle_continue(connection, sender, channel)
                return

            logger.info(f"Mentioned in {channel} by {sender}: {clean_message}")

            # Generate AI response
            full_response = self.ollama_client.generate_full_response(clean_message)
            chunked_response = self.get_first_chunk(full_response, sender, channel)

            # Send response to channel
            connection.privmsg(channel, f"{sender}: {chunked_response}")
            logger.info(f"Sent public response in {channel}")

    def is_mentioned(self, message):
        """Check if the bot is mentioned in the message"""
        message_lower = message.lower()
        bot_name_lower = self.bot_name.lower()

        # Check for various mention patterns
        mentions = [
            f"{bot_name_lower}:",
            f"{bot_name_lower},",
            f"{bot_name_lower} ",
            f"@{bot_name_lower}",
            bot_name_lower
        ]

        return any(mention in message_lower for mention in mentions)

    def clean_message(self, message):
        """Remove bot name and clean up the message"""
        message_lower = message.lower()
        bot_name_lower = self.bot_name.lower()

        # Remove common mention patterns
        patterns_to_remove = [
            f"{bot_name_lower}:",
            f"{bot_name_lower},",
            f"@{bot_name_lower}",
            bot_name_lower
        ]

        clean_msg = message
        for pattern in patterns_to_remove:
            clean_msg = clean_msg.replace(pattern, "", 1)
            clean_msg = clean_msg.replace(pattern.title(), "", 1)
            clean_msg = clean_msg.replace(pattern.upper(), "", 1)

        return clean_msg.strip()

    MAX_IRC_MSG_LEN = 400  # Safe limit for PRIVMSG content (accounting for protocol overhead)

    def get_first_chunk(self, full_text, user, context):
        """Get the first chunk of text and store the rest for continuation"""
        prefix = f"{user}: " if context != user else ""
        prefix_len = len(prefix)
        max_len = self.MAX_IRC_MSG_LEN - prefix_len

        key = f"{user}@{context}"

        # Clean the text for IRC
        clean_text = full_text.replace('\r\n', ' ').replace('\r', ' ').replace('\n', ' ')
        clean_text = ' '.join(clean_text.split())

        # Reserve space for the continuation message
        continuation_msg = " (say 'continue' for more)"
        max_content_length = max_len - len(continuation_msg)

        if len(clean_text) <= max_content_length:
            # Text fits in one message, no need to store
            if key in self.stored_responses:
                del self.stored_responses[key]
            return f"{prefix}{clean_text}".strip()

        # Find a good break point (prefer ending at word boundary)
        chunk_end = max_content_length - 3  # Reserve space for "..."

        # Try to break at a word boundary
        space_pos = clean_text.rfind(' ', 0, chunk_end)
        if space_pos > chunk_end - 50:  # Only use word boundary if it's not too far back
            chunk_end = space_pos

        # Store full text for continuation
        self.stored_responses[key] = {
            "full_text": clean_text,
            "position": chunk_end
        }

        # Return first chunk with continuation indicator
        first_chunk = clean_text[:chunk_end] + "..."
        return f"{prefix}{first_chunk}{continuation_msg}".strip()

    def handle_continue(self, connection, user, context):
        """Handle continue requests"""
        key = f"{user}@{context}"

        if key not in self.stored_responses:
            response = "No previous message to continue."
        else:
            stored = self.stored_responses[key]
            full_text = stored["full_text"]
            start_pos = stored["position"]

            if start_pos >= len(full_text):
                response = "End of message reached."
                del self.stored_responses[key]
            else:
                # Account for sender prefix in channel context
                prefix = f"{user}: " if context != user else ""
                prefix_len = len(prefix)
                max_len = self.MAX_IRC_MSG_LEN - prefix_len
                continuation_msg = " (say 'continue' for more)"
                max_content_length = max_len - len(continuation_msg)

                remaining_text = full_text[start_pos:]

                if len(remaining_text) <= max_content_length:
                    # This is the last chunk
                    response = f"{prefix}{remaining_text}"
                    del self.stored_responses[key]
                else:
                    # More chunks remain - find good break point
                    chunk_end = max_content_length - 3  # Reserve space for "..."

                    # Try to break at word boundary
                    space_pos = remaining_text.rfind(' ', 0, chunk_end)
                    if space_pos > chunk_end - 50:  # Only use word boundary if it's not too far back
                        chunk_end = space_pos

                    chunk = remaining_text[:chunk_end] + "..."
                    self.stored_responses[key]["position"] = start_pos + chunk_end
                    response = f"{prefix}{chunk}{continuation_msg}"

        # Send continuation response
        if context == user:  # DM
            connection.privmsg(user, response)
        else:  # Channel
            connection.privmsg(context, f"{user}: {response}")

        logger.info(f"Sent continuation to {user} in {context}")

    def on_error(self, connection, event):
        """Handle IRC errors"""
        logger.error(f"IRC Error: {event}")

    def on_disconnect(self, connection, event):
        """Handle disconnection"""
        self.is_connected = False
        logger.warning("Disconnected from IRC server")
        # Trigger reconnection in the main thread
        if self.reconnect_enabled and not self.should_stop:
            logger.info("Scheduling reconnection...")
            threading.Thread(target=self._reconnect_loop, daemon=True).start()

    def on_kick(self, connection, event):
        """Handle being kicked from a channel"""
        channel = event.target
        kicker = event.source.nick
        reason = event.arguments[0] if event.arguments else "No reason given"

        logger.warning(f"Kicked from {channel} by {kicker}: {reason}")

        # Wait a bit then try to rejoin
        def rejoin_after_kick():
            time.sleep(30)  # Wait 30 seconds before attempting to rejoin
            if self.is_connected:
                try:
                    connection.join(channel)
                    logger.info(f"Attempted to rejoin {channel} after being kicked")
                except Exception as e:
                    logger.error(f"Failed to rejoin {channel}: {e}")

        threading.Thread(target=rejoin_after_kick, daemon=True).start()

    def stop_bot(self):
        """Gracefully stop the bot"""
        self.should_stop = True
        self.reconnect_enabled = False
        if hasattr(self, 'connection') and self.connection.is_connected():
            self.connection.quit("Bot shutting down")
        logger.info("Bot stop requested")

    def _reconnect_loop(self):
        """Reconnection loop with exponential backoff"""
        attempts = 0
        max_attempts = self.max_reconnect_attempts
        base_delay = self.base_reconnect_delay
        max_delay = self.max_reconnect_delay

        while attempts < max_attempts and self.reconnect_enabled and not self.should_stop:
            attempts += 1
            delay = min(base_delay * (2 ** (attempts - 1)) + random.uniform(0, 5), max_delay)
            logger.info(f"Reconnection attempt {attempts}/{max_attempts} in {delay:.0f}s...")
            time.sleep(delay)

            try:
                logger.info(f"Reconnecting (attempt {attempts})...")
                self.server = self.config['irc']['server']
                self.port = self.config['irc']['port']
                self.start()
                # If we get here, reconnection succeeded
                logger.info(f"Reconnected successfully after attempt {attempts}")
                return
            except Exception as e:
                logger.error(f"Reconnection attempt {attempts} failed: {e}")

        logger.error(f"Failed to reconnect after {max_attempts} attempts")

    def start_bot(self):
        """Start the IRC bot (single attempt, no reconnection loop)"""
        try:
            logger.info("Starting IRC bot...")
            self.start()
        except KeyboardInterrupt:
            logger.info("Bot interrupted by user")
        except Exception as e:
            logger.error(f"Error starting IRC bot: {e}")

def run_irc_bot(config):
    """Function to run the IRC bot in a separate thread"""
    bot = IRCBot(config)
    bot.start_bot()