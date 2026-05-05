import asyncio, logging, os, signal, threading, json, io, traceback
from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes, PicklePersistence,
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
from consulta_financeira import (
    resumo_mes, pendentes, atrasados, _valor,
    saldo_todas_contas, transferencias,
    projecao_caixa, saldo_cliente,
)
from catalogo import (
    invalidar_cache, contas_financeiras, categorias_receita,
    categorias_despesa, centros_custo, categorias_dre,
)
from scheduler import iniciar
from baixa_flow import iniciar_baixa, callback_baixa, receber_texto_baixa
from editar_parcela_flow import iniciar_edicao, callback_editar_parcela, receber_texto_edicao
import graficos, export, busca, orcamento
from daily_flow import enviar_briefing, callback_daily, callback_alerta_rec
import favoritos as _favoritos
import dre as _dre
import aging as _aging
import comparar as _comparar
import meta as _meta
import historico as _historico
import config_alertas as _cfg
from nfe_parser import parse_nfe

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

    # Extrai o body da resposta HTTP da exceção (ex: requests.HTTPError)
    resp_text = ""
    err = context.error
    if hasattr(err, "response") and err.response is not None:
        resp_text = f"\n\n*API response:*\n`{err.response.text[:600]}`"

    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            f"❌ *Erro:* `{str(err)[:150]}`{resp_text}",
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
        '• _"Fornecedor X R$300 em 3x"_  → lança parcelas\n'
        '• _"Paguei o aluguel"_  → dá baixa\n'
        '• _"Alterar vencimento da fatura energia"_\n'
        '• _"Qual meu saldo?"_  → saldo por conta\n'
        '• _"Transferências de maio"_\n'
        '• _"Quanto o cliente João pagou em 2026?"_\n'
        '• _"Gráfico de despesas do mês"_\n'
        '• _"Definir orçamento mercado 800"_\n\n'
        "📌 *Comandos:*\n"
        "/pendentes     — contas a vencer\n"
        "/atrasados     — contas em atraso\n"
        "/relatorio     — resumo do dia\n"
        "/saldo         — saldo das contas\n"
        "/transferencias — transferências entre contas\n"
        "/grafico       — visualizações\n"
        "/orcamento     — orçamentos por categoria\n"
        "/buscar        — busca livre\n"
        "/export        — exportar planilha\n"
        "/baixa         — dar baixa em parcela\n"
        "/editar        — editar parcela existente\n"
        "/hoje          — vencimentos de hoje\n"
        "/favoritos     — templates favoritos\n"
        "/cliente       — saldo por cliente/fornecedor\n"
        "/projecao      — projeção de caixa\n"
        "/dre           — resultado por categoria\n"
        "/aging         — aging de recebíveis\n"
        "/comparar      — comparar dois meses\n"
        "/meta          — meta de faturamento\n"
        "/historico     — últimas ações do bot\n"
        "/config_alertas — configurar notificações\n"
        "/recorrentes   — sugestão de relançamentos\n"
        "/fechar_mes    — checklist de fechamento\n"
        "/catalogo      — categorias e contas\n"
        "/manual        — lançamento guiado",
        parse_mode="Markdown",
    )


async def cmd_pendentes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Feature 1: lista pendentes com botão inline [💳 Baixar] em cada item."""
    if not _ok(update):
        return
    itens = pendentes(dias=30)
    if not itens:
        await update.message.reply_text("✅ Nenhuma conta pendente nos próximos 30 dias.")
        return

    # Salva lista para o callback de baixa rápida
    chat_id = update.effective_chat.id
    context.bot_data[f"pend_{chat_id}"] = itens[:20]

    for idx, i in enumerate(itens[:20]):
        emoji  = "📥" if i["tipo"] == "RECEBER" else "📤"
        desc   = (i.get("descricao") or "?")[:35]
        v      = _valor(i)
        venc   = i.get("data_vencimento", "")
        acao_label = "💳 Baixar" if i["tipo"] == "PAGAR" else "✅ Recebido"
        await update.message.reply_text(
            f"{emoji} *{desc}*\nR$ {v:.2f} — {venc}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(acao_label,
                                     callback_data=f"pend:baixar:{idx}:{chat_id}"),
                InlineKeyboardButton("👁️ Detalhes",
                                     callback_data=f"pend:detalhe:{idx}:{chat_id}"),
            ]]),
        )


async def callback_pendente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Feature 1: processa clique em [Baixar] ou [Detalhes] do /pendentes."""
    query   = update.callback_query
    await query.answer()
    partes  = query.data.split(":")
    sub     = partes[1]
    idx     = int(partes[2])
    chat_id = int(partes[3])
    itens   = context.bot_data.get(f"pend_{chat_id}", [])
    if idx >= len(itens):
        await query.edit_message_text("⚠️ Item expirado. Rode /pendentes novamente.")
        return
    item = itens[idx]
    desc = (item.get("descricao") or "?")[:40]

    if sub == "detalhe":
        v    = _valor(item)
        venc = item.get("data_vencimento", "")
        cat  = (item.get("categoria") or {}).get("nome") or item.get("categoria") or "—"
        tipo = item["tipo"]
        await query.edit_message_text(
            f"{'📥' if tipo == 'RECEBER' else '📤'} *{desc}*\n"
            f"Valor: R$ {v:.2f}\nVencimento: {venc}\nCategoria: {cat}\nStatus: {item.get('status','')}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💳 Dar baixa",
                                     callback_data=f"pend:baixar:{idx}:{chat_id}"),
            ]]),
        )
        return

    # sub == "baixar"
    await query.edit_message_text(f"⏳ Iniciando baixa de *{desc}*...",
                                   parse_mode="Markdown")
    tipo  = item.get("tipo", "PAGAR")
    await iniciar_baixa(update, context, desc, tipo=tipo)


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
    await enviar_briefing(context.application, update.message.chat_id)


async def cmd_hoje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Feature 1/2: mostra vencimentos de hoje com botão de baixa rápida."""
    if not _ok(update):
        return
    await enviar_briefing(context.application, update.message.chat_id)


async def cmd_favoritos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Feature 11: lista favoritos salvos."""
    if not _ok(update):
        return
    lista = _favoritos.listar()
    if not lista:
        await update.message.reply_text(
            "⭐ Nenhum favorito salvo.\n\n"
            "Para salvar, após um lançamento diga: _\"salvar como favorito <nome>\"_",
            parse_mode="Markdown",
        )
        return
    botoes = [[InlineKeyboardButton(f"⭐ {nome}", callback_data=f"fav:usar:{nome}")]
              for nome in lista[:10]]
    botoes.append([InlineKeyboardButton("🗑️ Remover um", callback_data="fav:remover_menu")])
    await update.message.reply_text(
        "⭐ *Seus favoritos:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(botoes),
    )


async def callback_favorito(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callbacks para usar/remover favoritos."""
    query = update.callback_query
    await query.answer()
    partes = query.data.split(":")
    sub    = partes[1]

    if sub == "usar" and len(partes) >= 3:
        nome   = ":".join(partes[2:])
        dados  = _favoritos.obter(nome)
        if not dados:
            await query.edit_message_text(f"❌ Favorito '{nome}' não encontrado.")
            return
        await query.edit_message_text(f"⭐ Lançando favorito *{nome}*...",
                                      parse_mode="Markdown")
        await iniciar_selecao(update, context, dados)

    elif sub == "remover_menu":
        lista = _favoritos.listar()
        botoes = [[InlineKeyboardButton(f"🗑️ {nome}", callback_data=f"fav:rm:{nome}")]
                  for nome in lista[:10]]
        botoes.append([InlineKeyboardButton("↩️ Voltar", callback_data="fav:listar")])
        await query.edit_message_reply_markup(InlineKeyboardMarkup(botoes))

    elif sub == "rm" and len(partes) >= 3:
        nome = ":".join(partes[2:])
        _favoritos.remover_favorito(nome)
        await query.edit_message_text(f"🗑️ Favorito '{nome}' removido.")

    elif sub == "listar":
        lista   = _favoritos.listar()
        botoes  = [[InlineKeyboardButton(f"⭐ {n}", callback_data=f"fav:usar:{n}")]
                   for n in lista[:10]]
        await query.edit_message_reply_markup(InlineKeyboardMarkup(botoes))


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
        await update.message.reply_text(
            "Uso: `/buscar <termo> [cliente:<nome>]`\n"
            "Ex: `/buscar aluguel 2026`  ou  `/buscar cliente:João`",
            parse_mode="Markdown",
        )
        return
    termo = " ".join(context.args)
    await _executar_busca(update.message, termo)


async def _executar_busca(message, termo: str):
    # Extrai filtro de cliente: "cliente:João" ou "do cliente João"
    import re as _re
    cliente = None
    m = _re.search(r"cliente:([\w\s]+)", termo, _re.IGNORECASE)
    if m:
        cliente = m.group(1).strip()
        termo   = _re.sub(r"cliente:[\w\s]+", "", termo, flags=_re.IGNORECASE).strip()
    await message.reply_text(f"🔎 Buscando '{termo}'{f' (cliente: {cliente})' if cliente else ''}...")
    try:
        ini, fim = busca.parse_periodo_livre(termo)
        r = busca.buscar(termo, ini, fim, cliente=cliente)
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
    args   = export.parse_export_args(periodo_txt)
    ini, fim, tipo, status = args["ini"], args["fim"], args["tipo"], args["status"]
    tipo_str = f" ({tipo.lower()})" if tipo != "AMBOS" else ""
    await message.reply_text(f"📦 Gerando export {ini.strftime('%m/%Y')}{tipo_str}...")
    try:
        conteudo, nome = export.exportar_xlsx(ini, fim, tipo=tipo, status=status)
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


async def cmd_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    await update.message.reply_text("🏦 Consultando saldos...")
    try:
        contas = saldo_todas_contas()
        if not contas:
            await update.message.reply_text("Nenhuma conta encontrada.")
            return
        linhas = []
        total  = 0.0
        for c in contas:
            s = c.get("saldo")
            s_str = f"R$ {s:.2f}" if s is not None else "_(indisponível)_"
            emoji = "✅" if (s or 0) >= 0 else "⚠️"
            linhas.append(f"{emoji} *{c['nome']}*: {s_str}")
            if s is not None:
                total += s
        linhas.append(f"\n💰 *Total: R$ {total:.2f}*")
        await update.message.reply_text(
            "🏦 *Saldo das contas*\n\n" + "\n".join(linhas),
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao consultar saldos: {e}")


async def cmd_transferencias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    arg = " ".join(context.args) if context.args else ""
    await _executar_transferencias(update.message, arg)


async def _executar_transferencias(message, periodo_txt: str):
    from export import parse_periodo
    ini, fim = parse_periodo(periodo_txt)
    await message.reply_text(f"↔️ Consultando transferências {ini.strftime('%m/%Y')}...")
    try:
        itens = transferencias(ini, fim)
        if not itens:
            await message.reply_text("Nenhuma transferência encontrada no período.")
            return
        linhas = []
        for t in itens[:20]:
            orig = (t.get("conta_origem")  or t.get("conta_financeira_origem")  or {}).get("nome", "?")
            dest = (t.get("conta_destino") or t.get("conta_financeira_destino") or {}).get("nome", "?")
            v    = t.get("valor") or 0
            dt   = t.get("data") or t.get("data_transferencia") or ""
            linhas.append(f"↔️ {orig} → {dest}  R$ {v:.2f}  ({dt})")
        total = sum(t.get("valor", 0) for t in itens)
        await message.reply_text(
            f"↔️ *Transferências {ini.strftime('%m/%Y')}* ({len(itens)} total, R$ {total:.2f})\n\n"
            + "\n".join(linhas)
            + (f"\n_...e mais {len(itens) - 20}_" if len(itens) > 20 else ""),
            parse_mode="Markdown",
        )
    except Exception as e:
        await message.reply_text(f"❌ Erro ao consultar transferências: {e}")


async def cmd_projecao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Feature 2: projeção de caixa para os próximos 15 dias."""
    if not _ok(update):
        return
    await update.message.reply_text("📊 Calculando projeção de caixa...")
    try:
        p = projecao_caixa(15)
    except Exception as e:
        await update.message.reply_text(f"❌ Erro: {e}")
        return

    emoji_saldo = "✅" if p["saldo_projetado"] >= 0 else "🔴"
    alerta = ""
    if p["data_alerta"]:
        alerta = (
            f"\n\n🚨 *ALERTA:* Saldo pode ficar negativo em "
            f"*{p['dias_ate_negativo']} dias* ({p['data_alerta']})!"
        )

    await update.message.reply_text(
        f"📊 *Projeção de caixa — próximos {p['dias_simulados']} dias*\n\n"
        f"💰 Saldo atual:    R$ {p['saldo_atual']:,.2f}\n"
        f"📥 A receber:      R$ {p['a_receber']:,.2f}\n"
        f"📤 A pagar:        R$ {p['a_pagar']:,.2f}\n"
        f"{emoji_saldo} Saldo projetado: R$ {p['saldo_projetado']:,.2f}"
        f"{alerta}",
        parse_mode="Markdown",
    )


async def cmd_cliente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Feature 3: saldo total de um cliente/fornecedor."""
    if not _ok(update):
        return
    if not context.args:
        await update.message.reply_text(
            "Uso: `/cliente <nome>`\nEx: `/cliente João Silva`",
            parse_mode="Markdown",
        )
        return
    nome = " ".join(context.args)
    await update.message.reply_text(f"🔎 Consultando '{nome}'...")
    try:
        r = saldo_cliente(nome)
    except Exception as e:
        await update.message.reply_text(f"❌ Erro: {e}")
        return

    if r["parcelas_rec"] == 0 and r["parcelas_pag"] == 0:
        await update.message.reply_text(f"❓ Nenhum lançamento encontrado para '{nome}'.")
        return

    atras_str = f"\n⚠️ {r['atrasados']} parcela(s) em atraso" if r["atrasados"] else ""
    await update.message.reply_text(
        f"👤 *{nome}*\n\n"
        f"📥 A receber: R$ {r['a_receber']:,.2f} ({r['parcelas_rec']} parcela(s))\n"
        f"📤 A pagar:   R$ {r['a_pagar']:,.2f} ({r['parcelas_pag']} parcela(s))"
        f"{atras_str}",
        parse_mode="Markdown",
    )


async def cmd_recorrentes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Feature 5: detecta recorrentes e sugere relançar no próximo mês."""
    if not _ok(update):
        return
    await update.message.reply_text("🔄 Analisando lançamentos recorrentes...")
    from recorrentes import detectar_recorrentes, get_ignorados, salvar_ignorados
    try:
        sugestoes = detectar_recorrentes(meses=3)
    except Exception as e:
        await update.message.reply_text(f"❌ Erro: {e}")
        return

    ignorados = get_ignorados()
    sugestoes = [s for s in sugestoes if s["titulo_norm"] not in ignorados]

    if not sugestoes:
        await update.message.reply_text("✅ Nenhum lançamento recorrente sem relançamento no próximo mês.")
        return

    chat_id = update.effective_chat.id
    context.bot_data[f"recorr_{chat_id}"] = sugestoes

    for idx, s in enumerate(sugestoes[:8]):
        emoji = "📥" if s["tipo"] == "RECEBER" else "📤"
        await update.message.reply_text(
            f"{emoji} *{s['titulo_original']}*\n"
            f"R$ {s['valor_medio']:.2f} — apareceu {s['ocorrencias']}x\n"
            f"Sugestão: lançar para *{s['data_sugerida']}*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Lançar",   callback_data=f"recorr:lancar:{idx}:{chat_id}"),
                InlineKeyboardButton("🚫 Ignorar",  callback_data=f"recorr:ignorar:{idx}:{chat_id}"),
            ]]),
        )


async def callback_recorrente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Feature 5: processa confirmação/ignorar de sugestão recorrente."""
    query   = update.callback_query
    await query.answer()
    partes  = query.data.split(":")
    sub     = partes[1]
    idx     = int(partes[2])
    chat_id = int(partes[3])
    sugestoes = context.bot_data.get(f"recorr_{chat_id}", [])
    if idx >= len(sugestoes):
        await query.edit_message_text("⚠️ Sugestão expirada.")
        return
    s = sugestoes[idx]

    if sub == "ignorar":
        from recorrentes import salvar_ignorados
        salvar_ignorados([s["titulo_norm"]])
        await query.edit_message_text(f"🚫 *{s['titulo_original']}* ignorado.\nNão vou mais sugerir.",
                                       parse_mode="Markdown")
        return

    # sub == "lancar"
    await query.edit_message_text(f"⏳ Preparando lançamento de *{s['titulo_original']}*...",
                                   parse_mode="Markdown")
    await iniciar_selecao(update, context, {
        "tipo":        s["tipo"],
        "titulo":      s["titulo_original"],
        "valor":       s["valor_medio"],
        "vencimento":  s["data_sugerida"],
        "parcelas":    1,
        "termo_extra": s["titulo_norm"],
    })


async def cmd_fechar_mes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Feature 6: checklist de fechamento de mês."""
    if not _ok(update):
        return
    await update.message.reply_text("🗂️ Verificando checklist de fechamento...")
    try:
        from datetime import date as _date
        hoje  = _date.today()
        ini   = hoje.replace(day=1)
        resumo = resumo_mes()
        pend   = resumo["contas_receber"] + resumo["contas_pagar"]

        # Sem categoria
        sem_cat = [i for i in pend
                   if not (i.get("categoria") or i.get("categoria_id"))]
        # Sem centro de custo
        sem_cc  = [i for i in pend
                   if not (i.get("centro_custo") or i.get("centro_de_custo_id"))]
        # Em aberto (não baixados)
        em_aberto_rec = [i for i in resumo["contas_receber"]
                         if i.get("status") in ("EM_ABERTO", "ATRASADO")]
        em_aberto_pag = [i for i in resumo["contas_pagar"]
                         if i.get("status") in ("EM_ABERTO", "ATRASADO")]

        ok  = lambda cond: "✅" if cond else "❌"
        qtd = lambda lst: f"({len(lst)})"

        linhas = [
            f"{ok(not em_aberto_rec)} Recebimentos baixados   {qtd(em_aberto_rec) if em_aberto_rec else ''}",
            f"{ok(not em_aberto_pag)} Pagamentos baixados      {qtd(em_aberto_pag) if em_aberto_pag else ''}",
            f"{ok(not sem_cat)}  Todos com categoria     {qtd(sem_cat) if sem_cat else ''}",
            f"{ok(not sem_cc)}   Todos com centro custo  {qtd(sem_cc) if sem_cc else ''}",
            f"{'✅' if resumo['resultado'] >= 0 else '⚠️'} Resultado do mês:        R$ {resumo['resultado']:,.2f}",
        ]
        pendencias = sum(1 for l in linhas if l.startswith("❌"))
        status_geral = "✅ Mês pronto para fechar!" if pendencias == 0 else f"⚠️ {pendencias} pendência(s)"

        await update.message.reply_text(
            f"🗂️ *Checklist — {ini.strftime('%m/%Y')}*\n\n"
            + "\n".join(linhas)
            + f"\n\n{status_geral}",
            parse_mode="Markdown",
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Erro: {e}")


async def cmd_dre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Feature 2: DRE simplificado por categoria."""
    if not _ok(update):
        return
    arg = " ".join(context.args) if context.args else ""
    await _executar_dre(update.message, arg)


async def _executar_dre(message, periodo_txt: str):
    from comparar import _parse_mes
    from datetime import date
    mes = _parse_mes(periodo_txt) if periodo_txt.strip() else date.today().replace(day=1)
    if not mes:
        await message.reply_text("❌ Período inválido. Ex: `/dre abr` ou `/dre 04/2026`",
                                  parse_mode="Markdown")
        return
    await message.reply_text(f"📊 Gerando DRE de {mes.strftime('%m/%Y')}...")
    try:
        d = _dre.gerar_dre(mes)
        await message.reply_text(_dre.formatar_dre(d), parse_mode="Markdown")
    except Exception as e:
        await message.reply_text(f"❌ Erro ao gerar DRE: {e}")


async def cmd_aging(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Feature 3: Aging de recebíveis."""
    if not _ok(update):
        return
    arg  = " ".join(context.args).upper() if context.args else ""
    tipo = "PAGAR" if "PAG" in arg else "RECEBER"
    await update.message.reply_text(f"📋 Gerando aging de {'recebíveis' if tipo == 'RECEBER' else 'pagáveis'}...")
    try:
        a = _aging.gerar_aging(tipo)
        await update.message.reply_text(_aging.formatar_aging(a), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Erro no aging: {e}")


async def cmd_extrato_cliente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Feature 4: extrato histórico de um cliente."""
    if not _ok(update):
        return
    if not context.args:
        await update.message.reply_text(
            "Uso: `/extrato_cliente <nome>`", parse_mode="Markdown"
        )
        return
    nome = " ".join(context.args)
    await _executar_extrato_cliente(update.message, nome)


async def _executar_extrato_cliente(message, nome: str):
    await message.reply_text(f"📜 Buscando extrato de '{nome}'...")
    try:
        from consulta_financeira import saldo_cliente, _valor
        r = saldo_cliente(nome)
        if r["parcelas_rec"] == 0 and r["parcelas_pag"] == 0:
            await message.reply_text(f"❌ Nenhum lançamento encontrado para '{nome}'.")
            return
        linhas = [f"📜 *Extrato — {nome}*\n"]
        if r["itens_rec"]:
            linhas.append("📥 *A Receber / Recebidos:*")
            for i in r["itens_rec"]:
                st  = i.get("status", "")[:3]
                dt  = i.get("data_vencimento", "")
                v   = _valor(i)
                desc = (i.get("descricao") or "?")[:30]
                linhas.append(f"  [{st}] {dt}  R$ {v:,.2f}  {desc}")
        if r["itens_pag"]:
            linhas.append("\n📤 *A Pagar / Pagos:*")
            for i in r["itens_pag"]:
                st  = i.get("status", "")[:3]
                dt  = i.get("data_vencimento", "")
                v   = _valor(i)
                desc = (i.get("descricao") or "?")[:30]
                linhas.append(f"  [{st}] {dt}  R$ {v:,.2f}  {desc}")
        linhas.append(f"\n💰 Total a receber: R$ {r['a_receber']:,.2f}")
        linhas.append(f"💸 Total a pagar:   R$ {r['a_pagar']:,.2f}")
        await message.reply_text("\n".join(linhas), parse_mode="Markdown")
    except Exception as e:
        await message.reply_text(f"❌ Erro: {e}")


async def cmd_comparar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Feature 5: comparar dois meses."""
    if not _ok(update):
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Uso: `/comparar <mes_a> <mes_b>`\nEx: `/comparar abr mar`",
            parse_mode="Markdown",
        )
        return
    await _executar_comparar(update.message, context.args[0], context.args[1])


async def _executar_comparar(message, pa: str, pb: str):
    await message.reply_text(f"📊 Comparando {pa} vs {pb}...")
    try:
        c = _comparar.comparar(pa, pb)
        if not c:
            await message.reply_text("❌ Não consegui identificar os períodos. Use: `/comparar abr mar`",
                                      parse_mode="Markdown")
            return
        await message.reply_text(_comparar.formatar_comparacao(c), parse_mode="Markdown")
    except Exception as e:
        await message.reply_text(f"❌ Erro: {e}")


async def cmd_meta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Feature 6: consultar ou definir meta de faturamento."""
    if not _ok(update):
        return
    chat_id = update.effective_chat.id
    args    = context.args or []

    if args:
        # Define nova meta: /meta 20000 ou /meta receita 20000 ou /meta resultado 15000
        tipo = "receita"
        if args[0].lower() in ("receita", "resultado"):
            tipo = args[0].lower()
            args = args[1:]
        if not args:
            await update.message.reply_text("Uso: `/meta [receita|resultado] <valor>`",
                                             parse_mode="Markdown")
            return
        try:
            valor = float(args[0].replace(",", ".").replace("R$", "").strip())
        except ValueError:
            await update.message.reply_text("Valor inválido. Ex: `/meta 20000`",
                                             parse_mode="Markdown")
            return
        _meta.definir_meta(chat_id, valor, tipo)
        await update.message.reply_text(
            f"🎯 Meta de {tipo} definida: R$ {valor:,.2f}", parse_mode="Markdown"
        )
        return

    await _mostrar_meta(update.message, chat_id)


async def _mostrar_meta(message, chat_id: int):
    p = _meta.progresso(chat_id)
    if not p:
        await message.reply_text(
            "🎯 Nenhuma meta definida.\n\nUse: `/meta 20000` ou `/meta resultado 8000`",
            parse_mode="Markdown",
        )
        return
    barra = _meta.barra_progresso(p["pct"])
    emoji = "✅" if p["pct"] >= 100 else ("🟡" if p["pct"] >= 70 else "🔴")
    tipo_str = "Receita" if p["tipo"] == "receita" else "Resultado"
    await message.reply_text(
        f"🎯 *Meta de {tipo_str} — {p['dias_pass']}/{p['dias_mes']} dias*\n\n"
        f"{barra}  {p['pct']:.1f}%\n"
        f"Realizado:  R$ {p['realizado']:,.2f}\n"
        f"Meta:       R$ {p['meta_valor']:,.2f}\n"
        f"Faltam:     R$ {p['faltam']:,.2f}\n"
        f"Projeção:   R$ {p['projecao_fim']:,.2f}  {emoji}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✏️ Alterar meta", callback_data="meta:alterar"),
            InlineKeyboardButton("🗑️ Remover",     callback_data="meta:remover"),
        ]]),
    )


async def callback_meta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    sub     = query.data.split(":")[1]
    if sub == "remover":
        _meta.remover_meta(chat_id)
        await query.edit_message_text("🗑️ Meta removida.")
    elif sub == "alterar":
        context.user_data["aguardando_meta"] = True
        await query.edit_message_text(
            "✏️ Digite o novo valor da meta (ex: `25000`):", parse_mode="Markdown"
        )


async def cmd_historico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Feature 8: histórico de ações do bot."""
    if not _ok(update):
        return
    chat_id = update.effective_chat.id
    itens   = _historico.listar(chat_id, limite=15)
    if not itens:
        await update.message.reply_text("📋 Nenhuma ação registrada ainda.")
        return
    linhas = ["📋 *Últimas ações do bot:*\n"]
    for i in itens:
        linhas.append(f"`{i['ts']}`  *{i['acao']}*  {i['descricao']}")
    await update.message.reply_text("\n".join(linhas), parse_mode="Markdown")


async def cmd_config_alertas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Feature 9: configurar notificações."""
    if not _ok(update):
        return
    chat_id = update.effective_chat.id
    await _mostrar_config_alertas(update.message, chat_id)


async def _mostrar_config_alertas(message, chat_id: int):
    from config_alertas import ALERTAS_DISPONIVEIS, get_config
    cfg     = get_config(chat_id)
    botoes  = []
    for chave, label in ALERTAS_DISPONIVEIS.items():
        ativo  = cfg.get(chave, True)
        estado = "✅" if ativo else "🔕"
        botoes.append([InlineKeyboardButton(
            f"{estado} {label}",
            callback_data=f"cfg:{chave}:{'0' if ativo else '1'}:{chat_id}",
        )])
    await message.reply_text(
        "🔔 *Configurar alertas*\nToque para ligar/desligar:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(botoes),
    )


async def callback_config_alerta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    partes  = query.data.split(":")
    chave   = partes[1]
    novo    = partes[2] == "1"   # "1" = ativar
    chat_id = int(partes[3])
    _cfg.set_alerta(chat_id, chave, novo)
    # Re-renderiza o menu atualizado
    from config_alertas import ALERTAS_DISPONIVEIS, get_config
    cfg    = get_config(chat_id)
    botoes = []
    for k, label in ALERTAS_DISPONIVEIS.items():
        ativo  = cfg.get(k, True)
        estado = "✅" if ativo else "🔕"
        botoes.append([InlineKeyboardButton(
            f"{estado} {label}",
            callback_data=f"cfg:{k}:{'0' if ativo else '1'}:{chat_id}",
        )])
    await query.edit_message_reply_markup(InlineKeyboardMarkup(botoes))


async def cmd_editar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    if not context.args:
        await update.message.reply_text(
            "Uso: `/editar <descrição>` (ex: `/editar fatura energia`)",
            parse_mode="Markdown",
        )
        return
    termo = " ".join(context.args)
    await iniciar_edicao(update, context, termo, tipo="PAGAR")


# ─── Callbacks de lançamento ──────────────────────────────────────────────────

async def callback_lancar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    partes  = query.data.split(":")
    acao    = partes[1]
    user_id = int(partes[2])
    dados   = context.bot_data.pop(f"lancamento_{user_id}", None)

    if acao == "nao" or not dados:
        limpar_estado(context)
        await query.edit_message_text("❌ Lançamento cancelado.")
        return

    limpar_estado(context)
    await query.edit_message_text("⏳ Lançando no Conta Azul...")
    resultado = criar_lancamento(dados)

    if resultado["ok"]:
        tipo_emoji = "📥" if dados["tipo"] == "RECEBER" else "📤"
        id_str = resultado.get("id")
        sufixo = f"\nID: `{id_str}`" if id_str else ""
        # Guarda último lançamento para CANCELAR_ULTIMO (feature 8)
        if id_str:
            import time as _t
            context.user_data["ultimo_lancamento_id"]    = id_str
            context.user_data["ultimo_lancamento_dados"] = dados
            context.user_data["ultimo_lancamento_ts"]    = _t.time()
        # Registra no histórico
        _historico.registrar(
            "LANÇAMENTO",
            f"{dados.get('tipo','')} {dados.get('titulo','')[:50]} R$ {dados.get('valor',0):.2f}",
            update.effective_chat.id,
            {"id": id_str},
        )
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

    limpar_estado(context)
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
    elif acao == "SALDO":
        await cmd_saldo(update, context)
    elif acao == "TRANSFERENCIAS":
        await _executar_transferencias(msg, dados.get("periodo", ""))
    elif acao == "EDITAR_PARCELA":
        termo = dados.get("termo_extra") or dados.get("titulo") or texto
        await iniciar_edicao(update, context, termo, tipo="PAGAR")
    elif acao == "BAIXA":
        termo = dados.get("termo_extra") or dados.get("titulo") or texto
        await iniciar_baixa(update, context, termo, tipo="PAGAR")
    elif acao == "BAIXA_POR_VALOR":
        # Feature 8: busca parcela pelo valor informado
        v = dados.get("valor") or 0
        if not v:
            await msg.reply_text("⚠️ Não identifiquei o valor. Tente: _\"recebi R$ 500\"_",
                                  parse_mode="Markdown")
            return
        await msg.reply_text(f"🔎 Procurando parcela de R$ {v:.2f}...")
        try:
            r = busca.buscar(str(v), None, None)
            if not r:
                await msg.reply_text(f"Nenhuma parcela encontrada com valor ~ R$ {v:.2f}.")
                return
            melhor = min(r, key=lambda i: abs(_valor(i) - v))
            await iniciar_baixa(update, context,
                                melhor.get("descricao") or str(v), tipo="PAGAR")
        except Exception as e:
            await msg.reply_text(f"❌ Erro na busca por valor: {e}")
    elif acao == "BAIXA_LOTE":
        # Feature 3: baixar tudo que vence hoje
        await msg.reply_text(
            "💡 Para baixar tudo de hoje, use o briefing matinal ou /hoje."
        )
    elif acao == "CANCELAR_ULTIMO":
        # Feature 8: cancela sem confirmar se < 5 min, senão pede confirmação
        import time as _t
        ultimo_id    = context.user_data.get("ultimo_lancamento_id")
        ultimo_dados = context.user_data.get("ultimo_lancamento_dados", {})
        ultimo_ts    = context.user_data.get("ultimo_lancamento_ts", 0)
        if not ultimo_id:
            await msg.reply_text("⚠️ Nenhum lançamento recente para cancelar.")
            return
        desc            = ultimo_dados.get("titulo") or ultimo_id
        dentro_de_5min  = (_t.time() - ultimo_ts) < 300
        if dentro_de_5min:
            from baixa_parcela import patch_parcela
            try:
                patch_parcela(ultimo_id, {"status": "CANCELADO"})
                context.user_data.pop("ultimo_lancamento_id", None)
                context.user_data.pop("ultimo_lancamento_dados", None)
                context.user_data.pop("ultimo_lancamento_ts", None)
                await msg.reply_text(f"✅ Cancelado: *{desc}*", parse_mode="Markdown")
            except Exception as e:
                await msg.reply_text(f"❌ Erro ao cancelar: {e}")
        else:
            botoes = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Sim, cancelar",  callback_data=f"cancela_ultimo:sim:{ultimo_id}"),
                InlineKeyboardButton("❌ Não",            callback_data="cancela_ultimo:nao"),
            ]])
            await msg.reply_text(
                f"⚠️ Confirma cancelamento de *{desc}* (ID: `{ultimo_id}`)?\n"
                f"_(Esta ação não pode ser desfeita)_",
                parse_mode="Markdown",
                reply_markup=botoes,
            )
    elif acao == "DRE":
        await _executar_dre(msg, dados.get("periodo", ""))
    elif acao == "AGING":
        tipo = "PAGAR" if "PAG" in (dados.get("termo_extra") or "").upper() else "RECEBER"
        await msg.reply_text(f"📋 Gerando aging...")
        try:
            a = _aging.gerar_aging(tipo)
            await msg.reply_text(_aging.formatar_aging(a), parse_mode="Markdown")
        except Exception as e:
            await msg.reply_text(f"❌ Erro: {e}")
    elif acao == "EXTRATO_CLIENTE":
        nome = dados.get("cliente") or dados.get("termo_extra") or texto
        await _executar_extrato_cliente(msg, nome)
    elif acao == "COMPARAR":
        pa = dados.get("periodo") or ""
        pb = dados.get("termo_extra") or ""
        if pa and pb:
            await _executar_comparar(msg, pa, pb)
        else:
            await msg.reply_text("Para comparar, diga: _\"compare abril com março\"_",
                                  parse_mode="Markdown")
    elif acao == "META":
        await _mostrar_meta(msg, update.effective_chat.id)
    elif acao == "META_DEFINIR":
        valor = dados.get("valor") or 0
        tipo  = (dados.get("termo_extra") or "receita").lower()
        if tipo not in ("receita", "resultado"):
            tipo = "receita"
        if valor:
            _meta.definir_meta(update.effective_chat.id, float(valor), tipo)
            await msg.reply_text(f"🎯 Meta de {tipo}: R$ {float(valor):,.2f}",
                                  parse_mode="Markdown")
        else:
            await msg.reply_text("⚠️ Não identifiquei o valor da meta. Ex: _\"meta de receita 20000\"_",
                                  parse_mode="Markdown")
    elif acao == "HISTORICO":
        await cmd_historico(update, context)
    elif acao == "CONFIG_ALERTAS":
        await cmd_config_alertas(update, context)
    elif acao == "PROJECAO":
        await cmd_projecao(update, context)
    elif acao == "CLIENTE":
        nome = dados.get("cliente") or dados.get("termo_extra") or ""
        if nome:
            context.args = nome.split()
            await cmd_cliente(update, context)
        else:
            await msg.reply_text("Qual o nome do cliente/fornecedor?")
    elif acao == "FECHAR_MES":
        await cmd_fechar_mes(update, context)
    elif acao == "RECORRENTES":
        await cmd_recorrentes(update, context)
    elif acao == "HOJE":
        await enviar_briefing(context.application, update.effective_chat.id)
    elif acao == "FAVORITOS":
        await cmd_favoritos(update, context)
    elif acao == "FAVORITO_SALVAR":
        nome   = dados.get("titulo") or texto.replace("salvar como favorito", "").strip()
        ultimo = context.user_data.get("ultimo_lancamento_dados")
        if not ultimo or not nome:
            await msg.reply_text("⚠️ Não encontrei um lançamento recente para salvar.")
            return
        _favoritos.salvar_favorito(nome, ultimo)
        await msg.reply_text(f"⭐ Salvo como favorito: *{nome}*", parse_mode="Markdown")
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
        termo   = dados.get("termo_extra") or texto
        cliente = dados.get("cliente") or None
        await _executar_busca_com_cliente(msg, termo, cliente)
    elif acao == "EXPORT":
        await _executar_export(msg, dados.get("periodo", "") + " " + (dados.get("termo_extra") or ""))
    elif acao == "CONSULTA":
        # Feature 10: contexto enriquecido com saldo + resumo financeiro
        resumo = resumo_mes()
        try:
            contas = saldo_todas_contas()
            saldo_total = sum(c.get("saldo") or 0 for c in contas)
        except Exception:
            saldo_total = None
        ctx_dict = {k: v for k, v in resumo.items()
                    if k not in ("contas_receber", "contas_pagar")}
        if saldo_total is not None:
            ctx_dict["saldo_atual_contas"] = round(saldo_total, 2)
        ctx = json.dumps(ctx_dict, ensure_ascii=False)
        resp = responder_consulta(texto, ctx)
        await msg.reply_text(resp)
    else:
        await msg.reply_text(
            dados.get("mensagem") or "Não entendi. Tente reformular ou use /manual."
        )


# ─── Helper busca com cliente ─────────────────────────────────────────────────

async def _executar_busca_com_cliente(message, termo: str, cliente: str | None):
    await message.reply_text(
        f"🔎 Buscando '{termo}'{f' (cliente: {cliente})' if cliente else ''}..."
    )
    try:
        ini, fim = busca.parse_periodo_livre(termo)
        r = busca.buscar(termo, ini, fim, cliente=cliente)
        await message.reply_text(busca.formatar_resumo(termo, r), parse_mode="Markdown")
    except Exception as e:
        await message.reply_text(f"❌ Erro na busca: {e}")


# ─── Handler de texto ────────────────────────────────────────────────────────

async def handle_mensagem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return

    # Aguardando novo valor para meta
    if context.user_data.get("aguardando_meta"):
        texto = update.message.text.strip()
        try:
            valor = float(texto.replace(",", ".").replace("R$", "").strip())
            _meta.definir_meta(update.effective_chat.id, valor)
            context.user_data.pop("aguardando_meta", None)
            await update.message.reply_text(
                f"🎯 Meta atualizada: R$ {valor:,.2f}", parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("❌ Valor inválido. Digite apenas o número (ex: 20000).")
        return

    # Fluxos ativos com entrada de texto livre têm prioridade
    if await receber_texto_baixa(update, context):
        return
    if await receber_texto_edicao(update, context):
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
    doc  = update.message.document
    mime = doc.mime_type or "application/octet-stream"

    # Feature 7: XML de NF-e — tenta parsear antes de chamar Gemini
    if mime in ("text/xml", "application/xml") or (doc.file_name or "").lower().endswith(".xml"):
        await update.message.reply_text("🯧 Lendo XML de NF-e...")
        file      = await context.bot.get_file(doc.file_id)
        xml_bytes = bytes(await file.download_as_bytearray())
        dados     = parse_nfe(xml_bytes)
        if dados:
            await _mostrar_preview_nfe(update, context, dados)
            return
        # Não é NF-e válida — cai no fluxo normal
        await update.message.reply_text("⚠️ XML não reconhecido como NF-e. Tentando ler com IA...")
        dados = extrair_de_imagem(xml_bytes, mime)
        await _mostrar_preview_media(update, context, dados)
        return

    await update.message.reply_text("📄 Lendo documento...")
    file      = await context.bot.get_file(doc.file_id)
    img_bytes = await file.download_as_bytearray()
    dados     = extrair_de_imagem(bytes(img_bytes), mime)
    await _mostrar_preview_media(update, context, dados)


async def _mostrar_preview_nfe(
    update: Update, context: ContextTypes.DEFAULT_TYPE, dados: dict
):
    """Feature 7: mostra card formatado de NF-e antes de lançar."""
    user_id = update.effective_user.id
    context.bot_data[f"preview_{user_id}"] = dados

    dups = dados.get("duplicatas", [])
    parc_str = (
        f"{len(dups)}x parcelas" if len(dups) > 1
        else f"1x R$ {dados['valor']:.2f}"
    )
    dup_linhas = ""
    if len(dups) > 1:
        dup_linhas = "\n" + "\n".join(
            f"  {i+1}. R$ {d['valor']:.2f} — {d['vencimento']}"
            for i, d in enumerate(dups[:5])
        )

    texto = (
        f"🧧 *NF-e detectada:*\n\n"
        f"  Emitente: {dados.get('emitente', '?')}\n"
        f"  CNPJ:     {dados.get('cnpj', '?')}\n"
        f"  Número:   {dados.get('numero_nf', '?')}\n"
        f"  Op.:      {dados.get('nat_op', '?')}\n"
        f"  Valor:    R$ {dados['valor']:,.2f}\n"
        f"  Vcto:     {dados['vencimento']}\n"
        f"  Parcelas: {parc_str}"
        f"{dup_linhas}\n\n"
        f"Lançar como *despesa* (conta a pagar)?"
    )
    await update.message.reply_text(
        texto,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Confirmar", callback_data=f"preview:confirmar:{user_id}"),
            InlineKeyboardButton("❌ Cancelar",  callback_data=f"preview:cancelar:{user_id}"),
        ]]),
    )


async def handle_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _ok(update):
        return
    await update.message.reply_text("📷 Lendo imagem...")
    foto  = update.message.photo[-1]
    file  = await context.bot.get_file(foto.file_id)
    dados = extrair_de_imagem(await file.download_as_bytearray(), "image/jpeg")
    await _mostrar_preview_media(update, context, dados)


async def _mostrar_preview_media(
    update: Update, context: ContextTypes.DEFAULT_TYPE, dados: dict
):
    """Feature 4: exibe prévia do lançamento extraído com botões Confirmar/Editar/Cancelar."""
    user_id = update.effective_user.id
    context.bot_data[f"preview_{user_id}"] = dados

    acao   = dados.get("acao", "?")
    tipo   = "📥 Receita" if acao == "RECEBER" else "📤 Despesa" if acao == "PAGAR" else acao
    v      = dados.get("valor") or 0
    dt     = dados.get("vencimento") or "hoje"
    titulo = dados.get("titulo") or "(sem título)"
    cat    = dados.get("categoria") or "(sem categoria)"

    texto = (
        f"🔍 *Prévia do lançamento:*\n\n"
        f"  Tipo:       {tipo}\n"
        f"  Título:     {titulo}\n"
        f"  Valor:      R$ {v:.2f}\n"
        f"  Vencimento: {dt}\n"
        f"  Categoria:  {cat}\n\n"
        f"Confirmar esse lançamento?"
    )
    botoes = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirmar", callback_data=f"preview:confirmar:{user_id}"),
        InlineKeyboardButton("✏️ Editar",   callback_data=f"preview:editar:{user_id}"),
        InlineKeyboardButton("❌ Cancelar", callback_data=f"preview:cancelar:{user_id}"),
    ]])
    await update.message.reply_text(texto, parse_mode="Markdown", reply_markup=botoes)


async def callback_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Feature 4: trata botões de confirmação/edição/cancelamento da prévia."""
    query   = update.callback_query
    await query.answer()
    partes  = query.data.split(":")
    sub     = partes[1]
    user_id = int(partes[2])
    dados   = context.bot_data.pop(f"preview_{user_id}", None)

    if sub == "cancelar" or not dados:
        await query.edit_message_text("❌ Lançamento cancelado.")
        return

    if sub == "editar":
        context.bot_data[f"preview_{user_id}"] = dados  # repõe para o fluxo editar
        await query.edit_message_text(
            "✏️ O que deseja alterar? (ex: _\"valor 250\"_, _\"vencimento 30/06\"_)",
            parse_mode="Markdown",
        )
        context.user_data["editando_preview"] = dados
        return

    # sub == "confirmar"
    await query.edit_message_text("⏳ Lançando no Conta Azul...")
    await iniciar_selecao(update, context, {
        "tipo":        dados.get("acao", "PAGAR"),
        "titulo":      dados.get("titulo", ""),
        "valor":       dados.get("valor", 0),
        "vencimento":  dados.get("vencimento", str(date.today())),
        "parcelas":    dados.get("parcelas", 1),
        "termo_extra": dados.get("titulo", ""),
    })


# ─── Callback alerta vencimento (D-1/D-3 botões) ────────────────────────────

async def callback_alerta_venc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    partes   = query.data.split(":")
    sub      = partes[1]
    idx      = int(partes[2])
    chat_id  = int(partes[3])
    alertas  = context.bot_data.get(f"alertas_venc_{chat_id}", [])
    if idx >= len(alertas):
        await query.edit_message_text("⚠️ Alerta expirado.")
        return
    item = alertas[idx]

    if sub == "baixa":
        termo = item.get("descricao") or str(_valor(item))
        await query.edit_message_text(f"⏳ Iniciando baixa de *{termo}*...",
                                      parse_mode="Markdown")
        await iniciar_baixa(update, context, termo, tipo="PAGAR")

    elif sub == "lembrar":
        desc = item.get("descricao") or "parcela"
        from datetime import datetime
        dt_hoje = date.today()
        hora_lembrete = datetime(dt_hoje.year, dt_hoje.month, dt_hoje.day, 18, 0)
        context.job_queue.run_once(
            _cb_lembrete_18h,
            when=hora_lembrete,
            chat_id=chat_id,
            data={"desc": desc, "valor": _valor(item)},
        )
        await query.edit_message_text(f"⏰ Lembrete agendado para hoje às 18h: *{desc}*",
                                      parse_mode="Markdown")


async def _cb_lembrete_18h(context):
    job  = context.job
    d    = job.data or {}
    desc = d.get("desc", "parcela")
    v    = d.get("valor", 0)
    await context.bot.send_message(
        chat_id=job.chat_id,
        text=f"⏰ *Lembrete:* {desc} — R$ {v:.2f}\nVence hoje!",
        parse_mode="Markdown",
    )


async def callback_cancela_ultimo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Feature 7: processa confirmação de cancelamento do último lançamento."""
    query  = update.callback_query
    await query.answer()
    partes = query.data.split(":")
    sub    = partes[1]
    if sub == "nao":
        await query.edit_message_text("↩️ Cancelamento abortado.")
        return
    # sub == "sim"
    lancamento_id = partes[2]
    from baixa_parcela import patch_parcela
    try:
        patch_parcela(lancamento_id, {"status": "CANCELADO"})
        context.user_data.pop("ultimo_lancamento_id", None)
        context.user_data.pop("ultimo_lancamento_dados", None)
        await query.edit_message_text(f"✅ Lançamento `{lancamento_id}` cancelado.",
                                      parse_mode="Markdown")
    except Exception as e:
        await query.edit_message_text(f"❌ Erro ao cancelar: {e}")


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
    persistence = PicklePersistence(filepath="bot_persistence.pkl")
    app = Application.builder().token(TELEGRAM_TOKEN).persistence(persistence).build()

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
    app.add_handler(CommandHandler("saldo",             cmd_saldo))
    app.add_handler(CommandHandler("transferencias",    cmd_transferencias))
    app.add_handler(CommandHandler("editar",            cmd_editar))
    app.add_handler(CommandHandler("hoje",              cmd_hoje))
    app.add_handler(CommandHandler("favoritos",         cmd_favoritos))
    app.add_handler(CommandHandler("projecao",          cmd_projecao))
    app.add_handler(CommandHandler("cliente",           cmd_cliente))
    app.add_handler(CommandHandler("recorrentes",       cmd_recorrentes))
    app.add_handler(CommandHandler("fechar_mes",        cmd_fechar_mes))
    app.add_handler(CommandHandler("dre",               cmd_dre))
    app.add_handler(CommandHandler("aging",             cmd_aging))
    app.add_handler(CommandHandler("extrato_cliente",   cmd_extrato_cliente))
    app.add_handler(CommandHandler("comparar",          cmd_comparar))
    app.add_handler(CommandHandler("meta",              cmd_meta))
    app.add_handler(CommandHandler("historico",         cmd_historico))
    app.add_handler(CommandHandler("config_alertas",    cmd_config_alertas))

    app.add_handler(CallbackQueryHandler(callback_meta,          pattern="^meta:"))
    app.add_handler(CallbackQueryHandler(callback_config_alerta, pattern="^cfg:"))
    app.add_handler(CallbackQueryHandler(callback_pendente,    pattern="^pend:"))
    app.add_handler(CallbackQueryHandler(callback_recorrente,  pattern="^recorr:"))
    app.add_handler(CallbackQueryHandler(callback_selecao, pattern="^sel:"))
    app.add_handler(CallbackQueryHandler(callback_lancar,  pattern="^lancar:"))
    app.add_handler(CallbackQueryHandler(callback_forcar,  pattern="^forcar:"))
    app.add_handler(CallbackQueryHandler(callback_editar,  pattern="^edit:"))
    app.add_handler(CallbackQueryHandler(callback_baixa,          pattern="^baixa:"))
    app.add_handler(CallbackQueryHandler(callback_grafico,        pattern="^graf:"))
    app.add_handler(CallbackQueryHandler(callback_editar_parcela, pattern="^editpar:"))
    app.add_handler(CallbackQueryHandler(callback_daily,          pattern="^daily:"))
    app.add_handler(CallbackQueryHandler(callback_alerta_rec,     pattern="^alerta_rec:"))
    app.add_handler(CallbackQueryHandler(callback_alerta_venc,    pattern="^alerta_venc:"))
    app.add_handler(CallbackQueryHandler(callback_preview,        pattern="^preview:"))
    app.add_handler(CallbackQueryHandler(callback_favorito,       pattern="^fav:"))
    app.add_handler(CallbackQueryHandler(callback_cancela_ultimo, pattern="^cancela_ultimo:"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: u.callback_query.answer("✅ Dia conferido!"),
        pattern="^fechamento:ok$",
    ))

    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, handle_novo_membro))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO,         handle_voz))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,       handle_mensagem))
    app.add_handler(MessageHandler(filters.Document.ALL,                  handle_documento))
    app.add_handler(MessageHandler(filters.PHOTO,                         handle_foto))

    app.add_error_handler(handle_erro)

    iniciar(app, TELEGRAM_ALLOWED_CHAT_IDS)
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
