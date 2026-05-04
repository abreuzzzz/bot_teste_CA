import asyncio, logging, os, signal, threading, json
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
)
from config import TELEGRAM_TOKEN, TELEGRAM_ALLOWED_CHAT_ID
from gemini_client import extrair_lancamento, extrair_de_imagem, responder_consulta
from fluxo_lancamento import iniciar_selecao, callback_selecao, receber_texto_livre
from contaazul_client import criar_lancamento, _post, _rateio, _sanitizar, BASE
from consulta_financeira import resumo_mes, pendentes, atrasados
from catalogo import invalidar_cache, contas_financeiras, categorias_receita, categorias_despesa, centros_custo
from scheduler import iniciar

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ─── Autorização ──────────────────────────────────────────────────────────────

def _ok(update: Update) -> bool:
    return (
        update.effective_user is not None
        and update.effective_chat is not None
        and update.effective_chat.id == TELEGRAM_ALLOWED_CHAT_ID
    )

# ─── Comandos ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    await update.message.reply_text(
        "👋 *Assistente Financeiro IA*\n\n"
        "Pode falar naturalmente! Exemplos:\n"
        "• _\"Receber R$ 500 de João vence 20/05\"_\n"
        "• _\"Pagar conta de luz R$ 220 vence 15/05\"_\n"
        "• _\"Quanto gastei este mês?\"_\n\n"
        "📌 *Comandos disponíveis:*\n"
        "/pendentes — contas a vencer\n"
        "/atrasados — contas em atraso\n"
        "/relatorio — resumo do dia\n"
        "/catalogo  — ver categorias e contas\n"
        "/manual    — lançamento guiado",
        parse_mode="Markdown",
    )


async def cmd_pendentes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    itens = pendentes(dias=30)
    if not itens:
        await update.message.reply_text("✅ Nenhuma conta pendente nos próximos 30 dias.")
        return
    linhas = "\n".join(
        f"{'📥' if i['tipo'] == 'RECEBER' else '📤'} "
        f"{i.get('descricao', '?')[:35]} — "
        f"R$ {i.get('valor', 0):.2f} ({i.get('data_vencimento', '')})"
        for i in itens[:20]
    )
    await update.message.reply_text(
        f"📅 *Pendentes (30 dias):*\n\n{linhas}",
        parse_mode="Markdown",
    )


async def cmd_atrasados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    itens = atrasados()
    if not itens:
        await update.message.reply_text("✅ Nenhuma conta atrasada!")
        return
    linhas = "\n".join(
        f"⚠️ {i.get('descricao', '?')[:35]} — "
        f"R$ {i.get('valor', 0):.2f} ({i.get('data_vencimento', '')})"
        for i in itens[:20]
    )
    await update.message.reply_text(
        f"🚨 *Atrasados:*\n\n{linhas}",
        parse_mode="Markdown",
    )


async def cmd_relatorio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    from scheduler import _relatorio_diario
    await _relatorio_diario(context.application, update.message.chat_id)


async def cmd_catalogo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    invalidar_cache()
    await update.message.reply_text("🔄 Atualizando catálogo...")

    contas  = contas_financeiras()
    cat_rec = categorias_receita()
    cat_pag = categorias_despesa()
    centros = centros_custo()

    def _fmt(lista):
        return "\n".join(f"  • {i['nome']}" for i in lista) or "  _(nenhum)_"

    await update.message.reply_text(
        f"📋 *Catálogo Conta Azul*\n\n"
        f"🏦 *Contas ({len(contas)}):*\n{_fmt(contas)}\n\n"
        f"📥 *Categorias Receita ({len(cat_rec)}):*\n{_fmt(cat_rec)}\n\n"
        f"📤 *Categorias Despesa ({len(cat_pag)}):*\n{_fmt(cat_pag)}\n\n"
        f"🏷️ *Centros de Custo ({len(centros)}):*\n{_fmt(centros)}",
        parse_mode="Markdown",
    )


async def cmd_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    context.user_data["manual"] = {"etapa": "titulo"}
    await update.message.reply_text(
        "📝 *Lançamento manual*\n\nQual o *título* / descrição?",
        parse_mode="Markdown",
    )

# ─── Callbacks de lançamento ──────────────────────────────────────────────────

async def callback_lancar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    partes      = query.data.split(":")
    acao        = partes[1]
    chat_id     = int(partes[2])
    dados       = context.bot_data.pop(f"lancamento_{chat_id}", None)

    if acao == "nao" or not dados:
        await query.edit_message_text("❌ Lançamento cancelado.")
        return

    await query.edit_message_text("⏳ Lançando no Conta Azul...")
    resultado = criar_lancamento(dados)

    if resultado["ok"]:
        tipo_emoji = "📥" if dados["tipo"] == "RECEBER" else "📤"
        await query.edit_message_text(
            f"✅ {tipo_emoji} *Lançamento criado com sucesso!*\n"
            f"ID: `{resultado.get('id', '?')}`",
            parse_mode="Markdown",
        )

    elif resultado.get("erro") == "DUPLICATA":
        context.bot_data[f"lancamento_{chat_id}"] = dados
        await query.edit_message_text(
            f"⚠️ *Possível duplicata detectada!*\n"
            f"{resultado['mensagem']}\n\n"
            f"Deseja lançar mesmo assim?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Forçar mesmo assim", callback_data=f"forcar:{chat_id}"),
                InlineKeyboardButton("❌ Cancelar",           callback_data=f"lancar:nao:{chat_id}"),
            ]]),
        )

    else:
        await query.edit_message_text(
            f"❌ Erro: {resultado.get('erro', 'Desconhecido')}"
        )


async def callback_forcar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()

    chat_id = int(query.data.split(":")[1])
    dados   = context.bot_data.pop(f"lancamento_{chat_id}", None)

    if not dados:
        await query.edit_message_text("⚠️ Sessão expirada.")
        return

    await query.edit_message_text("⏳ Lançando (forçado)...")

    valor    = float(dados["valor"])
    parcelas = int(dados.get("parcelas", 1))
    venc     = dados["vencimento"]
    titulo   = _sanitizar(dados["titulo"])
    valor_p  = round(valor / parcelas, 2)
    venc_dt  = date.fromisoformat(venc)

    parcelas_body = [
        {
            "descricao":        _sanitizar(f"{titulo} ({n + 1}/{parcelas})"),
            "data_vencimento":  str(venc_dt),
            "nota":             "Lançamento forçado",
            "conta_financeira": dados.get("conta_id"),
            "detalhe_valor":    {"valor_bruto": valor_p, "valor_liquido": valor_p},
        }
        for n in range(parcelas)
    ]

    body = {
        "data_competencia":   venc,
        "valor":              valor,
        "descricao":          titulo,
        "observacao":         "Lançamento forçado via bot",
        "conta_financeira":   dados.get("conta_id"),
        "rateio":             _rateio(dados.get("categoria_id"), valor, dados.get("centro_id")),
        "condicao_pagamento": {"parcelas": parcelas_body},
    }

    endpoint = "contas-a-receber" if dados["tipo"] == "RECEBER" else "contas-a-pagar"
    r = _post(f"{BASE}/{endpoint}", body)
    await query.edit_message_text(
        f"✅ Lançado! ID: `{r.get('id', '?')}`",
        parse_mode="Markdown",
    )

# ─── Handler de mensagens de texto ────────────────────────────────────────────

async def handle_mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return

    # 1. Fluxo de seleção de conta/categoria/centro
    if await receber_texto_livre(update, context):
        return

    # 2. Fluxo manual guiado
    manual = context.user_data.get("manual")
    if manual:
        await _handle_manual(update, context, manual)
        return

    # 3. IA analisa o texto
    texto = update.message.text.strip()
    await update.message.reply_text("🤔 Analisando...")

    dados = extrair_lancamento(texto)
    acao  = dados.get("acao", "INDEFINIDO")

    if acao in ("RECEBER", "PAGAR"):
        await iniciar_selecao(update, context, {
            "tipo":        acao,
            "titulo":      dados.get("titulo", texto[:50]),
            "valor":       dados.get("valor", 0),
            "vencimento":  dados.get("vencimento", str(date.today())),
            "parcelas":    dados.get("parcelas", 1),
            "termo_extra": dados.get("termo_extra", ""),
        })

    elif acao == "BAIXA":
        await update.message.reply_text(
            "🔎 Para dar baixa, use /atrasados para ver os lançamentos pendentes "
            "e me diga o nome exato para eu localizar."
        )

    elif acao == "CONSULTA":
        resumo = resumo_mes()
        ctx    = json.dumps(
            {k: v for k, v in resumo.items() if k not in ("contas_receber", "contas_pagar")},
            ensure_ascii=False,
        )
        resp = responder_consulta(texto, ctx)
        await update.message.reply_text(resp)

    else:
        msg = dados.get("mensagem", "")
        await update.message.reply_text(
            msg or "Não entendi. Tente descrever o lançamento ou use /manual."
        )

# ─── Handler de documentos e fotos ───────────────────────────────────────────

async def handle_documento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    await update.message.reply_text("📄 Lendo documento...")
    doc       = update.message.document
    file      = await context.bot.get_file(doc.file_id)
    img_bytes = await file.download_as_bytearray()
    mime      = doc.mime_type or "application/octet-stream"
    dados     = extrair_de_imagem(bytes(img_bytes), mime)
    acao      = dados.get("acao", "INDEFINIDO")

    if acao in ("RECEBER", "PAGAR"):
        await iniciar_selecao(update, context, {
            "tipo":        acao,
            "titulo":      dados.get("titulo", "Documento"),
            "valor":       dados.get("valor", 0),
            "vencimento":  dados.get("vencimento", str(date.today())),
            "parcelas":    dados.get("parcelas", 1),
            "termo_extra": dados.get("termo_extra", ""),
        })
    else:
        await update.message.reply_text(
            dados.get("mensagem", "Não consegui extrair os dados do documento.")
        )


async def handle_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    await update.message.reply_text("📷 Lendo imagem...")
    foto  = update.message.photo[-1]
    file  = await context.bot.get_file(foto.file_id)
    dados = extrair_de_imagem(await file.download_as_bytearray(), "image/jpeg")
    acao  = dados.get("acao", "INDEFINIDO")

    if acao in ("RECEBER", "PAGAR"):
        await iniciar_selecao(update, context, {
            "tipo":        acao,
            "titulo":      dados.get("titulo", "Foto"),
            "valor":       dados.get("valor", 0),
            "vencimento":  dados.get("vencimento", str(date.today())),
            "parcelas":    dados.get("parcelas", 1),
            "termo_extra": dados.get("termo_extra", ""),
        })
    else:
        await update.message.reply_text(
            dados.get("mensagem", "Não consegui extrair os dados da imagem.")
        )

# ─── Fluxo manual guiado ──────────────────────────────────────────────────────

async def _handle_manual(update: Update, context: ContextTypes.DEFAULT_TYPE, manual: dict):
    texto = update.message.text.strip()
    etapa = manual["etapa"]

    if etapa == "titulo":
        manual["titulo"] = texto
        manual["etapa"]  = "tipo"
        await update.message.reply_text(
            "É uma conta a *receber* ou a *pagar*?\nDigite: receber ou pagar",
            parse_mode="Markdown",
        )

    elif etapa == "tipo":
        t = texto.upper()
        if "REC" in t:
            manual["tipo"] = "RECEBER"
        elif "PAG" in t:
            manual["tipo"] = "PAGAR"
        else:
            await update.message.reply_text("Digite *receber* ou *pagar*.", parse_mode="Markdown")
            return
        manual["etapa"] = "valor"
        await update.message.reply_text("💰 Qual o *valor*? (ex: 250.00)", parse_mode="Markdown")

    elif etapa == "valor":
        try:
            manual["valor"] = float(texto.replace(",", ".").replace("R$", "").strip())
        except ValueError:
            await update.message.reply_text("Valor inválido. Tente novamente (ex: 250.00).")
            return
        manual["etapa"] = "vencimento"
        await update.message.reply_text(
            "📅 Qual a *data de vencimento*? (ex: 15/05/2026)",
            parse_mode="Markdown",
        )

    elif etapa == "vencimento":
        from datetime import datetime
        for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(texto, fmt)
                manual["vencimento"] = dt.strftime("%Y-%m-%d")
                break
            except ValueError:
                continue
        else:
            await update.message.reply_text("Data inválida. Use o formato DD/MM/AAAA.")
            return
        manual["etapa"] = "parcelas"
        await update.message.reply_text(
            "🔢 Quantas *parcelas*? (1 para à vista)",
            parse_mode="Markdown",
        )

    elif etapa == "parcelas":
        try:
            manual["parcelas"] = int(texto)
        except ValueError:
            await update.message.reply_text("Digite um número inteiro.")
            return
        context.user_data.pop("manual")
        await iniciar_selecao(update, context, {
            "tipo":        manual["tipo"],
            "titulo":      manual["titulo"],
            "valor":       manual["valor"],
            "vencimento":  manual["vencimento"],
            "parcelas":    manual["parcelas"],
            "termo_extra": manual["titulo"],
        })

# ─── Auto-shutdown para GitHub Actions ───────────────────────────────────────

def _agendar_shutdown(app: Application):
    """
    Encerra o bot após 290 min (4h50).
    O cron do Actions reinicia a cada 5h — isso garante que o step
    de salvar tokens sempre execute antes do timeout do job.
    Só ativa quando rodando dentro do GitHub Actions.
    """
    if not os.environ.get("GITHUB_ACTIONS"):
        return

    MINUTOS = 290

    def _timer():
        import time
        print(f"[SHUTDOWN] Auto-shutdown em {MINUTOS} min (GitHub Actions mode).")
        time.sleep(MINUTOS * 60)
        print("[SHUTDOWN] Encerrando bot para reinício automático pelo cron...")
        os.kill(os.getpid(), signal.SIGTERM)

    t = threading.Thread(target=_timer, daemon=True)
    t.start()

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Comandos
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("pendentes", cmd_pendentes))
    app.add_handler(CommandHandler("atrasados", cmd_atrasados))
    app.add_handler(CommandHandler("relatorio", cmd_relatorio))
    app.add_handler(CommandHandler("catalogo",  cmd_catalogo))
    app.add_handler(CommandHandler("manual",    cmd_manual))

    # Callbacks de botões inline
    app.add_handler(CallbackQueryHandler(callback_selecao, pattern="^sel:"))
    app.add_handler(CallbackQueryHandler(callback_lancar,  pattern="^lancar:"))
    app.add_handler(CallbackQueryHandler(callback_forcar,  pattern="^forcar:"))

    # Mensagens
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_mensagem))
    app.add_handler(MessageHandler(filters.Document.ALL,            handle_documento))
    app.add_handler(MessageHandler(filters.PHOTO,                   handle_foto))

    # Scheduler de relatório diário
    iniciar(app, TELEGRAM_ALLOWED_CHAT_ID)

    # Auto-shutdown para GitHub Actions (só ativa se GITHUB_ACTIONS=true)
    _agendar_shutdown(app)

    print("🤖 Bot iniciado!")
    print(f"   GitHub Actions mode: {'SIM' if os.environ.get('GITHUB_ACTIONS') else 'NÃO'}")

    # stop_signals=None necessário para funcionar no ambiente do Actions
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        stop_signals=None if os.environ.get("GITHUB_ACTIONS") else None,
    )


if __name__ == "__main__":
    main()
