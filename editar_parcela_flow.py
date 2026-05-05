"""Fluxo de edição de parcelas existentes via PATCH.
Busca → seleciona → escolhe campo → edita → confirma.
"""
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from baixa_parcela import buscar_por_descricao, get_parcela, patch_parcela, METODOS_PAGAMENTO
from consulta_financeira import _valor

# context.user_data["_editar_parcela"] = {
#   "tipo": str,
#   "itens": list,
#   "selecionado": dict | None,
#   "campo_ativo": str | None,   # campo aguardando digitação
# }

_CAMPOS = {
    "vencimento": ("📅 Vencimento",        "Nova data (DD/MM/AAAA, ex: 15/06/2026)"),
    "valor":      ("💰 Valor",             "Novo valor em R$ (ex: 250.00)"),
    "descricao":  ("📝 Descrição",         "Nova descrição (máx. 500 chars)"),
    "nota":       ("📌 Nota",              "Texto da nota"),
    "metodo":     ("💳 Método pagamento",  None),   # usa inline keyboard
}


# ─── Entrada pública ──────────────────────────────────────────────────────────

async def iniciar_edicao(update: Update, context: ContextTypes.DEFAULT_TYPE,
                         termo: str, tipo: str = "PAGAR"):
    """Busca parcelas pelo termo e exibe lista para seleção."""
    chat = update.effective_message
    await chat.reply_text(f"🔎 Buscando '{termo}'...")

    candidatos = buscar_por_descricao(termo, tipo)
    if not candidatos:
        outro = "RECEBER" if tipo == "PAGAR" else "PAGAR"
        candidatos = buscar_por_descricao(termo, outro)
        if candidatos:
            tipo = outro

    if not candidatos:
        await chat.reply_text(f"❌ Nenhuma parcela encontrada para '{termo}'.")
        return

    candidatos = candidatos[:8]
    context.user_data["_editar_parcela"] = {
        "tipo": tipo, "itens": candidatos,
        "selecionado": None, "campo_ativo": None,
    }

    botoes = []
    for idx, i in enumerate(candidatos):
        desc  = (i.get("descricao", "?") or "?")[:25]
        v     = _valor(i)
        venc  = i.get("data_vencimento", "")
        emoji = "📥" if tipo == "RECEBER" else "📤"
        botoes.append([InlineKeyboardButton(
            f"{emoji} {desc} — R${v:.2f} ({venc})",
            callback_data=f"editpar:sel:{idx}",
        )])
    botoes.append([InlineKeyboardButton("❌ Cancelar", callback_data="editpar:cancelar")])

    await chat.reply_text(
        f"📋 *{len(candidatos)} parcela(s)* encontrada(s). Qual deseja editar?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(botoes),
    )


async def receber_texto_edicao(update: Update,
                                context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Intercepta texto livre enquanto aguarda valor de campo editável."""
    estado = context.user_data.get("_editar_parcela")
    if not estado or not estado.get("campo_ativo"):
        return False

    campo = estado["campo_ativo"]
    texto = update.message.text.strip()
    item  = estado.get("selecionado")
    if not item:
        context.user_data.pop("_editar_parcela", None)
        return False

    parcela_completa = get_parcela(item["id"])
    if not parcela_completa:
        await update.message.reply_text("❌ Não foi possível carregar os dados da parcela.")
        context.user_data.pop("_editar_parcela", None)
        return True

    patch: dict = {"versao": parcela_completa.get("versao", 1)}

    if campo == "vencimento":
        for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(texto, fmt)
                patch["vencimento"] = dt.strftime("%Y-%m-%d")
                break
            except ValueError:
                continue
        else:
            await update.message.reply_text("❌ Data inválida. Use DD/MM/AAAA.")
            return True

    elif campo == "valor":
        try:
            v = float(texto.replace(",", ".").replace("R$", "").strip())
            patch["composicao_valor"] = {"valor_bruto": v}
        except ValueError:
            await update.message.reply_text("❌ Valor inválido. Ex: 250.00")
            return True

    elif campo == "descricao":
        patch["descricao"] = texto[:500]

    elif campo == "nota":
        patch["nota"] = texto

    estado["campo_ativo"] = None
    ok = patch_parcela(item["id"], patch)
    context.user_data.pop("_editar_parcela", None)

    if ok:
        await update.message.reply_text("✅ Parcela atualizada com sucesso!")
    else:
        await update.message.reply_text(
            "❌ Falha ao atualizar parcela. Verifique os logs."
        )
    return True


# ─── Callback principal ───────────────────────────────────────────────────────

async def callback_editar_parcela(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    partes = query.data.split(":")
    acao   = partes[1]

    if acao == "cancelar":
        context.user_data.pop("_editar_parcela", None)
        await query.edit_message_text("❌ Edição cancelada.")
        return

    estado = context.user_data.get("_editar_parcela")
    if not estado:
        await query.edit_message_text("⚠️ Sessão expirada.")
        return

    # ── Seleção da parcela ──────────────────────────────────────────────────
    if acao == "sel":
        idx  = int(partes[2])
        item = estado["itens"][idx]
        estado["selecionado"] = item
        desc = (item.get("descricao", "?") or "?")[:40]
        v    = _valor(item)
        venc = item.get("data_vencimento", "")
        await query.edit_message_text(
            f"✏️ *Editando:*\n{desc}\nR$ {v:.2f} — venc {venc}\n\n*O que deseja alterar?*",
            parse_mode="Markdown",
            reply_markup=_menu_campos(),
        )
        return

    # ── Seleção do campo ────────────────────────────────────────────────────
    if acao == "campo":
        campo = partes[2]
        if campo not in _CAMPOS:
            await query.edit_message_text("⚠️ Campo desconhecido.")
            return

        if campo == "metodo":
            botoes = [
                [InlineKeyboardButton(nome, callback_data=f"editpar:metodo:{codigo}")]
                for codigo, nome in METODOS_PAGAMENTO
            ]
            botoes.append([InlineKeyboardButton("❌ Cancelar", callback_data="editpar:cancelar")])
            await query.edit_message_text(
                "💳 *Selecione o novo método de pagamento:*",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(botoes),
            )
        else:
            estado["campo_ativo"] = campo
            _, dica = _CAMPOS[campo]
            await query.edit_message_text(
                f"✏️ Digite o novo valor para *{_CAMPOS[campo][0]}*:\n_{dica}_",
                parse_mode="Markdown",
            )
        return

    # ── Seleção de método de pagamento ──────────────────────────────────────
    if acao == "metodo":
        codigo = partes[2]
        item   = estado.get("selecionado")
        if not item:
            await query.edit_message_text("⚠️ Sessão expirada.")
            return
        parcela_completa = get_parcela(item["id"])
        if not parcela_completa:
            await query.edit_message_text("❌ Não foi possível carregar os dados da parcela.")
            context.user_data.pop("_editar_parcela", None)
            return
        ok = patch_parcela(item["id"], {
            "versao":            parcela_completa.get("versao", 1),
            "metodo_pagamento":  codigo,
        })
        context.user_data.pop("_editar_parcela", None)
        if ok:
            await query.edit_message_text("✅ Método de pagamento atualizado!")
        else:
            await query.edit_message_text("❌ Falha ao atualizar parcela.")
        return

    # ── Voltar ao menu de campos ────────────────────────────────────────────
    if acao == "menu":
        estado["campo_ativo"] = None
        item = estado.get("selecionado")
        if not item:
            await query.edit_message_text("⚠️ Sessão expirada.")
            return
        desc = (item.get("descricao", "?") or "?")[:40]
        v    = _valor(item)
        venc = item.get("data_vencimento", "")
        await query.edit_message_text(
            f"✏️ *Editando:*\n{desc}\nR$ {v:.2f} — venc {venc}\n\n*O que deseja alterar?*",
            parse_mode="Markdown",
            reply_markup=_menu_campos(),
        )


# ─── Helpers privados ─────────────────────────────────────────────────────────

def _menu_campos() -> InlineKeyboardMarkup:
    botoes = [
        [InlineKeyboardButton(label, callback_data=f"editpar:campo:{campo}")]
        for campo, (label, _) in _CAMPOS.items()
    ]
    botoes.append([InlineKeyboardButton("❌ Cancelar", callback_data="editpar:cancelar")])
    return InlineKeyboardMarkup(botoes)
