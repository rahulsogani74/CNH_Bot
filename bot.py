from pyrogram import Client, filters
from pyrogram.types import Message
import asyncio
import os
import re
import requests
import subprocess
from bs4 import BeautifulSoup
from pyrogram.errors import FloodWait
from tqdm import tqdm
import time
import logging

from dotenv import load_dotenv

load_dotenv()

api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
bot_token = os.getenv("BOT_TOKEN")

MAX_SIZE_MB = 500
RESOLUTIONS = ["720x1280", "540x960", "360x640", "270x480"]
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

stop_flag = set()
current_task = None
waiting_for_file = set()
pending_video_data = {}
video_selection_msg = {}

bot = Client("bot_session", api_id=api_id, api_hash=api_hash, bot_token=bot_token)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()  # Show in terminal
    ]
)

async def send_temp_message(bot, chat_id, text, delay=60):
    try:
        msg = await bot.send_message(chat_id, text)
        # Instead of await asyncio.sleep...
        asyncio.create_task(delete_after(bot, msg, delay))
        return msg
    except:
        pass

async def delete_after(bot, msg, delay):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except:
        pass


def get_video_size(url):
    try:
        r = requests.get(url, stream=True, timeout=10)
        if r.status_code == 200 and 'Content-Length' in r.headers:
            return int(r.headers['Content-Length']) / (1024 * 1024)
        else:
            print(f"⚠️ No Content-Length from {url}")
    except Exception as e:
        print(f"⚠️ Error while checking size: {e}")
    return None


def find_best_resolution(base_url):
    for res in RESOLUTIONS:
        test_url = base_url.replace("720x1280", res)
        size = get_video_size(test_url)
        if size and size <= MAX_SIZE_MB:
            return test_url, res
    return None, None

def generate_thumbnail(video_path):
    thumb = "thumb.jpg"
    cmd = ["ffmpeg", "-ss", "00:00:05", "-i", video_path, "-frames:v", "1", "-q:v", "2", thumb]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return thumb if os.path.exists(thumb) else None

def parse_html(path):
    with open(path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")
    videos = []
    for link in soup.find_all("a", onclick=True):
        match = re.search(r"playVideo\('([^']+\.mp4)'\)", link["onclick"])
        if match:
            videos.append({"url": match.group(1), "title": link.text.strip()})
    return videos, soup

def extract_course_name(soup):
    div = soup.find("div", class_="header")
    if div:
        text = div.find(string=True, recursive=False)
        return text.strip() if text else "Course"
    return "Course"

def parse_txt(path):
    videos = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f.readlines():
            parts = line.strip().split('|')
            if len(parts) >= 2:
                videos.append({"url": parts[0], "title": parts[1]})
    return videos, None


async def download_video(entry, index, course_name, chat_id):
    if chat_id in stop_flag:
        raise asyncio.CancelledError("Stopped by user.")

    url, title = entry['url'], entry['title']
    final_url, res = find_best_resolution(url)
    if not final_url:
        print(f"\n❌ No resolution found: {title}")
        return None, None

    print(f"\n📚 Lecture {index} | {title}\n📺 Resolution: {res}")
    await send_temp_message(bot, chat_id, f"\n📚 Lecture {index}\n🎮 {title}\n📺 Trying Resolution: {res}", delay=10)

    safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)[:150].strip()
    filename = os.path.join(DOWNLOAD_DIR, f"Lecture {index} - {safe_title} ({res}).mp4")

    caption = (
        f"📚 Lecture {index}\n🎮 {title}\n"
        f"📖 Course: {course_name}\n📺 Resolution: {res}\n"
        f"─────────────────\n🧠 Extracted by: @CompNotesHub"
    )

    try:
        r = await asyncio.to_thread(lambda: requests.get(final_url, stream=True, timeout=15))

        total = int(r.headers.get("Content-Length", 0))
        if "video" not in r.headers.get("Content-Type", ""):
            return None, None

        start = time.time()
        with open(filename, "wb") as f:
            with tqdm(total=total, unit="B", unit_scale=True, desc=f"📥 Download {index}", ascii=" ░▒▓", ncols=80) as bar:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chat_id in stop_flag:
                        raise asyncio.CancelledError("Stopped by user during download.")
                    if chunk:
                        f.write(chunk)
                        bar.update(len(chunk))
        end = time.time()
        print(f"⏱ Download Time: {round(end - start, 2)}s")
        return filename, caption
    except asyncio.CancelledError:
        print("⛔ Download cancelled.")
        if os.path.exists(filename): os.remove(filename)
        return None, None
    except Exception as e:
        print(f"❌ Download error: {e}")
        return None, None


async def upload_video(app, chat_id, filename, caption, index):
    if not os.path.exists(filename) or chat_id in stop_flag:
        raise asyncio.CancelledError("Stopped by user.")

    try:
        thumb = "cnh.jpeg" if os.path.exists("cnh.jpeg") else generate_thumbnail(filename)
        print(f"\n📤 Uploading Lecture {index}...")

        total_size = os.path.getsize(filename)
        uploaded = 0
        start_time = time.time()
        last_update_time = start_time  # NEW

        bar = tqdm(
            total=total_size,
            unit="B",
            unit_scale=True,
            desc=f"📤 Upload {index}",
            ascii=" ░▒▓",
            ncols=100,
            bar_format="{desc} |{bar}| {percentage:.1f}% {n_fmt}/{total_fmt} • {rate_fmt} • {postfix}"
        )

        # Initial status message on Telegram
        status_msg = await app.send_message(
            chat_id,
            f"📤 Uploading Lecture {index}...\n"
            f"🎮 Title: {os.path.basename(filename)}\n"
            f"📺 Resolution: {caption.split('📺 Resolution: ')[-1].splitlines()[0]}"
        )

        async def progress(current, total):
            nonlocal uploaded, start_time, status_msg, last_update_time
            if chat_id in stop_flag:
                raise asyncio.CancelledError("Stopped by user during upload.")

            elapsed = time.time() - start_time
            speed = (current / elapsed) if elapsed > 0 else 0
            eta = (total - current) / speed if speed > 0 else 0

            uploaded_mb = current / (1024 * 1024)
            total_mb = total / (1024 * 1024)
            speed_str = f"{speed / 1024 / 1024:.2f} MB/s"
            eta_str = f"{int(eta)}s remaining"

            # Update terminal bar
            delta = current - uploaded
            bar.update(delta)
            bar.refresh()  # 🔁 Force refresh to make sure it displays
            uploaded = current
            bar.set_postfix({
                "Speed": speed_str,
                "ETA": eta_str
            })

            # ✅ Update after every 5 seconds or when upload completes
            now = time.time()
            if now - last_update_time >= 5 or current == total:
                last_update_time = now
                try:
                    await status_msg.edit_text(
                        f"📤 Uploading Lecture {index}...\n"
                        f"🎮 Title: {os.path.basename(filename)}\n"
                        f"📺 Resolution: {caption.split('📺 Resolution: ')[-1].splitlines()[0]}\n"
                        f"💾 {uploaded_mb:.2f}MB / {total_mb:.2f}MB\n"
                        f"⚡ Speed: {speed_str}\n"
                        f"⏱ ETA: {eta_str}"
                    )
                except:
                    pass

                
        await app.send_video(
            chat_id,
            video=filename,
            caption=caption,
            thumb=thumb,
            supports_streaming=True,
            progress=progress
        )

        bar.close()
        await status_msg.edit_text(f"✅ Lecture {index} uploaded successfully.")
        print(f"✅ Uploaded Lecture {index} | Size: {total_size / (1024*1024):.2f} MB")

    except asyncio.CancelledError:
        print("⛔ Upload cancelled.")
        if os.path.exists(filename):
            os.remove(filename)
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await upload_video(app, chat_id, filename, caption, index)
    except Exception as e:
        print(f"❌ Upload error: {e}")
    finally:
        if os.path.exists(filename):
            os.remove(filename)


@bot.on_message(filters.command("start"))
async def start_message(bot, message: Message):
    logging.info(f"/start by {message.from_user.id} ({message.from_user.first_name})")
    await send_temp_message(bot, message.chat.id,
        "👋 Welcome to the Lecture Video Uploader Bot!\n\n"
        "📂 Use /upload to start uploading your lecture file (.html or .txt).\n"
        "🛑 Use /stop anytime to cancel.\n\n"
        "🔗 Channel: @CompNotesHub")

@bot.on_message(filters.command("upload"))
async def upload_command(bot, message: Message):
    chat_id = message.chat.id
    waiting_for_file.add(chat_id)
    await send_temp_message(bot, chat_id, "📄 Send your .html or .txt file now.")

    async def clear_flag():
        await asyncio.sleep(120)
        if chat_id in waiting_for_file:
            waiting_for_file.discard(chat_id)
            await send_temp_message(bot, chat_id, "⏳ Upload timed out. Send /upload again.")

    asyncio.create_task(clear_flag())

@bot.on_message(filters.command("stop"))
async def stop_command(bot, message: Message):
    global current_task
    chat_id = message.chat.id
    stop_flag.add(chat_id)
    if current_task and not current_task.done():
        current_task.cancel()
    await send_temp_message(bot, chat_id, "🛑 Upload cancelled. Use /upload to start again.")

@bot.on_message(filters.command("ronny"))
async def shutdown_bot(bot, message: Message):
    chat_id = message.chat.id
    await bot.send_message(chat_id, "🛑 Bot is shutting down by command /ronny.")
    logging.warning(f"❌ Bot shutdown triggered by user {chat_id} ({message.from_user.first_name})")
    await asyncio.sleep(2)
    os._exit(0)  # Force exit without cleanup


@bot.on_message(filters.document)
async def handle_document(bot, message: Message):
    chat_id = message.chat.id
    if chat_id not in waiting_for_file:
        await send_temp_message(bot, chat_id, "⚠️ Use /upload first.")
        return
    waiting_for_file.discard(chat_id)

    file_ext = message.document.file_name.split('.')[-1].lower()
    path = os.path.join(DOWNLOAD_DIR, f"input.{file_ext}")
    await message.download(file_name=path)
    logging.info(f"📄 File received: {message.document.file_name} from {chat_id}")

    if not os.path.exists(path):
        await send_temp_message(bot, chat_id, "❌ File download failed.")
        return

    if file_ext == "html":
        videos, soup = parse_html(path)
        course_name = extract_course_name(soup)
    elif file_ext == "txt":
        videos, soup = parse_txt(path)
        course_name = "Text Course"
    else:
        await send_temp_message(bot, chat_id, "❌ Unsupported file type.")
        return

    os.remove(path)
    if not videos:
        await send_temp_message(bot, chat_id, "⚠️ No videos found.")
        return

    await bot.send_message(chat_id, f"📘 Course: {course_name}\n🎞 Total Videos: {len(videos)}")

    selection_msg = await bot.send_message(chat_id,
        "🟢 From which lecture should I start?\n\n"
        "Reply with:\n"
        "<lecture_number> → upload from that number onward\n"
        "<lecture_number> only → upload only that one\n\n"
        "Example: 3 or 4 only")

    video_selection_msg[chat_id] = selection_msg
    pending_video_data[chat_id] = {"videos": videos, "course_name": course_name}

    async def auto_delete():
        await asyncio.sleep(180)
        try:
            await selection_msg.delete()
        except:
            pass

    asyncio.create_task(auto_delete())

@bot.on_message(filters.text & ~filters.command(["start", "upload", "stop"]))
async def handle_video_selection(bot, message: Message):
    chat_id = message.chat.id
    text = message.text.strip().lower()

    if chat_id not in pending_video_data:
        return

    data = pending_video_data.pop(chat_id)
    videos = data["videos"]
    course_name = data["course_name"]

    match = re.match(r"(\d+)( only)?", text)
    if not match:
        await send_temp_message(bot, chat_id, "❌ Invalid format. Example: 3 or 3 only")
        return

    start = int(match.group(1))
    only = match.group(2) is not None

    if start < 1 or start > len(videos):
        await send_temp_message(bot, chat_id, "⚠️ Invalid lecture number.")
        return

    try:
        await video_selection_msg[chat_id].delete()
    except:
        pass

    video_range = range(start, start + 1) if only else range(start, len(videos) + 1)

    async def process():
        for i in video_range:
            if chat_id in stop_flag:
                break
            entry = videos[i - 1]
            filename, caption = await download_video(entry, i, course_name, chat_id)
            if filename:
                await upload_video(bot, chat_id, filename, caption, i)
            else:
                await send_temp_message(bot, chat_id, f"⚠️ Skipped Lecture {i}")
        stop_flag.discard(chat_id)
        await send_temp_message(bot, chat_id, "✅ Upload complete or stopped.")

    asyncio.create_task(process())  # ← ensures immediate async run

    
if __name__ == "__main__":
    print("🚀 Starting bot...")
    logging.info("🚀 Starting bot...")
    bot.run()
