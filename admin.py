"""
GEO Audit — pannello interno del team VerticalAI.

Chiude il cerchio aperto dal flusso di accesso: i lead raccolti da
`/richiedi-accesso` diventano clienti qui, e da qui si vede se il motore sta
girando e chi non ha ancora installato il tracking.

⚠️ **Chi vede queste pagine vede i dati di tutti i clienti.** Il controllo del
ruolo sta sul server, in `server.py`, prima di ogni route — non in un redirect
JavaScript, che non e' un controllo.

Direzione degli import: `server.py` → `admin.py` → `db.py` → `config.py`, come
per `views.py`. Sta in un modulo suo perche' e' un'applicazione a se': stessa
base dati, altro pubblico.
"""
import json
from datetime import datetime, timezone, timedelta

import geo_audit
from db import (_LEAD_SOURCE, _e_attivo, _sb_audits_recenti, _sb_auth_find_by_email,
                _sb_auth_users, _sb_contact_requests, _sb_progetti_tutti,
                _sb_projects_with_tracking)


# ─────────────────────────────────────────────────────────────────────────────
# Pezzi comuni
# ─────────────────────────────────────────────────────────────────────────────

def _quando(iso: str | None) -> str:
    """«3 giorni fa». Un timestamp assoluto qui non serve a nessuno: la domanda
    che ci si fa guardando un lead e' da quanto sta aspettando."""
    if not iso:
        return "—"
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return "—"
    d = datetime.now(timezone.utc) - t
    secondi = d.total_seconds()
    if secondi < 90:
        return "adesso"
    if secondi < 3600:
        return f"{int(secondi // 60)} min fa"
    if secondi < 86400:
        ore = int(secondi // 3600)
        return f"{ore} or{'a' if ore == 1 else 'e'} fa"
    giorni = int(secondi // 86400)
    return f"{giorni} giorn{'o' if giorni == 1 else 'i'} fa"


def _giorni_da(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int((datetime.now(timezone.utc) - t).total_seconds() // 86400)


def _colore_punteggio(overall) -> str:
    if overall is None:
        return "var(--text-muted)"
    if overall >= 75:
        return "var(--state-good)"
    if overall >= 50:
        return "var(--state-warn)"
    return "var(--state-critical)"


def _gauge(overall, dimensione: int = 58) -> str:
    """Anello col punteggio. La circonferenza si calcola dal raggio e l'offset
    dal valore: un arco che non corrisponde al numero che gli sta dentro insegna
    a non fidarsi dei numeri."""
    r = (dimensione - 10) / 2
    circonferenza = 2 * 3.14159 * r
    quota = 0 if overall is None else max(0, min(100, overall))
    offset = circonferenza * (1 - quota / 100)
    colore = _colore_punteggio(overall)
    return (
        f'<div class="mini-gauge" style="width:{dimensione}px;height:{dimensione}px">'
        f'<svg viewBox="0 0 {dimensione} {dimensione}" width="{dimensione}" height="{dimensione}">'
        f'<circle class="mini-gauge-track" cx="{dimensione/2}" cy="{dimensione/2}" r="{r}"/>'
        f'<circle class="mini-gauge-fill" cx="{dimensione/2}" cy="{dimensione/2}" r="{r}" '
        f'stroke="{colore}" stroke-dasharray="{circonferenza:.1f}" stroke-dashoffset="{offset:.1f}"/>'
        f'</svg>'
        f'<div class="mini-gauge-num" style="color:{colore}">'
        f'{overall if overall is not None else "—"}</div></div>'
    )


def _vuoto(titolo: str, spiegazione: str) -> str:
    return (f'<div class="vuoto"><b>{geo_audit.esc(titolo)}</b>{geo_audit.esc(spiegazione)}</div>')


# ─────────────────────────────────────────────────────────────────────────────
# I dati del pannello
# ─────────────────────────────────────────────────────────────────────────────

def _lead_in_attesa() -> list:
    """Le richieste di accesso che aspettano ancora una risposta.

    ⚠️ «In attesa» non e' una colonna: e' il fatto che quell'email **non ha
    ancora un account**. Vedi `db.py`, sezione «Chi puo' entrare» — un solo
    concetto, nessuno stato da tenere allineato.
    """
    richieste = _sb_contact_requests(limit=300)
    audit = {a["id"]: a for a in _sb_audits_recenti(limit=1000)}
    account = {(u.get("email") or "").lower() for u in _sb_auth_users()}

    out = []
    for r in richieste:
        email = (r.get("email") or "").lower()
        if email in account:
            continue                      # gia' approvato: non e' piu' un lead
        a = audit.get(r.get("audit_id")) if r.get("audit_id") else None
        # Solo le richieste nate dal form di accesso: quelle del report esterno
        # sono un'altra cosa e stanno in «Interesse commerciale».
        if r.get("audit_id") and a and a.get("source") != _LEAD_SOURCE:
            continue
        if not r.get("audit_id") and not r.get("domain"):
            continue
        out.append({**r, "audit": a})
    return out


def _clienti() -> list:
    """Gli account, con quanti progetti hanno e quando sono entrati l'ultima volta."""
    utenti = _sb_auth_users()
    progetti = _sb_progetti_tutti()
    per_utente: dict = {}
    for p in progetti:
        per_utente.setdefault(p.get("user_id"), []).append(p)

    out = []
    for u in utenti:
        suoi = per_utente.get(u.get("id"), [])
        out.append({
            "id": u.get("id"),
            "email": u.get("email") or "",
            "attivo": _e_attivo(u),
            "admin": (u.get("app_metadata") or {}).get("role") == "admin",
            "creato": u.get("created_at"),
            "ultimo_accesso": u.get("last_sign_in_at"),
            "progetti": suoi,
        })
    out.sort(key=lambda x: (not x["attivo"], x["email"]))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Schermate
# ─────────────────────────────────────────────────────────────────────────────

def schermata_lead(lead: list) -> str:
    if not lead:
        return _vuoto("Nessuna richiesta in attesa",
                      "Quando qualcuno chiede l'accesso dal form, la richiesta compare qui "
                      "con il punteggio del suo sito già calcolato.")

    carte = []
    for l in lead:
        a = l.get("audit")
        email = l.get("email") or ""
        sito = l.get("domain") or "—"
        giorni = _giorni_da(l.get("created_at"))
        in_ritardo = (giorni or 0) >= 2

        if a and a.get("overall") is not None:
            # Le prime criticità del sito: è ciò che il commerciale mette sul
            # tavolo invece di una telefonata a freddo.
            opportunita = []
            for c in (a.get("site_checks") or [])[:20]:
                if c.get("status") in ("fail", "warn"):
                    colore = ("var(--state-critical)" if c.get("status") == "fail"
                              else "var(--state-warn)")
                    opportunita.append(
                        f'<div class="audit-opp"><span class="dot" style="background:{colore}"></span>'
                        f'{geo_audit.esc(c.get("title") or c.get("id") or "")}</div>')
                if len(opportunita) == 3:
                    break
            anteprima = (
                '<div class="audit-preview">'
                '<div class="audit-preview-label">Audit preliminare — pronto</div>'
                '<div class="audit-ready">'
                f'{_gauge(a.get("overall"))}'
                f'<div class="audit-opps">{"".join(opportunita) or "<div class=audit-opp>Nessuna criticità rilevante.</div>"}</div>'
                f'<a class="audit-report-link" href="/r/{a["id"]}" target="_blank" rel="noopener">Report completo →</a>'
                '</div></div>'
            )
            pronto = True
        else:
            anteprima = (
                '<div class="audit-preview">'
                '<div class="audit-preview-label">Audit preliminare</div>'
                '<div class="audit-pending"><span class="spinner"></span>'
                'Analisi in corso — di solito richiede un paio di minuti, ricarica fra poco'
                '</div></div>'
            )
            pronto = False

        telefono = (f'<span><svg width="12" height="12" viewBox="0 0 24 24" fill="none" '
                    f'stroke="currentColor" stroke-width="2"><path d="M22 16.92v3a2 2 0 01-2.18 2 '
                    f'19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 '
                    f'014.11 2h3a2 2 0 012 1.72c.127.96.361 1.902.7 2.81a2 2 0 01-.45 2.11L8.09 '
                    f'9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.908.339 1.85.573 2.81.7A2 2 0 '
                    f'0122 16.92z"/></svg>{geo_audit.esc(l.get("phone") or "")}</span>'
                    ) if l.get("phone") else ""

        badge = (f'<span class="overdue-badge">In attesa da {giorni}gg</span>'
                 if in_ritardo else "")

        corpo_lead = json.dumps({"email": email})
        carte.append(
            f'<div class="lead-card{" overdue" if in_ritardo else ""}">'
            '<div class="lead-top"><div class="lead-info">'
            f'<div class="lead-avatar">{geo_audit.esc((sito or email)[:1].upper())}</div>'
            f'<div><div class="lead-email">{geo_audit.esc(sito)}{badge}</div>'
            '<div class="lead-meta">'
            f'<span><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="2"><path d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 '
            f'0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>{geo_audit.esc(email)}</span>'
            f'{telefono}</div></div></div>'
            f'<div class="lead-time">Ricevuto {_quando(l.get("created_at"))}</div></div>'
            f'{anteprima}'
            '<div class="lead-actions">'
            f'<button class="btn btn-primary" data-azione="/admin/lead/approva" '
            f"data-corpo='{corpo_lead}' "
            f'data-conferma="Attivare l\'accesso per {geo_audit.esc(email)}? Riceverà il link per entrare."'
            f'{" disabled" if not pronto else ""}>'
            '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>Valida cliente</button>'
            '</div></div>'
        )

    avviso = ""
    non_pronti = [l for l in lead if not (l.get("audit") and l["audit"].get("overall") is not None)]
    if non_pronti:
        avviso = (
            '<div class="avviso"><div>⏳</div><div>'
            f'<b>{len(non_pronti)} richiest{"a" if len(non_pronti) == 1 else "e"} '
            f'{"ha" if len(non_pronti) == 1 else "hanno"} l\'audit ancora in corso.</b> '
            'Il bottone «Valida cliente» resta spento finché il punteggio non c\'è: '
            'approvare prima vorrebbe dire richiamare senza il dato che rende utile la chiamata.'
            '</div></div>'
        )

    return avviso + f'<div class="lead-list">{"".join(carte)}</div>'


def schermata_clienti(clienti: list) -> str:
    if not clienti:
        return _vuoto("Nessun cliente", "Gli account approvati compaiono qui.")

    righe = []
    for c in clienti:
        giorni = _giorni_da(c["ultimo_accesso"])
        if c["ultimo_accesso"] is None:
            accesso = '<span class="pill neutro">mai entrato</span>'
        elif giorni is not None and giorni > 14:
            accesso = f'<span class="pill warn">{_quando(c["ultimo_accesso"])}</span>'
        else:
            accesso = _quando(c["ultimo_accesso"])

        stato = ('<span class="pill ok">attivo</span>' if c["attivo"]
                 else '<span class="pill bad">disabilitato</span>')
        if c["admin"]:
            stato += ' <span class="pill neutro">team</span>'

        corpo = json.dumps({"user_id": c["id"], "attivo": not c["attivo"]})
        etichetta = "Disabilita" if c["attivo"] else "Riabilita"
        conferma = (f'Disabilitare l\'accesso di {c["email"]}? Non potrà più entrare.'
                    if c["attivo"] else f'Riabilitare l\'accesso di {c["email"]}?')
        azione = (f'<button class="btn btn-ghost" data-azione="/admin/clienti/stato" '
                  f"data-corpo='{corpo}' data-conferma=\"{geo_audit.esc(conferma)}\">{etichetta}</button>")
        if c["admin"]:
            # Un membro del team che si disabilita da solo si chiude fuori dal
            # pannello, e non c'è una schermata per rientrare.
            azione = '<span class="pill neutro">—</span>'

        righe.append(
            f'<tr><td><b>{geo_audit.esc(c["email"])}</b></td>'
            f'<td>{len(c["progetti"])}</td>'
            f'<td>{accesso}</td>'
            f'<td>{stato}</td>'
            f'<td style="text-align:right">{azione}</td></tr>'
        )

    return ('<div class="tab-wrap"><table class="tab"><thead><tr>'
            '<th>Email</th><th>Progetti</th><th>Ultimo accesso</th><th>Stato</th><th></th>'
            f'</tr></thead><tbody>{"".join(righe)}</tbody></table></div>')


def schermata_overview(lead: list, clienti: list) -> str:
    """Il punto della situazione, coi numeri veri.

    Niente stime e niente medie su dati assenti: dove un numero non c'è si
    scrive che non c'è, come nel resto del prodotto.
    """
    attivi = [c for c in clienti if c["attivo"] and not c["admin"]]
    progetti = [p for c in clienti for p in c["progetti"]]
    mai_entrati = [c for c in attivi if not c["ultimo_accesso"]]
    fermi = [c for c in attivi
             if c["ultimo_accesso"] and (_giorni_da(c["ultimo_accesso"]) or 0) > 14]

    def tessera(valore, etichetta, sotto="", colore=""):
        stile = f' style="color:{colore}"' if colore else ""
        return (
            '<div style="background:var(--bg-surface);border:1px solid var(--border-subtle);'
            'border-radius:var(--radius-lg);padding:18px 20px;box-shadow:var(--card-shadow)">'
            f'<div style="font-size:11.5px;color:var(--text-muted);font-weight:500">{etichetta}</div>'
            f'<div style="font-family:var(--font-display);font-size:30px;font-weight:600;'
            f'line-height:1.1;margin-top:6px"{stile}>{valore}</div>'
            + (f'<div style="font-size:11.5px;color:var(--text-muted);margin-top:4px">{sotto}</div>'
               if sotto else "")
            + '</div>'
        )

    kpi = (
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));'
        'gap:12px;margin-bottom:24px">'
        + tessera(len(attivi), "Clienti attivi", f"{len(progetti)} progetti in tutto")
        + tessera(len(lead), "Lead in attesa",
                  "richieste da lavorare" if lead else "nessuno da lavorare",
                  "var(--state-warn)" if lead else "")
        + tessera(len(mai_entrati), "Non sono mai entrati",
                  "hanno l'accesso e non l'hanno usato",
                  "var(--state-critical)" if mai_entrati else "")
        + tessera(len(fermi), "Fermi da oltre 14 giorni",
                  "erano entrati, poi più nulla",
                  "var(--state-warn)" if fermi else "")
        + '</div>'
    )

    # Le cose che chiedono un intervento, con il link a dove si interviene.
    voci = []
    if lead:
        pronti = [l for l in lead if l.get("audit") and l["audit"].get("overall") is not None]
        voci.append(
            f'<a class="nav-item" href="/admin/lead" style="background:var(--bg-surface);'
            f'border:1px solid var(--border-subtle);margin-bottom:8px">'
            f'<span><b>{len(lead)}</b> richiest{"a" if len(lead) == 1 else "e"} di accesso in attesa'
            + (f' — {len(pronti)} con l\'audit già pronto' if pronti else " — audit in corso")
            + '</span><span style="color:var(--accent-primary)">→</span></a>'
        )
    if mai_entrati:
        voci.append(
            '<a class="nav-item" href="/admin/clienti" style="background:var(--bg-surface);'
            'border:1px solid var(--border-subtle);margin-bottom:8px">'
            f'<span><b>{len(mai_entrati)}</b> client{"e" if len(mai_entrati) == 1 else "i"} '
            f'non {"ha" if len(mai_entrati) == 1 else "hanno"} mai fatto il primo accesso'
            '</span><span style="color:var(--accent-primary)">→</span></a>'
        )

    attenzione = ""
    if voci:
        attenzione = ('<div style="font-family:var(--font-display);font-size:17px;font-weight:600;'
                      'margin:4px 0 12px">Richiede attenzione</div>' + "".join(voci))
    else:
        attenzione = _vuoto("Non c'è niente in sospeso",
                            "Nessuna richiesta da approvare e nessun cliente fermo.")

    return kpi + attenzione


def schermata_log(azioni: list) -> str:
    """Chi ha fatto cosa nel pannello."""
    if not azioni:
        return _vuoto("Nessuna azione registrata",
                      "Ogni approvazione, abilitazione o disabilitazione fatta da qui "
                      "lascia una riga in questo elenco.")

    NOMI = {
        "approva_lead": "ha attivato l'accesso di",
        "abilita_cliente": "ha riabilitato",
        "disabilita_cliente": "ha disabilitato",
    }
    righe = []
    for a in azioni:
        p = a.get("properties") or {}
        azione = NOMI.get(p.get("azione"), p.get("azione") or "—")
        righe.append(
            f'<tr><td>{_quando(a.get("created_at"))}</td>'
            f'<td><b>{geo_audit.esc(p.get("attore") or "—")}</b></td>'
            f'<td>{geo_audit.esc(azione)}</td>'
            f'<td>{geo_audit.esc(p.get("bersaglio") or "")}</td></tr>'
        )
    return ('<div class="tab-wrap"><table class="tab"><thead><tr>'
            '<th>Quando</th><th>Chi</th><th>Cosa</th><th>Su</th>'
            f'</tr></thead><tbody>{"".join(righe)}</tbody></table></div>')


def schermata_job(audit: list) -> str:
    """Le esecuzioni del motore, le fallite per prime.

    ⚠️ `status` in pratica è sempre `done`: sia gli audit manuali sia il cron
    inseriscono righe già completate, e un audit che fallisce **non lascia una
    riga** — l'eccezione viene catturata prima. Quindi qui un elenco vuoto di
    fallimenti non significa «va tutto bene», significa «non ne abbiamo traccia»,
    e la schermata lo dice invece di far sembrare che tutto giri.
    """
    falliti = [a for a in audit if a.get("status") == "failed" or a.get("error")]
    righe = []
    for a in audit[:80]:
        rotto = a.get("status") == "failed" or a.get("error")
        stato = ('<span class="pill bad">fallito</span>' if rotto
                 else '<span class="pill ok">ok</span>')
        origine = {"auto": "automatico", "manual": "manuale",
                   _LEAD_SOURCE: "lead"}.get(a.get("source"), a.get("source") or "n.d.")
        punteggio = a.get("overall")
        righe.append(
            f'<tr><td>{_quando(a.get("created_at"))}</td>'
            f'<td><b>{geo_audit.esc(a.get("domain") or a.get("url") or "—")}</b></td>'
            f'<td>{geo_audit.esc(origine)}</td>'
            f'<td style="color:{_colore_punteggio(punteggio)}">'
            f'{punteggio if punteggio is not None else "—"}</td>'
            f'<td>{stato}</td>'
            f'<td style="color:var(--text-muted);font-size:12px">'
            f'{geo_audit.esc((a.get("error") or "")[:70])}</td></tr>'
        )

    nota = (
        '<div class="avviso"><div>ℹ️</div><div>'
        '<b>Un audit che fallisce non lascia una riga.</b> Oggi l\'errore viene '
        'catturato e la riga non viene scritta, quindi questo elenco mostra le '
        'esecuzioni riuscite: un elenco senza fallimenti non vuol dire che non ce '
        'ne siano stati. Per vederli davvero va salvata anche la riga fallita — '
        'è il primo intervento da fare su questa schermata.'
        '</div></div>'
    )
    if not audit:
        return nota + _vuoto("Nessuna esecuzione", "Il motore non ha ancora prodotto audit.")
    return (nota + '<div class="tab-wrap"><table class="tab"><thead><tr>'
            '<th>Quando</th><th>Sito</th><th>Origine</th><th>Punteggio</th><th>Esito</th><th>Errore</th>'
            f'</tr></thead><tbody>{"".join(righe)}</tbody></table></div>')


def schermata_tracking(progetti: list, con_tracking: set, clienti: list) -> str:
    """I progetti che non hanno mai mandato un evento.

    È il dato che dice dove il prodotto non sta ancora misurando niente — e
    quindi dove il cliente non vedrà mai un numero.
    """
    per_utente = {c["id"]: c["email"] for c in clienti}
    senza = [p for p in progetti if p["id"] not in con_tracking]
    if not senza:
        return _vuoto("Tutti i progetti mandano dati",
                      "Ogni progetto ha almeno un evento registrato.")

    righe = []
    for p in sorted(senza, key=lambda x: x.get("created_at") or ""):
        giorni = _giorni_da(p.get("created_at"))
        etichetta = (f'<span class="pill warn">{giorni} giorni</span>'
                     if giorni and giorni > 14 else f"{giorni if giorni is not None else '—'} giorni")
        righe.append(
            f'<tr><td><b>{geo_audit.esc(p.get("domain") or "")}</b></td>'
            f'<td>{geo_audit.esc(per_utente.get(p.get("user_id"), "—"))}</td>'
            f'<td>{etichetta}</td></tr>'
        )
    return ('<div class="avviso"><div>📉</div><div>'
            f'<b>{len(senza)} progetti su {len(progetti)} non hanno mai mandato un evento.</b> '
            'Senza lo snippet installato la scheda AI Traffic resta vuota, e il cliente '
            'non vedrà mai un numero.</div></div>'
            '<div class="tab-wrap"><table class="tab"><thead><tr>'
            '<th>Sito</th><th>Cliente</th><th>Dalla creazione</th>'
            f'</tr></thead><tbody>{"".join(righe)}</tbody></table></div>')


def schermata_interesse(richieste: list, audit_per_id: dict, account: set) -> str:
    """I segnali commerciali: chi ha chiesto di essere ricontattato dal report.

    Sono le `contact_requests` **non** nate dal form di accesso — quelle stanno
    nella coda lead.
    """
    voci = []
    for r in richieste:
        a = audit_per_id.get(r.get("audit_id")) if r.get("audit_id") else None
        if a and a.get("source") == _LEAD_SOURCE:
            continue                       # è un lead, non un segnale commerciale
        if not r.get("audit_id"):
            continue                       # richiesta senza report: è un lead senza audit
        voci.append(r)

    if not voci:
        return _vuoto("Nessuna richiesta di contatto",
                      "Qui arrivano le richieste «voglio essere contattato» dal report esterno.")

    righe = []
    for r in voci:
        email = (r.get("email") or "").lower()
        stato = ('<span class="pill ok">è già cliente</span>' if email in account
                 else '<span class="pill warn">da contattare</span>')
        righe.append(
            f'<tr><td>{_quando(r.get("created_at"))}</td>'
            f'<td><b>{geo_audit.esc(r.get("email") or "")}</b></td>'
            f'<td>{geo_audit.esc(r.get("domain") or "—")}</td>'
            f'<td style="color:{_colore_punteggio(r.get("overall"))}">'
            f'{r.get("overall") if r.get("overall") is not None else "—"}</td>'
            f'<td>{geo_audit.esc(r.get("phone") or "")}</td>'
            f'<td>{stato}</td></tr>'
        )
    return ('<div class="tab-wrap"><table class="tab"><thead><tr>'
            '<th>Quando</th><th>Email</th><th>Sito</th><th>Punteggio</th><th>Telefono</th><th></th>'
            f'</tr></thead><tbody>{"".join(righe)}</tbody></table></div>')
