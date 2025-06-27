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
channel = "NeetUgCourse"  # <- ✅ Remove @ symbol here for pyrogram compatibility

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
    return video_entries

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
async def download_video(entry, semaphore, upload_queue, index):
    async with semaphore:
        url, title = entry['url'], entry['title']
        print(f"\n⬇️ [D{index}] Finding best resolution for: {title}")
        final_url, res = find_best_resolution(url)
        if not final_url:
            print(f"❌ [D{index}] Skipped: No suitable resolution found.")
            return

        safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)[:150].strip()
        filename = f"Lecture {index} - {safe_title} ({res}).mp4"

        caption = (
            f"<b>📚 Lecture {index}</b>\n"
            f"<i>🎬 {title}</i>\n"
            f"<b>📖 Course:</b> NEET UG\n"
            f"<b>📺 Resolution:</b> {res}\n"
            f"\n───────────────\n"
            f"<i>🧠 Extracted by: <a href='https://t.me/CompNotesHub'>@CompNotesHub</a></i>"
        )

        print(f"⬇️ [D{index}] Downloading: {final_url}")
        try:
            r = requests.get(final_url, stream=True, timeout=15)
            if "video" not in r.headers.get("Content-Type", ""):
                print(f"❌ [D{index}] Not a valid video content")
                return
            download_with_progress(r, filename)
            print(f"✅ [D{index}] Downloaded: {filename}")
        except Exception as e:
            print(f"❌ [D{index}] Download error: {e}")
            return

        thumbnail = "cnh.jpeg" if os.path.exists("cnh.jpeg") else generate_thumbnail(filename)

        await upload_queue.put((filename, caption, index, thumbnail))
        print(f"📤 [D{index}] Queued for upload: {filename}")
        print(f"📊 Upload queue length: {upload_queue.qsize()}")

# 📤 Upload worker
async def upload_worker(app, upload_queue, chat_peer, videos, download_queue, download_semaphore):
    print("🚀 Upload worker started...")
    while True:
        filename = caption = thumbnail = None
        try:
            filename, caption, idx, thumbnail = await upload_queue.get()
            print(f"📦 [U{idx}] Uploading: {filename}")

            if not os.path.exists(filename):
                print(f"❌ [U{idx}] File missing: {filename}")
                upload_queue.task_done()
                continue

            def progress(current, total):
                percent = (current / total) * 100
                bar_length = 30
                filled = int(bar_length * current // total)
                bar = '█' * filled + '-' * (bar_length - filled)
                print(f"\r📈 Uploading: |{bar}| {percent:.2f}% complete", end='', flush=True)

            try:
                await app.send_video(
                    chat_id=chat_peer,
                    video=filename,
                    caption=caption,
                    thumb=thumbnail if thumbnail else None,
                    supports_streaming=True,
                    progress=progress,
                )
                print(f"\n✅ [U{idx}] Upload done: {filename}")
            except FloodWait as e:
                print(f"⏳ FloodWait: Sleeping for {e.value} seconds")
                await asyncio.sleep(e.value)
                continue

        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"\n❌ [U{idx}] Upload failed: {e}")
        finally:
            if filename and os.path.exists(filename):
                os.remove(filename)
                print(f"🗑️ [U{idx}] Deleted file after upload: {filename}")
            upload_queue.task_done()

            if not download_queue.empty():
                next_index = await download_queue.get()
                print(f"📥 Triggering download of video {next_index + 1} after upload of video {idx}")
                await download_video(videos[next_index], download_semaphore, upload_queue, next_index + 1)

# 🔁 Main pipeline
async def main():
    print("📂 Parsing videos from HTML file...")
    videos = parse_videos_from_html(html_file)
    print(f"🔢 Found {len(videos)} videos to process.")

    if not videos:
        print("⚠️ No videos found in the HTML file.")
        return

    max_parallel_downloads = 3
    download_semaphore = asyncio.Semaphore(max_parallel_downloads)
    upload_queue = asyncio.Queue()
    download_queue = asyncio.Queue()

    app = Client("uploader", api_id=api_id, api_hash=api_hash)
    await app.start()

    await app.send_message(channel, f"🚀 Starting upload of {len(videos)} NEET UG lectures...")

    upload_task = asyncio.create_task(
        upload_worker(app, upload_queue, channel, videos, download_queue, download_semaphore)
    )

    for i in range(min(3, len(videos))):
        print(f"📥 Scheduling initial download for video {i + 1}")
        await download_video(videos[i], download_semaphore, upload_queue, i + 1)

    for i in range(3, len(videos)):
        await download_queue.put(i)

    await upload_queue.join()

    await app.send_message(channel, "✅ All lectures uploaded successfully!")
    upload_task.cancel()
    await app.stop()
    print("🔚 Telegram client stopped.")

# 🔧 Entry point
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Stopped by user.")