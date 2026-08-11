import os
import re
import sqlite3
import asyncio
import logging
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHECK_MINUTES = int(os.environ.get("CHECK_MINUTES", "30"))
DB = "precos.db"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

def db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        url TEXT NOT NULL,
        title TEXT,
        price REAL NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    con.commit()
    return con

def brl(value):
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def get_price(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Android 13; Mobile) AppleWebKit/537.36 Chrome/126 Safari/537.36",
        "Accept-Language": "pt-BR,pt;q=0.9"
    }
    r = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    title = None
    for selector in [
        ('meta', {'property': 'og:title'}),
        ('meta', {'name': 'twitter:title'})
    ]:
        tag = soup.find(*selector)
        if tag and tag.get("content"):
            title = tag["content"].strip()
            break
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)

    # Prefer structured price data when the store exposes it.
    candidates = []
    for tag in soup.find_all("meta"):
        for attr in ("property", "name", "itemprop"):
            key = (tag.get(attr) or "").lower()
            if key in ("product:price:amount", "og:price:amount", "price", "lowprice"):
                val = tag.get("content")
                if val:
                    candidates.append(val)

    for tag in soup.find_all(attrs={"itemprop": "price"}):
        if tag.get("content"):
            candidates.append(tag["content"])
        elif tag.get_text(strip=True):
            candidates.append(tag.get_text(" ", strip=True))

    # JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        text = script.string or script.get_text()
        candidates += re.findall(r'"price"\s*:\s*"?(?:R\$\s*)?([0-9][0-9\.,]*)', text, re.I)

    def parse_money(x):
        x = re.sub(r"[^\d,\.]", "", str(x))
        if not x:
            return None
        if "," in x:
            x = x.replace(".", "").replace(",", ".")
        else:
            # Treat a number with one dot and 2 decimals as decimal.
            if x.count(".") > 1:
                x = x.replace(".", "")
        try:
            return float(x)
        except ValueError:
            return None

    prices = [parse_money(x) for x in candidates]
    prices = [p for p in prices if p and p > 0]

    if not prices:
        # Fallback: look for common Brazilian currency strings.
        text = soup.get_text(" ", strip=True)
        matches = re.findall(r"R\$\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})", text)
        prices = [parse_money(x) for x in matches]

    if not prices:
        raise ValueError("Não consegui encontrar o preço nessa página.")

    return title or "Produto", min(prices)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Oi! Eu sou o Monitor de Preços da Heidy.\n\n"
        "Me envie:\n"
        "/monitorar LINK\n\n"
        "Comandos:\n"
        "/lista - produtos monitorados\n"
        "/quedas - últimas quedas\n"
        "/remover ID - parar um monitoramento\n"
        "/ajuda - ajuda"
    )

async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def monitorar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Cole o link depois de /monitorar.\nExemplo: /monitorar https://...")
        return
    url = context.args[0].strip()
    if not url.startswith(("http://", "https://")):
        await update.message.reply_text("Preciso de um link começando com https://")
        return

    await update.message.reply_text("🔎 Vou consultar o preço agora...")
    try:
        title, price = await asyncio.to_thread(get_price, url)
    except Exception as e:
        await update.message.reply_text(
            "❌ Não consegui ler o preço dessa página.\n"
            "Vamos começar testando com links de produtos do Mercado Livre."
        )
        log.exception(e)
        return

    con = db()
    con.execute(
        "INSERT INTO products (chat_id,url,title,price) VALUES (?,?,?,?)",
        (update.effective_chat.id, url, title[:300], price)
    )
    con.commit()
    pid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
    con.close()

    await update.message.reply_text(
        f"✅ Produto monitorado!\n\n"
        f"🆔 ID: {pid}\n"
        f"🛍️ {title[:180]}\n"
        f"💰 Preço inicial: {brl(price)}\n"
        f"⏱️ Verificação: a cada {CHECK_MINUTES} minutos."
    )

async def lista(update: Update, context: ContextTypes.DEFAULT_TYPE):
    con = db()
    rows = con.execute(
        "SELECT id,title,price,url FROM products WHERE chat_id=? ORDER BY id DESC",
        (update.effective_chat.id,)
    ).fetchall()
    con.close()
    if not rows:
        await update.message.reply_text("Você ainda não tem produtos monitorados.")
        return
    msg = "📋 *Produtos monitorados*\n\n"
    for pid, title, price, url in rows:
        msg += f"🆔 {pid} — {title[:70]}\n💰 {brl(price)}\n{url}\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def remover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Use: /remover ID\nExemplo: /remover 3")
        return
    pid = int(context.args[0])
    con = db()
    cur = con.execute(
        "DELETE FROM products WHERE id=? AND chat_id=?",
        (pid, update.effective_chat.id)
    )
    con.commit()
    con.close()
    await update.message.reply_text("🗑️ Monitoramento removido." if cur.rowcount else "Não encontrei esse ID.")

async def check_prices(app):
    while True:
        try:
            con = db()
            rows = con.execute("SELECT id,chat_id,url,title,price FROM products").fetchall()
            con.close()

            for pid, chat_id, url, old_title, old_price in rows:
                try:
                    title, new_price = await asyncio.to_thread(get_price, url)
                    if new_price < old_price - 0.01:
                        drop = (old_price - new_price) / old_price * 100
                        msg = (
                            "🚨 *PREÇO BAIXOU!*\n\n"
                            f"🛍️ {title[:180]}\n"
                            f"~~{brl(old_price)}~~ → *{brl(new_price)}*\n"
                            f"📉 Queda de *{drop:.1f}%*\n\n"
                            f"🔗 {url}"
                        )
                        await app.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
                        con = db()
                        con.execute("UPDATE products SET title=?, price=? WHERE id=?",
                                    (title[:300], new_price, pid))
                        con.commit()
                        con.close()
                except Exception as e:
                    log.warning("Falha no produto %s: %s", pid, e)

        except Exception:
            log.exception("Erro no ciclo de monitoramento")

        await asyncio.sleep(CHECK_MINUTES * 60)

async def post_init(app):
    asyncio.create_task(check_prices(app))

def main():
    db().close()
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ajuda", ajuda))
    app.add_handler(CommandHandler("monitorar", monitorar))
    app.add_handler(CommandHandler("lista", lista))
    app.add_handler(CommandHandler("remover", remover))
    app.run_polling()

if __name__ == "__main__":
    main()
