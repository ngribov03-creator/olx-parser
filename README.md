# olx-parser

## Telegram setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the bot token.
2. Get the chat ID:
   - For a private chat, start the bot and fetch updates via
     `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`, then copy `chat.id`.
   - For a channel, use the channel username (e.g. `@my_channel`) or inspect updates after
     posting in the channel.
3. Add the bot as an admin to the channel (or grant permission to post in the chat).

Set the following environment variables:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
