import re
from calendar import monthrange
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import date
from consulta_financeira import _valor


def _esc(texto: str) -> str:
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!\\])", r"\\\1", str(texto))


def iniciar(app, chat_id: int):
    scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")
    scheduler.add_job(_relatorio_diario,  "cron", hour=8,  minute=0,
                      args=[app, chat_id])
    scheduler.add_job(_relatorio_semanal, "cron", day_of_week="fri", hour=18, minute=0,
                      args=[app, chat_id])
    scheduler.add_job(_relatorio_mensal,  "cron", day="last", hour=18, minute=0,
                      args=[app, chat_id])
    scheduler.add_job(_checar_orcamento,  "cron", hour=9, minute=0,
                      args=[app, chat_id])
    scheduler.start()
    print("[SCHEDULER] Jobs agendados: diário 08:00, semanal sex 18:00, "
          "mensal último dia 18:00, orçamento 09:00.")


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


# ─── Relatório mensal ─────────────────────────────────────────────────────────

async def _relatorio_mensal(app, chat_id: int):
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
