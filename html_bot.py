import re
import os
import requests
import asyncio
import time
import subprocess
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait
from bs4 import BeautifulSoup

# ✅ Telegram credentials
api_id = 26321307
api_hash = "989c16548c72fb4c56f1442780d557ea"
session_name = "html_uploader"

# 📏 Max file size
MAX_SIZE_MB = 500
RESOLUTIONS = ["720x1280", "540x960", "360x640", "270x480"]

# 🧠 Get video size
def get_video_size(url):
    try:
        r = requests.head(url, allow_redirects=True, timeout=10)
        if r.status_code == 200 and 'Content-Length' in r.headers:
            return int(r.headers['Content-Length']) / (1024 * 1024)
    except Exception as e:
        print(f"[ERROR] get_video_size: {e}")
    return None

# 🧠 Find best resolution under size limit
def find_best_resolution(base_url):
    for res in RESOLUTIONS:
        test_url = base_url.replace("720x1280", res)
        size = get_video_size(test_url)
        if size:
            print(f"🔍 {res}: {size:.2f} MB")
            if size <= MAX_SIZE_MB:
                print(f"✅ Selected: {res}")
                return test_url, res
        else:
            print(f"❌ Couldn't get size for {res}")
    return None, None

# 🧠 Parse videos from HTML
def parse_videos_from_html(content):
    soup = BeautifulSoup(content, "html.parser")
    video_entries = []
    for link in soup.find_all("a", onclick=True):
        match = re.search(r"playVideo\('([^']+\.mp4)'\)", link["onclick"])
        if match:
            video_entries.append({
                "url": match.group(1),
                "title": link.text.strip()
            })
    return video_entries, soup

# 📌 Extract course name from <div class="header">
def extract_course_name(soup):
    header_div = soup.find("div", class_="header")
    if header_div:
        course_text = header_div.find(text=True, recursive=False)
        return course_text.strip() if course_text else " "
    return " "

# 🖼️ Generate thumbnail using ffmpeg
def generate_thumbnail(video_path):
    thumb_path = "thumb.jpg"
    try:
        cmd = ["ffmpeg", "-ss", "00:00:05", "-i", video_path, "-frames:v", "1", "-q:v", "2", thumb_path]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return thumb_path if os.path.exists(thumb_path) else None
    except Exception as e:
        print(f"[ERROR] Generating thumbnail: {e}")
        return None

# 📥 Download with progress
def download_with_progress(response, filename):
    total = int(response.headers.get('content-length', 0))
    downloaded = 0
    with open(filename, "wb") as f:
        for chunk in response.iter_content(1024 * 1024):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                percent = (downloaded / total) * 100
                bar = '█' * int(percent // 3) + '-' * (33 - int(percent // 3))
                print(f"\r📥 Downloading: |{bar}| {percent:.2f}%", end='', flush=True)
    print()

# 📦 Core processing function
async def process_html_file(app: Client, chat_id: int, html_path: str):
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    videos, soup = parse_videos_from_html(content)
    course_name = extract_course_name(soup)

    await app.send_message(chat_id, f"🚀 Starting upload of {len(videos)} lectures for {course_name}...")

    for idx, entry in enumerate(videos, 1):
        url, title = entry['url'], entry['title']
        final_url, res = find_best_resolution(url)
        if not final_url:
            await app.send_message(chat_id, f"❌ Skipped: {title} - No suitable resolution found.")
            continue

        safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)[:150].strip()
        filename = f"Lecture {idx} - {safe_title} ({res}).mp4"

        try:
            r = requests.get(final_url, stream=True, timeout=15)
            if "video" not in r.headers.get("Content-Type", ""):
                await app.send_message(chat_id, f"❌ Not a valid video: {title}")
                continue
            download_with_progress(r, filename)
        except Exception as e:
            await app.send_message(chat_id, f"❌ Download error for {title}: {e}")
            continue

        caption = (
            f"<b>📚 Lecture {idx}</b>\n"
            f"<i>🎬 {title}</i>\n"
            f"<b>📖 Course:</b> {course_name}\n"
            f"<b>📺 Resolution:</b> {res}\n"
            f"\n───────────────\n"
            f"<i>🧠 Extracted by: <a href='https://t.me/CompNotesHub'>@CompNotesHub</a></i>"
        )

        thumb = "cnh.jpeg" if os.path.exists("cnh.jpeg") else generate_thumbnail(filename)
        await app.send_video(chat_id, video=filename, caption=caption, thumb=thumb, supports_streaming=True)
        os.remove(filename)
        print(f"✅ Uploaded and deleted: {filename}")

    await app.send_message(chat_id, f"✅ All lectures uploaded for {course_name}!")

# 🚀 Pyrogram Bot
app = Client(session_name, api_id=api_id, api_hash=api_hash)

@app.on_message(filters.document & filters.private)
async def handle_html_file(client: Client, message: Message):
    if message.document.mime_type == "text/html" or message.document.file_name.endswith(".html"):
        file_path = f"downloads/{message.document.file_name}"
        await message.download(file_path)
        await process_html_file(client, message.chat.id, file_path)
        os.remove(file_path)
    else:
        await message.reply("❌ Please send a valid .html file.")

if __name__ == "__main__":
    app.run()
