import re
import os
import requests
import asyncio
import time
import subprocess
from pyrogram import Client
from pyrogram.errors import FloodWait
from bs4 import BeautifulSoup

# ✅ Telegram credentials
api_id = 26321307
api_hash = "989c16548c72fb4c56f1442780d557ea"
channel = "NeetUgCourse"  # No @ here for pyrogram

# 📄 Input HTML file
html_file = "NEET_UG.html"

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
                print("⚠️ Too large, trying lower...")
        else:
            print(f"❌ Couldn't get size for {res}")
    return None, None

# 🧠 Parse videos from HTML
def parse_videos_from_html(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")
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
        cmd = [
            "ffmpeg", "-ss", "00:00:05", "-i", video_path,
            "-frames:v", "1", "-q:v", "2", thumb_path
        ]
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

# 📥 Download video
async def download_video(entry, index, course_name):
    url, title = entry['url'], entry['title']
    print(f"\n⬇️ [D{index}] Finding best resolution for: {title}")
    final_url, res = find_best_resolution(url)
    if not final_url:
        print(f"❌ [D{index}] Skipped: No suitable resolution found.")
        return None, None, None, None

    safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)[:150].strip()
    filename = f"Lecture {index} - {safe_title} ({res}).mp4"

    caption = (
        f"<b>📚 Lecture {index}</b>\n"
        f"<i>🎬 {title}</i>\n"
        f"<b>📖 Course:</b> {course_name}\n"
        f"<b>📺 Resolution:</b> {res}\n"
        f"\n───────────────\n"
        f"<i>🧠 Extracted by: <a href='https://t.me/CompNotesHub'>@CompNotesHub</a></i>"
    )

    print(f"⬇️ [D{index}] Downloading: {final_url}")
    try:
        r = requests.get(final_url, stream=True, timeout=15)
        if "video" not in r.headers.get("Content-Type", ""):
            print(f"❌ [D{index}] Not a valid video content")
            return None, None, None, None
        download_with_progress(r, filename)
        print(f"✅ [D{index}] Downloaded: {filename}")
        return filename, caption, index, res
    except Exception as e:
        print(f"❌ [D{index}] Download error: {e}")
        return None, None, None, None

# 📤 Upload video
async def upload_video(app, chat_id, filename, caption, index):
    if not os.path.exists(filename):
        print(f"❌ [U{index}] File missing: {filename}")
        return

    last_time = time.time()
    last_bytes = 0

    def progress(current, total):
        nonlocal last_time, last_bytes
        now = time.time()
        elapsed = now - last_time
        speed = (current - last_bytes) / elapsed if elapsed > 0 else 0

        percent = (current / total) * 100
        downloaded_mb = current / (1024 * 1024)
        total_mb = total / (1024 * 1024)
        speed_mb = speed / (1024 * 1024)
        eta_seconds = (total - current) / speed if speed > 0 else 0

        bar_length = 40
        filled = int(bar_length * percent // 100)
        bar = '█' * filled + '-' * (bar_length - filled)

        print(
            f"\r📈 Uploading Lecture {index} |{bar}| {percent:5.2f}% "
            f"[{downloaded_mb:.2f}/{total_mb:.2f} MB] "
            f"🚀 {speed_mb:.2f} MB/s ⏳ ETA: {eta_seconds:.1f}s",
            end='',
            flush=True
        )

        last_time = now
        last_bytes = current

    try:
        thumb = "cnh.jpeg" if os.path.exists("cnh.jpeg") else generate_thumbnail(filename)
        await app.send_video(
            chat_id=chat_id,
            video=filename,
            caption=caption,
            thumb=thumb if thumb else None,
            supports_streaming=True,
            progress=progress
        )
        print(f"\n✅ [U{index}] Upload done: {filename}")
    except FloodWait as e:
        print(f"⏳ FloodWait: Sleeping for {e.value} seconds")
        await asyncio.sleep(e.value)
    except Exception as e:
        print(f"❌ [U{index}] Upload error: {e}")
    finally:
        if os.path.exists(filename):
            os.remove(filename)
            print(f"🗑️ [U{index}] Deleted file after upload: {filename}")

# 🔁 Main pipeline
async def main():
    print("📂 Parsing videos from HTML file...")
    videos, soup = parse_videos_from_html(html_file)
    course_name = extract_course_name(soup)
    print(f"📘 Course Name: {course_name}")
    print(f"🔢 Found {len(videos)} videos to process.")

    if not videos:
        print("⚠️ No videos found in the HTML file.")
        return

    try:
        start_from = int(input(f"📥 Start uploading from lecture number (1 to {len(videos)}): "))
        if start_from < 1 or start_from > len(videos):
            print("❌ Invalid number. Starting from Lecture 1.")
            start_from = 1
    except:
        print("❌ Invalid input. Starting from Lecture 1.")
        start_from = 1

    only_one = input("📌 Do you want to upload ONLY this lecture? (yes/no): ").strip().lower()

    app = Client("uploader", api_id=api_id, api_hash=api_hash)
    await app.start()
    await app.send_message(channel, f"🚀 Starting upload from Lecture {start_from} for {course_name}...")

    # 👇 Conditional loop: Single or Multiple
    if only_one in ['yes', 'y']:
        i = start_from - 1
        filename, caption, idx, res = await download_video(videos[i], i + 1, course_name)
        if filename and caption:
            await upload_video(app, channel, filename, caption, i + 1)
    else:
        for i in range(start_from - 1, len(videos)):
            filename, caption, idx, res = await download_video(videos[i], i + 1, course_name)
            if filename and caption:
                await upload_video(app, channel, filename, caption, i + 1)

    await app.send_message(channel, f"✅ Upload process completed for {course_name}!")
    await app.stop()
    print("🔚 Telegram client stopped.")


# 🔧 Entry point
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Stopped by user.")
