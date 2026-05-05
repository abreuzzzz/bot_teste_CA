import re
from calendar import monthrange
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import date, timedelta
from consulta_financeira import _valor
from config_alertas import is_ativo


def _esc(texto: str) -> str:
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!\\])", r"\\\1", str(texto))


def iniciar(app, chat_ids):
    """Agenda todos os jobs para cada chat autorizado."""
    if isinstance(chat_ids, int):
        chat_ids = [chat_ids]
    scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")
    for chat_id in chat_ids:
        # Feature 1: Briefing personalizado
        scheduler.add_job(_briefing_diario,   "cron", hour=8,  minute=0,
                          args=[app, chat_id])
        # Feature 5: Alertas D-1 e D-3 por parcela individual
        scheduler.add_job(_alertas_vencimento, "cron", hour=8, minute=30,
                          args=[app, chat_id])
        # Feature 6: Alertas de recebimentos em atraso
        scheduler.add_job(_alertas_recebimentos, "cron", hour=9, minute=0,
                          args=[app, chat_id])
        # Feature 2 (novo): Alerta de projeção negativa de caixa
        scheduler.add_job(_alerta_projecao_caixa, "cron", hour=9, minute=15,
                          args=[app, chat_id])
        # Feature 9: Resumo semanal visual
        scheduler.add_job(_resumo_semanal_visual, "cron", day_of_week="fri", hour=17, minute=0,
                          args=[app, chat_id])
        # Feature 5 (novo): Sugestão de recorrentes toda segunda-feira
        scheduler.add_job(_sugerir_recorrentes, "cron", day_of_week="mon", hour=9, minute=45,
                          args=[app, chat_id])
        # Relatório mensal
        scheduler.add_job(_relatorio_mensal,  "cron", day="last", hour=18, minute=0,
                          args=[app, chat_id])
        # Orçamento
        scheduler.add_job(_checar_orcamento,  "cron", hour=9, minute=30,
                          args=[app, chat_id])
        # Fechamento do dia
        scheduler.add_job(_fechamento_dia, "cron", hour=17, minute=0,
                          args=[app, chat_id])
    scheduler.start()
    print(f"[SCHEDULER] Jobs agendados para {len(chat_ids)} chat(s).")


# ─── Relatório diário ─────────────────────────────────────────────────────────

async def _relatorio_diario(app, chat_id: int):
    from consulta_financeira import resumo_mes, pendentes, atrasados

    hoje   = date.today()
    resumo = resumo_mes()
    pend   = pendentes(dias=7)
    atras  = atrasados()

    if pend:
        linhas_pend = "\n".join(
            f"  {'📥' if i['tipo'] == 'RECEBER' else '📤'} "
            f"{_esc(i.get('descricao', '?')[:30])} — R$ {_esc('{:.2f}'.format(_valor(i)))} "
            f"\\({_esc(i.get('data_vencimento', ''))}\\)"
            for i in pend[:5]
        )
    else:
        linhas_pend = "  _\\(nenhum\\)_"

    if atras:
        linhas_atras = "\n".join(
            f"  ⚠️ {_esc(i.get('descricao', '?')[:30])} — R$ {_esc('{:.2f}'.format(_valor(i)))} "
            f"\\({_esc(i.get('data_vencimento', ''))}\\)"
            for i in atras[:5]
        )
    else:
        linhas_atras = "  _\\(nenhum\\)_"

    alerta_saldo = ""
    if resumo["saldo_projetado"] < 0:
        alerta_saldo = (f"\n⚠️ *ALERTA: Saldo projetado negativo\\!* "
                        f"R$ {_esc('{:.2f}'.format(resumo['saldo_projetado']))}\n")

    msg = (
        f"☀️ *Bom dia\\! Relatório de {_esc(hoje.strftime('%d/%m/%Y'))}*\n\n"
        f"📊 *Mês atual \\({_esc(resumo['periodo'])}\\):*\n"
        f"  📥 A receber: R$ {_esc('{:.2f}'.format(resumo['total_receber']))}\n"
        f"  📤 A pagar:   R$ {_esc('{:.2f}'.format(resumo['total_pagar']))}\n"
        f"  ✅ Recebido:  R$ {_esc('{:.2f}'.format(resumo['recebido']))}\n"
        f"  ✅ Pago:      R$ {_esc('{:.2f}'.format(resumo['pago']))}\n"
        f"  💰 Resultado: R$ {_esc('{:.2f}'.format(resumo['resultado']))}\n"
        f"{alerta_saldo}\n"
        f"📅 *Próximos 7 dias:*\n{linhas_pend}\n\n"
        f"🚨 *Atrasados:*\n{linhas_atras}"
    )

    await _enviar(app, chat_id, msg, fallback=lambda: _plain_diario(hoje, resumo, pend, atras))


def _plain_diario(hoje, resumo, pend, atras):
    return (
        f"Relatório de {hoje.strftime('%d/%m/%Y')}\n\n"
        f"Mês ({resumo['periodo']}):\n"
        f"  A receber: R$ {resumo['total_receber']:.2f}\n"
        f"  A pagar:   R$ {resumo['total_pagar']:.2f}\n"
        f"  Resultado: R$ {resumo['resultado']:.2f}\n\n"
        f"Pendentes 7d: {len(pend)} | Atrasados: {len(atras)}"
    )


# ─── Relatório semanal ────────────────────────────────────────────────────────

async def _relatorio_semanal(app, chat_id: int):
    from datetime import timedelta
    from consulta_financeira import _buscar, _valor_pago, STATUS_RECEBIDO

    fim = date.today()
    ini = fim - timedelta(days=6)
    p = {"data_vencimento_de": str(ini), "data_vencimento_ate": str(fim)}
    rec = _buscar("contas-a-receber/buscar", p)
    pag = _buscar("contas-a-pagar/buscar",   p)
    recebido = sum(_valor_pago(i) for i in rec if i.get("status") in STATUS_RECEBIDO)
    pago     = sum(_valor_pago(i) for i in pag if i.get("status") in STATUS_RECEBIDO)
    res = recebido - pago

    msg = (
        f"📆 *Relatório semanal* \\({_esc(ini.strftime('%d/%m'))} a {_esc(fim.strftime('%d/%m'))}\\)\n\n"
        f"  📥 Recebido: R$ {_esc('{:.2f}'.format(recebido))}\n"
        f"  📤 Pago:     R$ {_esc('{:.2f}'.format(pago))}\n"
        f"  💰 Saldo:    R$ {_esc('{:.2f}'.format(res))}\n\n"
        f"Lançamentos: {len(rec)} a receber, {len(pag)} a pagar."
    )
    await _enviar(app, chat_id, msg,
                  fallback=lambda: f"Semana {ini}–{fim}: recebido {recebido:.2f}, pago {pago:.2f}, saldo {res:.2f}")


# ─── Feature 1: Briefing diário ──────────────────────────────────────────────

async def _briefing_diario(app, chat_id: int):
    if not is_ativo(chat_id, "briefing"):
        return
    from daily_flow import enviar_briefing
    try:
        await enviar_briefing(app, chat_id)
    except Exception as e:
        print(f"[SCHEDULER] Erro briefing: {e}")
        await _relatorio_diario(app, chat_id)


# ─── Feature 2: Alerta proativo de projeção de caixa negativa ────────────────

async def _alerta_projecao_caixa(app, chat_id: int):
    if not is_ativo(chat_id, "projecao"):
        return
    from consulta_financeira import projecao_caixa
    try:
        p = projecao_caixa(15)
    except Exception as e:
        print(f"[SCHEDULER] Erro projeção: {e}")
        return
    # Só envia se a projeção ficar negativa dentro de 15 dias
    if p["data_alerta"] is None:
        return
    try:
        await app.bot.send_message(
            chat_id=chat_id,
            text=(
                f"🚨 *Alerta de caixa*\n\n"
                f"Seu saldo pode ficar negativo em *{p['dias_ate_negativo']} dia(s)* "
                f"({p['data_alerta']}).\n\n"
                f"💰 Saldo atual: R$ {p['saldo_atual']:,.2f}\n"
                f"📥 A receber:   R$ {p['a_receber']:,.2f}\n"
                f"📤 A pagar:     R$ {p['a_pagar']:,.2f}\n"
                f"🔴 Projetado:   R$ {p['saldo_projetado']:,.2f}"
            ),
            parse_mode="Markdown",
        )
    except Exception as e:
        print(f"[SCHEDULER] Erro alerta projeção: {e}")


# ─── Feature 5d: Alertas D-1/D-3 individuais ─────────────────────────────────

async def _alertas_vencimento(app, chat_id: int):
    if not is_ativo(chat_id, "vencimento"):
        return
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from consulta_financeira import _buscar, _valor

    hoje = date.today()
    alertas = []
    for dias_aviso in (1, 3):
        alvo = hoje + timedelta(days=dias_aviso)
        p = {"data_vencimento_de": str(alvo), "data_vencimento_ate": str(alvo),
             "status": ["EM_ABERTO"]}
        for i in _buscar("contas-a-pagar/buscar", p):
            alertas.append({"dias": dias_aviso, "data": alvo, "tipo": "PAGAR", **i})
        for i in _buscar("contas-a-receber/buscar", p):
            alertas.append({"dias": dias_aviso, "data": alvo, "tipo": "RECEBER", **i})

    if not alertas:
        return
    app.bot_data[f"alertas_venc_{chat_id}"] = alertas

    for idx, item in enumerate(alertas[:10]):
        desc    = (item.get("descricao") or "?")[:40]
        v       = _valor(item)
        dias    = item["dias"]
        dt_str  = item["data"].strftime("%d/%m/%Y")
        emoji   = "📥" if item["tipo"] == "RECEBER" else "📤"
        urgencia = "🔴" if dias == 1 else "⚠️"
        quando   = "amanhã" if dias == 1 else f"em {dias} dias"
        botoes  = [[InlineKeyboardButton("⏰ Lembrar às 18h",
                                         callback_data=f"alerta_venc:lembrar:{idx}:{chat_id}")]]
        if item["tipo"] == "PAGAR":
            botoes.insert(0, [InlineKeyboardButton("💳 Dar baixa antecipada",
                                                    callback_data=f"alerta_venc:baixa:{idx}:{chat_id}")])
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text=f"{urgencia} *Vence {quando}*\n\n{emoji} {desc}\nR$ {v:.2f} — {dt_str}",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(botoes),
            )
        except Exception as e:
            print(f"[SCHEDULER] Erro alerta venc idx={idx}: {e}")


# ─── Feature 6: Alertas de recebimentos atrasados ────────────────────────────

async def _alertas_recebimentos(app, chat_id: int):
    if not is_ativo(chat_id, "recebimentos"):
        return
    from daily_flow import enviar_alerta_recebimentos
    try:
        await enviar_alerta_recebimentos(app, chat_id)
    except Exception as e:
        print(f"[SCHEDULER] Erro alertas recebimentos: {e}")


# ─── Feature 5e: Sugestão de recorrentes toda segunda-feira ──────────────────

async def _sugerir_recorrentes(app, chat_id: int):
    if not is_ativo(chat_id, "recorrentes"):
        return
    from recorrentes import detectar_recorrentes, get_ignorados
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    try:
        sugestoes = detectar_recorrentes(meses=3)
    except Exception as e:
        print(f"[SCHEDULER] Erro recorrentes: {e}")
        return
    ignorados = get_ignorados()
    sugestoes = [s for s in sugestoes if s["titulo_norm"] not in ignorados][:5]
    if not sugestoes:
        return
    app.bot_data[f"recorr_{chat_id}"] = sugestoes
    for idx, s in enumerate(sugestoes):
        emoji = "📥" if s["tipo"] == "RECEBER" else "📤"
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🔄 *Recorrente detectado*\n\n"
                    f"{emoji} *{s['titulo_original']}*\n"
                    f"R$ {s['valor_medio']:.2f} — apareceu {s['ocorrencias']}x\n"
                    f"Sugestão: lançar para *{s['data_sugerida']}*"
                ),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Lançar",  callback_data=f"recorr:lancar:{idx}:{chat_id}"),
                    InlineKeyboardButton("🚫 Ignorar", callback_data=f"recorr:ignorar:{idx}:{chat_id}"),
                ]]),
            )
        except Exception as e:
            print(f"[SCHEDULER] Erro sugestão recorrente: {e}")


# ─── Feature 9: Resumo semanal visual ────────────────────────────────────────

async def _resumo_semanal_visual(app, chat_id: int):
    if not is_ativo(chat_id, "semanal"):
        return
    from consulta_financeira import _buscar, _valor_pago, STATUS_RECEBIDO

    fim = date.today()
    ini = fim - timedelta(days=6)
    p   = {"data_vencimento_de": str(ini), "data_vencimento_ate": str(fim)}
    rec = _buscar("contas-a-receber/buscar", p)
    pag = _buscar("contas-a-pagar/buscar",   p)

    recebido  = sum(_valor_pago(i) for i in rec if i.get("status") in STATUS_RECEBIDO)
    pago      = sum(_valor_pago(i) for i in pag if i.get("status") in STATUS_RECEBIDO)
    resultado = recebido - pago

    # Semana anterior
    ini_ant = ini - timedelta(days=7)
    fim_ant = fim - timedelta(days=7)
    p_ant   = {"data_vencimento_de": str(ini_ant), "data_vencimento_ate": str(fim_ant)}
    rec_ant = _buscar("contas-a-receber/buscar", p_ant)
    pag_ant = _buscar("contas-a-pagar/buscar",   p_ant)
    res_ant = (sum(_valor_pago(i) for i in rec_ant if i.get("status") in STATUS_RECEBIDO)
               - sum(_valor_pago(i) for i in pag_ant if i.get("status") in STATUS_RECEBIDO))

    def _barra(v: float, maximo: float, t: int = 8) -> str:
        if maximo <= 0:
            return "░" * t
        cheios = min(int(round((v / maximo) * t)), t)
        return "█" * cheios + "░" * (t - cheios)

    maximo    = max(recebido, pago, 1)
    barra_rec = _barra(recebido, maximo)
    barra_pag = _barra(pago, maximo)

    if res_ant != 0:
        var      = ((resultado - res_ant) / abs(res_ant)) * 100
        var_str  = f"▲ {var:.0f}%" if var >= 0 else f"▼ {abs(var):.0f}%"
        var_emoji = "🟢" if var >= 0 else "🔴"
    else:
        var_str, var_emoji = "primeiro período", "🟡"

    emoji_res = "✅" if resultado >= 0 else "🔴"
    texto = (
        f"📊 *Resumo da semana* ({ini.strftime('%d/%m')} – {fim.strftime('%d/%m')})\n\n"
        f"Entrou: R$ {recebido:>9,.2f}  {barra_rec}\n"
        f"Saiu:   R$ {pago:>9,.2f}  {barra_pag}\n"
        f"Sobrou: R$ {resultado:>9,.2f}  {emoji_res}\n\n"
        f"{var_emoji} vs semana anterior: R$ {res_ant:.2f} ({var_str})\n"
        f"📋 {len(rec)} receb., {len(pag)} pagam."
    )
    try:
        await app.bot.send_message(chat_id=chat_id, text=texto, parse_mode="Markdown")
    except Exception as e:
        print(f"[SCHEDULER] Erro resumo semanal: {e}")
        try:
            await app.bot.send_message(chat_id=chat_id, text=texto.replace("*", ""))
        except Exception:
            pass


# ─── Relatório mensal ────────────────────────────────────────────────────────

async def _relatorio_mensal(app, chat_id: int):
    if not is_ativo(chat_id, "mensal"):
        return
    from consulta_financeira import resumo_mes
    hoje = date.today()
    # Só executa se for o último dia do mês (cron day="last" já garante,
    # mas validamos por segurança).
    if hoje.day != monthrange(hoje.year, hoje.month)[1]:
        return
    resumo = resumo_mes()
    msg = (
        f"📅 *Fechamento mensal* — {_esc(hoje.strftime('%B/%Y'))}\n\n"
        f"  📥 A receber: R$ {_esc('{:.2f}'.format(resumo['total_receber']))}\n"
        f"  📤 A pagar:   R$ {_esc('{:.2f}'.format(resumo['total_pagar']))}\n"
        f"  ✅ Recebido:  R$ {_esc('{:.2f}'.format(resumo['recebido']))}\n"
        f"  ✅ Pago:      R$ {_esc('{:.2f}'.format(resumo['pago']))}\n"
        f"  💰 Resultado: R$ {_esc('{:.2f}'.format(resumo['resultado']))}\n\n"
        f"Atrasados: {resumo['atrasados_receber']} a receber, {resumo['atrasados_pagar']} a pagar\\."
    )
    await _enviar(app, chat_id, msg,
                  fallback=lambda: f"Fechamento {hoje.strftime('%m/%Y')}: resultado {resumo['resultado']:.2f}")


# ─── Alertas de orçamento ─────────────────────────────────────────────────────

async def _checar_orcamento(app, chat_id: int):
    if not is_ativo(chat_id, "orcamento"):
        return
    try:
        from orcamento import checar_alertas
        novos = checar_alertas()
    except Exception as e:
        print(f"[SCHEDULER] Erro checagem orçamento: {e}")
        return
    if not novos:
        return
    linhas = []
    for a in novos:
        emoji = "🚨" if a["nivel"] == "100" else "⚠️"
        pct_str = "{:.0f}".format(a["pct"])
        linhas.append(
            f"{emoji} *{_esc(a['categoria'])}*: "
            f"R$ {_esc('{:.2f}'.format(a['gasto']))} de R$ {_esc('{:.2f}'.format(a['limite']))} "
            f"\\({_esc(pct_str)}%\\)"
        )
    msg = "💡 *Alerta de orçamento*\n\n" + "\n".join(linhas)
    await _enviar(app, chat_id, msg,
                  fallback=lambda: "Alerta de orçamento: " + "; ".join(
                      f"{a['categoria']} {a['pct']:.0f}%" for a in novos))

# ─── Feature 10: Fechamento do dia ─────────────────────────────────────────────────

async def _fechamento_dia(app, chat_id: int):
    if not is_ativo(chat_id, "fechamento"):
        return
    from consulta_financeira import _buscar, _valor_pago, STATUS_RECEBIDO
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    hoje = date.today()
    amanha = hoje + timedelta(days=1)

    # Recebido hoje
    p_hoje = {"data_vencimento_de": str(hoje), "data_vencimento_ate": str(hoje)}
    rec_hoje = _buscar("contas-a-receber/buscar", p_hoje)
    pag_hoje = _buscar("contas-a-pagar/buscar",   p_hoje)
    recebido  = sum(_valor_pago(i) for i in rec_hoje if i.get("status") in STATUS_RECEBIDO)
    pago      = sum(_valor_pago(i) for i in pag_hoje if i.get("status") in STATUS_RECEBIDO)

    # Vencer amanha
    p_amanha = {"data_vencimento_de": str(amanha), "data_vencimento_ate": str(amanha),
                "status": ["EM_ABERTO"]}
    rec_am = _buscar("contas-a-receber/buscar", p_amanha)
    pag_am = _buscar("contas-a-pagar/buscar",   p_amanha)
    total_amanha_rec = sum(_valor(i) for i in rec_am)
    total_amanha_pag = sum(_valor(i) for i in pag_am)

    texto = (
        f"🌅 *Fechamento do dia — {hoje.strftime('%d/%m/%Y')}*\n\n"
        f"  ✅ Recebido hoje:  R$ {recebido:,.2f} ({len([i for i in rec_hoje if i.get('status') in STATUS_RECEBIDO])} parcelas)\n"
        f"  ✅ Pago hoje:      R$ {pago:,.2f} ({len([i for i in pag_hoje if i.get('status') in STATUS_RECEBIDO])} parcelas)\n\n"
        f"  📅 Vence amanhã (📥):  R$ {total_amanha_rec:,.2f} ({len(rec_am)} parcelas)\n"
        f"  📅 Vence amanhã (📤):  R$ {total_amanha_pag:,.2f} ({len(pag_am)} parcelas)"
    )
    try:
        await app.bot.send_message(
            chat_id=chat_id,
            text=texto,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Dia conferido", callback_data="fechamento:ok"),
            ]]),
        )
    except Exception as e:
        print(f"[SCHEDULER] Erro fechamento_dia: {e}")

# ─── Helper de envio com fallback plain ───────────────────────────────────────

async def _enviar(app, chat_id, msg_md, fallback=None):
    try:
        await app.bot.send_message(chat_id=chat_id, text=msg_md, parse_mode="MarkdownV2")
    except Exception as e:
        print(f"[SCHEDULER] Erro envio MarkdownV2: {e}")
        if fallback:
            try:
                await app.bot.send_message(chat_id=chat_id, text=fallback())
            except Exception as e2:
                print(f"[SCHEDULER] Falha total: {e2}")
