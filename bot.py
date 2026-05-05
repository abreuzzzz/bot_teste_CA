import asyncio, logging, os, signal, threading, json, io, traceback
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
)
from config import TELEGRAM_TOKEN, TELEGRAM_ALLOWED_CHAT_IDS, TELEGRAM_ALLOWED_CHAT_ID
from gemini_client import (
    extrair_lancamento, extrair_de_imagem, responder_consulta,
    extrair_de_audio,
)
from fluxo_lancamento import (
    iniciar_selecao, callback_selecao, receber_texto_livre,
    callback_editar, limpar_estado,
)
from contaazul_client import criar_lancamento
from consulta_financeira import resumo_mes, pendentes, atrasados, _valor
from catalogo import invalidar_cache, contas_financeiras, categorias_receita, categorias_despesa, centros_custo
from scheduler import iniciar
from baixa_flow import iniciar_baixa, callback_baixa
import graficos, export, busca, orcamento

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ─── Autorização ──────────────────────────────────────────────────────────────

def _ok(update: Update) -> bool:
    return (
        update.effective_user is not None
        and update.effective_chat is not None
        and update.effective_chat.id in TELEGRAM_ALLOWED_CHAT_IDS
    )

def _user_key(update: Update) -> int:
    """Chave única por usuário para evitar colisão em grupos."""
    return update.effective_user.id

# ─── Error Handler ────────────────────────────────────────────────────────────

async def handle_erro(update: object, context: ContextTypes.DEFAULT_TYPE):
    tb = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    logging.error(f"[ERRO] Update causou exceção:\n{tb}")
    if isinstance(update, Update) and update.effective_message:
        erro_curto = str(context.error)[:200]
        await update.effective_message.reply_text(
            f"❌ *Erro interno:*\n`{erro_curto}`\n\n_Tente novamente ou contate o administrador._",
            parse_mode="Markdown",
        )

# ─── Comandos ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    await update.message.reply_text(
        "👋 *Assistente Financeiro IA*\n\n"
        "Pode falar (texto, áudio, foto ou PDF). Exemplos:\n"
        '• _"Receber R$ 500 de João vence 20/05"_\n'
        '• _"Paguei o aluguel"_  → dá baixa\n'
        '• _"Gráfico de despesas do mês"_\n'
        '• _"Quanto paguei pra fornecedor X em 2026?"_\n'
        '• _"Definir orçamento mercado 800"_\n\n'
        "📌 *Comandos:*\n"
        "/pendentes  — contas a vencer\n"
        "/atrasados  — contas em atraso\n"
        "/relatorio  — resumo do dia\n"
        "/grafico    — visualizações\n"
        "/orcamento  — orçamentos por categoria\n"
        "/buscar     — busca livre\n"
        "/export     — exportar planilha\n"
        "/baixa      — dar baixa em parcela\n"
        "/catalogo   — categorias e contas\n"
        "/manual     — lançamento guiado",
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
        f"R$ {_valor(i):.2f} ({i.get('data_vencimento', '')})"
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
        f"R$ {_valor(i):.2f} ({i.get('data_vencimento', '')})"
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


# ─── Novos comandos ──────────────────────────────────────────────────────────

async def cmd_grafico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    botoes = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Receita vs Despesa (6 meses)", callback_data="graf:meses")],
        [InlineKeyboardButton("📤 Despesas por categoria",       callback_data="graf:cat_pag")],
        [InlineKeyboardButton("📥 Receitas por categoria",       callback_data="graf:cat_rec")],
        [InlineKeyboardButton("💸 Fluxo de caixa (30 dias)",     callback_data="graf:fluxo")],
    ])
    await update.message.reply_text("📈 Escolha o gráfico:", reply_markup=botoes)


async def callback_grafico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tipo = query.data.split(":")[1]
    await query.edit_message_text("⏳ Gerando gráfico...")
    try:
        if tipo == "meses":
            png = graficos.grafico_meses(6)
        elif tipo == "cat_pag":
            png = graficos.grafico_categorias("PAGAR")
        elif tipo == "cat_rec":
            png = graficos.grafico_categorias("RECEBER")
        else:
            png = graficos.grafico_fluxo_caixa(30)
        await context.bot.send_photo(chat_id=query.message.chat_id, photo=io.BytesIO(png))
    except Exception as e:
        await query.edit_message_text(f"❌ Erro ao gerar: {e}")


async def cmd_orcamento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    args = context.args or []
    if len(args) >= 2:
        try:
            limite    = float(args[-1].replace(",", ".").replace("R$", "").strip())
            categoria = " ".join(args[:-1])
            orcamento.definir(categoria, limite)
            await update.message.reply_text(f"✅ Orçamento '{categoria}' = R$ {limite:.2f}")
            return
        except ValueError:
            await update.message.reply_text("Uso: /orcamento <categoria> <valor>")
            return

    if len(args) == 1 and args[0].lower() in ("rm", "remover", "del"):
        await update.message.reply_text("Use: /orcamento_remover <categoria>")
        return

    await _mostrar_orcamento(update.message)


async def cmd_orcamento_remover(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: /orcamento_remover <categoria>")
        return
    cat = " ".join(context.args)
    if orcamento.remover(cat):
        await update.message.reply_text(f"🗑️ Removido: {cat}")
    else:
        await update.message.reply_text(f"❌ Não encontrei: {cat}")


async def _mostrar_orcamento(message):
    status = orcamento.status_atual()
    if not status:
        await message.reply_text(
            "💰 Nenhum orçamento definido.\n"
            "Use: `/orcamento <categoria> <valor>`\nEx: `/orcamento mercado 800`",
            parse_mode="Markdown",
        )
        return
    linhas = []
    for s in status:
        emoji = "🟢" if s["pct"] < 80 else "🟡" if s["pct"] < 100 else "🔴"
        linhas.append(
            f"{emoji} *{s['categoria']}*: R$ {s['gasto']:.2f} / R$ {s['limite']:.2f} ({s['pct']:.0f}%)"
        )
    await message.reply_text("💰 *Orçamento do mês*\n\n" + "\n".join(linhas),
                             parse_mode="Markdown")


async def cmd_buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: `/buscar <termo>` (ex: `/buscar fornecedor X 2026`)",
                                        parse_mode="Markdown")
        return
    termo = " ".join(context.args)
    await _executar_busca(update.message, termo)


async def _executar_busca(message, termo: str):
    await message.reply_text(f"🔎 Buscando '{termo}'...")
    try:
        ini, fim = busca.parse_periodo_livre(termo)
        r = busca.buscar(termo, ini, fim)
        await message.reply_text(busca.formatar_resumo(termo, r),
                                 parse_mode="Markdown")
    except Exception as e:
        await message.reply_text(f"❌ Erro na busca: {e}")


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    arg = " ".join(context.args) if context.args else ""
    await _executar_export(update.message, arg)


async def _executar_export(message, periodo_txt: str):
    ini, fim = export.parse_periodo(periodo_txt)
    await message.reply_text(f"📦 Gerando export {ini.strftime('%m/%Y')}...")
    try:
        conteudo, nome = export.exportar_xlsx(ini, fim)
        await message.reply_document(document=io.BytesIO(conteudo), filename=nome)
    except Exception as e:
        await message.reply_text(f"❌ Erro ao exportar: {e}")


async def cmd_baixa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: `/baixa <descrição>` (ex: `/baixa aluguel`)",
                                        parse_mode="Markdown")
        return
    termo = " ".join(context.args)
    await iniciar_baixa(update, context, termo, tipo="PAGAR")


# ─── Callbacks de lançamento ──────────────────────────────────────────────────

async def callback_lancar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    partes  = query.data.split(":")
    acao    = partes[1]
    user_id = int(partes[2])
    dados   = context.bot_data.pop(f"lancamento_{user_id}", None)

    if acao == "nao" or not dados:
        limpar_estado(user_id)
        await query.edit_message_text("❌ Lançamento cancelado.")
        return

    limpar_estado(user_id)
    await query.edit_message_text("⏳ Lançando no Conta Azul...")
    resultado = criar_lancamento(dados)

    if resultado["ok"]:
        tipo_emoji = "📥" if dados["tipo"] == "RECEBER" else "📤"
        id_str = resultado.get("id")
        sufixo = f"\nID: `{id_str}`" if id_str else ""
        await query.edit_message_text(
            f"✅ {tipo_emoji} *Lançamento criado!*{sufixo}",
            parse_mode="Markdown",
        )
    elif resultado.get("erro") == "DUPLICATA":
        context.bot_data[f"lancamento_{user_id}"] = dados
        await query.edit_message_text(
            f"⚠️ *Possível duplicata!*\n{resultado['mensagem']}\n\nLançar mesmo assim?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Forçar",   callback_data=f"forcar:{user_id}"),
                InlineKeyboardButton("❌ Cancelar", callback_data=f"lancar:nao:{user_id}"),
            ]]),
        )
    else:
        await query.edit_message_text(f"❌ Erro: {resultado.get('erro', 'Desconhecido')}")


async def callback_forcar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reusa criar_lancamento(forcar=True) — garante mesma lógica de parcelas/contato/centro."""
    query = update.callback_query
    await query.answer()

    user_id = int(query.data.split(":")[1])
    dados   = context.bot_data.pop(f"lancamento_{user_id}", None)
    if not dados:
        await query.edit_message_text("⚠️ Sessão expirada.")
        return

    limpar_estado(user_id)
    await query.edit_message_text("⏳ Lançando (forçado)...")
    resultado = criar_lancamento(dados, forcar=True)

    if resultado["ok"]:
        id_str = resultado.get("id")
        sufixo = f"\nID: `{id_str}`" if id_str else ""
        await query.edit_message_text(
            f"✅ Lançado!{sufixo}",
            parse_mode="Markdown",
        )
    else:
        await query.edit_message_text(f"❌ Erro: {resultado.get('erro', 'Desconhecido')}")


# ─── Despachante de ações detectadas pela IA ─────────────────────────────────

async def _despachar_acao(update: Update, context: ContextTypes.DEFAULT_TYPE,
                          texto: str, dados: dict):
    acao = dados.get("acao", "INDEFINIDO")
    msg  = update.message

    if acao in ("RECEBER", "PAGAR"):
        await iniciar_selecao(update, context, {
            "tipo":        acao,
            "titulo":      dados.get("titulo", texto[:50]),
            "valor":       dados.get("valor", 0),
            "vencimento":  dados.get("vencimento", str(date.today())),
            "parcelas":    dados.get("parcelas", 1),
            "termo_extra": dados.get("termo_extra", ""),
        })
    elif acao == "PENDENTES":
        await cmd_pendentes(update, context)
    elif acao == "ATRASADOS":
        await cmd_atrasados(update, context)
    elif acao == "RELATORIO":
        await cmd_relatorio(update, context)
    elif acao == "BAIXA":
        termo = dados.get("termo_extra") or dados.get("titulo") or texto
        await iniciar_baixa(update, context, termo, tipo="PAGAR")
    elif acao == "GRAFICO":
        sub = (dados.get("termo_extra") or "").lower()
        await msg.reply_text("⏳ Gerando gráfico...")
        try:
            if "categoria_despesa" in sub or "despesa" in sub:
                png = graficos.grafico_categorias("PAGAR")
            elif "categoria_receita" in sub or "receita" in sub:
                png = graficos.grafico_categorias("RECEBER")
            elif "fluxo" in sub or "caixa" in sub:
                png = graficos.grafico_fluxo_caixa(30)
            else:
                png = graficos.grafico_meses(6)
            await context.bot.send_photo(chat_id=msg.chat_id, photo=io.BytesIO(png))
        except Exception as e:
            await msg.reply_text(f"❌ Erro: {e}")
    elif acao == "ORCAMENTO":
        cat = (dados.get("categoria") or "").strip()
        lim = dados.get("limite")
        if cat and lim:
            try:
                orcamento.definir(cat, float(lim))
                await msg.reply_text(f"✅ Orçamento '{cat}' = R$ {float(lim):.2f}")
            except Exception as e:
                await msg.reply_text(f"❌ {e}")
        else:
            await _mostrar_orcamento(msg)
    elif acao == "BUSCA":
        termo = dados.get("termo_extra") or texto
        await _executar_busca(msg, termo)
    elif acao == "EXPORT":
        await _executar_export(msg, dados.get("periodo", ""))
    elif acao == "CONSULTA":
        resumo = resumo_mes()
        ctx = json.dumps(
            {k: v for k, v in resumo.items() if k not in ("contas_receber", "contas_pagar")},
            ensure_ascii=False,
        )
        resp = responder_consulta(texto, ctx)
        await msg.reply_text(resp)
    else:
        await msg.reply_text(
            dados.get("mensagem") or "Não entendi. Tente reformular ou use /manual."
        )


# ─── Handler de texto ────────────────────────────────────────────────────────

async def handle_mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return

    if await receber_texto_livre(update, context):
        return

    manual = context.user_data.get("manual")
    if manual:
        await _handle_manual(update, context, manual)
        return

    texto = update.message.text.strip()
    await update.message.reply_text("🤔 Analisando...")
    dados = extrair_lancamento(texto)
    await _despachar_acao(update, context, texto, dados)


# ─── Handler de áudio (voz) ──────────────────────────────────────────────────

async def handle_voz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    await update.message.reply_text("🎙️ Ouvindo áudio...")
    audio = update.message.voice or update.message.audio
    file  = await context.bot.get_file(audio.file_id)
    audio_bytes = bytes(await file.download_as_bytearray())
    mime  = getattr(audio, "mime_type", None) or "audio/ogg"

    transcricao, dados = extrair_de_audio(audio_bytes, mime)
    if transcricao:
        await update.message.reply_text(f"🗣️ _\"{transcricao}\"_", parse_mode="Markdown")
    await _despachar_acao(update, context, transcricao or "", dados)


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
    await _despachar_acao(update, context, dados.get("titulo", "Documento"), dados)


async def handle_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    await update.message.reply_text("📷 Lendo imagem...")
    foto  = update.message.photo[-1]
    file  = await context.bot.get_file(foto.file_id)
    dados = extrair_de_imagem(await file.download_as_bytearray(), "image/jpeg")
    await _despachar_acao(update, context, dados.get("titulo", "Foto"), dados)


# ─── Handler de novo membro (bloqueia grupos não autorizados) ─────────────────

async def handle_novo_membro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for membro in update.message.new_chat_members:
        if membro.id == context.bot.id:
            if update.effective_chat.id not in TELEGRAM_ALLOWED_CHAT_IDS:
                await update.message.reply_text("⛔ Grupo não autorizado.")
                await context.bot.leave_chat(update.effective_chat.id)
            break


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
        await update.message.reply_text("💰 Qual o *valor*?", parse_mode="Markdown")
    elif etapa == "valor":
        try:
            manual["valor"] = float(texto.replace(",", ".").replace("R$", "").strip())
        except ValueError:
            await update.message.reply_text("Valor inválido. Tente novamente.")
            return
        manual["etapa"] = "vencimento"
        await update.message.reply_text(
            "📅 *Data de vencimento*? (ex: 15/05/2026)", parse_mode="Markdown",
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
            await update.message.reply_text("Data inválida. Use DD/MM/AAAA.")
            return
        manual["etapa"] = "parcelas"
        await update.message.reply_text("🔢 Quantas *parcelas*? (1 para à vista)",
                                        parse_mode="Markdown")
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
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    MINUTOS = 290
    def _timer():
        import time
        print(f"[SHUTDOWN] Auto-shutdown em {MINUTOS} min.")
        time.sleep(MINUTOS * 60)
        os.kill(os.getpid(), signal.SIGTERM)
    threading.Thread(target=_timer, daemon=True).start()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",             cmd_start))
    app.add_handler(CommandHandler("pendentes",         cmd_pendentes))
    app.add_handler(CommandHandler("atrasados",         cmd_atrasados))
    app.add_handler(CommandHandler("relatorio",         cmd_relatorio))
    app.add_handler(CommandHandler("catalogo",          cmd_catalogo))
    app.add_handler(CommandHandler("manual",            cmd_manual))
    app.add_handler(CommandHandler("grafico",           cmd_grafico))
    app.add_handler(CommandHandler("orcamento",         cmd_orcamento))
    app.add_handler(CommandHandler("orcamento_remover", cmd_orcamento_remover))
    app.add_handler(CommandHandler("buscar",            cmd_buscar))
    app.add_handler(CommandHandler("export",            cmd_export))
    app.add_handler(CommandHandler("baixa",             cmd_baixa))

    app.add_handler(CallbackQueryHandler(callback_selecao, pattern="^sel:"))
    app.add_handler(CallbackQueryHandler(callback_lancar,  pattern="^lancar:"))
    app.add_handler(CallbackQueryHandler(callback_forcar,  pattern="^forcar:"))
    app.add_handler(CallbackQueryHandler(callback_editar,  pattern="^edit:"))
    app.add_handler(CallbackQueryHandler(callback_baixa,   pattern="^baixa:"))
    app.add_handler(CallbackQueryHandler(callback_grafico, pattern="^graf:"))

    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_novo_membro))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO,         handle_voz))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,       handle_mensagem))
    app.add_handler(MessageHandler(filters.Document.ALL,                  handle_documento))
    app.add_handler(MessageHandler(filters.PHOTO,                         handle_foto))

    app.add_error_handler(handle_erro)                             # ← novo

    iniciar(app, TELEGRAM_ALLOWED_CHAT_ID)
    _agendar_shutdown(app)

    print("🤖 Bot iniciado!")
    print(f"   Chats autorizados: {TELEGRAM_ALLOWED_CHAT_IDS}")
    print(f"   GitHub Actions mode: {'SIM' if os.environ.get('GITHUB_ACTIONS') else 'NÃO'}")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        stop_signals=None,
    )


if __name__ == "__main__":
    main()
