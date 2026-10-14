# -*- coding: utf-8 -*-
"""Richieste di contatto → lead nel CRM VerticalAI Ops (14/10/2026).

Chi chiede l'analisi completa da un report (POST /contact/{job_id}) diventa, in
Ops, un cliente in stato Lead con il referente e un task di pre-vendita per
Marco, con punteggio e link al report già dentro: si richiama avendo il
risultato in mano invece di fare una telefonata a freddo.

Modulo foglia come `ai_sources.py`: importa solo `config` e `requests`, quindi
si prova senza toccare `server.py`.

⚠️ La chiamata parte in coda (BackgroundTasks) e non solleva MAI: se Ops è
lento o giù, il modulo pubblico non deve aspettare né fallire. Un invio perso
resta nel log e nella tabella `contact_requests`, da cui si può recuperare.
Rimandarlo è sicuro per cliente e persona (Ops li riusa), ma crea un secondo
task: per questo non c'è un ritentativo automatico.
"""
import requests

from config import OPS_LEAD_TOKEN, OPS_LEAD_URL

_TIMEOUT = 10


def payload_lead(job_id: str, domain: str, overall: int, grade: str, email: str,
                 phone: str, preference: str, report_url: str):
    """Il corpo per `POST /api/lead-in-ingresso` di Ops, oppure None se manca il
    dominio: Ops vuole la ragione sociale o il dominio, e il dominio
    dell'email (gmail.com, libero.it…) creerebbe un cliente sbagliato."""
    dominio = (domain or "").strip()
    if not dominio or dominio == "—":
        return None
    dettagli = {
        "overall": overall,
        "grade": grade,
        "audit_id": job_id,
        "report_url": report_url,
        "preferenza_contatto": "telefono" if preference == "phone" else "email",
    }
    corpo = {"dominio": dominio, "email": email, "fonte": "geo_audit", "dettagli": dettagli}
    if phone:
        corpo["telefono"] = phone
    return corpo


def invia_lead_a_ops(job_id: str, domain: str, overall: int, grade: str, email: str,
                     phone: str, preference: str, report_url: str) -> None:
    """Manda il lead a Ops. Senza OPS_LEAD_TOKEN non fa niente (in locale, nei
    test, o finché il token dedicato non è configurato su Vercel)."""
    if not OPS_LEAD_TOKEN:
        return
    corpo = payload_lead(job_id, domain, overall, grade, email, phone, preference, report_url)
    if corpo is None:
        print(f"[lead->ops] {email}: report {job_id} senza dominio, lead non inviato")
        return
    try:
        r = requests.post(
            OPS_LEAD_URL,
            json=corpo,
            headers={"Authorization": f"Bearer {OPS_LEAD_TOKEN}"},
            timeout=_TIMEOUT,
        )
    except Exception as e:
        print(f"[lead->ops] {email} ({corpo['dominio']}): invio fallito: {e!r}")
        return
    if r.status_code != 201:
        print(f"[lead->ops] {email} ({corpo['dominio']}): Ops ha risposto {r.status_code}: {r.text[:300]}")
