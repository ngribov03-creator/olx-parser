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

- `OLX_SEARCH_URL` (example: `https://www.olx.ua/nedvizhimost/kvartiry/?search%5Bprivate_business%5D=private`)
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Sample parsing check

Run a quick parse against three listings (apartment, parking/garage, commercial) and log the
final fields:

```bash
python scripts/sample_listings.py \
  --urls "https://www.olx.ua/d/uk/obyavlenie/kvartira-2k-uzhgorod-ID123456.html" \
  "https://www.olx.ua/d/uk/obyavlenie/garazh-uzhgorod-ID234567.html" \
  "https://www.olx.ua/d/uk/obyavlenie/ofis-uzhgorod-ID345678.html"
```

Example log:

```
2024-05-03 12:00:00 INFO sample_listings Fetching 1/3: https://www.olx.ua/d/uk/obyavlenie/kvartira-2k-uzhgorod-ID123456.html
2024-05-03 12:00:01 INFO sample_listings Parsed listing title=2к квартира в центрі price=12 000 грн location=Ужгород, Центр description=Світла квартира з ремонтом…
2024-05-03 12:00:01 INFO sample_listings Fetching 2/3: https://www.olx.ua/d/uk/obyavlenie/garazh-uzhgorod-ID234567.html
2024-05-03 12:00:02 INFO sample_listings Parsed listing title=Гараж у кооперативі price=3 000 $ location=Ужгород, Боздош description=Гараж сухий, є світло…
2024-05-03 12:00:02 INFO sample_listings Fetching 3/3: https://www.olx.ua/d/uk/obyavlenie/ofis-uzhgorod-ID345678.html
2024-05-03 12:00:03 INFO sample_listings Parsed listing title=Офісне приміщення price=250 грн/м² location=Ужгород, Центр description=Комерційне приміщення під офіс…
```

## Debug one listing

```bash
python debug_single.py
```
