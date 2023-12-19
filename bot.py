import imaplib
import email
import smtplib
from email import encoders
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.header import decode_header
from os import getenv
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
load_dotenv()

class UserSession:
    username: str = ""
    imap: imaplib.IMAP4_SSL = None
    smtp: smtplib.SMTP = None
    skip: int = 0
    attachment = None

    def store_attachment(self, filename, data):
        part = MIMEBase("application", "octet-stream")
        part.set_payload(data)
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f"attachment; filename= {filename}",
        )
        self.attachment = part
    def get_attachment(self):
        e = self.attachment
        self.attachment = None
        return e

    def __init__(self, username, password, imap = "imap.gmail.com", smtp = "smtp.gmail.com"):
        self.username = username
        self.imap = imaplib.IMAP4_SSL(imap)
        self.imap.login(username, password)
        self.imap.select("inbox")
        self.smtp = smtplib.SMTP(smtp, 587)
        self.smtp.starttls()
        self.smtp.login(username, password)
    def get_mail(self):
        status, messages = self.imap.search(None, "UNSEEN")
        #skip = self.skip
        #self.skip += 1
        for num in messages[0].split():
            #if skip > 0:
            #    skip -= 1
            #    continue
            status, data = self.imap.fetch(num, "(RFC822)")
            raw_email = data[0][1]
            msg = email.message_from_bytes(raw_email)
            subject = decode_header(msg["Subject"])[0][0]
            sender = decode_header(msg["From"])[0][0]
            if isinstance(subject, bytes):
                subject = subject.decode()
            if isinstance(sender, bytes):
                sender = sender.decode()
            bbody = ""
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition"))
                    if content_type == "text/plain" and "attachment" not in content_disposition:
                        body = part.get_payload(decode=True)
                        if not body is None: bbody = body.decode()
                    else:
                        body = msg.get_payload(decode=True)
                        if not body is None: bbody = body.decode()
            return (sender, subject, bbody)

USERS_SESSIONS: dict[int, UserSession] = dict()

async def hello(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f'Привет, {update.effective_user.first_name}.\n'
                                    + 'Напиши /login <username> <password> чтобы войти в google account.\n'
                                    + 'Если тебе нужен другой сервер, напиши /login <imap server> <smtp server> <username> <password>\n')

async def authorize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.split()[1:]
    uid = update.effective_user.id
    try:
        if len(msg) == 2:
            USERS_SESSIONS[uid] = UserSession(msg[0], msg[1])
        elif len(msg) == 4:
            USERS_SESSIONS[uid] = UserSession(msg[0], msg[1], msg[2], msg[3])
        else:
            await update.message.reply_text("Не удалось понять, что вы имели ввиду. Помощь: /start")
            return
    except Exception as e:
        USERS_SESSIONS[uid] = None
        m = e.message if hasattr(e, 'message') else e
        await update.message.reply_text(f"Не удалось подключиться: {m}")
    else:
        await update.message.reply_text("Успешно! Теперь вы можете читать сообщения: /read")

async def get_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in USERS_SESSIONS or USERS_SESSIONS[uid] is None:
        await update.message.reply_text("Для начала авторизуйтесь: /start")
        return
    try:
        sender, subject, body = USERS_SESSIONS[uid].get_mail()
        body = body[:200]
        await update.message.reply_text(f"Отправитель: {sender}\nТема: {subject}\n\n{body}")
    except Exception as e:
        USERS_SESSIONS[uid] = None
        m = e.message if hasattr(e, 'message') else e
        await update.message.reply_text(f"Не удалось подключиться: {m}")
async def send_guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Чтобы отправить сообщение напишите /sndd <email>\n<тема сообщения, с новой строки в одну строчку>\n<пустая строка>\n<текст сообщения, можно в несколько строк...>\n\nДля прикрепления файлов воспользуйтесь /attach вместе с файлом, который хотите прикрепить")
async def send_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.splitlines(keepends=False)
    uid = update.effective_user.id
    if uid not in USERS_SESSIONS or USERS_SESSIONS[uid] is None:
        await update.message.reply_text("Для начала авторизуйтесь: /start")
        return
    if len(msg) < 4 or msg[2].strip() != "" or len(email := msg[0].split()) != 2:
        await update.message.reply_text("Неправильный синтаксис письма. Попробуйте /send")
        return
    email = email[1]
    subject = msg[1]
    body = "\n".join(msg[3:])
    message = MIMEMultipart()
    message["From"] = USERS_SESSIONS[uid].username
    message["To"] = email
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))
    part = USERS_SESSIONS[uid].get_attachment()
    if part is not None:
        message.attach(part)
    try:
        USERS_SESSIONS[uid].smtp.send_message(message)
        await update.message.reply_text(f"Отправлено на {email}")
    except Exception as e:
        m = e.message if hasattr(e, 'message') else e
        await update.message.reply_text(f"Не удалось отправить: {m}")
async def attach_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in USERS_SESSIONS or USERS_SESSIONS[uid] is None:
        await update.message.reply_text("Для начала авторизуйтесь: /start")
        return
    if update.message.document:
        file = update.message.document
        file_id = file.file_id
        filename = file.file_name
        new_file = await context.bot.get_file(file_id)
        data = await new_file.download_as_bytearray()
        USERS_SESSIONS[uid].store_attachment(filename, data)
        await update.message.reply_text("Файл успешно сохранён и будет приложен к следующему отправленному письму.\n"
                                        + "\nЧтобы удалить файл, напишите /attach")
    else:
        USERS_SESSIONS[uid].get_attachment()
        await update.message.reply_text("Файл успешно удалён")


app = ApplicationBuilder().token(getenv("TOKEN")).build()

app.add_handler(CommandHandler("start", hello))
app.add_handler(CommandHandler("login", authorize))
app.add_handler(CommandHandler("read", get_message))
app.add_handler(CommandHandler("send", send_guide))
app.add_handler(CommandHandler("sndd", send_message))
app.add_handler(CommandHandler("attach", attach_file))
app.add_handler(MessageHandler(filters.ATTACHMENT, attach_file))

app.run_polling()

