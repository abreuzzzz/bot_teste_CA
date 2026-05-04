"""Fluxo de baixa de parcelas: busca por termo → seleção → confirmação."""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from baixa_parcela import buscar_por_descricao, dar_baixa
from consulta_financeira import _valor

# context.user_data["baixa"] = {"tipo": ..., "candidatos": [...]}


async def iniciar_baixa(update: Update, context: ContextTypes.DEFAULT_TYPE,
                        termo: str, tipo: str = "PAGAR"):
    """Busca parcelas correspondentes ao termo e mostra opções."""
    chat = update.effective_message
    await chat.reply_text(f"🔎 Buscando '{termo}' em contas a {tipo.lower()}...")

    candidatos = buscar_por_descricao(termo, tipo)
    if not candidatos:
        # Tenta o tipo oposto automaticamente
        outro = "RECEBER" if tipo == "PAGAR" else "PAGAR"
        candidatos = buscar_por_descricao(termo, outro)
        if candidatos:
            tipo = outro

    if not candidatos:
        await chat.reply_text(f"❌ Nenhuma parcela em aberto encontrada para '{termo}'.")
        return

    candidatos = candidatos[:8]
    context.user_data["baixa"] = {"tipo": tipo, "itens": candidatos}

    botoes = []
    for idx, i in enumerate(candidatos):
        desc = (i.get("descricao", "?") or "?")[:25]
        v = _valor(i)
        venc = i.get("data_vencimento", "")
        emoji = "📥" if tipo == "RECEBER" else "📤"
        botoes.append([InlineKeyboardButton(
            f"{emoji} {desc} — R${v:.2f} ({venc})",
            callback_data=f"baixa:sel:{idx}",
        )])
    botoes.append([InlineKeyboardButton("❌ Cancelar", callback_data="baixa:cancelar")])

    await chat.reply_text(
        f"📋 *{len(candidatos)} parcela(s)* encontrada(s). Qual deseja baixar?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(botoes),
    )


async def callback_baixa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    partes = query.data.split(":")
    acao = partes[1]

    if acao == "cancelar":
        context.user_data.pop("baixa", None)
        await query.edit_message_text("❌ Baixa cancelada.")
        return

    estado = context.user_data.get("baixa")
    if not estado:
        await query.edit_message_text("⚠️ Sessão expirada.")
        return

    if acao == "sel":
        idx = int(partes[2])
        item = estado["itens"][idx]
        estado["selecionado"] = item
        desc = item.get("descricao", "?")
        v = _valor(item)
        venc = item.get("data_vencimento", "")
        await query.edit_message_text(
            f"📌 *Confirmar baixa:*\n\n"
            f"{desc}\nR$ {v:.2f} — venc {venc}\n\n"
            f"Confirma baixa com data de hoje?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Confirmar", callback_data="baixa:confirmar"),
                InlineKeyboardButton("❌ Cancelar",  callback_data="baixa:cancelar"),
            ]]),
        )
        return

    if acao == "confirmar":
        item = estado.get("selecionado")
        if not item:
            await query.edit_message_text("⚠️ Sessão expirada.")
            return
        await query.edit_message_text("⏳ Dando baixa...")
        parcela_id = item.get("id") or item.get("parcela_id")
        ok = dar_baixa(parcela_id, estado["tipo"])
        context.user_data.pop("baixa", None)
        if ok:
            await query.edit_message_text(
                f"✅ Baixa registrada!\n_{item.get('descricao', '')}_",
                parse_mode="Markdown",
            )
        else:
            await query.edit_message_text("❌ Falha ao dar baixa. Verifique os logs.")
