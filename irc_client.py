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
import os
from ollama_client import OllamaClient
from context_manager import ContextManager


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

        # Message history for AI context (last 24h, up to 4000 tokens)
        self.context = ContextManager(
            max_tokens=4000,
            max_age_hours=24,
            storage_path=os.path.join(os.path.dirname(__file__), 'message_history.json')
        )

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
        """Handle nick in use: ghost via NickServ before falling back"""
        self._nick_retries += 1
        desired = self.nickname
        current = connection.get_nickname()
        logger.info(f"on_nicknameinuse: desired={desired}, current={current}, args={event.arguments}, retry=#{self._nick_retries}")

        nickserv_password = self.config['irc'].get('nickserv_password', '')

        # First attempt: try GHOST via NickServ to reclaim the nick
        if nickserv_password and self._nick_retries == 1:
            logger.info(f"Attempting to GHOST old {desired} session via NickServ")
            connection.privmsg('NickServ', f'IDENTIFY {nickserv_password}')
            connection.privmsg('NickServ', f'GHOST {desired}')
            # Give NickServ a moment to process, then try reclaiming
            threading.Thread(target=self._reclaim_nick, args=(connection, desired), daemon=True).start()
            return

        # Fallback: use a random suffix
        if self._nick_retries > 3:
            logger.error("Nick retry limit reached, using whatever nick we have")
            return
        fallback = f"{desired}{random.randint(10, 999)}"
        connection.nick(fallback)
        if nickserv_password:
            connection.privmsg('NickServ', f'IDENTIFY {nickserv_password}')

    def _reclaim_nick(self, connection, desired):
        """Try to reclaim the desired nick after NickServ GHOST"""
        time.sleep(3)
        try:
            logger.info(f"Attempting to reclaim nick {desired} after GHOST")
            connection.nick(desired)
        except Exception as e:
            logger.warning(f"Failed to reclaim nick {desired}: {e}")

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

        # Log the DM for context
        self.context.add_message(sender, sender, message)

        # Generate AI response with chat context
        chat_context = self.context.get_context_for_prompt(sender, sender)
        full_response = self.ollama_client.generate_full_response_with_context(
            message, sender, chat_context
        )

        # Log bot response
        self.context.add_bot_message(sender, full_response)
        self.context.save()

        # Send response (auto-split if long)
        self.send_response(connection, full_response, sender, sender)
        logger.info(f"Sent private response to {sender}")

    def on_pubmsg(self, connection, event):
        """Handle public channel messages"""
        sender = event.source.nick
        channel = event.target
        message = event.arguments[0].strip() if event.arguments else ""

        # Log all channel messages for context
        self.context.add_message(sender, channel, message)

        # Check if bot is mentioned
        if self.is_mentioned(message):
            # Remove bot name from message
            clean_message = self.clean_message(message)

            logger.info(f"Mentioned in {channel} by {sender}: {clean_message}")

            # Build context from recent chat history
            chat_context = self.context.get_context_for_prompt(sender, channel)

            # Generate AI response with context
            full_response = self.ollama_client.generate_full_response_with_context(
                clean_message, sender, chat_context
            )

            # Log bot response
            self.context.add_bot_message(channel, full_response)
            self.context.save()

            # Send response (auto-split if long)
            self.send_response(connection, full_response, sender, channel)
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

    def send_response(self, connection, full_text, user, context):
        """Send a response to IRC, auto-splitting if it exceeds the message limit.
        Multiple chunks are sent sequentially with a brief delay."""
        prefix = f"{user}: " if context != user else ""
        prefix_len = len(prefix)
        max_len = self.MAX_IRC_MSG_LEN - prefix_len

        # Clean the text for IRC
        clean_text = full_text.replace('\r\n', ' ').replace('\r', ' ').replace('\n', ' ')
        clean_text = ' '.join(clean_text.split())

        if len(clean_text) <= max_len:
            # Fits in one message
            msg = f"{prefix}{clean_text}".strip()
            if context == user:
                connection.privmsg(user, msg)
            else:
                connection.privmsg(context, msg)
            return

        # Split into chunks
        chunks = []
        remaining = clean_text
        while remaining:
            chunk_end = max_len - 3  # Reserve for "..."
            if len(remaining) <= chunk_end:
                chunks.append(remaining)
                break
            # Break at word boundary
            space_pos = remaining.rfind(' ', 0, chunk_end)
            if space_pos > chunk_end - 50:
                chunk_end = space_pos
            chunks.append(remaining[:chunk_end] + "...")
            remaining = remaining[chunk_end:].strip()

        # Send all chunks with a small delay between each
        def _deliver_chunks():
            for i, chunk in enumerate(chunks):
                if context == user:
                    connection.privmsg(user, chunk)
                else:
                    connection.privmsg(context, f"{prefix}{chunk}")
                time.sleep(0.8)  # Brief pause to avoid IRC flood
            logger.info(f"Sent {len(chunks)} chunks to {user} in {context}")

        threading.Thread(target=_deliver_chunks, daemon=True).start()

    def get_first_chunk(self, full_text, user, context):
        """Deprecated wrapper for send_response - kept for backward compatibility"""
        return full_text[:397] + "..." if len(full_text) > 400 else full_text

    def handle_continue(self, connection, user, context):
        """Deprecated - all chunks are sent automatically now"""
        pass

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