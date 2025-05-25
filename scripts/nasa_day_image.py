import requests
import feedparser
from bs4 import BeautifulSoup
from PIL import Image
from io import BytesIO
import argparse
import sys
import os
from datetime import datetime, timezone
from app.config_telegram import TELEGRAM_BOTS, DEFAULT_BOT_NAME

NASA_DAY_RSS_URL = "https://www.nasa.gov/rss/dyn/lg_image_of_the_day.rss"
TAKE_LAST_IF_NOTFOUND = False
MAX_DESCRIPTION_LENGTH = 600

def get_timestamp():
    return f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"

def sanitize_text(text):
    return text.encode('utf-8', 'ignore').decode('utf-8')

def send_photo_to_telegram(bot_settings, image_buffer, caption, script_name, post_description, bot_name):
    response = requests.post(
        f"https://api.telegram.org/bot{bot_settings['bot_token']}/sendPhoto",
        data={
            'chat_id': bot_settings['chat_id'],
            'caption': caption,
            'parse_mode': 'HTML'
        },
        files={'photo': (f"nasa_{datetime.now().strftime('%Y%m%d%H%M%S')}.jpg", image_buffer, 'image/jpeg')}
    )

    bot_token_tail = bot_settings['bot_token'][-5:]
    status = "Success" if response.status_code == 200 else f"Failed! Status: {response.status_code} {response.text}"
    
    print(f"{get_timestamp()} Telegram post: {status} "
          f"[script_name: {script_name}; "
          f"post_description: {post_description.strip()[:50]}; "
          f"chat_id: {bot_settings['chat_id']}; "
          f"bot_name: {bot_name}; "
          f"bot_token: ***{bot_token_tail};]")

def main(bot_settings, bot_name):
    try:
        print(f"{get_timestamp()} Script executed. Launch command: {' '.join(sys.argv[0:])}")
        print(f"{get_timestamp()} Fetching RSS feed...")
        feed = feedparser.parse(NASA_DAY_RSS_URL)
        latest = max(feed.entries, key=lambda e: e.published_parsed)

        title = sanitize_text(latest.title)
        description = sanitize_text(latest.summary).strip()
        if len(description) > MAX_DESCRIPTION_LENGTH:
            description = description[:MAX_DESCRIPTION_LENGTH] + "..."

        link = latest.link
        pub_date = datetime(*latest.published_parsed[:6], tzinfo=timezone.utc)
        post_date = pub_date.strftime("%Y %B %d")

        today_utc = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        from datetime import timedelta
        if pub_date < (today_utc - timedelta(hours=12)) and not TAKE_LAST_IF_NOTFOUND:

            print(f"{get_timestamp()} No new image today. Skipping post.")
            return

        print(f"{get_timestamp()} Found today's image: {title}")
        print(f"{get_timestamp()} Fetching image page...")
        response = requests.get(link)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            image_url = og_image['content']
        else:
            image_url = next((img.get('src') for img in soup.find_all('img') if img.get('src', '').endswith('.jpg')), None)


        if not image_url:
            print(f"{get_timestamp()} ERROR: No image found on the page.")
            return

        if not image_url.startswith("http"):
            image_url = f"https://www.nasa.gov{image_url}"

        print(f"{get_timestamp()} Image URL: {image_url}")

        print(f"{get_timestamp()} Downloading and resizing image...")
        img_response = requests.get(image_url)
        img_response.raise_for_status()
        img = Image.open(BytesIO(img_response.content))
        img = img.resize((1200, int(1200 * img.height / img.width)))

        buffer = BytesIO()
        img.save(buffer, format='JPEG', quality=85)
        buffer.seek(0)

        caption = f"🚀 <b>NASA Image of the Day!</b>\n" \
                  f"<b>Date:</b> {post_date}\n" \
                  f"📷 <b>{title}</b>\n\n" \
                  f"<b>{description}</b>\n" \
                  f"🔗 <a href='{link}'>View full post</a>"

        send_photo_to_telegram(bot_settings, buffer, caption, script_name="nasa_day_image", post_description=title, bot_name=bot_name)

        print(f"{get_timestamp()} Script finished.")
    except Exception as e:
        print(f"{get_timestamp()} Exception occurred: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--bot', help='Specify Telegram bot name from config_telegram.py')
    args = parser.parse_args()

    bot_name = args.bot if args.bot else DEFAULT_BOT_NAME
    bot_settings = TELEGRAM_BOTS.get(bot_name)

    if not bot_settings:
        print(f"{get_timestamp()} ERROR: Bot '{bot_name}' not found in config_telegram.py.")
        sys.exit(1)

    main(bot_settings, bot_name)

