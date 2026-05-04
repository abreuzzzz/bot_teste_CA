from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import date, timedelta
import asyncio


def iniciar(app, chat_id: int):
    scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")
    scheduler.add_job(
        _relatorio_diario,
        trigger="cron",
        hour=8,
        minute=0,
        args=[app, chat_id],
    )
    scheduler.start()
    print("[SCHEDULER] Relatorio diario agendado 08:00.")


async def _relatorio_diario(app, chat_id: int):
    from consulta_financeira import resumo_mes, pendentes, atrasados

    hoje   = date.today()
    resumo = resumo_mes()
    pend   = pendentes(dias=7)
    atras  = atrasados()

    linhas_pend = "\n".join(
        f"  {'📥' if i['tipo']=='RECEBER' else '📤'} {i.get('descricao','?')[:30]} — R$ {i.get('valor',0):.2f} ({i.get('data_vencimento','')})"
        for i in pend[:5]
    ) or "  _(nenhum)_"

    linhas_atras = "\n".join(
        f"  ⚠️ {i.get('descricao','?')[:30]} — R$ {i.get('valor',0):.2f} ({i.get('data_vencimento','')})"
        for i in atras[:5]
    ) or "  _(nenhum)_"

    alerta_saldo = ""
    if resumo["saldo_projetado"] < 0:
        alerta_saldo = f"\n⚠️ *ALERTA: Saldo projetado negativo!* R$ {resumo['saldo_projetado']:.2f}\n"

    msg = (
        f"☀️ *Bom dia! Relatório de {hoje.strftime('%d/%m/%Y')}*\n\n"
        f"📊 *Mês atual ({resumo['periodo']}):*\n"
        f"  📥 A receber: R$ {resumo['total_receber']:.2f}\n"
        f"  📤 A pagar:   R$ {resumo['total_pagar']:.2f}\n"
        f"  ✅ Recebido:  R$ {resumo['recebido']:.2f}\n"
        f"  ✅ Pago:      R$ {resumo['pago']:.2f}\n"
        f"  💰 Resultado: R$ {resumo['resultado']:.2f}\n"
        f"{alerta_saldo}\n"
        f"📅 *Próximos 7 dias:*\n{linhas_pend}\n\n"
        f"🚨 *Atrasados:*\n{linhas_atras}"
    )

    await app.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
