import requests
import sys
import os
import argparse
from io import BytesIO
from datetime import datetime
from app.config_telegram import TELEGRAM_BOTS, DEFAULT_BOT_NAME
from dotenv import load_dotenv
load_dotenv()

NASA_APOD_URL = "https://api.nasa.gov/planetary/apod"
NASA_API_KEY = os.getenv("NASA_API_KEY")

if not NASA_API_KEY:
    print("Warning: NASA_API_KEY not found. Using DEMO_KEY (limited access).")
    NASA_API_KEY = "DEMO_KEY"

def get_timestamp():
    return f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]"

def send_photo_to_telegram(bot_settings, image_buffer, caption, script_name, post_description, bot_name):
    response = requests.post(
        f"https://api.telegram.org/bot{bot_settings['bot_token']}/sendPhoto",
        data={
            'chat_id': bot_settings['chat_id'],
            'caption': caption,
            'parse_mode': 'HTML'
        },
        files={'photo': ('nasa_apod.jpg', image_buffer, 'image/jpeg')}
    )

    bot_token_tail = bot_settings['bot_token'][-5:]
    status = "Success" if response.status_code == 200 else f"Failed! Status: {response.status_code} {response.text}"
    
    print(f"{get_timestamp()} Telegram post: {status} "
          f"[script_name: {script_name}; "
          f"post_description: {post_description.strip()[:50]}; "
          f"chat_id: {bot_settings['chat_id']}; "
          f"bot_name: {bot_name}; "
          f"bot_token: ***{bot_token_tail};]")

def get_nasa_image(bot_settings, bot_name):
    print(f"{get_timestamp()} Script executed. Launch command: {' '.join(sys.argv[0:])}")
    try:
        params = {"api_key": NASA_API_KEY}
        print(f"{get_timestamp()} Requesting NASA image of the day...")
        response = requests.get(NASA_APOD_URL, params=params)
        if response.status_code != 200:
            print(f"{get_timestamp()} Error! Request failed with status: {response.status_code}")
            sys.exit(1)

        data = response.json()
        if data.get("media_type") != "image":
            media_type = data.get("media_type")
            url = data.get("url")
            title = data.get("title", "NASA APOD")
            date = data.get("date", datetime.now().strftime("%Y-%m-%d"))
            post_date = datetime.strptime(date, "%Y-%m-%d").strftime("%Y %B %d")

            page_url = "https://apod.nasa.gov/apod/astropix.html"

            # Convert embed YouTube URL to watch format for Telegram preview
            if "youtube.com/embed/" in url:
                video_id = url.split("/embed/")[-1].split("?")[0]
                url = f"https://www.youtube.com/watch?v={video_id}"

            caption = f"🌌 <b>NASA Astronomy Picture of the Day!</b>\n" \
                    f"<b>Date:</b> {post_date}\n" \
                    f"🎥 <b>{title}</b>\n" \
                    f"{url}\n" \
                    f"🔗 <a href='{page_url}'>View full post</a>"
                    


            response = requests.post(
                f"https://api.telegram.org/bot{bot_settings['bot_token']}/sendMessage",
                data={
                    'chat_id': bot_settings['chat_id'],
                    'text': caption,
                    'parse_mode': 'HTML'
                }
            )

            bot_token_tail = bot_settings['bot_token'][-5:]
            status = "Success" if response.status_code == 200 else f"Failed! Status: {response.status_code} {response.text}"
            print(f"{get_timestamp()} Telegram post: {status} "
                f"[script_name: nasa_apod_image; "
                f"post_description: {title.strip()[:50]}; "
                f"chat_id: {bot_settings['chat_id']}; "
                f"bot_name: {bot_name}; "
                f"bot_token: ***{bot_token_tail};]")
            print(f"{get_timestamp()} Script finished.")
            return


        image_url = data.get("url")
        title = data.get("title", "NASA Image")
        date = data.get("date", datetime.now().strftime("%Y-%m-%d"))
        page_url = "https://apod.nasa.gov/apod/astropix.html"

        print(f"{get_timestamp()} Found image: {title} ({date})")
        print(f"{get_timestamp()} Downloading image...")

        image_response = requests.get(image_url)
        if image_response.status_code != 200:
            print(f"{get_timestamp()} Error downloading image!")
            sys.exit(1)

        image_buffer = BytesIO(image_response.content)

        post_date = datetime.strptime(date, "%Y-%m-%d").strftime("%Y %B %d")

        caption = f"🌌 <b>NASA Astronomy Picture of the Day!</b>\n" \
                  f"<b>Date:</b> {post_date}\n" \
                  f"📷 <b>{title}</b>\n" \
                  f"🔗 <a href='{page_url}'>View full post</a>"

        send_photo_to_telegram(bot_settings, image_buffer, caption, script_name="nasa_apod_image", post_description=title, bot_name=bot_name)

    except Exception as e:
        print(f"{get_timestamp()} Exception occurred: {str(e)}")
        sys.exit(1)
    finally:
        print(f"{get_timestamp()} Script finished.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--bot', help='Specify Telegram bot name from config_telegram.py')
    args = parser.parse_args()

    bot_name = args.bot if args.bot else DEFAULT_BOT_NAME
    bot_settings = TELEGRAM_BOTS.get(bot_name)

    if not bot_settings:
        print(f"{get_timestamp()} ERROR: Bot '{bot_name}' not found in config_telegram.py.")
        sys.exit(1)

    get_nasa_image(bot_settings, bot_name)
