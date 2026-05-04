from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from catalogo import contas_financeiras, categorias_receita, categorias_despesa, centros_custo
from sugestao import sugerir_conta, sugerir_categoria, sugerir_centro, match_livre, top3

estados: dict = {}
AGUARDANDO_LIVRE = "aguardando_livre"


# ─── Entrada pública ──────────────────────────────────────────────────────────

async def iniciar_selecao(update: Update, context: ContextTypes.DEFAULT_TYPE, dados: dict):
    """
    dados = {
      "tipo": "RECEBER" | "PAGAR",
      "titulo": str,
      "valor": float,
      "vencimento": str,   # "YYYY-MM-DD"
      "parcelas": int,
      "termo_extra": str,  # termo livre extraído pela IA (opcional)
    }
    """
    chat_id = update.message.chat_id
    estados[chat_id] = {
        "etapa": "conta",
        "dados": {
            **dados,
            "conta_id":     None, "conta_nome":     None,
            "categoria_id": None, "categoria_nome": None,
            "centro_id":    None, "centro_nome":    None,
        },
    }
    await _perguntar(update.message, context, chat_id)


async def callback_selecao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    if chat_id not in estados:
        await query.edit_message_text("⚠️ Sessão expirada. Refaça o lançamento.")
        return

    partes = query.data.split(":", 3)
    _, etapa, id_val, nome = partes[0], partes[1], partes[2], partes[3]
    estado = estados[chat_id]

    if id_val == "LIVRE":
        estado["etapa"] = AGUARDANDO_LIVRE
        estado["etapa_livre"] = etapa
        estado["lista_livre"] = _lista_para(etapa, estado["dados"]["tipo"])
        await query.edit_message_text(
            f"✏️ Digite o nome da *{_label(etapa)}* desejada\n"
            f"_(ou parte do nome — vou fazer o match automaticamente)_",
            parse_mode="Markdown",
        )
        return

    if id_val == "PULAR":
        _salvar(estado, etapa, None, None)
        await query.edit_message_text(f"⏭️ *{_label(etapa)}* pulada.", parse_mode="Markdown")
    else:
        _salvar(estado, etapa, id_val, nome)
        await query.edit_message_text(
            f"✅ *{_label(etapa)}* selecionada: *{nome}*",
            parse_mode="Markdown",
        )

    await _avancar(query, context, chat_id)


async def receber_texto_livre(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Deve ser chamado no handler principal ANTES da IA.
    Retorna True se consumiu a mensagem.
    """
    chat_id = update.message.chat_id
    estado  = estados.get(chat_id)
    if not estado or estado.get("etapa") != AGUARDANDO_LIVRE:
        return False

    texto = update.message.text.strip()
    etapa = estado["etapa_livre"]
    lista = estado["lista_livre"]

    match = match_livre(lista, texto)
    if match:
        _salvar(estado, etapa, match["id"], match["nome"])
        await update.message.reply_text(
            f"✅ Encontrei: *{match['nome']}*",
            parse_mode="Markdown",
        )
        estado["etapa"] = etapa
        await _avancar(update, context, chat_id)
    else:
        sugestoes = top3(lista, texto)
        if sugestoes:
            botoes = [
                [InlineKeyboardButton(s["nome"], callback_data=f"sel:{etapa}:{s['id']}:{s['nome']}")]
                for s in sugestoes
            ]
            botoes.append([InlineKeyboardButton("⏭️ Pular", callback_data=f"sel:{etapa}:PULAR:")])
            await update.message.reply_text(
                f"🔍 Não achei exatamente *\"{texto}\"*. Você quis dizer?",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(botoes),
            )
        else:
            await update.message.reply_text(
                "❌ Nenhum resultado. Tente novamente ou use /catalogo para ver as opções disponíveis."
            )
    return True


# ─── Privados ─────────────────────────────────────────────────────────────────

async def _perguntar(msg_or_query, context, chat_id: int):
    estado = estados[chat_id]
    etapa  = estado["etapa"]
    dados  = estado["dados"]
    tipo   = dados["tipo"]
    termo  = dados.get("termo_extra") or dados["titulo"]

    if etapa == "conta":
        sugestoes = sugerir_conta(termo)
        titulo    = "🏦 *Conta Financeira*"
    elif etapa == "categoria":
        sugestoes = sugerir_categoria(termo, tipo)
        titulo    = "📂 *Categoria*"
    else:
        sugestoes = sugerir_centro(termo)
        titulo    = "🏷️ *Centro de Custo*"

    botoes = [
        [InlineKeyboardButton(
            f"{'✅' if i == 0 else '🔹'} {s['nome']}",
            callback_data=f"sel:{etapa}:{s['id']}:{s['nome']}"
        )]
        for i, s in enumerate(sugestoes)
    ]
    botoes.append([
        InlineKeyboardButton("✏️ Outra (digitar)", callback_data=f"sel:{etapa}:LIVRE:"),
        InlineKeyboardButton("⏭️ Pular",           callback_data=f"sel:{etapa}:PULAR:"),
    ])

    texto = (
        f"{titulo}\n"
        f"Sugestões baseadas em *\"{termo}\"*:\n\n"
        f"Escolha uma ou clique em *Outra* para digitar:"
    )

    send = getattr(msg_or_query, "reply_text", None) or getattr(msg_or_query, "edit_message_text", None)
    await send(texto, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(botoes))


async def _avancar(update_or_query, context, chat_id: int):
    estado = estados[chat_id]
    etapa  = estado["etapa"]

    if etapa == "conta":
        estado["etapa"] = "categoria"
        await _perguntar(_msg(update_or_query), context, chat_id)

    elif etapa == "categoria":
        if centros_custo():
            estado["etapa"] = "centro_custo"
            await _perguntar(_msg(update_or_query), context, chat_id)
        else:
            await _confirmar(update_or_query, context, chat_id)

    else:
        await _confirmar(update_or_query, context, chat_id)


async def _confirmar(update_or_query, context, chat_id: int):
    estado = estados[chat_id]
    dados  = estado["dados"]

    tipo_emoji = "📥" if dados["tipo"] == "RECEBER" else "📤"
    resumo = (
        f"📋 *Resumo do lançamento*\n\n"
        f"{tipo_emoji} *{dados['titulo']}*\n"
        f"💰 R$ {float(dados['valor']):.2f}  ×{dados['parcelas']}x\n"
        f"📅 Vencimento: {dados['vencimento']}\n"
        f"🏦 Conta: {dados['conta_nome'] or '_(padrão)_'}\n"
        f"📂 Categoria: {dados['categoria_nome'] or '_(padrão)_'}\n"
        f"🏷️ Centro: {dados['centro_nome'] or '_(sem centro)_'}\n\n"
        f"Confirma o lançamento?"
    )
    botoes = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirmar", callback_data=f"lancar:sim:{chat_id}"),
        InlineKeyboardButton("❌ Cancelar",  callback_data=f"lancar:nao:{chat_id}"),
    ]])

    context.bot_data[f"lancamento_{chat_id}"] = dados

    send = getattr(_msg(update_or_query), "reply_text", None)
    if send:
        await send(resumo, parse_mode="Markdown", reply_markup=botoes)
    else:
        await update_or_query.message.reply_text(resumo, parse_mode="Markdown", reply_markup=botoes)


def _salvar(estado, etapa, id_val, nome):
    if etapa == "conta":
        estado["dados"]["conta_id"]     = id_val
        estado["dados"]["conta_nome"]   = nome
    elif etapa == "categoria":
        estado["dados"]["categoria_id"]   = id_val
        estado["dados"]["categoria_nome"] = nome
    else:
        estado["dados"]["centro_id"]   = id_val
        estado["dados"]["centro_nome"] = nome
    estado["etapa"] = etapa


def _lista_para(etapa: str, tipo: str) -> list:
    if etapa == "conta":       return contas_financeiras()
    if etapa == "categoria":   return categorias_receita() if tipo == "RECEBER" else categorias_despesa()
    return centros_custo()


def _label(etapa: str) -> str:
    return {"conta": "Conta Financeira", "categoria": "Categoria", "centro_custo": "Centro de Custo"}.get(etapa, etapa)


def _msg(update_or_query):
    if hasattr(update_or_query, "message"):
        return update_or_query.message
    return update_or_query
