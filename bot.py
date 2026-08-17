import os
import random
import string
import asyncio
import re
import aiohttp
import logging
from fastapi import FastAPI, Request, Response
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = "8293365930:AAEPA3dpgJLB2R106NT-0cf8Dm_kWkBF1U0"
GROUP_ID = -1004339334563
ADMIN_ID = 6790347169

app = FastAPI()
telegram_app = None

# Menyimpan status loop aktif per chat_id agar bisa dihentikan jika diperlukan
active_loops = set()

def sensor_text(text):
    if not text or len(text) <= 3: return "***"
    return text[:-3] + "***"

class MailTMBot:
    def __init__(self):
        self.base_url = "https://api.mail.tm"
        self.email = ""
        self.token = ""

    async def create_account(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.base_url}/domains") as r:
                domains = await r.json()
                domain = domains['hydra:member'][0]['domain']
                user = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
                self.email = f"{user}@{domain}"
            
            payload = {"address": self.email, "password": "Password123!"}
            await session.post(f"{self.base_url}/accounts", json=payload)
            async with session.post(f"{self.base_url}/token", json=payload) as r:
                data = await r.json()
                self.token = data.get('token', '')
        logger.info(f"Akun Mail.tm dibuat: {self.email}")

    async def fetch_otp(self, timeout=60):
        headers = {"Authorization": f"Bearer {self.token}"}
        start_time = asyncio.get_event_loop().time()
        
        async with aiohttp.ClientSession(headers=headers) as session:
            while (asyncio.get_event_loop().time() - start_time) < timeout:
                try:
                    async with session.get(f"{self.base_url}/messages", headers={**headers, "Cache-Control": "no-cache"}) as r:
                        data = await r.json()
                        if data.get('hydra:totalItems', 0) > 0:
                            for msg in data['hydra:member']:
                                msg_id = msg['id']
                                async with session.get(f"{self.base_url}/messages/{msg_id}", headers=headers) as r2:
                                    msg_detail = await r2.json()
                                    raw_text = msg_detail.get('text', '') or ''
                                    raw_html = msg_detail.get('html', '') or ''
                                    subject = msg_detail.get('subject', '') or ''
                                    
                                    if isinstance(raw_text, list): raw_text = "\n".join(str(x) for x in raw_text)
                                    if isinstance(raw_html, list): raw_html = "\n".join(str(x) for x in raw_html)
                                    if isinstance(subject, list): subject = " ".join(str(x) for x in subject)

                                    combined_content = f"{subject} {raw_text} {raw_html}"
                                    
                                    match = re.search(r'(?:otp\s*code|kode\s*konfirmasi|otp)[:\s\-]*([A-Za-z0-9]{6})', combined_content, re.IGNORECASE)
                                    if match:
                                        logger.info(f"OTP berhasil dibaca: {match.group(1)}")
                                        return match.group(1).strip()
                                    words = re.findall(r'\b[A-Z0-9]{6}\b', combined_content)
                                    if words:
                                        for w in words:
                                            if not any(x in w.lower() for x in ['emalupe', 'mail', 'http', 'com', 'co.id', 'xlsmart']):
                                                return w
                except Exception as e:
                    logger.error(f"Error saat fetch OTP: {e}")
                await asyncio.sleep(0.5)
        return None

    async def fetch_xl_confirmation_email(self, timeout=60):
        headers = {"Authorization": f"Bearer {self.token}"}
        start_time = asyncio.get_event_loop().time()
        
        async with aiohttp.ClientSession(headers=headers) as session:
            logger.info("Menunggu email konfirmasi eSIM dari XL...")
            while (asyncio.get_event_loop().time() - start_time) < timeout:
                try:
                    async with session.get(f"{self.base_url}/messages", headers={**headers, "Cache-Control": "no-cache"}) as r:
                        data = await r.json()
                        if data.get('hydra:totalItems', 0) > 0:
                            for msg in data['hydra:member']:
                                msg_id = msg['id']
                                async with session.get(f"{self.base_url}/messages/{msg_id}", headers=headers) as r2:
                                    msg_detail = await r2.json()
                                    raw_text = msg_detail.get('text', '') or ''
                                    raw_html = msg_detail.get('html', '') or ''
                                    subject = msg_detail.get('subject', '') or ''
                                    
                                    if isinstance(raw_text, list): raw_text = "\n".join(str(x) for x in raw_text)
                                    if isinstance(raw_html, list): raw_html = "\n".join(str(x) for x in raw_html)
                                    if isinstance(subject, list): subject = " ".join(str(x) for x in subject)

                                    if not raw_text.strip() and raw_html.strip():
                                        raw_text = re.sub('<[^<]+?>', '', raw_html)

                                    combined_content = f"{subject}\n{raw_text}\n{raw_html}"
                                    
                                    if 'MSISDN' in combined_content or 'Activation Code' in combined_content or 'eSIM' in combined_content:
                                        logger.info("Email sukses eSIM XL ditemukan, mengekstrak detail...")
                                        
                                        msisdn = re.search(r'MSISDN\s*[:\s\-]*([0-9\+\s]+)', combined_content, re.IGNORECASE)
                                        puk = re.search(r'(?:Kode\s*PUK|PUK)\s*[:\s\-]*([0-9\s]+)', combined_content, re.IGNORECASE)
                                        smdp = re.search(r'SM-DP\+?\s*Address\s*[:\s\-]*([a-zA-Z0-9\.\_\-]+)', combined_content, re.IGNORECASE)
                                        act_code = re.search(r'Activation\s*Code\s*[:\s\-]*([a-zA-Z0-9\-]+)', combined_content, re.IGNORECASE)
                                        
                                        clean_msisdn = msisdn.group(1).strip() if msisdn else '-'
                                        clean_puk = puk.group(1).strip() if puk else '-'
                                        clean_smdp = smdp.group(1).strip() if smdp else '-'
                                        clean_act = act_code.group(1).strip() if act_code else '-'
                                        
                                        extracted_info = (
                                            "Detail eSIM Kamu\n"
                                            f"MSISDN\t: {clean_msisdn}\n"
                                            f"Kode PUK\t: {clean_puk}\n"
                                            f"SM-DP+ Address\t: {clean_smdp}\n"
                                            f"Activation Code\t: {clean_act}\n\n"
                                            "CREATED : @forariey\n"
                                            "Donation : Dana : 082151916181"
                                        )
                                        return extracted_info, clean_msisdn, clean_puk, clean_smdp, clean_act
                except Exception as e:
                    logger.error(f"Error saat ekstrak detail email XL: {e}")
                await asyncio.sleep(2)
        return f"Email konfirmasi dari XL belum diterima / timeout, akun terdaftar: {self.email}", None, None, None, None

async def process_xl_esim(chat_id, status_callback):
    temp = MailTMBot()
    await temp.create_account()

    full_name = f"mhmdsari{''.join(random.choices(string.ascii_lowercase + string.digits, k=4))}xlstore"
    whatsapp = "08" + ''.join(random.choices(string.digits, k=9))
    
    screenshot_path = f"esim_{chat_id}.png"
    debug_path = f"debug_{chat_id}.png"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        page = await browser.new_page(viewport={"width": 1366, "height": 768})
        
        try:
            logger.info("Membuka halaman XL...")
            await status_callback("🌐 [LOG: 1/7] Membuka halaman XL eSIM Trial...")
            await page.goto("https://www.xl.co.id/esim-trial/claim", timeout=90000, wait_until="domcontentloaded")

            logger.info("Klik mulai...")
            await status_callback("🖱️ [LOG: 2/7] Klik tombol mulai...")
            try:
                await page.wait_for_selector("text=Mulai Isi Data", timeout=20000)
                await page.get_by_text("Mulai Isi Data").first.click()
            except Exception:
                await page.click("button:has-text('Mulai Isi Data')", timeout=5000)
            
            await asyncio.sleep(2)

            logger.info("Isi data...")
            await status_callback("📝 [LOG: 3/7] Mengisi data diri otomatis...")
            try:
                inputs = await page.locator("input").all()
                if len(inputs) >= 3:
                    await inputs[0].fill(full_name)
                    await inputs[1].fill(temp.email)
                    await inputs[2].fill(whatsapp)
                else:
                    raise Exception("Gagal mendeteksi input form")
            except Exception as e:
                logger.error(f"Error isi data: {e}")
                raise Exception("Error: Form input tidak ditemukan.")

            logger.info("Kirim OTP...")
            await status_callback("📤 [LOG: 4/7] Mengirim permintaan OTP...")
            try:
                await page.get_by_role("button", name="Lanjut").click(timeout=15000)
            except Exception:
                await page.click("button:has-text('Lanjut'), button:has-text('Kirim')")

            logger.info("Menunggu OTP...")
            await status_callback(f"⏳ [LOG: 5/7] Menunggu OTP masuk ke `{temp.email}`...")
            otp = await temp.fetch_otp(timeout=60)
            
            if not otp: 
                await page.screenshot(path=debug_path)
                raise Exception("Error: Waktu tunggu OTP habis (Timeout).")
            
            logger.info(f"Input OTP: {otp}")
            await status_callback(f"✅ [LOG: OTP OK] Kode: `{otp}`. Memasukkan ke sistem...")
            
            try:
                await page.locator("input").first.click()
            except Exception:
                pass
            
            await page.keyboard.type(otp, delay=150)

            logger.info("Konfirmasi OTP...")
            await status_callback("📤 [LOG: Konfirmasi OTP] Menekan tombol Lanjut...")
            await asyncio.sleep(1.5)
            try:
                await page.get_by_role("button", name="Lanjut").click(timeout=10000)
            except Exception:
                await page.click("button:has-text('Lanjut'), button:has-text('Konfirmasi')")

            logger.info("Pilih nomor...")
            await status_callback("📱 [LOG: 6/7] Menunggu dan memilih nomor eSIM...")
            
            try:
                await page.wait_for_selector('input[type="radio"], label, .number-card, text=/08/', timeout=30000)
            except Exception:
                logger.warning("Timeout menunggu elemen pilihan nomor, mencoba lanjut paksa via evaluate...")

            await asyncio.sleep(3) 
            
            await page.evaluate("""() => {
                const radios = Array.from(document.querySelectorAll('input[type="radio"]'));
                if (radios.length > 0) {
                    radios[0].checked = true;
                    radios[0].click();
                    radios[0].dispatchEvent(new Event('change', { bubbles: true }));
                    return;
                }
                const candidates = Array.from(document.querySelectorAll('div, label, span, button')).filter(el => {
                    const text = el.innerText ? el.innerText.trim() : '';
                    return text.startsWith('08') && text.length >= 10 && text.length <= 15 && el.children.length <= 2;
                });
                if (candidates.length > 0) {
                    candidates[0].click();
                }
            }""")

            logger.info("Lanjut ke QR...")
            await status_callback("📤 [LOG: 7/7] Menekan tombol Lanjut...")
            await asyncio.sleep(2)

            await page.evaluate("""() => {
                const btns = Array.from(document.querySelectorAll('button, div[role="button"]'));
                const target = btns.find(b => b.innerText && (b.innerText.toLowerCase().includes('lanjut') || b.innerText.toLowerCase().includes('konfirmasi') || b.innerText.toLowerCase().includes('pilih')));
                if (target) {
                    target.click();
                }
            }""")

            logger.info("Proses akhir QR...")
            await status_callback("⏳ Sedang memproses eSIM di server XL (Menunggu QR & Email)...")
            await asyncio.sleep(10) 
            
            await status_callback("✨ QR Code berhasil dimuat! Mengambil screenshot & membaca detail email...")
            await page.screenshot(path=screenshot_path, full_page=True)
            await browser.close()
            
            if os.path.exists(debug_path):
                os.remove(debug_path)
                
            info, ms, pk, sm, ac = await temp.fetch_xl_confirmation_email(timeout=60)
                
            return screenshot_path, info, ms, pk, sm, ac

        except Exception as e:
            logger.error(f"Error di proses utama: {e}")
            try:
                await page.screenshot(path=debug_path)
                await browser.close()
            except Exception:
                pass
            return debug_path, str(e), None, None, None, None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    
    user = update.effective_user
    username = f"@{user.username}" if user.username else user.first_name
    chat_id = update.effective_chat.id
    msg = await update.message.reply_text("🚀 Bot Telegram aktif! Memproses klaim eSIM...")
    
    async def update_status(text):
        try:
            await context.bot.edit_message_text(text=text, chat_id=chat_id, message_id=msg.message_id, parse_mode="Markdown")
        except Exception:
            pass

    path, info, ms, pk, sm, ac = await process_xl_esim(chat_id, update_status)
    
    if path and "esim_" in path and os.path.exists(path):
        caption = info
        await context.bot.send_photo(
            chat_id=chat_id, 
            photo=open(path, 'rb'), 
            caption=caption, 
            parse_mode="Markdown"
        )
        
        if ms:
            grup_text = (
                f"Halo {username}\n\nEsim berhasil dibuat\n\nDetail eSIM Kamu\n"
                f"MSISDN : {sensor_text(ms)}\n"
                f"Kode PUK : {sensor_text(pk)}\n"
                f"SM-DP+ Address : {sm}\n"
                f"Activation Code : {sensor_text(ac)}\n\n"
                f"Dibuat oleh: {username}\n"
                "CREATED : @forariey\n"
                "Donation : Dana : 082151916181"
            )
            await context.bot.send_message(chat_id=GROUP_ID, text=grup_text)
            
        try:
            os.remove(path)
        except Exception:
            pass
    else:
        if path and os.path.exists(path):
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=open(path, 'rb'),
                caption=f"❌ **Gagal Memproses:**\n`{info}`",
                parse_mode="Markdown"
            )
            os.remove(path)
        else:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ **Gagal Memproses:**\n`{info}`", parse_mode="Markdown")

async def loop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    
    user = update.effective_user
    username = f"@{user.username}" if user.username else user.first_name
    chat_id = update.effective_chat.id

    if chat_id in active_loops:
        await update.message.reply_text("⚠️ Looping pembuatan eSIM sudah berjalan di chat ini.")
        return

    active_loops.add(chat_id)
    success_count = 0
    target_success = 50

    await update.message.reply_text(f"🔄 **Looping eSIM Dimulai!**\nTarget: {target_success} kali berhasil membuat eSIM.\nKirim /stop untuk menghentikan.")

    while chat_id in active_loops and success_count < target_success:
        msg = await update.message.reply_text(f"🚀 [Loop ke-{success_count + 1}] Memproses klaim eSIM...")

        async def update_status(text):
            try:
                await context.bot.edit_message_text(text=text, chat_id=chat_id, message_id=msg.message_id, parse_mode="Markdown")
            except Exception:
                pass

        path, info, ms, pk, sm, ac = await process_xl_esim(chat_id, update_status)

        if path and "esim_" in path and os.path.exists(path) and ms:
            success_count += 1
            caption = info
            await context.bot.send_photo(
                chat_id=chat_id, 
                photo=open(path, 'rb'), 
                caption=f"✅ **[Berhasil ke-{success_count}/{target_success}]**\n\n{caption}", 
                parse_mode="Markdown"
            )
            
            grup_text = (
                f"Halo {username}\n\nEsim berhasil dibuat (Loop ke-{success_count})\n\nDetail eSIM Kamu\n"
                f"MSISDN : {sensor_text(ms)}\n"
                f"Kode PUK : {sensor_text(pk)}\n"
                f"SM-DP+ Address : {sm}\n"
                f"Activation Code : {sensor_text(ac)}\n\n"
                f"Dibuat oleh: {username}\n"
                "CREATED : @forariey\n"
                "Donation : Dana : 082151916181"
            )
            await context.bot.send_message(chat_id=GROUP_ID, text=grup_text)
            
            try:
                os.remove(path)
            except Exception:
                pass
        else:
            if path and os.path.exists(path):
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=open(path, 'rb'),
                    caption=f"❌ **Gagal di Looping (Akan dilanjut):**\n`{info}`",
                    parse_mode="Markdown"
                )
                os.remove(path)
            else:
                await context.bot.send_message(chat_id=chat_id, text=f"❌ **Gagal di Looping (Akan dilanjut):**\n`{info}`", parse_mode="Markdown")
        
        if chat_id in active_loops and success_count < target_success:
            await asyncio.sleep(5)

    if chat_id in active_loops:
        active_loops.remove(chat_id)
    
    await update.message.reply_text(f"🏁 **Looping Selesai!** Berhasil membuat {success_count} eSIM.")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in active_loops:
        active_loops.remove(chat_id)
        await update.message.reply_text("🛑 Looping berhasil dihentikan!")
    else:
        await update.message.reply_text("⚠️ Tidak ada looping yang sedang aktif.")

# Endpoint Webhook FastAPI yang aman dari trigger palsu/ping kosong
@app.post("/")
async def webhook(request: Request):
    global telegram_app
    try:
        data = await request.json()
        if "message" in data and "text" in data["message"]:
            update = Update.de_json(data, telegram_app.bot)
            if update and update.message:
                await telegram_app.process_update(update)
    except Exception as e:
        logger.error(f"Error pada webhook: {e}")
    return {"status": "ok"}

@app.get("/")
async def health_check():
    return Response(content="Bot is running smoothly!", status_code=200)

@app.on_event("startup")
async def startup_event():
    global telegram_app
    telegram_app = Application.builder().token(TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("loop", loop_command))
    telegram_app.add_handler(CommandHandler("stop", stop_command))
    await telegram_app.initialize()
    await telegram_app.start()
    logger.info("Bot Telegram webhook siap menerima koneksi di Railway...")
