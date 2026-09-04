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


def _durata(a: dict) -> str:
    """Quanto ci ha messo un'esecuzione, da quando e' partita a quando ha finito.

    ⚠️ Una durata di zero non e' «istantaneo»: e' «non lo sappiamo». Gli audit
    falliti registrati prima del 4 settembre 2026 segnavano inizio e fine nello
    stesso istante, perche' l'ora la prendeva il ramo d'errore. Su quelli qui
    compare «—», che e' la verita'; scrivere «0s» direbbe che il motore ha
    fallito subito, mentre magari ha girato due minuti prima di andare in
    timeout — cioe' proprio l'informazione per cui questa colonna esiste.
    """
    inizio, fine = a.get("created_at"), a.get("completed_at")
    if not inizio or not fine:
        return "—"
    try:
        t0 = datetime.fromisoformat(inizio.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(fine.replace("Z", "+00:00"))
    except ValueError:
        return "—"
    secondi = (t1 - t0).total_seconds()
    if secondi <= 0:
        return "—"
    if secondi < 60:
        return f"{secondi:.0f}s"
    return f"{int(secondi // 60)}m {int(secondi % 60):02d}s"


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

# Quanti se ne rilanciano al massimo in un colpo solo. Ogni audit e' un giro di
# crawler da un paio di minuti: partirne trenta insieme vuol dire farli morire
# tutti sul limite di durata della function, e ritrovarsi con trenta fallimenti
# nuovi al posto di quelli vecchi.
MAX_RILANCIO_BLOCCO = 10


def falliti_da_rilanciare(audit: list) -> list:
    """I fallimenti su cui «Rilancia» avrebbe ancora un effetto.

    ⚠️ Un fallimento e' «ancora aperto» solo se dopo di lui, per quel progetto,
    non e' piu' riuscito niente. E' questo che rende il rilancio idempotente
    senza bisogno di lucchetti: se qualcuno ha gia' rilanciato — o se il cron e'
    ripassato da solo — quella riga esce da qui da sola.

    Sta fuori dalla schermata perche' la usano in due: il bottone che dice
    «rilancia tutti e N» e la route che li rilancia. Se il conto lo facessero
    separatamente, prima o poi direbbero numeri diversi.
    """
    ultimo_ok: dict = {}
    for a in audit:
        if a.get("status") != "failed" and not a.get("error"):
            chiave = a.get("project_id") or a.get("url")
            if chiave and chiave not in ultimo_ok:
                ultimo_ok[chiave] = a.get("created_at") or ""

    out = []
    for a in audit:
        if a.get("status") != "failed" and not a.get("error"):
            continue
        if not a.get("url"):
            continue
        chiave = a.get("project_id") or a.get("url")
        if (ultimo_ok.get(chiave) or "") > (a.get("created_at") or ""):
            continue                      # gia' rifatto, con successo
        out.append(a)
    return out


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


def _modale_aggiungi_cliente() -> str:
    """Il modulo per creare un accesso a mano, senza passare dalla coda lead.

    ⚠️ La casella «mandagli subito il link» esiste perche' la scelta — avvisare
    o no — e' una **decisione di prodotto ancora aperta** (documento Admin
    Dashboard §7.2). Finche' non e' presa, non la prende il codice al posto del
    team: la prende chi sta creando l'account, una volta per volta. Il valore
    predefinito e' «si» perche' un cliente creato e mai avvisato non sa di
    esistere, e resterebbe nell'elenco come «mai entrato» per sempre.
    """
    return (
        '<div class="modale" id="agg-cliente" hidden>'
        '<div class="modale-corpo">'
        '<div class="modale-titolo">Aggiungi un cliente</div>'
        '<div class="modale-sotto">'
        "L’accesso nasce già attivo: chi lo riceve entra senza passare "
        "dalla richiesta di analisi.</div>"
        '<label class="campo"><span>Email</span>'
        '<input type="email" name="email" required placeholder="nome@azienda.it" '
        'autocomplete="off" spellcheck="false"></label>'
        '<label class="campo-check">'
        '<input type="checkbox" name="avvisa" checked>'
        "<span>Mandagli subito il link per entrare. Senza, l’accesso esiste "
        "ma lui non lo sa: dovrà chiederlo lui dalla pagina di accesso."
        "</span></label>"
        '<div class="modale-azioni">'
        '<button class="btn btn-ghost" data-chiudi>Annulla</button>'
        '<button class="btn btn-primary" data-azione="/admin/clienti/aggiungi" '
        'data-campi="agg-cliente">Crea l&rsquo;accesso</button>'
        '</div></div></div>'
    )


def schermata_clienti(clienti: list, chi_sono: str = "") -> str:
    testata = ('<div style="display:flex;justify-content:flex-end;margin-bottom:14px">'
               '<button class="btn btn-primary" data-apri="agg-cliente">'
               '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" '
               'stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>'
               'Aggiungi cliente</button></div>')

    if not clienti:
        return (testata + _vuoto("Nessun cliente", "Gli account approvati compaiono qui.")
                + _modale_aggiungi_cliente())

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

    return (testata + '<div class="tab-wrap"><table class="tab"><thead><tr>'
            '<th>Email</th><th>Progetti</th><th>Ultimo accesso</th><th>Stato</th><th></th>'
            f'</tr></thead><tbody>{"".join(righe)}</tbody></table></div>'
            + _modale_aggiungi_cliente())


# Da quando i fallimenti lasciano una riga. Prima di questa data «zero audit
# falliti» non significa «non ne sono falliti»: significa che non lo sapevamo.
# Il grafico non disegna la linea dei fallimenti prima di qui — una linea a zero
# su un periodo cieco è la bugia più facile da raccontare con un grafico.
DA_QUANDO_TRACCIAMO_I_FALLITI = datetime(2026, 9, 3, tzinfo=timezone.utc)


def _serie(valori: list, colore: str, larghezza: int = 64, altezza: int = 26) -> str:
    """Una sparkline. Meno di due punti non è un andamento: non si disegna."""
    if len(valori) < 2:
        return ""
    lo, hi = min(valori), max(valori)
    campo = (hi - lo) or 1
    passo = larghezza / (len(valori) - 1)
    punti = " ".join(
        f"{i * passo:.0f},{altezza - 3 - (v - lo) / campo * (altezza - 6):.0f}"
        for i, v in enumerate(valori))
    return (f'<svg class="kpi-spark" viewBox="0 0 {larghezza} {altezza}">'
            f'<polyline points="{punti}" fill="none" stroke="{colore}" '
            f'stroke-width="1.5"/></svg>')


def _per_giorno(righe: list, giorni: int, campo: str = "created_at") -> list:
    """Raggruppa per giorno, dal più vecchio al più recente, senza buchi.

    I giorni senza righe restano nella lista come lista vuota: servono, perché
    un grafico che salta i giorni vuoti comprime il tempo e fa sembrare costante
    quello che invece si era fermato.
    """
    oggi = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    secchi = {(oggi - timedelta(days=n)).date(): [] for n in range(giorni)}
    for r in righe:
        try:
            t = datetime.fromisoformat((r.get(campo) or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        g = t.date()
        if g in secchi:
            secchi[g].append(r)
    return [(g, secchi[g]) for g in sorted(secchi)]


def _grafico_portfolio(audit: list, giorni: int) -> str:
    """Punteggio medio e fallimenti, giorno per giorno.

    ⚠️ Le due linee non coprono lo stesso periodo, e non è un difetto: quella
    dei fallimenti comincia da quando i fallimenti hanno cominciato a lasciare
    una riga. Prolungarla indietro a zero direbbe «prima non ne falliva
    nessuno», che è esattamente ciò che non sappiamo.
    """
    giorni_dati = _per_giorno(audit, giorni)
    L, A = 900, 150

    def punti(valori) -> str:
        if not valori:
            return ""
        passo = L / max(1, len(giorni_dati) - 1)
        alto = max(v for _, v in valori) or 1
        return " ".join(f"{i * passo:.0f},{A - 12 - (v / alto) * (A - 30):.0f}"
                        for i, v in valori)

    medie = []
    for i, (_, righe) in enumerate(giorni_dati):
        ok = [r["overall"] for r in righe
              if r.get("overall") is not None and r.get("status") != "failed"]
        if ok:
            medie.append((i, sum(ok) / len(ok)))

    falliti = []
    for i, (g, righe) in enumerate(giorni_dati):
        quel_giorno = datetime(g.year, g.month, g.day, tzinfo=timezone.utc)
        if quel_giorno < DA_QUANDO_TRACCIAMO_I_FALLITI:
            continue                      # periodo cieco: non si disegna
        falliti.append((i, len([r for r in righe
                                if r.get("status") == "failed" or r.get("error")])))

    scelta = []
    for n, etichetta in ((7, "7 giorni"), (30, "30 giorni"), (90, "90 giorni")):
        attivo = ' class="active"' if n == giorni else ""
        scelta.append(f'<a href="/admin?giorni={n}"><span{attivo}>{etichetta}</span></a>')
    testata = ('<div class="trend-top">'
               '<div class="trend-title">Salute del portfolio nel tempo</div>'
               f'<div class="range-toggle">{"".join(scelta)}</div></div>')

    if len(medie) < 2 and len(falliti) < 2:
        return ('<div class="trend-card">' + testata
                + '<div style="padding:26px 4px;color:var(--text-muted);font-size:13px">'
                f'Non c&rsquo;&egrave; ancora abbastanza storico: negli ultimi {giorni} '
                'giorni il motore non ha prodotto esecuzioni in giorni diversi, e '
                'con un punto solo non si disegna un andamento.</div></div>')

    linee = ""
    if len(medie) >= 2:
        linee += (f'<polyline points="{punti(medie)}" fill="none" '
                  f'stroke="var(--state-good)" stroke-width="2"/>')
    mostra_falliti = len(falliti) >= 2 and any(v for _, v in falliti)
    if mostra_falliti:
        linee += (f'<polyline points="{punti(falliti)}" fill="none" '
                  f'stroke="var(--state-critical)" stroke-width="2"/>')

    legenda = ['<span class="legend-item"><span class="legend-dot" '
               'style="background:var(--state-good)"></span>Punteggio medio portfolio</span>']
    if mostra_falliti:
        legenda.append('<span class="legend-item"><span class="legend-dot" '
                       'style="background:var(--state-critical)"></span>Audit falliti</span>')

    # La nota spiega la linea dei fallimenti: se quella linea non c'e', la nota
    # parlerebbe di qualcosa che non si vede — e una spiegazione senza il suo
    # oggetto confonde invece di chiarire.
    nota = ""
    if mostra_falliti and giorni_dati:
        g0 = giorni_dati[0][0]
        if datetime(g0.year, g0.month, g0.day, tzinfo=timezone.utc) < DA_QUANDO_TRACCIAMO_I_FALLITI:
            nota = ('<div style="font-size:11.5px;color:var(--text-muted);margin-top:8px">'
                    'La linea dei fallimenti parte dal 3 settembre 2026: prima gli errori '
                    'non lasciavano traccia, e disegnarla a zero direbbe che non ce '
                    'n&rsquo;erano.</div>')

    return (
        '<div class="trend-card">' + testata
        + f'<div class="trend-chart"><svg viewBox="0 0 {L} {A}" preserveAspectRatio="none">'
        f'<line x1="0" y1="37" x2="{L}" y2="37" stroke="var(--border-subtle)"/>'
        f'<line x1="0" y1="75" x2="{L}" y2="75" stroke="var(--border-subtle)"/>'
        f'<line x1="0" y1="112" x2="{L}" y2="112" stroke="var(--border-subtle)"/>'
        f'{linee}</svg></div>'
        f'<div class="trend-legend">{"".join(legenda)}</div>{nota}</div>'
    )


def _attivita_recente(azioni: list) -> str:
    """Le ultime righe del registro, in cima all'Overview.

    Stessa fonte della schermata «Log azioni admin»: qui è solo un assaggio, e
    il link porta all'elenco intero.
    """
    # ⚠️ Con il registro vuoto la card resta, e dice che è vuoto. Farla sparire
    # toglierebbe un pezzo di pagina senza spiegare perché — e chi guarda non
    # saprebbe se non è successo niente o se qualcosa non funziona.
    if not azioni:
        return ('<div class="activity-card"><div class="activity-header">'
                '<div class="activity-title">Attivit&agrave; recente</div>'
                '<a class="activity-link" href="/admin/log">Vedi tutto &rarr;</a></div>'
                '<div class="activity-row"><span class="activity-text" '
                'style="color:var(--text-muted)">Nessuna azione registrata finora. '
                'Ogni approvazione, promemoria o rilancio fatto da queste pagine '
                'comparir&agrave; qui.</span></div></div>')
    COLORE = {"approva_lead": "good", "aggiungi_cliente": "good",
              "abilita_cliente": "good", "disabilita_cliente": "warn"}
    NOMI = {
        "approva_lead": "ha attivato l&rsquo;accesso di",
        "aggiungi_cliente": "ha aggiunto il cliente",
        "abilita_cliente": "ha riabilitato",
        "disabilita_cliente": "ha disabilitato",
        "segna_contattato": "ha segnato come contattato",
        "nota_cliente": "ha scritto una nota su",
        "promemoria_tracking": "ha mandato il promemoria tracking a",
        "magic_link_manuale": "ha rimandato il link di accesso a",
        "rilancia_job": "ha rilanciato",
    }
    righe = []
    for a in azioni[:5]:
        tipo = a.get("action_type") or ""
        righe.append(
            '<div class="activity-row">'
            f'<span class="activity-dot {COLORE.get(tipo, "accent")}"></span>'
            f'<span class="activity-text"><b>{geo_audit.esc(a.get("actor_email") or "?")}</b> '
            f'{NOMI.get(tipo, geo_audit.esc(tipo))} '
            f'<b>{geo_audit.esc(a.get("target") or "")}</b></span>'
            f'<span class="activity-time">{_quando(a.get("created_at"))}</span></div>')
    return ('<div class="activity-card"><div class="activity-header">'
            '<div class="activity-title">Attivit&agrave; recente</div>'
            '<a class="activity-link" href="/admin/log">Vedi tutto &rarr;</a></div>'
            + "".join(righe) + '</div>')


def schermata_overview(lead: list, clienti: list, audit: list | None = None,
                       azioni: list | None = None, senza_tracking: int = 0,
                       giorni: int = 30) -> str:
    """Il punto della situazione, coi numeri veri.

    Niente stime e niente medie su dati assenti: dove un numero non c'è si
    scrive che non c'è, come nel resto del prodotto.
    """
    audit = audit or []
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

    # ── Punteggio medio del portfolio ──────────────────────────────────────
    # Un audit per progetto, il più recente: senza questo un sito rianalizzato
    # dieci volte peserebbe dieci volte nella media.
    ultimo_per_progetto: dict = {}
    for a in sorted(audit, key=lambda x: x.get("created_at") or "", reverse=True):
        chiave = a.get("project_id") or a.get("url")
        if chiave and chiave not in ultimo_per_progetto and a.get("overall") is not None:
            ultimo_per_progetto[chiave] = a
    punteggi = [a["overall"] for a in ultimo_per_progetto.values()]
    media = round(sum(punteggi) / len(punteggi)) if punteggi else None

    # ── Audit falliti nel periodo ──────────────────────────────────────────
    limite = datetime.now(timezone.utc) - timedelta(days=30)
    recenti = []
    for a in audit:
        try:
            t = datetime.fromisoformat((a.get("created_at") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if t >= limite:
            recenti.append(a)
    falliti = [a for a in recenti if a.get("status") == "failed" or a.get("error")]

    def tessera(valore, etichetta, sotto="", classe="", spark="") -> str:
        cls = f" {classe}" if classe else ""
        return ('<div class="kpi">'
                f'<div class="kpi-label">{etichetta}</div>'
                f'<div class="kpi-value-row"><span class="kpi-value{cls}">{valore}</span>'
                f'{spark}</div>'
                + (f'<div class="kpi-sub">{sotto}</div>' if sotto else "")
                + '</div>')

    # Le sparkline si disegnano solo dove l'andamento è ricostruibile davvero.
    # Per «lead in attesa» non lo è — un lead approvato esce dalla coda e non
    # lascia il conteggio di ieri — quindi lì non c'è, invece di inventarne una.
    creati = sorted(c["creato"] for c in clienti if c.get("creato"))
    spark_clienti = _serie(list(range(1, len(creati) + 1)), "var(--state-good)") if len(creati) > 2 else ""

    per_giorno_medie = []
    for _, righe in _per_giorno(audit, giorni):
        ok = [r["overall"] for r in righe
              if r.get("overall") is not None and r.get("status") != "failed"]
        if ok:
            per_giorno_medie.append(sum(ok) / len(ok))
    spark_media = _serie(per_giorno_medie, "var(--state-good)")

    kpi = (
        '<div class="kpi-strip">'
        + tessera(len(attivi), "Clienti attivi", f"{len(progetti)} progetti in tutto",
                  spark=spark_clienti)
        + tessera(media if media is not None else "&mdash;", "Punteggio medio portfolio",
                  (f"su {len(punteggi)} progetti analizzati" if punteggi
                   else "nessun progetto ancora analizzato"),
                  classe=("good" if media is not None and media >= 75 else
                          "warn" if media is not None and media >= 50 else
                          "critical" if media is not None else ""),
                  spark=spark_media)
        + tessera(len(falliti), "Audit falliti (30gg)",
                  f"su {len(recenti)} esecuzioni" if recenti else "nessuna esecuzione",
                  classe="critical" if falliti else "")
        + tessera(len(lead), "Lead in attesa",
                  "richieste da lavorare" if lead else "nessuno da lavorare",
                  classe="warn" if lead else "")
        + '</div>'
    )

    # ── Richiede attenzione ────────────────────────────────────────────────
    def card(numero, tono, titolo, desc, link, invito, icona) -> str:
        return (f'<a class="attention-card" href="{link}">'
                f'<div class="attention-top">'
                f'<div class="attention-icon {tono}">{icona}</div>'
                f'<div class="attention-badge {tono}">{numero}</div></div>'
                f'<div class="attention-title">{titolo}</div>'
                f'<div class="attention-desc">{desc}</div>'
                f'<div class="attention-link">{invito}</div></a>')

    I_PERSONA = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" '
                 'stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 '
                 '00-4-4H5a4 4 0 00-4 4v2"/><circle cx="8.5" cy="7" r="4"/>'
                 '<path d="M20 8v6M23 11h-6"/></svg>')
    I_ALLARME = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" '
                 'stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/>'
                 '<line x1="12" y1="8" x2="12" y2="12"/>'
                 '<line x1="12" y1="16" x2="12.01" y2="16"/></svg>')
    I_BARRE = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" '
               'stroke="currentColor" stroke-width="2"><path d="M12 20V10M18 20V4M6 20v-4"/></svg>')

    voci = []
    if lead:
        pronti = [l for l in lead if l.get("audit") and l["audit"].get("overall") is not None]
        voci.append(card(
            len(lead), "accent", "Lead da approvare",
            (f"{len(pronti)} con l&rsquo;audit preliminare gi&agrave; pronto" if pronti
             else "audit preliminare ancora in corso"),
            "/admin/lead", "Vai alla coda &rarr;", I_PERSONA))
    aperti = falliti_da_rilanciare(audit)
    if aperti:
        voci.append(card(
            len(aperti), "critical", "Audit falliti",
            "Analisi non riuscite e non ancora rifatte, da rilanciare",
            "/admin/job-log", "Vai al log &rarr;", I_ALLARME))
    if senza_tracking:
        voci.append(card(
            senza_tracking, "warn", "Tracking non installato",
            "Progetti senza snippet: di loro non sappiamo niente",
            "/admin/tracking", "Vedi elenco &rarr;", I_BARRE))
    if mai_entrati:
        voci.append(card(
            len(mai_entrati), "warn", "Non sono mai entrati",
            "Hanno l&rsquo;accesso attivo e non l&rsquo;hanno mai usato",
            "/admin/clienti", "Vedi clienti &rarr;", I_PERSONA))

    if voci:
        attenzione = ('<div class="section-title">Richiede attenzione</div>'
                      f'<div class="attention-grid">{"".join(voci)}</div>')
    else:
        attenzione = _vuoto("Non c'è niente in sospeso",
                            "Nessuna richiesta da approvare, nessun audit fallito da "
                            "rilanciare e nessun cliente fermo.")

    return kpi + attenzione + _grafico_portfolio(audit, giorni) + _attivita_recente(azioni or [])

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

    aperti = falliti_da_rilanciare(audit)
    id_aperti = {a["id"] for a in aperti if a.get("id")}

    righe = []
    for a in audit[:80]:
        rotto = a.get("status") == "failed" or a.get("error")
        stato = ('<span class="pill bad">fallito</span>' if rotto
                 else '<span class="pill ok">ok</span>')
        origine = {"auto": "automatico", "manual": "manuale",
                   _LEAD_SOURCE: "lead"}.get(a.get("source"), a.get("source") or "n.d.")
        punteggio = a.get("overall")

        azione = ""
        if rotto:
            if a.get("id") not in id_aperti:
                azione = '<span class="pill ok">poi riuscito</span>'
            elif a.get("url"):
                corpo = json.dumps({"audit_id": a["id"]})
                azione = ('<button class="btn" data-azione="/admin/job/rilancia" '
                          f"data-corpo='{corpo}' "
                          f'data-conferma="Rilanciare l&apos;analisi di '
                          f'{geo_audit.esc(a.get("domain") or a.get("url") or "")}?">'
                          'Rilancia</button>')

        righe.append(
            f'<tr><td>{_quando(a.get("created_at"))}</td>'
            f'<td><b>{geo_audit.esc(a.get("domain") or a.get("url") or "—")}</b></td>'
            f'<td>{geo_audit.esc(origine)}</td>'
            f'<td style="color:{_colore_punteggio(punteggio)}">'
            f'{punteggio if punteggio is not None else "—"}</td>'
            f'<td>{stato}</td>'
            f'<td style="font-family:var(--font-mono);font-size:11.5px;'
            f'color:var(--text-muted)">{_durata(a)}</td>'
            f'<td style="color:var(--text-muted);font-size:12px">'
            f'{geo_audit.esc((a.get("error") or "")[:70])}</td>'
            f'<td style="text-align:right">{azione}</td></tr>'
        )

    if falliti:
        # Il rilancio in blocco compare solo quando ce n'è più d'uno da rifare:
        # con un fallimento solo il bottone della sua riga fa la stessa cosa, e
        # due strade per la stessa azione sono un'occasione di sbagliare.
        tutti = ""
        if len(aperti) > 1:
            quanti = min(len(aperti), MAX_RILANCIO_BLOCCO)
            etichetta = (f"Rilancia tutti e {quanti}" if quanti == len(aperti)
                         else f"Rilancia i primi {quanti} di {len(aperti)}")
            conferma = (f"Rilanciare l&apos;analisi di {quanti} siti? "
                        "Partono insieme e ci mettono qualche minuto.")
            tutti = ('<div style="margin-top:10px">'
                     '<button class="btn" data-azione="/admin/job/rilancia-tutti" '
                     f'data-conferma="{conferma}">{etichetta}</button>'
                     + (f'<div style="font-size:11.5px;color:var(--text-muted);margin-top:6px">'
                        f'Se ne rilanciano al massimo {MAX_RILANCIO_BLOCCO} per volta: '
                        f'ciascuno richiede un giro di crawler da qualche minuto.</div>'
                        if len(aperti) > MAX_RILANCIO_BLOCCO else "")
                     + '</div>')
        nota = ('<div class="avviso"><div>⚠️</div><div>'
                f'<b>{len(falliti)} esecuzion{"e" if len(falliti) == 1 else "i"} '
                f'{"fallita" if len(falliti) == 1 else "fallite"} fra le ultime {len(audit)}.</b> '
                'La colonna «Errore» dice cosa è successo: un dominio che non risolve e un '
                'timeout del crawler vogliono interventi diversi.'
                + (f' <b>{len(aperti)}</b> non {"è" if len(aperti) == 1 else "sono"} '
                   f'ancora {"stata rifatta" if len(aperti) == 1 else "state rifatte"}.'
                   if aperti else " Sono state tutte rifatte con successo.")
                + tutti + '</div></div>')
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
            '<th>Quando</th><th>Sito</th><th>Origine</th><th>Punteggio</th>'
            '<th>Esito</th><th>Durata</th><th>Errore</th><th></th>'
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


def schermata_interesse(richieste: list, audit_per_id: dict, account: set,
                       voti: dict | None = None, iscrizioni: list | None = None,
                       nomi_feature: dict | None = None) -> str:
    """Tutti i segnali commerciali in un posto solo.

    Sono tre fonti diverse e vanno tenute distinte, perché non valgono uguale:
    chi ha chiesto di essere ricontattato ha lasciato un recapito **e** un sito
    già analizzato; chi si è iscritto alla roadmap ha lasciato solo l'email; un
    voto non lascia niente ed è solo un segnale su cosa costruire.
    """
    voti = voti or {}
    iscrizioni = iscrizioni or []
    nomi_feature = nomi_feature or {}

    voci = []
    for r in richieste:
        a = audit_per_id.get(r.get("audit_id")) if r.get("audit_id") else None
        if a and a.get("source") == _LEAD_SOURCE:
            continue                       # è un lead, non un segnale commerciale
        if not r.get("audit_id"):
            continue                       # richiesta senza report: è un lead senza audit
        voci.append(r)

    # ⚠️ «Da contattare» esclude chi ha gia' un account: la prima versione
    # contava solo lo stato, e la schermata diceva «1 da contattare» sopra una
    # tabella in cui l'unica riga era marcata «e' gia' cliente». Un numero che
    # contraddice la tabella che ha sotto insegna a non fidarsi di nessuno dei due.
    da_contattare = [r for r in voci
                     if (r.get("status") or "") != "contattata"
                     and (r.get("email") or "").lower() not in account]
    piu_votata = max(voti.items(), key=lambda x: x[1]) if voti else None

    # ── i tre numeri in cima ───────────────────────────────────────────────
    def tessera(valore, etichetta, sotto, piccolo=False) -> str:
        stile = ' style="font-size:16px"' if piccolo else ""
        return ('<div class="kpi">'
                f'<div class="kpi-label">{etichetta}</div>'
                f'<div class="kpi-value accent"{stile}>{valore}</div>'
                f'<div class="kpi-sub">{sotto}</div></div>')

    kpi = (
        '<div class="kpi-strip tre">'
        + tessera(len(voci), 'Richieste &laquo;analisi completa&raquo;',
                  (f"{len(da_contattare)} da contattare" if da_contattare
                   else "nessuna in sospeso") if voci else "nessuna finora")
        + tessera(len(iscrizioni), "Iscrizioni Roadmap",
                  'form &laquo;Avvisami&raquo;' if iscrizioni else "nessuna finora")
        + tessera(geo_audit.esc(nomi_feature.get(piu_votata[0], piu_votata[0]))
                  if piu_votata else "&mdash;",
                  "Funzionalit&agrave; pi&ugrave; votata",
                  (f"{piu_votata[1]} vot{'o' if piu_votata[1] == 1 else 'i'}"
                   if piu_votata else "nessun voto finora"), piccolo=True)
        + '</div>'
    )

    # ── richieste dal report esterno ───────────────────────────────────────
    if voci:
        righe = []
        for r in voci:
            email = (r.get("email") or "").lower()
            contattato = (r.get("status") or "") == "contattata"
            if contattato:
                stato = '<span class="badge contacted">Contattato</span>'
                azione = ""
            elif email in account:
                stato = '<span class="badge contacted">&Egrave; gi&agrave; cliente</span>'
                azione = ""
            else:
                stato = '<span class="badge new">Nuova</span>'
                corpo = json.dumps({"lead_id": r.get("id"), "stato": "contattata"})
                azione = ('<button class="btn btn-ghost" data-azione="/admin/lead/contattato" '
                          f"data-corpo='{corpo}'>Segna contattato</button>")
            righe.append(
                f'<tr><td><b>{geo_audit.esc(r.get("domain") or "&mdash;")}</b></td>'
                f'<td style="font-family:var(--font-mono);font-size:11.5px;'
                f'color:var(--text-muted)">{geo_audit.esc(r.get("email") or "")}</td>'
                f'<td style="color:{_colore_punteggio(r.get("overall"))}">'
                f'{r.get("overall") if r.get("overall") is not None else "&mdash;"}</td>'
                f'<td>{geo_audit.esc(r.get("phone") or "&mdash;")}</td>'
                f'<td>{_quando(r.get("created_at"))}</td>'
                f'<td>{stato}</td>'
                f'<td style="text-align:right">{azione}</td></tr>')
        sezione_richieste = (
            '<div class="section-title">Richieste &laquo;analisi completa&raquo;'
            '<span class="count">dal report esterno</span></div>'
            '<div class="sezione"><div class="tab-wrap"><table class="tab"><thead><tr>'
            '<th>Sito</th><th>Contatto</th><th>Punteggio</th><th>Telefono</th>'
            '<th>Quando</th><th>Stato</th><th></th>'
            f'</tr></thead><tbody>{"".join(righe)}</tbody></table></div></div>')
    else:
        sezione_richieste = (
            '<div class="section-title">Richieste &laquo;analisi completa&raquo;'
            '<span class="count">dal report esterno</span></div>'
            + _vuoto("Nessuna richiesta di contatto",
                     "Qui arrivano le richieste \u00abvoglio essere contattato\u00bb "
                     "dal report esterno."))

    # ── iscrizioni «Avvisami» ──────────────────────────────────────────────
    if iscrizioni:
        righe = []
        for i in iscrizioni:
            quale = nomi_feature.get(i.get("feature"), i.get("feature") or "")
            righe.append(
                f'<tr><td style="font-family:var(--font-mono);font-size:11.5px">'
                f'{geo_audit.esc(i.get("email") or "")}</td>'
                f'<td>{geo_audit.esc(quale) if quale else "&mdash;"}</td>'
                f'<td>{_quando(i.get("created_at"))}</td></tr>')
        sezione_iscritti = (
            '<div class="section-title">Iscrizioni Roadmap pubblica'
            '<span class="count">form &laquo;Avvisami&raquo;</span></div>'
            '<div class="sezione"><div class="tab-wrap"><table class="tab"><thead><tr>'
            '<th>Email</th><th>Per quale funzionalit&agrave;</th><th>Iscritto</th>'
            f'</tr></thead><tbody>{"".join(righe)}</tbody></table></div></div>')
    else:
        sezione_iscritti = ""

    # ── voti per funzionalità ──────────────────────────────────────────────
    if voti:
        massimo = max(voti.values()) or 1
        righe = []
        for chiave, n in sorted(voti.items(), key=lambda x: -x[1]):
            nome = nomi_feature.get(chiave, chiave)
            larghezza = round(n / massimo * 100)
            righe.append(
                '<div class="vote-row">'
                f'<div class="vote-name">{geo_audit.esc(nome)}</div>'
                '<div class="vote-bar-wrap"><div class="vote-bar-track">'
                f'<div class="vote-bar-fill" style="width:{larghezza}%"></div></div>'
                f'<div class="vote-conteggio">{n}</div></div></div>')
        sezione_voti = ('<div class="section-title">Voti per funzionalit&agrave;'
                        '<span class="count">Roadmap pubblica</span></div>'
                        f'<div class="sezione">{"".join(righe)}</div>')
    else:
        sezione_voti = ""

    return kpi + sezione_richieste + sezione_iscritti + sezione_voti

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
