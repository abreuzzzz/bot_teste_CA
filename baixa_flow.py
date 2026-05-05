"""Fluxo de baixa: busca → seleção → data → valor (parcial?) → método → confirmação → comprovante."""
from datetime import datetime, date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from baixa_parcela import buscar_por_descricao, dar_baixa, dar_baixa_parcial, METODOS_PAGAMENTO
from consulta_financeira import _valor

# context.user_data["baixa"] = {
#   "tipo": str, "itens": list,
#   "selecionado": dict | None,
#   "data_pagamento": str | None,
#   "valor_parcial": float | None,   # None = valor total
#   "metodo_pagamento": str | None,
#   "aguardando_data": bool,
#   "aguardando_valor": bool,
# }


async def iniciar_baixa(update: Update, context: ContextTypes.DEFAULT_TYPE,
                        termo: str, tipo: str = "PAGAR"):
    """Busca parcelas correspondentes ao termo e mostra opções."""
    chat = update.effective_message
    await chat.reply_text(f"🔎 Buscando '{termo}' em contas a {tipo.lower()}...")

    candidatos = buscar_por_descricao(termo, tipo)
    if not candidatos:
        outro = "RECEBER" if tipo == "PAGAR" else "PAGAR"
        candidatos = buscar_por_descricao(termo, outro)
        if candidatos:
            tipo = outro

    if not candidatos:
        await chat.reply_text(f"❌ Nenhuma parcela em aberto encontrada para '{termo}'.")
        return

    candidatos = candidatos[:8]
    context.user_data["baixa"] = {
        "tipo": tipo, "itens": candidatos,
        "selecionado": None, "data_pagamento": None,
        "valor_parcial": None, "metodo_pagamento": None,
        "aguardando_data": False, "aguardando_valor": False,
    }

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


async def receber_texto_baixa(update: Update,
                               context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Intercepta digitação livre quando aguardando data ou valor parcial."""
    estado = context.user_data.get("baixa")
    if not estado:
        return False

    texto = update.message.text.strip()

    # ─ Aguardando valor parcial ─────────────────────────────────
    if estado.get("aguardando_valor"):
        try:
            v = float(texto.replace(",", ".").replace("R$", "").strip())
        except ValueError:
            await update.message.reply_text("❌ Valor inválido. Use números (ex: 250,00).")
            return True
        item = estado["selecionado"]
        total = _valor(item)
        if v <= 0 or v > total:
            await update.message.reply_text(
                f"⚠️ Valor deve ser entre R$ 0,01 e R$ {total:.2f}."
            )
            return True
        estado["valor_parcial"]    = v
        estado["aguardando_valor"] = False
        await update.message.reply_text(
            f"✅ Valor parcial: *R$ {v:.2f}* (total: R$ {total:.2f})",
            parse_mode="Markdown",
        )
        await _perguntar_metodo(update.message, context)
        return True

    # ─ Aguardando data ──────────────────────────────────────────
    if not estado.get("aguardando_data"):
        return False

    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(texto, fmt)
            estado["data_pagamento"] = dt.strftime("%Y-%m-%d")
            estado["aguardando_data"] = False
            await update.message.reply_text(
                f"✅ Data registrada: *{dt.strftime('%d/%m/%Y')}*",
                parse_mode="Markdown",
            )
            await _perguntar_valor_parcial(update.message, context, estado)
            return True
        except ValueError:
            continue

    await update.message.reply_text(
        "❌ Data inválida. Use DD/MM/AAAA (ex: 15/06/2026)."
    )
    return True


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

    # ─ Seleção da parcela ──────────────────────────────────────
    if acao == "sel":
        idx = int(partes[2])
        item = estado["itens"][idx]
        estado["selecionado"] = item
        desc = (item.get("descricao", "?") or "?")[:40]
        v = _valor(item)
        venc = item.get("data_vencimento", "")
        await query.edit_message_text(
            f"📌 *{desc}*\nR$ {v:.2f} — venc {venc}\n\n📅 *Qual a data de pagamento?*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"✅ Hoje ({date.today().strftime('%d/%m/%Y')})",
                    callback_data="baixa:data_hoje",
                )],
                [InlineKeyboardButton("🗓️ Outra data", callback_data="baixa:data_manual")],
                [InlineKeyboardButton("❌ Cancelar",   callback_data="baixa:cancelar")],
            ]),
        )
        return

    # ─ Data de pagamento ────────────────────────────────────────
    if acao == "data_hoje":
        estado["data_pagamento"] = str(date.today())
        await query.edit_message_text(
            f"✅ Data: *{date.today().strftime('%d/%m/%Y')}*", parse_mode="Markdown"
        )
        await _perguntar_valor_parcial(query.message, context, estado)
        return

    if acao == "data_manual":
        estado["aguardando_data"] = True
        await query.edit_message_text(
            "🗓️ Digite a data de pagamento no formato DD/MM/AAAA:"
        )
        return

    # ─ Valor parcial / total ────────────────────────────────────
    if acao == "valor_total":
        estado["valor_parcial"] = None
        await _perguntar_metodo(query.message, context)
        return

    if acao == "valor_parcial":
        estado["aguardando_valor"] = True
        item  = estado["selecionado"]
        total = _valor(item)
        await query.edit_message_text(
            f"💰 Digite o valor que foi pago (total: R$ {total:.2f}):"
        )
        return

    # ─ Método de pagamento ────────────────────────────────────
    if acao == "metodo":
        estado["metodo_pagamento"] = partes[2] if partes[2] != "skip" else None
        await _confirmar_baixa(query, context, estado)
        return

    # ─ Confirmação final ─────────────────────────────────────────
    if acao == "confirmar":
        item = estado.get("selecionado")
        if not item:
            await query.edit_message_text("⚠️ Sessão expirada.")
            return
        await query.edit_message_text("⏳ Dando baixa...")
        parcela_id   = item.get("id") or item.get("parcela_id")
        valor_parcial = estado.get("valor_parcial")   # None = total

        if valor_parcial:
            ok = dar_baixa_parcial(
                parcela_id,
                estado["tipo"],
                valor_pago=valor_parcial,
                data_pagamento=estado.get("data_pagamento"),
                metodo_pagamento=estado.get("metodo_pagamento"),
            )
        else:
            ok = dar_baixa(
                parcela_id,
                estado["tipo"],
                data_pagamento=estado.get("data_pagamento"),
                metodo_pagamento=estado.get("metodo_pagamento"),
            )
        context.user_data.pop("baixa", None)
        if ok:
            try:
                import historico as _hist
                valor_h = valor_parcial or _valor(item)
                desc_h  = (item.get("descricao") or "")[:50]
                _hist.registrar(
                    "BAIXA",
                    f"{estado.get('tipo','?')} {desc_h} R$ {valor_h:.2f}",
                    query.message.chat_id,
                )
            except Exception:
                pass
            await _enviar_comprovante(query, item, estado, valor_parcial)
        else:
            await query.edit_message_text("❌ Falha ao dar baixa. Verifique os logs.")


async def _perguntar_valor_parcial(msg_or_query, context: ContextTypes.DEFAULT_TYPE, estado: dict):
    """Feature 4: pergunta se o pagamento foi total ou parcial."""
    item  = estado["selecionado"]
    total = _valor(item)
    send  = getattr(msg_or_query, "reply_text", None) or getattr(msg_or_query, "edit_message_text", None)
    await send(
        f"💰 *Valor pago:*\nTotal da parcela: R$ {total:.2f}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(f"✅ Total (R$ {total:.2f})", callback_data="baixa:valor_total"),
            InlineKeyboardButton("💸 Parcial",               callback_data="baixa:valor_parcial"),
        ]]),
    )


async def _perguntar_metodo(msg_or_query, context: ContextTypes.DEFAULT_TYPE):
    """Exibe seleção de método de pagamento."""
    botoes = [
        [InlineKeyboardButton(nome, callback_data=f"baixa:metodo:{codigo}")]
        for codigo, nome in METODOS_PAGAMENTO
    ]
    botoes.append([InlineKeyboardButton("⏭️ Pular", callback_data="baixa:metodo:skip")])

    send = getattr(msg_or_query, "reply_text", None) or getattr(msg_or_query, "edit_message_text", None)
    await send(
        "💳 *Qual o método de pagamento?*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(botoes),
    )


async def _confirmar_baixa(query, context, estado: dict):
    item          = estado["selecionado"]
    desc          = (item.get("descricao", "?") or "?")[:40]
    v_total       = _valor(item)
    v_parcial     = estado.get("valor_parcial")
    v_exib        = v_parcial if v_parcial else v_total
    parcial_str   = f" *(parcial — total: R$ {v_total:.2f})*" if v_parcial else ""
    data_str      = estado.get("data_pagamento") or str(date.today())
    met_str       = estado.get("metodo_pagamento") or "_(padrão)_"

    await query.edit_message_text(
        f"📌 *Confirmar baixa:*\n\n"
        f"*{desc}*\nR$ {v_exib:.2f}{parcial_str}\n"
        f"📅 Data: {data_str}\n"
        f"💳 Método: {met_str}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Confirmar", callback_data="baixa:confirmar"),
            InlineKeyboardButton("❌ Cancelar",  callback_data="baixa:cancelar"),
        ]]),
    )


async def _enviar_comprovante(query, item: dict, estado: dict, valor_parcial: float | None):
    """Feature 7: comprovante formatado após baixa bem-sucedida."""
    desc       = (item.get("descricao") or "?")[:50]
    v_total    = _valor(item)
    v_pago     = valor_parcial if valor_parcial else v_total
    data_str   = estado.get("data_pagamento") or str(date.today())
    metodo     = estado.get("metodo_pagamento") or "Padrão"
    tipo       = estado.get("tipo", "PAGAR")
    emoji_tipo = "📥" if tipo == "RECEBER" else "📤"
    saldo_rest = round(v_total - v_pago, 2) if valor_parcial else 0

    linhas = [
        f"{emoji_tipo} *Baixa registrada!*",
        "",
        f"📋 *{desc}*",
        f"💰 Valor pago:   R$ {v_pago:.2f}",
    ]
    if saldo_rest > 0:
        linhas.append(f"⚠️ Restante:     R$ {saldo_rest:.2f}")
    linhas += [
        f"📅 Data:         {data_str}",
        f"💳 Método:       {metodo}",
    ]
    if item.get("id"):
        linhas.append(f"🔑 ID parcela:   `{item['id']}`")

    await query.edit_message_text(
        "\n".join(linhas),
        parse_mode="Markdown",
    )
