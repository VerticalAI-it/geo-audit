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
        # Lo stato intermedio: l'ho chiamato ma non ho ancora deciso. Quando c'e'
        # gia', il bottone sparisce e resta l'etichetta — ripremerlo non direbbe
        # niente di nuovo.
        if (l.get("status") or "nuova") == "contattata":
            contattato = '<span class="pill neutro">già contattato</span>'
        else:
            corpo_contatto = json.dumps({"lead_id": l.get("id"), "stato": "contattata"})
            contattato = (
                '<button class="btn" data-azione="/admin/lead/contattato" '
                f"data-corpo='{corpo_contatto}'>Segna come contattato</button>")
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
            + contattato
            + '</div></div>'
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


def schermata_clienti(clienti: list, chi_sono: str = "") -> str:
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
        # ⚠️ Il divieto vero è disabilitare **sé stessi** — ci si chiuderebbe
        # fuori dal pannello senza una via di rientro — e quello lo applica il
        # server. Bloccare l'azione su tutti gli admin, come faceva il primo
        # taglio, oggi che il team coincide coi clienti renderebbe nessuno
        # disabilitabile.
        if c["id"] == chi_sono:
            azione = '<span class="pill neutro">sei tu</span>'

        righe.append(
            f'<tr><td><a href="/admin/clienti/{c["id"]}" style="color:var(--accent-primary)">'
            f'<b>{geo_audit.esc(c["email"])}</b></a></td>'
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
    # ⚠️ Gli account del team NON si escludono dal conteggio. Il primo taglio li
    # toglieva, dando per scontato che il team fosse gente diversa dai clienti;
    # con tutti gli account promossi la schermata diceva «Clienti attivi 0»
    # accanto a «27 progetti in tutto», che è palesemente falso. Un account è un
    # cliente: chi è del team ha in più le chiavi del pannello, e nell'elenco si
    # riconosce dal suo badge.
    attivi = [c for c in clienti if c["attivo"]]
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
        "segna_contattato": "ha segnato come contattato",
        "nota_cliente": "ha scritto una nota su",
        "promemoria_tracking": "ha mandato il promemoria tracking a",
        "magic_link_manuale": "ha rimandato il link di accesso a",
    }
    righe = []
    for a in azioni:
        azione = NOMI.get(a.get("action_type"), a.get("action_type") or "—")
        righe.append(
            f'<tr><td>{_quando(a.get("created_at"))}</td>'
            f'<td><b>{geo_audit.esc(a.get("actor_email") or "—")}</b></td>'
            f'<td>{geo_audit.esc(azione)}</td>'
            f'<td>{geo_audit.esc(a.get("target") or "")}</td></tr>'
        )
    return ('<div class="tab-wrap"><table class="tab"><thead><tr>'
            '<th>Quando</th><th>Chi</th><th>Cosa</th><th>Su</th>'
            f'</tr></thead><tbody>{"".join(righe)}</tbody></table></div>')


def schermata_job(audit: list) -> str:
    """Le esecuzioni del motore, con i fallimenti in evidenza.

    ⚠️ Fino al 3 settembre 2026 un audit che falliva **non lasciava una riga**:
    l'errore finiva in un `print`, cioè nei log della function, che nessuno
    guarda e che scadono. Questa schermata poteva solo dichiarare di non sapere.
    Ora la riga c'è (`_sb_audit_fallito`), quindi un elenco senza fallimenti
    significa davvero che non ce ne sono stati — **da quella data in poi**: quello
    che è fallito prima resta perduto, e non c'è modo di recuperarlo.
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

    if falliti:
        nota = ('<div class="avviso"><div>⚠️</div><div>'
                f'<b>{len(falliti)} esecuzion{"e" if len(falliti) == 1 else "i"} '
                f'{"fallita" if len(falliti) == 1 else "fallite"} fra le ultime {len(audit)}.</b> '
                'La colonna «Errore» dice cosa è successo: un dominio che non risolve e un '
                'timeout del crawler vogliono interventi diversi.'
                '</div></div>')
    else:
        nota = ('<div class="avviso" style="background:var(--state-good-dim);'
                'border-color:var(--state-good-dim)"><div>✓</div><div>'
                '<b>Nessuna esecuzione fallita.</b> La traccia dei fallimenti esiste '
                'dal 3 settembre 2026: prima gli errori finivano solo nei log della '
                'piattaforma, quindi su ciò che è successo prima questa schermata non '
                'può dire nulla.</div></div>')

    if not audit:
        return _vuoto("Nessuna esecuzione", "Il motore non ha ancora prodotto audit.")
    return (nota + '<div class="tab-wrap"><table class="tab"><thead><tr>'
            '<th>Quando</th><th>Sito</th><th>Origine</th><th>Punteggio</th><th>Esito</th><th>Errore</th>'
            f'</tr></thead><tbody>{"".join(righe)}</tbody></table></div>')


def schermata_tracking(progetti: list, con_tracking: set, clienti: list,
                       promemoria: dict | None = None) -> str:
    """I progetti che non hanno mai mandato un evento.

    È il dato che dice dove il prodotto non sta ancora misurando niente — e
    quindi dove il cliente non vedrà mai un numero.
    """
    per_utente = {c["id"]: c["email"] for c in clienti}
    senza = [p for p in progetti if p["id"] not in con_tracking]
    if not senza:
        return _vuoto("Tutti i progetti mandano dati",
                      "Ogni progetto ha almeno un evento registrato.")

    promemoria = promemoria or {}
    righe = []
    for p in sorted(senza, key=lambda x: x.get("created_at") or ""):
        giorni = _giorni_da(p.get("created_at"))
        etichetta = (f'<span class="pill warn">{giorni} giorni</span>'
                     if giorni and giorni > 14 else f"{giorni if giorni is not None else '—'} giorni")

        # ⚠️ Se gli si è già scritto, lo si dice invece di offrire un bottone
        # che manderebbe lo stesso messaggio una seconda volta.
        gia = promemoria.get(p["id"])
        if gia:
            azione = (f'<span class="pill neutro">mandato {_quando(gia.get("sent_at"))}</span>')
        else:
            corpo = json.dumps({"project_id": p["id"]})
            destinatario = per_utente.get(p.get("user_id"), "")
            azione = ('<button class="btn" data-azione="/admin/tracking/promemoria" '
                      f"data-corpo='{corpo}' "
                      f'data-conferma="Mandare a {geo_audit.esc(destinatario)} il promemoria '
                      f'per installare il tracking su {geo_audit.esc(p.get("domain") or "")}?">'
                      'Invia promemoria</button>')

        righe.append(
            f'<tr><td><b>{geo_audit.esc(p.get("domain") or "")}</b></td>'
            f'<td>{geo_audit.esc(per_utente.get(p.get("user_id"), "—"))}</td>'
            f'<td>{etichetta}</td>'
            f'<td style="text-align:right">{azione}</td></tr>'
        )
    return ('<div class="avviso"><div>📉</div><div>'
            f'<b>{len(senza)} progetti su {len(progetti)} non hanno mai mandato un evento.</b> '
            'Senza lo snippet installato la scheda AI Traffic resta vuota, e il cliente '
            'non vedrà mai un numero.</div></div>'
            '<div class="tab-wrap"><table class="tab"><thead><tr>'
            '<th>Sito</th><th>Cliente</th><th>Dalla creazione</th><th></th>'
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


def schermata_cliente(c: dict, accessi: list, note: list, audit: list,
                      con_tracking: set, chi_sono: str) -> str:
    """La scheda di un singolo cliente: chi è, cosa segue, come sta andando.

    È la schermata che il pannello non poteva avere finché non esistevano le
    tabelle per le note e per gli accessi.
    """
    email = c["email"]
    progetti = c["progetti"]

    ultimi = [a for a in audit if a.get("overall") is not None]
    media = round(sum(a["overall"] for a in ultimi) / len(ultimi)) if ultimi else None
    senza_tracking = [p for p in progetti if p["id"] not in con_tracking]
    accessi_riusciti = [a for a in accessi if a.get("event_type") == "accesso_riuscito"]
    link_chiesti = [a for a in accessi if a.get("event_type") == "link_richiesto"]

    def tessera(valore, etichetta, sotto="", colore=""):
        stile = f' style="color:{colore}"' if colore else ""
        return ('<div style="background:var(--bg-surface);border:1px solid var(--border-subtle);'
                'border-radius:var(--radius-lg);padding:16px 18px">'
                f'<div style="font-size:11.5px;color:var(--text-muted)">{etichetta}</div>'
                f'<div style="font-family:var(--font-display);font-size:26px;font-weight:600;'
                f'line-height:1.15;margin-top:5px"{stile}>{valore}</div>'
                + (f'<div style="font-size:11.5px;color:var(--text-muted);margin-top:3px">{sotto}</div>'
                   if sotto else "") + '</div>')

    kpi = ('<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));'
           'gap:12px;margin-bottom:22px">'
           + tessera(len(progetti), "Progetti",
                     f"{len(senza_tracking)} senza tracking" if senza_tracking else "tutti tracciati",
                     "var(--state-warn)" if senza_tracking else "")
           + tessera(media if media is not None else "—", "Punteggio medio",
                     "sui progetti con un audit", _colore_punteggio(media))
           # ⚠️ Con lo storico vuoto NON si scrive «mai entrato»: il nostro
           # registro parte da settembre 2026, mentre Supabase sa da sempre
           # qual è stato l'ultimo accesso. Dire «mai entrato» a chi è entrato
           # quaranta giorni fa sarebbe far passare «non lo sappiamo» per «non
           # è successo» — e su questa scheda si prendono decisioni commerciali.
           + (tessera(len(accessi_riusciti), "Accessi",
                      _quando(accessi_riusciti[0]["created_at"]) + " l'ultimo")
              if accessi_riusciti else
              tessera("—", "Accessi",
                      (f'ultimo: {_quando(c["ultimo_accesso"])}' if c["ultimo_accesso"]
                       else "non è mai entrato"),
                      "" if c["ultimo_accesso"] else "var(--state-critical)"))
           + tessera("attivo" if c["attivo"] else "disabilitato", "Stato",
                     "membro del team" if c["admin"] else "cliente",
                     "var(--state-good)" if c["attivo"] else "var(--state-critical)")
           + '</div>')

    if progetti:
        per_progetto = {}
        for a in audit:
            if a.get("project_id") and a["project_id"] not in per_progetto:
                per_progetto[a["project_id"]] = a
        righe = []
        for p in progetti:
            a = per_progetto.get(p["id"])
            punteggio = a.get("overall") if a else None
            tracc = ('<span class="pill ok">sì</span>' if p["id"] in con_tracking
                     else '<span class="pill warn">no</span>')
            righe.append(
                f'<tr><td><b>{geo_audit.esc(p.get("domain") or "")}</b></td>'
                f'<td style="color:{_colore_punteggio(punteggio)}">'
                f'{punteggio if punteggio is not None else "—"}</td>'
                f'<td>{_quando(a.get("created_at")) if a else "nessun audit"}</td>'
                f'<td>{tracc}</td></tr>')
        blocco_progetti = ('<div class="tab-wrap" style="margin-bottom:22px">'
                           '<table class="tab"><thead><tr>'
                           '<th>Sito</th><th>Punteggio</th><th>Ultimo audit</th><th>Tracking</th>'
                           f'</tr></thead><tbody>{"".join(righe)}</tbody></table></div>')
    else:
        blocco_progetti = ('<div class="vuoto" style="margin-bottom:22px">'
                           '<b>Nessun progetto</b>Ha accesso ma non ha ancora analizzato niente.</div>')

    if note:
        voci = "".join(
            '<div style="border-left:2px solid var(--accent-primary-dim);padding:2px 0 2px 12px;'
            'margin-bottom:14px">'
            f'<div style="font-size:13px;color:var(--text-secondary);white-space:pre-wrap">'
            f'{geo_audit.esc(n.get("text") or "")}</div>'
            f'<div style="font-size:11px;color:var(--text-muted);margin-top:4px">'
            f'{geo_audit.esc(n.get("author_email") or "")} · {_quando(n.get("created_at"))}</div>'
            '</div>' for n in note)
    else:
        voci = ('<p style="color:var(--text-muted);font-size:13px">'
                'Nessuna nota. Quello che si scrive qui resta: le note non si '
                'modificano e non si cancellano.</p>')

    blocco_note = (
        '<div style="background:var(--bg-surface);border:1px solid var(--border-subtle);'
        'border-radius:var(--radius-lg);padding:20px 22px;margin-bottom:22px">'
        '<div style="font-family:var(--font-display);font-size:16px;font-weight:600;'
        'margin-bottom:14px">Note interne</div>'
        f'{voci}'
        '<form method="post" action="/admin/clienti/nota" style="margin-top:16px">'
        f'<input type="hidden" name="client_id" value="{geo_audit.esc(c["id"])}">'
        '<textarea name="testo" rows="3" required placeholder="Cosa è emerso parlandoci…" '
        'style="width:100%;background:var(--bg-surface-raised);border:1px solid var(--border-subtle);'
        'border-radius:var(--radius-sm);padding:10px 12px;color:var(--text-primary);'
        'font-family:var(--font-body);font-size:13.5px;outline:none;resize:vertical"></textarea>'
        '<button class="btn" type="submit" style="margin-top:10px">Aggiungi nota</button>'
        '</form></div>')

    if accessi:
        NOMI = {"link_richiesto": "ha chiesto il link", "accesso_riuscito": "è entrato"}
        righe_acc = "".join(
            f'<tr><td>{_quando(a.get("created_at"))}</td>'
            f'<td>{NOMI.get(a.get("event_type"), a.get("event_type") or "")}</td></tr>'
            for a in accessi[:20])
        nota_divario = ""
        if len(link_chiesti) > len(accessi_riusciti):
            perduti = len(link_chiesti) - len(accessi_riusciti)
            nota_divario = (
                '<div class="avviso" style="margin-top:12px"><div>&#9993;</div><div>'
                f'<b>{perduti} link {"chiesto" if perduti == 1 else "chiesti"} '
                f'{"non ha" if perduti == 1 else "non hanno"} portato a un accesso.</b> '
                'Può voler dire che le email non arrivano, o che ci ripensa: se '
                'succede spesso, vale la pena chiedergli se le riceve.</div></div>')
        blocco_accessi = ('<div class="tab-wrap"><table class="tab"><thead><tr>'
                          '<th>Quando</th><th>Cosa</th></tr></thead>'
                          f'<tbody>{righe_acc}</tbody></table></div>{nota_divario}')
    else:
        blocco_accessi = _vuoto("Nessun accesso registrato",
                                "Lo storico parte da settembre 2026: prima non veniva "
                                "tenuto, quindi qui non c'è ciò che è successo prima.")

    corpo_link = json.dumps({"email": email})
    corpo_stato = json.dumps({"user_id": c["id"], "attivo": not c["attivo"]})
    verbo = "Disabilita" if c["attivo"] else "Riabilita"
    bottone_stato = "" if c["id"] == chi_sono else (
        f'<button class="btn btn-ghost" data-azione="/admin/clienti/stato" '
        f"data-corpo='{corpo_stato}' "
        f'data-conferma="{verbo} l&apos;accesso di {geo_audit.esc(email)}?">'
        f'{verbo} accesso</button>')
    azioni = ('<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:22px">'
              f'<button class="btn" data-azione="/admin/clienti/magic-link" '
              f"data-corpo='{corpo_link}' "
              f'data-conferma="Mandare a {geo_audit.esc(email)} un nuovo link di accesso?">'
              'Rimanda il link di accesso</button>'
              f'{bottone_stato}</div>')

    return ('<div style="margin-bottom:18px">'
            '<a class="back-link" href="/admin/clienti">&larr; Tutti i clienti</a></div>'
            + kpi + azioni
            + '<div style="font-family:var(--font-display);font-size:17px;font-weight:600;'
              'margin:4px 0 12px">Progetti</div>' + blocco_progetti
            + blocco_note
            + '<div style="font-family:var(--font-display);font-size:17px;font-weight:600;'
              'margin:4px 0 12px">Accessi</div>' + blocco_accessi)
