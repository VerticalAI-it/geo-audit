"""
GEO Audit — costruzione HTML delle schermate di progetto.

Qui vive tutto l'HTML generato in Python per dashboard e dettaglio progetto.
server.py importa queste funzioni e le monta nelle route; nessuna funzione di
questo modulo deve conoscere Request, Response o i cookie.

Regole di design (vedi CLAUDE.md e design_system/DESIGN_SYSTEM.md):
- usare i token del design system, mai i valori legacy hardcoded;
- il report generato da geo_audit.py ha stili inline propri e NON si tocca.
"""
import json
from datetime import datetime, timezone, timedelta

import geo_audit
from ai_sources import CRAWLER_CATEGORIE
from config import SITE_URL
from db import _TETTO_EVENTI, _sb_audits_by_project, _sb_has_tracking, _sb_issues_by_project, \
    _sb_recent_audits_by_user, _sb_tracking_events


_SCAN_FREQUENCY_LABELS = {"daily": "Giornaliero", "weekly": "Settimanale", "monthly": "Mensile"}


_MESI = ("gen", "feb", "mar", "apr", "mag", "giu",
         "lug", "ago", "set", "ott", "nov", "dic")


try:
    from zoneinfo import ZoneInfo
    _TZ_IT = ZoneInfo("Europe/Rome")
except Exception:   # tzdata assente nel runtime: si degrada su UTC
    _TZ_IT = timezone.utc



def _fmt_datetime(iso: str | None) -> str:
    """Data e ora in fuso italiano. Su Supabase i timestamp sono in UTC, ma qui
    serve l'ora locale: il riquadro esiste per rispondere a "sta girando?", e
    un orario spostato di due ore rende la risposta difficile da leggere."""
    if not iso:
        return "—"
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        d = d.astimezone(_TZ_IT)
        return f"{d.day} {_MESI[d.month - 1]} {d.year}, {d:%H:%M}"
    except Exception:
        return iso


def _run_origin_badge(source: str | None) -> str:
    if source == "auto":
        return '<span class="badge badge--brand"><span class="dot"></span>Automatico</span>'
    if source == "manual":
        return '<span class="badge badge--neutral">Manuale</span>'
    # Run precedenti all'introduzione della colonna `source`
    return '<span class="badge badge--neutral">n.d.</span>'


def _run_score_cell(audit: dict) -> str:
    overall = audit.get("overall")
    if overall is None:
        status = audit.get("status") or "—"
        cls = "badge--danger" if status == "failed" else "badge--neutral"
        return f'<span class="badge {cls}">{geo_audit.esc(status)}</span>'
    cls = {"score-ottimo": "score-badge--ottimo",
           "score-migliorabile": "score-badge--migliorabile",
           "score-critico": "score-badge--critico"}.get(_score_class(overall), "")
    grade = audit.get("grade") or ""
    suffix = f'<span style="opacity:.65">&#183;&#8239;{geo_audit.esc(grade)}</span>' if grade else ""
    return f'<span class="score-badge {cls}">{overall}{suffix}</span>'


def _ultimi_run_section(runs: list, domini: dict | None = None) -> str:
    """Riquadro in fondo alla dashboard con gli ultimi run, manuali e
    automatici, per vedere a colpo d'occhio se l'automazione sta girando.

    Riceve i run già letti invece di interrogare il database: la dashboard li
    ha già in mano, e una query in più su una pagina che ne faceva 38 sarebbe
    stata un passo indietro. `domini` mappa project_id -> dominio, perché i
    campi leggeri dell'audit non portano il nome del sito.

    Ritorna stringa vuota se non c'è nulla da mostrare.
    """
    if not runs:
        return ""
    domini = domini or {}

    righe = "".join(
        "<tr>"
        f'<td data-label="Data e ora"><b>{geo_audit.esc(_fmt_datetime(a.get("created_at")))}</b></td>'
        f'<td data-label="Origine">{_run_origin_badge(a.get("source"))}</td>'
        f'<td data-label="Sito"><a href="/r/{geo_audit.esc(str(a.get("id")))}">'
        f'{geo_audit.esc(domini.get(a.get("project_id")) or a.get("domain") or a.get("url") or "—")}</a></td>'
        f'<td data-label="Punteggio">{_run_score_cell(a)}</td>'
        "</tr>"
        for a in runs
    )

    ultimo_auto = next((a for a in runs if a.get("source") == "auto"), None)
    if ultimo_auto:
        stato = ("Ultimo audit automatico: "
                 f'<b>{geo_audit.esc(_fmt_datetime(ultimo_auto.get("created_at")))}</b>.')
    else:
        stato = ("Nessun audit automatico fra questi run: al momento vedi solo "
                 "analisi lanciate a mano.")

    return (
        '<div class="data-card" id="ultimi-run" style="margin-top:28px">'
        '<div class="section-header">'
        '<div><div class="section-title">Ultimi run</div>'
        '<div class="card-desc">Le analisi più recenti sui tuoi siti, lanciate a mano '
        'o dal monitoraggio automatico.</div></div>'
        '</div>'
        '<div class="table-scroll"><table class="data-grid"><thead><tr>'
        "<th>Data e ora</th><th>Origine</th><th>Sito</th><th>Punteggio</th>"
        "</tr></thead><tbody>" + righe + "</tbody></table></div>"
        f'<div class="table-footer"><span>{stato}</span></div>'
        "</div>"
    )



def _project_status(latest: dict | None) -> str:
    """Healthy / Needs attention / Critical / Audit required, calcolato
    dall'ultimo audit_run del progetto (nessuno stato persistito a mano)."""
    if not latest or latest.get("overall") is None:
        return "Audit required"
    try:
        created = datetime.fromisoformat(latest["created_at"].replace("Z", "+00:00"))
        age_days = (datetime.now(timezone.utc) - created).days
    except Exception:
        age_days = 0
    if age_days > 30:
        return "Audit required"
    if (latest.get("critical_count") or 0) > 0:
        return "Critical"
    overall = latest.get("overall") or 0
    if overall < 50:
        return "Critical"
    if overall < 75:
        return "Needs attention"
    return "Healthy"


_TAB_CATEGORIES = [
    ("overview", "Overview", None),
    ("audit", "Audit", [
        ("audit", "Riepilogo"), ("pages", "Pages"),
        ("technical", "Technical GEO"), ("opportunities", "Opportunities"),
    ]),
    ("ai", "AI Intelligence", [
        ("ai-visibility", "AI Visibility"), ("prompts", "Prompts & Queries"),
        ("competitors", "Competitors"), ("citations", "Citations"),
    ]),
    ("growth", "Traffic & Reports", [
        ("traffic", "AI Traffic"), ("reports", "Reports"),
    ]),
    ("settings", "Settings", None),
]


_COMING_SOON_TABS = {
    "ai-visibility": ("AI Visibility",
        "Richiede un panel di monitoraggio prompt sui provider AI (ChatGPT, Gemini, Perplexity). "
        "Non ancora configurato per questo progetto."),
    "prompts": ("Prompts & Queries",
        "Richiede il monitoraggio prompt attivo per esplorare cluster, risposte e storico. Non ancora configurato."),
    "competitors": ("Competitors",
        "Richiede lo stesso panel di monitoraggio prompt per calcolare Share of Voice e gap competitivi. "
        "Non ancora configurato."),
    "citations": ("Citations",
        "Richiede l'osservazione delle citazioni nelle risposte AI. Non ancora configurato."),
    "reports": ("Reports",
        "Richiede almeno un modulo di monitoraggio attivo per generare variazioni e alert. Non ancora disponibile."),
}


_STATUS_BADGE_CLS = {"ok": "badge--success", "warn": "badge--warning", "fail": "badge--danger", "unknown": "badge--neutral"}
_STATUS_LABEL     = {"ok": "OK", "warn": "Migliorabile", "fail": "Critico", "unknown": "N/D"}
_SEV_BADGE_CLS    = {"critical": "badge--danger", "high": "badge--danger", "medium": "badge--warning",
                      "low": "badge--neutral", "info": "badge--neutral"}


def _category_for_tab(tab: str) -> str:
    for cat_key, _, children in _TAB_CATEGORIES:
        if children is None:
            if cat_key == tab:
                return cat_key
        elif any(k == tab for k, _ in children):
            return cat_key
    return "overview"


# ── Sezioni dimostrative ─────────────────────────────────────────────────────
#
# Decisione di prodotto del 1 settembre 2026: le sezioni non ancora attive
# mostrano dati realistici con un banner esplicito, invece di una scatola vuota.
# Sostituisce la regola precedente ("mai dati simulati"), che vietava anche
# questo. Il banner e' obbligatorio: senza, sarebbero numeri finti spacciati
# per veri.
#
# I dati qui dentro sono FISSI e non provengono da nessuna misurazione. Quando
# una sezione diventa reale, si toglie la voce da _SEZIONI_CAMPIONE e si scrive
# la funzione vera.

def _banner_campione(dominio: str, cosa_serve: str) -> str:
    return (
        '<div class="sample-banner">'
        '<div class="sample-banner-left">'
        '<div class="sample-icon">'
        '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="white" '
        'stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="10"/>'
        '<path d="M12 8v4l3 2"/></svg>'
        '</div>'
        '<div class="sample-text">'
        '<div class="label">Report di esempio</div>'
        f'<div class="desc">Questi sono <b>dati dimostrativi</b>, non misurazioni di '
        f'<b>{geo_audit.esc(dominio)}</b>. {geo_audit.esc(cosa_serve)}</div>'
        '</div></div>'
        f'<a class="btn btn-primary" href="mailto:geo@verticalai.it'
        f'?subject=Attivazione%20monitoraggio%20per%20{geo_audit.esc(dominio)}">'
        'Richiedi l\'attivazione</a>'
        '</div>'
    )


def _barra_semplice(valore: int, classe: str = "warn") -> str:
    return (f'<div class="area-track"><div class="area-fill {classe}" '
            f'style="--w:{valore}%"></div></div>')


def _kpi_semplice(valore, etichetta: str, sotto: str = "", classe: str = "") -> str:
    """Una tessera della `.kpi-strip` del design system.

    Sta qui e non dentro una singola scheda perche' la usano in due, e due copie
    della stessa tessera divergono al primo ritocco.
    """
    return (
        '<div class="kpi">'
        f'<div class="kpi-top"><span class="kpi-label">{etichetta}</span></div>'
        f'<div class="kpi-value-row"><span class="kpi-value {classe}">{valore}</span></div>'
        + (f'<div class="kpi-sub">{sotto}</div>' if sotto else '')
        + '</div>'
    )


# Lo stesso script serve allo snippet di tracking e al rapporto da copiare: e'
# idempotente (`data-pronto`), quindi due inclusioni nella stessa pagina non
# agganciano due volte lo stesso bottone.
_COPIA_JS = """<script>
document.querySelectorAll('.copy-btn[data-copia]').forEach(function(b){
  if (b.dataset.pronto) return;
  b.dataset.pronto = "1";
  b.addEventListener('click', function(){
    navigator.clipboard.writeText(b.dataset.testo).then(function(){
      const et = b.querySelector('span');
      const prima = et.textContent;
      et.textContent = '✓ Copiato';
      b.classList.add('copied');
      setTimeout(function(){ et.textContent = prima; b.classList.remove('copied'); }, 1800);
    });
  });
});
</script>"""

_SEV_BARRA = {"critical": "critical", "high": "critical", "medium": "warn",
              "low": "good", "info": "good"}


def _campione_ai_visibility(dominio: str) -> str:
    motori = [("ChatGPT", 34, "warn"), ("Perplexity", 41, "warn"),
              ("Gemini", 22, "critical"), ("Google AI Overview", 18, "critical"),
              ("Claude", 12, "critical")]
    righe_motori = "".join(
        f'<div class="engine-row"><div class="engine-name">{geo_audit.esc(n)}</div>'
        f'{_barra_semplice(v, c)}<div class="area-value">{v}%</div></div>'
        for n, v, c in motori
    )
    argomenti = [("selle e accessori equitazione", 38, "+6"), ("abbigliamento da equitazione", 26, "+2"),
                 ("cura del cavallo", 19, "-3"), ("attrezzatura scuderia", 11, "0")]
    righe_arg = "".join(
        f'<tr><td class="topic-name">{geo_audit.esc(t)}</td>'
        f'<td><span class="score-cell {"warn" if v >= 25 else "critical"}">{v}%</span></td>'
        f'<td><span class="{"trend-up" if d.startswith("+") else ("trend-down" if d.startswith("-") else "trend-flat")}">{d}</span></td></tr>'
        for t, v, d in argomenti
    )
    return (
        '<div class="hero-row">'
        '<div class="hero-card">'
        '<div class="gauge-wrap">'
        '<svg viewBox="0 0 150 90" width="150" height="90" aria-hidden="true">'
        '<defs><linearGradient id="gaugeGrad" x1="0%" y1="0%" x2="100%" y2="0%">'
        '<stop offset="0%" stop-color="var(--state-critical)"/>'
        '<stop offset="100%" stop-color="var(--state-warn)"/></linearGradient></defs>'
        '<path d="M 10 85 A 65 65 0 0 1 140 85" fill="none" stroke="var(--bg-surface-raised)" '
        'stroke-width="14" stroke-linecap="round"/>'
        # 204 e' la lunghezza del semicerchio (pi greco per il raggio 65). Per
        # mostrare 29 su 100 l'arco pieno deve essere il 29%: 204 * (1 - 0,29).
        # Il prototipo aveva 169, che disegnava il 17% accanto al numero 29.
        '<path d="M 10 85 A 65 65 0 0 1 140 85" fill="none" stroke="url(#gaugeGrad)" '
        'stroke-width="14" stroke-linecap="round" stroke-dasharray="204" stroke-dashoffset="145"/>'
        '</svg>'
        '<div class="gauge-center"><div class="gauge-score">29<span class="gauge-max">/100</span></div></div>'
        '</div>'
        '<div class="gauge-label critical">Visibilità bassa</div>'
        '<div class="hero-note">Citato raramente nelle risposte AI rispetto ai competitor diretti.</div>'
        '</div>'
        '<div class="card">'
        '<div class="hero-side-top"><div class="hero-side-title">Andamento visibilità (6 mesi)</div></div>'
        '<div class="chart"><svg viewBox="0 0 600 130" preserveAspectRatio="none" aria-hidden="true">'
        '<polyline points="0,40 100,50 200,60 300,55 400,70 500,50 600,35" fill="none" '
        'stroke="var(--state-good)" stroke-width="2.5"/>'
        '<polyline points="0,80 100,78 200,85 300,90 400,88 500,92 600,86" fill="none" '
        'stroke="var(--accent-primary)" stroke-width="2.5"/>'
        '<polyline points="0,95 100,90 200,88 300,80 400,75 500,70 600,68" fill="none" '
        'stroke="var(--text-muted)" stroke-width="1.5" stroke-dasharray="4 3"/>'
        '</svg></div>'
        '<div class="chart-legend">'
        '<div class="legend-item"><span class="legend-dot" style="background:var(--state-good)"></span>Miglior competitor</div>'
        f'<div class="legend-item"><span class="legend-dot" style="background:var(--accent-primary)"></span>{geo_audit.esc(dominio)}</div>'
        '<div class="legend-item"><span class="legend-dot" style="background:var(--text-muted)"></span>Media di settore</div>'
        '</div></div></div>'

        '<div class="data-card">'
        '<div class="section-header"><div class="section-title">Distribuzione per motore AI</div>'
        '<div class="card-desc">Quanto spesso il sito compare nelle risposte di ciascun assistente</div></div>'
        f'<div style="padding:8px 20px 16px">{righe_motori}</div></div>'

        '<div class="data-card">'
        '<div class="section-header"><div class="section-title">Argomenti monitorati</div></div>'
        '<div class="table-scroll"><table class="data-grid"><thead><tr>'
        '<th>Argomento</th><th>Visibilità</th><th>Variazione</th>'
        f'</tr></thead><tbody>{righe_arg}</tbody></table></div></div>'
    )


def _campione_prompts(dominio: str) -> str:
    righe = [("Qual è la migliore sella da dressage?", "informazionale", 41, 3, "alto"),
             ("Dove comprare accessori per equitazione online", "transazionale", 28, 2, "alto"),
             ("Come scegliere la taglia di una sella", "informazionale", 22, 1, "medio"),
             ("Migliori marche di abbigliamento equestre", "comparativo", 17, 1, "medio"),
             ("Manutenzione della sella in cuoio", "informazionale", 9, 0, "basso")]
    corpo = "".join(
        f'<tr><td class="topic-name">{geo_audit.esc(p)}</td>'
        f'<td><span class="url-type">{geo_audit.esc(i)}</span></td>'
        f'<td><span class="score-cell {"warn" if v >= 20 else "critical"}">{v}%</span></td>'
        f'<td><span class="issue-count">{m}</span></td>'
        f'<td><span class="url-type">{geo_audit.esc(vol)}</span></td></tr>'
        for p, i, v, m, vol in righe
    )
    return (
        '<div class="data-card">'
        '<div class="section-header"><div class="section-title">Prompt monitorati</div>'
        '<div class="card-desc">Domande poste agli assistenti per verificare se il sito viene citato</div></div>'
        '<div class="table-scroll"><table class="data-grid"><thead><tr>'
        '<th>Prompt</th><th>Intento</th><th>Visibilità</th><th>Tue menzioni</th><th>Volume AI</th>'
        f'</tr></thead><tbody>{corpo}</tbody></table></div></div>'
        '<div class="data-card"><div class="section-header">'
        '<div class="section-title">Come si scelgono i prompt</div></div>'
        '<div style="padding:14px 20px"><p class="card-desc">Il monitoraggio usa domande '
        '<b>non di marca</b>: chiedere «cosa vendete» darebbe sempre una citazione e non '
        'misurerebbe nulla. Contano le domande che un cliente farebbe <i>prima</i> di '
        'conoscervi.</p></div></div>'
    )


def _campione_competitors(dominio: str) -> str:
    righe = [(dominio, 12, "neutro", 34, "0", True),
             ("competitor-alfa.com", 31, "positivo", 88, "+7", False),
             ("competitor-beta.it", 24, "positivo", 67, "+2", False),
             ("competitor-gamma.eu", 19, "neutro", 52, "-4", False),
             ("competitor-delta.com", 14, "neutro", 39, "+1", False)]
    corpo = "".join(
        f'<tr><td class="check-name">{geo_audit.esc(d)}'
        + (' <span class="badge neutral">tu</span>' if tuo else '') + '</td>'
        f'<td><span class="score-cell {"critical" if sov < 15 else "warn" if sov < 25 else "good"}">{sov}%</span></td>'
        f'<td><span class="url-type">{geo_audit.esc(sent)}</span></td>'
        f'<td><span class="issue-count">{men}</span></td>'
        f'<td><span class="{"trend-up" if t.startswith("+") else ("trend-down" if t.startswith("-") else "trend-flat")}">{t}</span></td></tr>'
        for d, sov, sent, men, t, tuo in righe
    )
    return (
        '<div class="data-card">'
        '<div class="section-header"><div class="section-title">Insight generati</div></div>'
        '<div style="padding:14px 20px"><p class="card-desc">Su un campione di prompt di settore, '
        '<b>competitor-alfa.com</b> viene citato quasi tre volte più spesso. Il divario più ampio '
        'è sulle domande comparative, dove il sito non compare mai.</p></div></div>'
        '<div class="data-card">'
        '<div class="section-header"><div class="section-title">Confronto dettagliato</div></div>'
        '<div class="table-scroll"><table class="data-grid"><thead><tr>'
        '<th>Dominio</th><th>Share of Voice</th><th>Sentiment</th><th>Menzioni (30gg)</th><th>Trend</th>'
        f'</tr></thead><tbody>{corpo}</tbody></table></div></div>'
    )


def _campione_citations(dominio: str) -> str:
    pagine = [("/selle-dressage", 14, "ChatGPT, Perplexity"),
              ("/guida-taglie", 9, "Perplexity"),
              ("/", 6, "ChatGPT, Gemini"),
              ("/manutenzione-cuoio", 3, "Perplexity")]
    corpo_pagine = "".join(
        f'<tr><td class="url-main">{geo_audit.esc(p)}</td>'
        f'<td><span class="issue-count">{n}</span></td>'
        f'<td class="detail-text">{geo_audit.esc(m)}</td></tr>'
        for p, n, m in pagine
    )
    terze = [("forum-equitazione.it", 11, "positivo"),
             ("rivista-cavalli.com", 7, "neutro"),
             ("blog-dressage.eu", 4, "positivo")]
    corpo_terze = "".join(
        f'<tr><td class="url-main">{geo_audit.esc(d)}</td>'
        f'<td><span class="issue-count">{n}</span></td>'
        f'<td><span class="url-type">{geo_audit.esc(s)}</span></td></tr>'
        for d, n, s in terze
    )
    return (
        '<div class="kpi-strip">'
        '<div class="kpi"><div class="kpi-top"><span class="kpi-label">Citazioni dirette (30gg)</span></div>'
        '<div class="kpi-value">32</div><div class="kpi-sub">il sito citato come fonte</div></div>'
        '<div class="kpi"><div class="kpi-top"><span class="kpi-label">Pagine citate</span></div>'
        '<div class="kpi-value">4</div><div class="kpi-sub">su 6 analizzate</div></div>'
        '<div class="kpi"><div class="kpi-top"><span class="kpi-label">Fonti terze</span></div>'
        '<div class="kpi-value">22</div><div class="kpi-sub">menzioni su altri domini</div></div>'
        '<div class="kpi"><div class="kpi-top"><span class="kpi-label">Sentiment medio</span></div>'
        '<div class="kpi-value good">positivo</div><div class="kpi-sub">su 54 menzioni</div></div>'
        '</div>'
        '<div class="data-card">'
        '<div class="section-header"><div class="section-title">Citazioni dirette del sito</div>'
        '<div class="card-desc">Quando un assistente indica una vostra pagina come fonte</div></div>'
        '<div class="table-scroll"><table class="data-grid"><thead><tr>'
        '<th>Pagina</th><th>Citazioni</th><th>Dove</th>'
        f'</tr></thead><tbody>{corpo_pagine}</tbody></table></div></div>'
        '<div class="data-card">'
        '<div class="section-header"><div class="section-title">Fonti terze che parlano del brand</div>'
        '<div class="card-desc">Domini esterni citati dalle AI parlando di voi: sono due fenomeni '
        'distinti e restano separati anche nei dati</div></div>'
        '<div class="table-scroll"><table class="data-grid"><thead><tr>'
        '<th>Dominio</th><th>Menzioni</th><th>Sentiment</th>'
        f'</tr></thead><tbody>{corpo_terze}</tbody></table></div></div>'
    )


def _campione_reports(dominio: str) -> str:
    avvisi = [("Variazione del punteggio", "Quando il GEO Score cambia di oltre 5 punti fra due audit."),
              ("Nuova criticità grave", "Quando compare un problema di severità alta o critica."),
              ("Digest settimanale", "Il lunedì mattina, il riepilogo di tutti i progetti.")]
    righe = "".join(
        '<div class="alert-row">'
        f'<div class="alert-text"><b>{geo_audit.esc(t)}</b><p>{geo_audit.esc(d)}</p></div>'
        '<div class="toggle-switch off" aria-hidden="true"></div>'
        '</div>'
        for t, d in avvisi
    )
    return (
        '<div class="data-card">'
        '<div class="section-header"><div class="section-title">Digest settimanale (esempio)</div></div>'
        '<div style="padding:16px 20px">'
        '<div class="mail-mock">'
        '<div class="mail-mock-head">'
        f'<div class="mail-mock-subject">GEO Audit \u00b7 {geo_audit.esc(dominio)}: '
        'il punto della settimana</div>'
        '<div class="mail-mock-meta">da geo@verticalai.it \u00b7 luned\u00ec, 07:00</div>'
        '</div>'
        '<div class="mail-mock-body">'
        'Il punteggio è passato da <b>78</b> a <b>82</b> (+4).<br>'
        'Sono state risolte <b>3 criticità</b>, una nuova è comparsa su <b>/contatti</b>.<br>'
        'Nessun calo di traffico dagli assistenti AI.<br><br>'
        'L\'intervento con più impatto questa settimana: <b>aggiungere la meta description</b> '
        'alle 3 pagine che ne sono prive.'
        '</div></div></div></div>'
        '<div class="data-card">'
        '<div class="section-header"><div class="section-title">Avvisi configurabili</div>'
        '<div class="card-desc">Non ancora attivabili: richiedono il sistema di notifiche</div></div>'
        f'<div style="padding:4px 20px 14px">{righe}</div></div>'
    )


_SEZIONI_CAMPIONE = {
    "ai-visibility": (_campione_ai_visibility,
        "Serve il monitoraggio dei prompt su ChatGPT, Gemini e Perplexity per avere i numeri veri."),
    "prompts": (_campione_prompts,
        "Serve il monitoraggio dei prompt per sapere su quali domande il sito compare."),
    "competitors": (_campione_competitors,
        "Serve il monitoraggio dei prompt e l'elenco dei concorrenti da confrontare."),
    "citations": (_campione_citations,
        "Serve l'osservazione delle citazioni nelle risposte degli assistenti."),
    # `reports` stava qui ed e' uscito il 2 settembre 2026: ogni numero del
    # digest d'esempio era gia' calcolabile sui dati del progetto. Vedi
    # `_tab_reports`. Cio' che manca non e' il rapporto ma la sua spedizione
    # automatica, e quella la scheda la dichiara invece di simularla.
}


def _tab_campione(chiave: str, dominio: str) -> str:
    """Sezione non ancora attiva, resa con dati dimostrativi e banner esplicito."""
    costruisci, cosa_serve = _SEZIONI_CAMPIONE[chiave]
    return _banner_campione(dominio, cosa_serve) + costruisci(dominio)


def _coming_soon_tab(title: str, description: str) -> str:
    return (
        '<div class="card coming-soon-card">'
        '<span class="badge badge--neutral"><span class="dot"></span>Coming soon</span>'
        f'<h2 class="card-title" style="margin-top:12px">{geo_audit.esc(title)}</h2>'
        f'<p class="card-sub">{geo_audit.esc(description)}</p>'
        '</div>'
    )


def _status_badge(status: str) -> str:
    cls = _STATUS_BADGE_CLS.get(status, "badge--neutral")
    label = _STATUS_LABEL.get(status, status or "—")
    return f'<span class="badge {cls}"><span class="dot"></span>{geo_audit.esc(label)}</span>'


def _sev_badge(sev: str) -> str:
    cls = _SEV_BADGE_CLS.get(sev, "badge--neutral")
    return f'<span class="badge {cls}">{geo_audit.esc(sev or "—")}</span>'


def _score_class(overall) -> str:
    if overall is None:
        return "score-unknown"
    if overall >= 75:
        return "score-ottimo"
    if overall >= 50:
        return "score-migliorabile"
    return "score-critico"


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return d.strftime("%d %b %Y")
    except Exception:
        return iso


def _checks_table(rows: list) -> str:
    """rows: [{'title','status','detail','recommendation'}]"""
    if not rows:
        return '<p class="card-sub">Nessun dato disponibile.</p>'
    body = "".join(
        f'<tr><td data-label="Check"><b>{geo_audit.esc(r["title"])}</b></td>'
        f'<td data-label="Stato">{_status_badge(r["status"])}</td>'
        f'<td data-label="Dettaglio">{geo_audit.esc(r.get("detail") or "—")}</td>'
        f'<td data-label="Raccomandazione">{geo_audit.esc(r.get("recommendation") or "—")}</td></tr>'
        for r in rows
    )
    return (
        '<div class="tbl-wrap"><table class="tbl tbl-responsive"><thead><tr>'
        '<th>Check</th><th>Stato</th><th>Dettaglio</th><th>Raccomandazione</th>'
        '</tr></thead><tbody>' + body + '</tbody></table></div>'
    )


def _aggregate_page_check(pages_detail: list, check_id: str) -> dict:
    """Aggrega lo stato di un check page-level su tutte le pagine dell'audit."""
    matches = [c for p in (pages_detail or []) for c in (p.get("checks") or []) if c.get("id") == check_id]
    if not matches:
        return {"total": 0}
    ok = len([c for c in matches if c["status"] == "ok"])
    warn = len([c for c in matches if c["status"] == "warn"])
    fail = len([c for c in matches if c["status"] == "fail"])
    worst = matches[0]
    for c in matches:
        if c["status"] == "fail":
            worst = c
            break
        if c["status"] == "warn" and worst["status"] != "fail":
            worst = c
    return {"title": worst["title"], "status": worst["status"], "recommendation": worst.get("recommendation"),
            "ok": ok, "warn": warn, "fail": fail, "total": len(matches)}


def _section_card(project_id: str, tab_key: str, label: str, stat_num: str, stat_label: str,
                   summary: str, soon: bool) -> str:
    badge = '<span class="badge badge--neutral">Coming soon</span>' if soon else ''
    cls = "card section-card" + (" coming-soon-card" if soon else "")
    return (
        f'<a href="/project/{project_id}?tab={tab_key}" class="{cls}">'
        f'{badge}'
        f'<div class="section-card-stat"><span class="section-stat-num">{geo_audit.esc(stat_num)}</span>'
        f'<span class="section-stat-label">{geo_audit.esc(stat_label)}</span></div>'
        f'<div class="card-title">{geo_audit.esc(label)}</div>'
        f'<p class="card-sub">{summary}</p>'
        '<span class="section-card-link">Apri dettaglio →</span>'
        '</a>'
    )


def _overview_sections_grid(project_id: str, latest: dict | None, open_issues: int, resolved_recent: int) -> str:
    if latest:
        pages = latest.get("pages_detail") or []
        pages_with_issues = len([p for p in pages if any(c.get("status") in ("warn", "fail") for c in (p.get("checks") or []))])
        site_checks = latest.get("site_checks") or []
        site_ok = len([c for c in site_checks if c.get("status") == "ok"])

        pages_stat = str(len(pages)) if pages else "—"
        pages_summary = f'{len(pages)} pagine analizzate, {pages_with_issues} con almeno un problema.' if pages else "Nessuna pagina analizzata."

        tech_stat = f'{round(100 * site_ok / len(site_checks))}%' if site_checks else "—"
        technical_summary = f'{site_ok}/{len(site_checks)} check di accesso e infrastruttura superati.' if site_checks else "Nessun dato tecnico disponibile."

        areas = latest.get("areas") or []
        audit_stat = str(latest.get("overall")) if latest.get("overall") is not None else "—"
        audit_summary = (f'Punteggio {latest.get("overall", "—")}/100 su {len(areas)} aree, '
                          f'area migliore «{geo_audit.esc(areas[-1]["key"])}».') if areas else "Nessun audit ancora eseguito."
    else:
        pages_stat = tech_stat = audit_stat = "—"
        pages_summary = technical_summary = audit_summary = "Nessun audit ancora eseguito."

    opportunities_summary = f'{open_issues} issue aperte' + (f', {resolved_recent} risolte di recente.' if resolved_recent else '.')

    tracking_events = _sb_tracking_events(project_id, days=30, limit=5000)
    if tracking_events:
        ai_sessions = len({e.get("session_id") for e in tracking_events if e.get("ai_source")})
        traffic_stat = str(ai_sessions)
        traffic_summary = f'{ai_sessions} sessioni da assistenti AI negli ultimi 30 giorni.'
    else:
        traffic_stat = "—"
        traffic_summary = "Nessun evento ricevuto: installa lo snippet di tracking per attivare questa sezione."

    cards = [
        _section_card(project_id, "audit", "Audit", audit_stat, "Punteggio GEO", audit_summary, False),
        _section_card(project_id, "pages", "Pages", pages_stat, "pagine analizzate", pages_summary, False),
        _section_card(project_id, "technical", "Technical GEO", tech_stat, "check superati", technical_summary, False),
        _section_card(project_id, "opportunities", "Opportunities", str(open_issues), "issue aperte", opportunities_summary, False),
        _section_card(project_id, "traffic", "AI Traffic", traffic_stat, "sessioni AI (30gg)", traffic_summary, False),
    ]
    for tab_key, (label, desc) in _COMING_SOON_TABS.items():
        cards.append(_section_card(project_id, tab_key, label, "—", "non configurato", desc, True))

    return f'<div class="card-title" style="margin:24px 0 12px">Tutte le sezioni</div><div class="section-grid">{"".join(cards)}</div>'


_SCORE_CHART_JS = r"""
(function(){
  var W = 600, H = 180, PAD = {left:30, right:10, top:14, bottom:22};
  var MS_DAY = 86400000;
  var months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  var allPoints = __DATA__.map(function(p){ return {t: new Date(p.t).getTime(), s: p.s}; });
  var card = document.getElementById("__CHART_ID__-card");
  var svg = document.getElementById("__CHART_ID__");
  var tip = document.getElementById("__CHART_ID__-tip");
  var wrap = svg.parentElement;
  var svgNS = "http://www.w3.org/2000/svg";

  function fmtDate(ms) {
    var d = new Date(ms);
    return d.getDate() + " " + months[d.getMonth()] + " " + d.getFullYear();
  }
  function elNS(tag, attrs) {
    var e = document.createElementNS(svgNS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }
  function xScale(t, minT, maxT) {
    if (maxT === minT) return (W - PAD.left - PAD.right) / 2 + PAD.left;
    return PAD.left + (t - minT) / (maxT - minT) * (W - PAD.left - PAD.right);
  }
  function yScale(s) {
    return PAD.top + (100 - s) / 100 * (H - PAD.top - PAD.bottom);
  }

  function render(points) {
    svg.innerHTML = "";
    tip.hidden = true;
    if (!points.length) {
      var msg = elNS("text", {x:W/2, y:H/2, "text-anchor":"middle", "class":"grid-label"});
      msg.textContent = "Nessun dato in questo intervallo.";
      svg.appendChild(msg);
      return;
    }
    var minT = points[0].t, maxT = points[points.length-1].t;

    [0,50,100].forEach(function(v){
      var y = yScale(v);
      svg.appendChild(elNS("line", {x1:PAD.left, x2:W-PAD.right, y1:y, y2:y, "class":"grid-line"}));
      var lbl = elNS("text", {x:4, y:y+3, "class":"grid-label"});
      lbl.textContent = v;
      svg.appendChild(lbl);
    });

    var last = points[points.length-1];
    var lastX = xScale(last.t, minT, maxT);
    if (points.length === 1) {
      svg.appendChild(elNS("circle", {cx:lastX, cy:yScale(last.s), r:5, "class":"score-dot"}));
    } else {
      var d = "";
      points.forEach(function(p, i){
        var x = xScale(p.t, minT, maxT), y = yScale(p.s);
        d += (i === 0 ? "M" : "L") + x + "," + y + " ";
      });
      var baseY = yScale(0);
      var firstX = xScale(points[0].t, minT, maxT);
      var area = d + "L" + lastX + "," + baseY + " L" + firstX + "," + baseY + " Z";
      svg.appendChild(elNS("path", {d: area, "class":"score-area"}));
      svg.appendChild(elNS("path", {d: d, "class":"score-line"}));
      svg.appendChild(elNS("circle", {cx:lastX, cy:yScale(last.s), r:5, "class":"score-dot"}));
    }

    var crossLine = elNS("line", {"class":"crosshair-line", y1:PAD.top, y2:H-PAD.bottom});
    var hoverDot = elNS("circle", {"class":"hover-dot", r:5});
    svg.appendChild(crossLine);
    svg.appendChild(hoverDot);

    var hit = elNS("rect", {x:PAD.left, y:PAD.top, width:Math.max(1,W-PAD.left-PAD.right), height:Math.max(1,H-PAD.top-PAD.bottom), "class":"hit-area"});
    svg.appendChild(hit);

    function nearest(clientX) {
      var pt = svg.createSVGPoint();
      pt.x = clientX; pt.y = 0;
      var loc = pt.matrixTransform(svg.getScreenCTM().inverse());
      var best = points[0], bestDist = Infinity;
      points.forEach(function(p){
        var x = xScale(p.t, minT, maxT);
        var dist = Math.abs(x - loc.x);
        if (dist < bestDist) { bestDist = dist; best = p; }
      });
      return best;
    }

    function showTip(clientX) {
      var p = nearest(clientX);
      var x = xScale(p.t, minT, maxT), y = yScale(p.s);
      crossLine.setAttribute("x1", x); crossLine.setAttribute("x2", x);
      crossLine.style.opacity = 1;
      hoverDot.setAttribute("cx", x); hoverDot.setAttribute("cy", y);
      hoverDot.style.opacity = 1;
      var rect = svg.getBoundingClientRect();
      var wrapRect = wrap.getBoundingClientRect();
      var px = rect.left + (x / W) * rect.width - wrapRect.left;
      var py = rect.top + (y / H) * rect.height - wrapRect.top;
      tip.innerHTML = "";
      var scEl = document.createElement("span"); scEl.className = "tip-score"; scEl.textContent = p.s + "/100";
      var dtEl = document.createElement("span"); dtEl.className = "tip-date"; dtEl.textContent = fmtDate(p.t);
      tip.appendChild(scEl); tip.appendChild(dtEl);
      tip.style.left = px + "px";
      tip.style.top = py + "px";
      tip.hidden = false;
    }
    function hideTip() {
      crossLine.style.opacity = 0;
      hoverDot.style.opacity = 0;
      tip.hidden = true;
    }

    hit.addEventListener("mousemove", function(e){ showTip(e.clientX); });
    hit.addEventListener("mouseleave", hideTip);
    hit.addEventListener("touchmove", function(e){
      if (e.touches[0]) { showTip(e.touches[0].clientX); e.preventDefault(); }
    }, {passive:false});
    hit.addEventListener("touchend", hideTip);
  }

  function filterPoints(rangeDays) {
    if (rangeDays === "all") return allPoints;
    var cutoff = Date.now() - parseInt(rangeDays, 10) * MS_DAY;
    return allPoints.filter(function(p){ return p.t >= cutoff; });
  }

  var buttons = card.querySelectorAll(".range-btn");
  for (var i = 0; i < buttons.length; i++) {
    buttons[i].addEventListener("click", function(){
      var b = this;
      for (var j = 0; j < buttons.length; j++) { buttons[j].classList.remove("active"); buttons[j].setAttribute("aria-pressed","false"); }
      b.classList.add("active"); b.setAttribute("aria-pressed","true");
      render(filterPoints(b.getAttribute("data-range")));
    });
  }

  render(allPoints);
})();
"""


def _score_history_chart(project_id: str, history: list) -> str:
    """Grafico storico del punteggio GEO con filtri 3/6 mesi / all time.
    `history` è la lista (ordine created_at desc) degli audit del progetto
    con almeno {overall, created_at}; il rendering effettivo è lato client
    (JS) così i filtri non richiedono un round-trip al server."""
    points = [
        {"t": h["created_at"], "s": h["overall"]}
        for h in reversed(history)
        if h.get("overall") is not None
    ]
    if not points:
        return ('<div class="card" style="margin-top:16px"><div class="card-title">Storico punteggio</div>'
                '<p class="card-sub">Ancora nessun punteggio registrato.</p></div>')

    current = points[-1]["s"]
    sc = _score_class(current)

    if len(points) == 1:
        return (
            '<div class="card" style="margin-top:16px">'
            '<div class="card-title">Storico punteggio</div>'
            f'<div class="score-history-single"><span class="score-history-current {sc}">{current}</span>'
            '<p class="card-sub">Servono almeno due audit per costruire uno storico. '
            'Il prossimo audit automatico aggiungerà un nuovo punto.</p></div>'
            '</div>'
        )

    chart_id = f"score-chart-{project_id}"
    js = (_SCORE_CHART_JS
          .replace("__DATA__", json.dumps(points))
          .replace("__CHART_ID__", chart_id))

    return (
        f'<div class="card score-history-card" id="{chart_id}-card" style="margin-top:16px">'
        '<div class="score-history-head">'
        '<div class="card-title" style="margin:0">Storico punteggio</div>'
        '<div class="range-filter" role="group" aria-label="Intervallo">'
        '<button type="button" class="range-btn" data-range="90" aria-pressed="false">3 mesi</button>'
        '<button type="button" class="range-btn" data-range="180" aria-pressed="false">6 mesi</button>'
        '<button type="button" class="range-btn active" data-range="all" aria-pressed="true">Tutto</button>'
        '</div></div>'
        '<div class="score-history-body">'
        '<div class="score-history-current-wrap">'
        f'<span class="score-history-current {sc}">{current}</span>'
        '<span class="score-history-current-label">punteggio attuale</span>'
        '</div>'
        '<div class="score-chart-wrap">'
        f'<svg class="score-chart-svg" id="{chart_id}" viewBox="0 0 600 180" preserveAspectRatio="none" '
        'role="img" aria-label="Andamento del punteggio GEO nel tempo"></svg>'
        f'<div class="score-chart-tooltip" id="{chart_id}-tip" hidden></div>'
        '</div></div></div>'
        f'<script>{js}</script>'
    )


def _ring_punteggio(overall, grade, delta) -> str:
    """L'anello del punteggio: elemento firma della pagina di progetto."""
    if overall is None:
        return ('<div class="hero-card"><div class="chart-empty">'
                'Nessun audit ancora eseguito per questo progetto.</div></div>')

    cls = {"score-ottimo": "good", "score-migliorabile": "warn",
           "score-critico": "critical"}.get(_score_class(overall), "unknown")
    circonferenza = 452.0
    offset = circonferenza * (1 - overall / 100)

    if delta is None:
        pill = '<span class="hero-delta flat">primo audit</span>'
    elif delta > 0:
        pill = f'<span class="hero-delta up">\u2191 +{delta} rispetto al precedente</span>'
    elif delta < 0:
        pill = f'<span class="hero-delta down">\u2193 {delta} rispetto al precedente</span>'
    else:
        pill = '<span class="hero-delta flat">\u2014 invariato</span>'

    colore = {"good": "var(--state-good)", "warn": "var(--state-warn)",
              "critical": "var(--state-critical)"}.get(cls, "var(--text-muted)")

    return (
        '<div class="hero-card">'
        '<div class="ring-wrap">'
        '<svg width="168" height="168" viewBox="0 0 168 168" aria-hidden="true">'
        '<defs><linearGradient id="ringGradient" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0%" stop-color="{colore}"/>'
        '<stop offset="100%" stop-color="var(--accent-primary)"/>'
        '</linearGradient></defs>'
        '<circle class="ring-track" cx="84" cy="84" r="72"/>'
        f'<circle class="ring-fill" cx="84" cy="84" r="72" style="--offset:{offset:.1f}"/>'
        '</svg>'
        '<div class="ring-center">'
        f'<div class="ring-score">{overall}</div>'
        f'<div class="ring-grade {cls}">{geo_audit.esc(grade or "")}</div>'
        '</div></div>'
        '<div class="hero-caption">'
        '<div class="label">GEO Score</div>'
        f'{pill}'
        '</div></div>'
    )


def _tab_overview(project_id: str, latest: dict | None, previous: dict | None,
                   open_issues: int, resolved_recent: int, history: list) -> str:
    overall = latest.get("overall") if latest else None
    grade = latest.get("grade") if latest else None
    delta = None
    if latest and previous and latest.get("overall") is not None and previous.get("overall") is not None:
        delta = latest["overall"] - previous["overall"]

    # riga principale: anello a sinistra, storico a destra
    hero = ('<div class="hero-row">'
            + _ring_punteggio(overall, grade, delta)
            + _score_history_chart(project_id, history)
            + '</div>')

    # indicatori
    pagine = latest.get("pages_count") if latest else None
    critici = latest.get("critical_count") if latest else None
    aree = (latest.get("areas") or []) if latest else []
    peggiore = min(aree, key=lambda a: a.get("score", 100)) if aree else None

    def kpi(etichetta, valore, classe, sotto):
        return ('<div class="kpi">'
                f'<div class="kpi-top"><span class="kpi-label">{geo_audit.esc(etichetta)}</span></div>'
                f'<div class="kpi-value {classe}">{geo_audit.esc(valore)}</div>'
                f'<div class="kpi-sub">{geo_audit.esc(sotto)}</div>'
                '</div>')

    cls_issue = "critical" if (critici or 0) > 0 else ("warn" if open_issues else "good")
    kpis = ('<div class="kpi-strip">'
            + kpi("Issue aperte", open_issues if open_issues is not None else "\u2014",
                  cls_issue, f"{resolved_recent} risolte di recente")
            + kpi("Criticità", critici if critici is not None else "\u2014",
                  "critical" if (critici or 0) > 0 else "good",
                  "check falliti nell'ultimo audit")
            + kpi("Pagine analizzate", pagine if pagine is not None else "\u2014",
                  "", "nell'ultimo audit")
            + kpi("Area più debole",
                  f'{peggiore["score"]}' if peggiore else "\u2014", "warn",
                  peggiore["key"] if peggiore else "nessun dato per area")
            + '</div>')

    # _overview_sections_grid stampa gia' il proprio titolo
    sezioni = _overview_sections_grid(project_id, latest, open_issues, resolved_recent)

    return hero + kpis + sezioni



def _tab_audit(latest: dict | None, history: list, project_id: str = "") -> str:
    """Riepilogo dell'audit: sintesi, punteggio per area, interventi, storico."""
    if not latest:
        return ('<div class="data-card"><div class="no-rows">Nessun audit ancora eseguito. '
                '<a href="/audit">Avvia la prima analisi \u2192</a></div></div>')

    overall = latest.get("overall")
    cls = {"score-ottimo": "good", "score-migliorabile": "warn",
           "score-critico": "critical"}.get(_score_class(overall), "unknown")

    issues_count = latest.get("issues_count") or 0
    critical_count = latest.get("critical_count") or 0
    totale_check = len(latest.get("site_checks") or []) + sum(
        len(p.get("checks") or []) for p in (latest.get("pages_detail") or []))
    pct_ok = round(100 * (totale_check - issues_count) / totale_check) if totale_check else None
    pagine = latest.get("pages_count")

    sintesi = (
        '<div class="score-summary">'
        f'<div class="score-summary-badge {cls}">'
        f'{overall if overall is not None else "n.d."}'
        f'<span class="grade">GRADE {geo_audit.esc(latest.get("grade") or "?")}</span></div>'
        '<div class="score-summary-text">'
        '<div class="headline">'
        # ⚠️ Erano due numeri fermi. Chi legge «32 problemi» vuole sapere QUALI:
        # portano all'elenco, quello dei critici già filtrato sulla severità.
        + (f'<a class="conta-link" href="/project/{project_id}?tab=opportunities'
           f'&stato=tutte"><b>{issues_count}</b> problemi</a> \u00b7 '
           if project_id and issues_count else
           f'<b>{issues_count}</b> problemi \u00b7 ')
        + (f'<a class="conta-link" href="/project/{project_id}?tab=opportunities'
           f'&stato=tutte&sev=critical"><span class="crit">{critical_count}</span> critici</a>'
           if project_id and critical_count else
           f'<span class="crit">{critical_count}</span> critici')
        + (f' \u00b7 {pct_ok}% controlli superati' if pct_ok is not None else '') +
        '</div>'
        f'<div class="score-summary-meta">Ultimo audit {_fmt_date(latest.get("created_at"))}'
        + (f' \u00b7 {pagine} pagin{"a" if pagine == 1 else "e"} analizzat{"a" if pagine == 1 else "e"}'
           if pagine else '') +
        '</div></div></div>'
    )

    aree = sorted(latest.get("areas") or [], key=lambda a: a.get("score", 0))
    righe_aree = "".join(
        '<div class="area-line">'
        f'<div class="area-name">{geo_audit.esc(a["key"])}</div>'
        f'<div class="area-track"><div class="area-fill '
        f'{ {"score-ottimo":"good","score-migliorabile":"warn","score-critico":"critical"}.get(_score_class(a["score"]), "warn") }" '
        f'style="--w:{a["score"]}%"></div></div>'
        f'<div class="area-value">{a["score"]}</div>'
        '</div>'
        for a in aree
    ) or '<div class="no-rows">Nessun punteggio per area disponibile.</div>'

    # ⚠️ Prima erano `[:8]` e basta: gli interventi dal nono in poi non erano
    # raggiungibili da nessuna parte in questa schermata, e nulla diceva che
    # esistessero. Ora ci sono tutti, con i primi sette in vista.
    tutti_interventi = latest.get("actions") or []
    VISIBILI = 7
    interventi = tutti_interventi
    sev_cls = {"critical": "high", "high": "high", "medium": "medium", "low": "low", "info": "low"}
    righe_interventi = "".join(
        f'<div class="interv-item{" oltre" if i >= VISIBILI else ""}"'
        f'{" hidden" if i >= VISIBILI else ""}>'
        f'<div class="interv-num">{i + 1:02d}</div>'
        '<div class="interv-body"><div class="interv-top">'
        f'<span class="interv-title">{geo_audit.esc(a["title"])}</span>'
        f'<span class="badge {sev_cls.get(a.get("severity"), "low")}">{geo_audit.esc(a.get("severity") or "")}</span>'
        '</div>'
        f'<div class="interv-desc">{geo_audit.esc(a.get("recommendation") or "")} \u2014 '
        f'{a["count"]} pagin{"a" if a["count"] == 1 else "e"} interessate</div>'
        '</div></div>'
        for i, a in enumerate(interventi)
    ) or ('<div class="no-rows">Nessun intervento prioritario: '
          'tutti i controlli principali sono superati.</div>')

    righe_storico = "".join(
        '<tr>'
        f'<td>{_fmt_date(h.get("created_at"))}</td>'
        f'<td><span class="score-cell { {"score-ottimo":"good","score-migliorabile":"warn","score-critico":"critical"}.get(_score_class(h.get("overall")), "unknown") }">'
        f'{h.get("overall") if h.get("overall") is not None else "n.d."}</span></td>'
        f'<td>{geo_audit.esc(h.get("grade") or "\u2014")}</td>'
        f'<td><span class="score-cell {"critical" if (h.get("critical_count") or 0) else "good"}">'
        f'{h.get("critical_count") if h.get("critical_count") is not None else "\u2014"}</span></td>'
        f'<td>{_run_origin_badge(h.get("source"))}</td>'
        '</tr>'
        for h in history
    ) or '<tr><td colspan="5" class="no-rows">Nessun audit precedente.</td></tr>'

    return (
        sintesi
        + '<div class="data-card">'
          '<div class="section-header"><div class="section-title">Punteggio per area</div></div>'
          f'<div style="padding:8px 20px 16px"><div class="area-list">{righe_aree}</div></div>'
          '</div>'
        + '<div class="data-card">'
          '<div class="section-header"><div class="section-title">Interventi prioritari</div>'
          '<div class="card-desc">In ordine di impatto sul punteggio</div></div>'
          f'<div style="padding:4px 20px 14px"><div class="interv-list">{righe_interventi}</div>'
          + (f'<button type="button" class="mostra-altro" data-quanti="{len(tutti_interventi) - VISIBILI}">'
             f'Mostra gli altri {len(tutti_interventi) - VISIBILI}</button>'
             if len(tutti_interventi) > VISIBILI else '')
          + '</div>'
          '</div>'
        + '<div class="data-card">'
          '<div class="section-header"><div class="section-title">Storico audit</div></div>'
          '<div class="table-scroll"><table class="data-grid"><thead><tr>'
          '<th>Data</th><th>Score</th><th>Grade</th><th>Critici</th><th>Origine</th>'
          f'</tr></thead><tbody>{righe_storico}</tbody></table></div>'
          '</div>'
        + '<script>'
        '(function(){'
        'var b=document.querySelector(".mostra-altro"); if(!b) return;'
        'b.addEventListener("click",function(){'
        'document.querySelectorAll(".interv-item.oltre").forEach(function(e){e.hidden=false;});'
        'b.remove();});'
        '})();'
        '</script>'
    )



def _tab_pages(latest: dict | None, project_id: str = "") -> str:
    """Elenco delle pagine analizzate: ricerca, filtri, ordinamento, CSV.

    Ordinamento e filtri sono lato client: il dataset e' una manciata di righe
    (in produzione l'audit analizza 6 pagine) e tenerlo in pagina evita un
    viaggio al server per ogni clic.
    """
    if not latest:
        return '<div class="data-card"><div class="no-rows">Nessun audit ancora eseguito.</div></div>'

    pagine = latest.get("pages_detail") or []
    dati = []
    for p in pagine:
        checks = p.get("checks") or []
        dati.append({
            "url": p.get("url") or "",
            "tipo": p.get("type") or "",
            "score": p.get("score"),
            "issue": len([c for c in checks if c.get("status") in ("warn", "fail")]),
            "critici": len([c for c in checks if c.get("status") == "fail"]),
        })

    tipi = sorted({d["tipo"] for d in dati if d["tipo"]})
    opzioni = "".join(f'<option value="{geo_audit.esc(t)}">{geo_audit.esc(t)}</option>' for t in tipi)

    return (
        '<div class="data-card">'

        '<div class="callout-link">'
        '<div class="callout-link-text">Il <b>report completo</b> contiene il dettaglio '
        'di ogni controllo, pagina per pagina.</div>'
        f'<a href="/r/{geo_audit.esc(latest.get("id", ""))}">Apri il report \u2192</a>'
        '</div>'

        '<div class="section-header">'
        '<div class="section-title">Pagine analizzate</div>'
        '<div class="section-tools">'
        '<div class="search-mini">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
        '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>'
        '<input type="text" id="pgCerca" placeholder="Cerca pagina o URL..." aria-label="Cerca fra le pagine">'
        '</div>'
        '<label class="filter-chip" for="pgTipo">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
        '<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>'
        f'<select id="pgTipo" aria-label="Filtra per tipo"><option value="">Tipo: tutti</option>{opzioni}</select>'
        '</label>'
        '<button class="filter-chip" id="pgSoloCritici" aria-pressed="false">Solo con critici</button>'
        '<button class="filter-chip" id="pgCsv">\u2193 CSV</button>'
        + (f'<a class="filter-chip" href="/project/{project_id}/export.xlsx?cosa=pagine">'
           '\u2193 Excel</a>' if project_id else '')
        + '</div></div>'

        '<div class="table-scroll">'
        '<table class="data-grid">'
        '<thead><tr>'
        '<th data-col="url">Pagina<span class="sort-icon">\u21c5</span></th>'
        '<th data-col="tipo">Tipo<span class="sort-icon">\u21c5</span></th>'
        '<th data-col="score" class="sorted">Score<span class="sort-icon">\u25be</span></th>'
        '<th data-col="issue">Issue<span class="sort-icon">\u21c5</span></th>'
        '<th data-col="critici">Critici<span class="sort-icon">\u21c5</span></th>'
        '<th></th>'
        '</tr></thead>'
        '<tbody id="pgCorpo"></tbody>'
        '</table></div>'
        '<div class="table-footer"><span id="pgConteggio"></span>'
        '<span>Ordina cliccando sull\'intestazione di una colonna</span></div>'
        '</div>'

        '<script>'
        f'const PG_DATI = {json.dumps(dati)};'
        f'const PG_PROGETTO = {json.dumps(project_id)};'
        r"""
        (function(){
          let ordine = {col: "score", verso: 1};   // 1 = crescente, -1 = decrescente
          let soloCritici = false;

          const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g,
            c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

          const classeScore = v => v == null ? "unknown"
            : v >= 75 ? "good" : v >= 50 ? "warn" : "critical";

          function visibili(){
            const q = document.getElementById("pgCerca").value.trim().toLowerCase();
            const tipo = document.getElementById("pgTipo").value;
            return PG_DATI.filter(d => {
              if (tipo && d.tipo !== tipo) return false;
              if (soloCritici && !d.critici) return false;
              if (q && !d.url.toLowerCase().includes(q) && !(d.tipo||"").toLowerCase().includes(q)) return false;
              return true;
            }).sort((a,b) => {
              const x = a[ordine.col], y = b[ordine.col];
              if (x == null && y == null) return 0;
              if (x == null) return 1;
              if (y == null) return -1;
              if (typeof x === "number") return (x - y) * ordine.verso;
              return String(x).localeCompare(String(y), "it") * ordine.verso;
            });
          }

          function disegna(){
            const righe = visibili();
            const corpo = document.getElementById("pgCorpo");
            corpo.innerHTML = righe.map(d => {
              const cls = classeScore(d.score);
              const punteggio = d.score == null ? "n.d." : d.score;
              const barra = d.score == null ? "" :
                '<span class="score-bar"><span class="score-bar-fill ' + cls +
                '" style="width:' + d.score + '%"></span></span>';
              return '<tr>'
                + '<td><div class="url-cell"><div class="url-main">' + esc(d.url) + '</div></div></td>'
                + '<td><span class="url-type">' + esc(d.tipo || "\u2014") + '</span></td>'
                + '<td><div class="score-bar-wrap"><span class="score-cell ' + cls + '">'
                +   punteggio + '</span>' + barra + '</div></td>'
                /* ⚠️ Un conteggio che l'utente vede deve portare all'elenco di
                   ciò che conta: qui erano due numeri fermi, e per sapere QUALI
                   problemi avesse quella pagina bisognava cercarla a mano in
                   Opportunities. Il filtro passa dall'indirizzo, così il link
                   resta valido anche se lo si condivide. */
                + '<td>' + (d.issue && PG_PROGETTO
                    ? '<a class="conta-link" href="/project/' + encodeURIComponent(PG_PROGETTO)
                      + '?tab=opportunities&stato=tutte&pagina=' + encodeURIComponent(d.url)
                      + '" title="Vedi le criticità di questa pagina">'
                      + '<span class="issue-count">' + d.issue + '</span></a>'
                    : '<span class="issue-count">' + d.issue + '</span>') + '</td>'
                + '<td>' + (d.critici && PG_PROGETTO
                    ? '<a class="conta-link" href="/project/' + encodeURIComponent(PG_PROGETTO)
                      + '?tab=opportunities&stato=tutte&sev=critical&pagina='
                      + encodeURIComponent(d.url)
                      + '" title="Vedi solo i problemi critici di questa pagina">'
                      + '<span class="score-cell critical">' + d.critici + '</span></a>'
                    : '<span class="score-cell good">' + d.critici + '</span>') + '</td>'
                + '<td class="row-action"><a href="' + esc(d.url) + '" target="_blank" rel="noopener">Apri \u2192</a></td>'
                + '</tr>';
            }).join("") || '<tr><td colspan="6" class="no-rows">Nessuna pagina corrisponde ai filtri.</td></tr>';

            document.getElementById("pgConteggio").textContent =
              righe.length + (righe.length === 1 ? " pagina" : " pagine")
              + (righe.length !== PG_DATI.length ? " su " + PG_DATI.length : "");

            document.querySelectorAll(".data-grid thead th[data-col]").forEach(th => {
              const attivo = th.dataset.col === ordine.col;
              th.classList.toggle("sorted", attivo);
              const ic = th.querySelector(".sort-icon");
              if (ic) ic.textContent = attivo ? (ordine.verso === 1 ? "\u25b4" : "\u25be") : "\u21c5";
            });
          }

          document.querySelectorAll(".data-grid thead th[data-col]").forEach(th => {
            th.addEventListener("click", () => {
              const col = th.dataset.col;
              if (ordine.col === col) ordine.verso = -ordine.verso;
              else ordine = {col: col, verso: col === "url" || col === "tipo" ? 1 : -1};
              disegna();
            });
          });

          document.getElementById("pgCerca").addEventListener("input", disegna);
          document.getElementById("pgTipo").addEventListener("change", disegna);
          document.getElementById("pgSoloCritici").addEventListener("click", function(){
            soloCritici = !soloCritici;
            this.classList.toggle("on", soloCritici);
            this.setAttribute("aria-pressed", soloCritici ? "true" : "false");
            disegna();
          });

          /* CSV generato in pagina: i dati sono gia' tutti qui, un endpoint
             dedicato non aggiungerebbe nulla.
             Per le CRITICITA' l'export sta invece sul server (Excel), perche'
             deve portarsi dietro il testo «come si risolve» — vedi
             `/project/<id>/export.xlsx`. */
          document.getElementById("pgCsv").addEventListener("click", function(){
            const righe = visibili();
            const csv = ["URL;Tipo;Score;Issue;Critici"].concat(
              righe.map(d => [d.url, d.tipo, d.score == null ? "" : d.score, d.issue, d.critici]
                .map(v => '"' + String(v).replace(/"/g, '""') + '"').join(";"))
            ).join("\r\n");
            const blob = new Blob(["\ufeff" + csv], {type: "text/csv;charset=utf-8"});
            const a = document.createElement("a");
            a.href = URL.createObjectURL(blob);
            a.download = "pagine-geo-audit.csv";
            a.click();
            URL.revokeObjectURL(a.href);
          });

          disegna();
        })();
        """
        '</script>'
    )



def _status_pill(stato: str) -> str:
    """Pastiglia di stato con icona, al posto del solo testo."""
    icone = {
        "ok": '<polyline points="20 6 9 17 4 12"/>',
        "warn": '<path d="M12 9v4M12 17h.01"/><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>',
        "fail": '<circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/>',
        "unknown": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
    }
    etichette = {"ok": "OK", "warn": "DA MIGLIORARE", "fail": "CRITICO", "unknown": "N.D."}
    classe = stato if stato in ("ok", "warn", "fail") else "na"
    return (f'<span class="status-pill {classe}">'
            f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" '
            f'aria-hidden="true">{icone.get(stato, icone["unknown"])}</svg>'
            f'{etichette.get(stato, "N.D.")}</span>')


def _check_table(righe: list, titolo: str, sottotitolo: str) -> str:
    """Tabella di controlli che sotto i 700px diventa schede impilate."""
    if not righe:
        return ""
    corpo = "".join(
        f'<tr data-stato="{"ok" if r["status"] == "ok" else "ko"}">'
        f'<td class="check-name">{geo_audit.esc(r["title"])}</td>'
        f'<td>{_status_pill(r["status"])}</td>'
        f'<td class="detail-text">{geo_audit.esc(r.get("detail") or "\u2014")}</td>'
        f'<td class="reco-text">{geo_audit.esc(r.get("recommendation") or "\u2014")}</td>'
        '</tr>'
        for r in righe
    )
    schede = "".join(
        f'<div class="check-card" data-stato="{"ok" if r["status"] == "ok" else "ko"}">'
        f'<div class="check-card-top"><span class="check-name">{geo_audit.esc(r["title"])}</span>'
        f'{_status_pill(r["status"])}</div>'
        f'<div class="check-card-detail">{geo_audit.esc(r.get("detail") or "")}</div>'
        + (f'<div class="check-card-reco">{geo_audit.esc(r["recommendation"])}</div>'
           if r.get("recommendation") else '') +
        '</div>'
        for r in righe
    )
    return (
        '<div class="data-card">'
        f'<div class="card-header"><div class="card-title">{geo_audit.esc(titolo)}</div>'
        f'<div class="card-sub">{geo_audit.esc(sottotitolo)}</div></div>'
        '<div class="table-scroll check-table"><table class="data-grid"><thead><tr>'
        '<th>Check</th><th>Stato</th><th>Dettaglio</th><th>Raccomandazione</th>'
        f'</tr></thead><tbody>{corpo}</tbody></table></div>'
        f'<div class="check-cards">{schede}</div>'
        '</div>'
    )


def _tab_technical(latest: dict | None, project_id: str = "") -> str:
    if not latest:
        return '<div class="data-card"><div class="no-rows">Nessun audit ancora eseguito.</div></div>'

    site_checks = [c for c in (latest.get("site_checks") or []) if c.get("id", "").startswith("crawl.")]
    accesso = [{"title": c["title"], "status": c["status"], "detail": c.get("detail"),
                "recommendation": c.get("recommendation")} for c in site_checks]

    pages_detail = latest.get("pages_detail") or []
    for check_id in ("meta.canonical", "render.parity"):
        agg = _aggregate_page_check(pages_detail, check_id)
        if agg.get("total"):
            accesso.append({"title": agg["title"], "status": agg["status"],
                            "detail": f'{agg["ok"]}/{agg["total"]} pagine OK',
                            "recommendation": agg.get("recommendation")})

    strutturati = []
    for check_id in ("sd.present", "sd.valid", "sd.highvalue", "sd.completeness", "sd.sameas",
                     "trust.contact", "trust.social", "trust.author", "sem.html"):
        agg = _aggregate_page_check(pages_detail, check_id)
        if agg.get("total"):
            strutturati.append({"title": agg["title"], "status": agg["status"],
                                "detail": f'{agg["ok"]}/{agg["total"]} pagine OK',
                                "recommendation": agg.get("recommendation")})

    tutti = accesso + strutturati
    superati = len([r for r in tutti if r["status"] == "ok"])
    da_migliorare = len([r for r in tutti if r["status"] in ("warn", "fail")])

    riepilogo = (
        '<div class="tech-summary">'
        # ⚠️ I due conteggi filtrano le tabelle qui sotto, invece di essere
        # decorazioni: le righe ci sono già nella stessa pagina, non serve
        # portare l'utente altrove — basta mostrargli solo quelle che ha chiesto.
        '<div class="kpi kpi-filtro" data-filtro="ok" role="button" tabindex="0" '
        'title="Mostra solo i controlli superati">'
        '<div class="kpi-label">Check superati</div>'
        f'<div class="kpi-value good">{superati} / {len(tutti)}</div></div>'
        '<div class="kpi kpi-filtro" data-filtro="ko" role="button" tabindex="0" '
        'title="Mostra solo i controlli da migliorare">'
        '<div class="kpi-label">Da migliorare</div>'
        f'<div class="kpi-value {"warn" if da_migliorare else "good"}">{da_migliorare}</div></div>'
        '<div class="kpi"><div class="kpi-label">Ultimo controllo</div>'
        f'<div class="kpi-value" style="font-size:16px">{_fmt_date(latest.get("created_at"))}</div></div>'
        '</div>'
    )

    return (
        riepilogo
        + _check_table(accesso, "Accesso crawler e infrastruttura",
                       "Verifica che i crawler AI possano raggiungere e leggere il sito.")
        + _check_table(strutturati, "Dati strutturati ed entity signals",
                       "Quanto il sito si fa capire: schema, contatti, profili, semantica.")
        + '<script>'
        r"""
        (function(){
          /* I due conteggi in cima filtrano le tabelle sotto. Cliccare di nuovo
             sullo stesso toglie il filtro: senza, l'unico modo per tornare a
             vedere tutto sarebbe ricaricare la pagina. */
          let attivo = null;
          const kpi = document.querySelectorAll(".kpi-filtro");

          function applica(){
            document.querySelectorAll("tr[data-stato], .check-card[data-stato]")
              .forEach(el => { el.hidden = !!attivo && el.dataset.stato !== attivo; });
            kpi.forEach(k => k.classList.toggle("attivo", k.dataset.filtro === attivo));
            /* Una tabella rimasta senza righe visibili dice perche', invece di
               presentarsi vuota e sembrare rotta. */
            document.querySelectorAll(".data-card").forEach(box => {
              const righe = box.querySelectorAll("tr[data-stato]");
              if (!righe.length) return;
              const viste = [...righe].filter(r => !r.hidden).length;
              let nota = box.querySelector(".filtro-vuoto");
              if (!viste){
                if (!nota){
                  nota = document.createElement("div");
                  nota.className = "no-rows filtro-vuoto";
                  box.appendChild(nota);
                }
                nota.textContent = attivo === "ok"
                  ? "Qui nessun controllo risulta superato."
                  : "Qui va tutto bene: nessun controllo da migliorare.";
                nota.hidden = false;
              } else if (nota) { nota.hidden = true; }
            });
          }

          kpi.forEach(k => {
            const scatta = () => {
              attivo = attivo === k.dataset.filtro ? null : k.dataset.filtro;
              applica();
            };
            k.addEventListener("click", scatta);
            k.addEventListener("keydown", e => {
              if (e.key === "Enter" || e.key === " "){ e.preventDefault(); scatta(); }
            });
          });
        })();
        """
        '</script>'
    )



def _rimedi_per_check(latest: dict | None) -> dict:
    """Da `check_id` al testo che dice cosa fare, letto dall'ultimo audit.

    ⚠️ Non si salva sulla riga della issue: la raccomandazione descrive il TIPO
    di problema, non quella singola occorrenza. Copiarla su ogni riga vorrebbe
    dire che, migliorando il testo in `geo_audit.py`, le issue già aperte
    continuerebbero a mostrare la versione vecchia.
    """
    if not latest:
        return {}
    rimedi = {}
    fonti = list(latest.get("site_checks") or [])
    for p in (latest.get("pages_detail") or []):
        fonti.extend(p.get("checks") or [])
    for c in fonti:
        cid = c.get("check_id") or c.get("id")
        testo = (c.get("recommendation") or "").strip()
        if cid and testo and cid not in rimedi:
            rimedi[cid] = testo
    return rimedi


def _tab_opportunities(project_id: str, latest: dict | None = None) -> str:
    """Criticità del progetto: filtri, raggruppamento e paginazione reale.

    Manca l'azione "Segna risolto" prevista dal redesign: richiede un terzo
    stato nel modello dati delle issue (aperta / risolta a mano / risolta
    dall'audit) e la logica che, al riscontro successivo, faccia vincere
    l'audit sullo stato manuale. È una modifica al database, quindi attende
    una decisione esplicita.
    """
    issues = _sb_issues_by_project(project_id)
    if not issues:
        return ('<div class="data-card"><div class="no-rows">Nessuna criticità registrata: '
                'esegui un audit per popolare questa sezione.</div></div>')

    rimedi = _rimedi_per_check(latest)

    dati = []
    for i in issues:
        stato = i.get("status")
        dati.append({
            "id": i.get("id"),
            # Cosa fare per risolverlo. Vuoto quando il check non porta una
            # raccomandazione: si scrive che manca, invece di inventarla.
            "rimedio": rimedi.get(i.get("check_id") or "", ""),
            "titolo": i.get("title") or i.get("check_id") or "",
            "check": i.get("check_id") or "",
            "sev": i.get("severity") or "",
            "url": i.get("url") or "",
            # 'resolved_manually' è chiusa quanto 'resolved': cambia solo chi
            # l'ha chiusa, e lo si vede dall'etichetta
            "stato": "aperta" if stato == "open" else "risolta",
            "manuale": stato == "resolved_manually",
            "prima": _fmt_date(i.get("first_seen_at")),
            "ultima": _fmt_date(i.get("last_seen_at")),
        })

    aperte = len([d for d in dati if d["stato"] == "aperta"])
    risolte = len(dati) - aperte

    return (
        '<div class="filter-bar">'
        '<div class="search-mini">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
        '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>'
        '<input type="text" id="opCerca" placeholder="Cerca per check o URL..." '
        'aria-label="Cerca fra le criticità">'
        '</div>'
        '<button class="filter-chip on" id="opAperte" aria-pressed="true">Solo aperte</button>'
        '<button class="filter-chip" id="opCritiche" aria-pressed="false">Solo gravi</button>'
        '<div class="filter-spacer"></div>'
        # ⚠️ Da qui non si poteva esportare niente: l'unico export del
        # prodotto stava in Pages e riguardava le pagine, non le criticita'.
        + (f'<a class="filter-chip" href="/project/{project_id}/export.xlsx?cosa=criticita" '
           'title="Scarica le criticità con dentro come si risolvono">↓ Excel</a>'
           if project_id else '')
        + '<div class="group-toggle" role="group" aria-label="Raggruppamento">'
        '<button id="opPerPagina" class="active">Per pagina</button>'
        '<button id="opPerCheck">Per check</button>'
        '</div>'
        '</div>'

        f'<div class="score-summary" style="padding:14px 18px">'
        '<div class="score-summary-text">'
        f'<div class="headline"><span class="crit">{aperte}</span> apert{"a" if aperte == 1 else "e"} '
        f'\u00b7 {risolte} risolt{"a" if risolte == 1 else "e"}</div>'
        '<div class="score-summary-meta">Una criticità risolta si chiude da sola al primo audit '
        'che non la rileva più.</div>'
        '</div></div>'

        '<div id="opGruppi"></div>'

        '<script>'
        f'const OP_DATI = {json.dumps(dati)};'
        f'const OP_PROGETTO = {json.dumps(project_id)};'
        r"""
        (function(){
          const PER_PAGINA = 12;
          let soloAperte = true, soloGravi = false, perPagina = true;
          const pagine = {};   // indice di pagina per ciascun gruppo

          const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g,
            c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
          const sevCls = s => ({critical:"high", high:"high", medium:"medium"}[s] || "low");

          /* I filtri possono arrivare dall'indirizzo: ?pagina=<url> o ?sev=critical.
             Servono ai numeri cliccabili delle altre schermate, e hanno il
             vantaggio di rendere il link condivisibile — chi lo riceve vede la
             stessa lista, non la lista intera. */
          (function daIndirizzo(){
            const p = new URLSearchParams(location.search);
            const pagina = p.get("pagina");
            const sev = p.get("sev");
            if (pagina){
              document.getElementById("opCerca").value = pagina;
              perPagina = true;
              document.getElementById("opPerPagina").classList.add("active");
              document.getElementById("opPerCheck").classList.remove("active");
            }
            if (sev === "critical"){
              soloGravi = true;
              const b = document.getElementById("opCritiche");
              b.classList.add("on");
              b.setAttribute("aria-pressed", "true");
            }
            if (p.get("stato") === "tutte"){
              soloAperte = false;
              const b = document.getElementById("opAperte");
              b.classList.remove("on");
              b.setAttribute("aria-pressed", "false");
            }
          })();

          function filtrate(){
            const q = document.getElementById("opCerca").value.trim().toLowerCase();
            return OP_DATI.filter(d => {
              if (soloAperte && d.stato !== "aperta") return false;
              if (soloGravi && !["critical","high"].includes(d.sev)) return false;
              if (q && !d.titolo.toLowerCase().includes(q) && !d.url.toLowerCase().includes(q)
                    && !d.check.toLowerCase().includes(q)) return false;
              return true;
            });
          }

          function raggruppa(righe){
            const m = new Map();
            righe.forEach(d => {
              const k = perPagina ? (d.url || "Livello sito") : (d.titolo || d.check);
              if (!m.has(k)) m.set(k, []);
              m.get(k).push(d);
            });
            // i gruppi piu' popolosi per primi: si vede subito dove si concentra il problema
            return [...m.entries()].sort((a, b) => b[1].length - a[1].length);
          }

          function tabella(righe){
            /* Ogni riga ne porta una seconda, nascosta, con la spiegazione.
               ⚠️ Il solo titolo del check non basta a chi deve agire da solo:
               «Completezza proprietà schema» dice cosa non va, non cosa fare. */
            const corpo = righe.map(d => '<tr class="riga-issue" data-id="' + esc(d.id) + '">'
              + '<td class="check-name"><span class="apri-riga" aria-hidden="true">›</span>'
              +   esc(d.titolo) + '</td>'
              + (perPagina ? '' : '<td class="detail-text">' + esc(d.url || "livello sito") + '</td>')
              + '<td><span class="badge ' + sevCls(d.sev) + '">' + esc(d.sev || "n.d.") + '</span></td>'
              + '<td class="date-muted">' + esc(d.prima) + '</td>'
              + '<td class="date-muted">' + esc(d.ultima) + '</td>'
              + '<td><span class="badge ' + d.stato + '">'
              +   (d.stato === "aperta" ? "Aperta" : (d.manuale ? "Chiusa a mano" : "Risolta"))
              + '</span></td>'
              + '<td class="row-action">'
              +   (d.stato === "aperta"
                    ? '<button class="row-resolve" data-id="' + esc(d.id) + '">Segna risolto</button>'
                    : '')
              + '</td>'
              + '</tr>'
              + '<tr class="riga-rimedio" data-per="' + esc(d.id) + '" hidden>'
              +   '<td colspan="' + (perPagina ? 6 : 7) + '">'
              +     '<div class="rimedio">'
              +       '<div class="rimedio-titolo">Come si risolve</div>'
              +       '<div class="rimedio-testo">'
              +         (d.rimedio
                          ? esc(d.rimedio)
                          : '<span class="rimedio-assente">Per questo controllo non '
                            + 'abbiamo ancora scritto una spiegazione operativa.</span>')
              +       '</div>'
              +       (d.url ? '<div class="rimedio-dove">Sulla pagina: <code>'
                               + esc(d.url) + '</code></div>' : '')
              +     '</div>'
              +   '</td>'
              + '</tr>').join("");
            return '<div class="table-scroll"><table class="data-grid"><thead><tr>'
              + '<th>Check</th>' + (perPagina ? '' : '<th>Pagina</th>')
              + '<th>Severità</th><th>Prima vista</th><th>Ultima vista</th><th>Stato</th><th></th>'
              + '</tr></thead><tbody>' + corpo + '</tbody></table></div>';
          }

          function paginazione(chiave, totale, pagina, nPagine){
            if (nPagine <= 1) return '';
            let btns = '<button class="pager-btn" data-g="' + esc(chiave) + '" data-p="'
                     + (pagina - 1) + '"' + (pagina === 0 ? ' disabled' : '') + '>‹</button>';
            for (let i = 0; i < nPagine; i++){
              if (nPagine > 7 && i > 2 && i < nPagine - 2 && Math.abs(i - pagina) > 1) {
                if (i === 3) btns += '<span class="pager-info">…</span>';
                continue;
              }
              btns += '<button class="pager-btn' + (i === pagina ? ' active' : '') + '" data-g="'
                    + esc(chiave) + '" data-p="' + i + '">' + (i + 1) + '</button>';
            }
            btns += '<button class="pager-btn" data-g="' + esc(chiave) + '" data-p="'
                  + (pagina + 1) + '"' + (pagina === nPagine - 1 ? ' disabled' : '') + '>›</button>';
            const da = pagina * PER_PAGINA + 1, a = Math.min((pagina + 1) * PER_PAGINA, totale);
            return '<div class="pager"><span class="pager-info">' + da + '–' + a
                 + ' di ' + totale + '</span><div class="pager-btns">' + btns + '</div></div>';
          }

          function disegna(){
            const gruppi = raggruppa(filtrate());
            const cont = document.getElementById("opGruppi");
            if (!gruppi.length){
              cont.innerHTML = '<div class="data-card"><div class="no-rows">'
                + 'Nessuna criticità corrisponde ai filtri.</div></div>';
              return;
            }
            cont.innerHTML = gruppi.map(([chiave, righe]) => {
              const nPagine = Math.ceil(righe.length / PER_PAGINA);
              let p = pagine[chiave] || 0;
              if (p >= nPagine) p = pagine[chiave] = 0;
              const fetta = righe.slice(p * PER_PAGINA, (p + 1) * PER_PAGINA);
              return '<div class="data-card gruppo">'
                + '<div class="section-header"><div class="gruppo-title">' + esc(chiave)
                + ' <span class="n">— ' + righe.length
                + (righe.length === 1 ? ' criticità' : ' criticità') + '</span></div></div>'
                + tabella(fetta)
                + paginazione(chiave, righe.length, p, nPagine)
                + '</div>';
            }).join("");

            cont.querySelectorAll(".pager-btn[data-p]").forEach(b => {
              b.addEventListener("click", () => {
                pagine[b.dataset.g] = parseInt(b.dataset.p, 10);
                disegna();
              });
            });

            cont.querySelectorAll(".row-resolve[data-id]").forEach(b => {
              b.addEventListener("click", () => chiudiAMano(b));
            });

            /* Aprire la riga per leggere la soluzione. Il clic sul bottone
               «Segna risolto» non deve aprirla: sono due intenzioni diverse. */
            cont.querySelectorAll("tr.riga-issue").forEach(tr => {
              tr.addEventListener("click", e => {
                if (e.target.closest("button, a")) return;
                const sotto = cont.querySelector(
                  'tr.riga-rimedio[data-per="' + CSS.escape(tr.dataset.id) + '"]');
                if (!sotto) return;
                sotto.hidden = !sotto.hidden;
                tr.classList.toggle("aperta", !sotto.hidden);
              });
            });
          }

          /* Chiusura manuale. Il riscontro all'utente arriva solo dopo la
             conferma del server: mostrare subito "risolta" e scoprire poi che
             la chiamata è fallita sarebbe peggio di mezzo secondo di attesa. */
          function chiudiAMano(bottone){
            const id = bottone.dataset.id;
            bottone.disabled = true;
            bottone.textContent = "Attendi…";
            fetch("/project/" + encodeURIComponent(OP_PROGETTO)
                  + "/issue/" + encodeURIComponent(id) + "/resolve", {method: "POST"})
              .then(r => {
                if (!r.ok) throw new Error("HTTP " + r.status);
                const d = OP_DATI.find(x => x.id === id);
                if (d){ d.stato = "risolta"; d.manuale = true; }
                disegna();
              })
              .catch(() => {
                bottone.disabled = false;
                bottone.textContent = "Non riuscito, riprova";
                bottone.classList.add("errore");
              });
          }

          function interruttore(id, leggi, scrivi){
            const b = document.getElementById(id);
            b.addEventListener("click", () => {
              scrivi(!leggi());
              b.classList.toggle("on", leggi());
              b.setAttribute("aria-pressed", leggi() ? "true" : "false");
              disegna();
            });
          }
          interruttore("opAperte", () => soloAperte, v => soloAperte = v);
          interruttore("opCritiche", () => soloGravi, v => soloGravi = v);

          document.getElementById("opCerca").addEventListener("input", disegna);
          document.getElementById("opPerPagina").addEventListener("click", function(){
            perPagina = true; this.classList.add("active");
            document.getElementById("opPerCheck").classList.remove("active"); disegna();
          });
          document.getElementById("opPerCheck").addEventListener("click", function(){
            perPagina = false; this.classList.add("active");
            document.getElementById("opPerPagina").classList.remove("active"); disegna();
          });

          disegna();
        })();
        """
        '</script>'
    )



def _tracking_badge(project_id: str) -> str:
    return ('<span class="badge badge--success"><span class="dot"></span>Tracking attivo</span>'
            if _sb_has_tracking(project_id) else
            '<span class="badge badge--neutral">Tracking not installed</span>')


def _tracking_snippet_html(project_id: str) -> str:
    """Snippet di tracking in un blocco di codice con bottone Copia."""
    src = f"{SITE_URL}/static/js/geo-track.js" if SITE_URL else "/static/js/geo-track.js"
    grezzo = f'<script src="{src}" data-project="{project_id}" async></script>'
    colorato = (
        '&lt;<span class="tag">script</span> '
        '<span class="attr">src</span>=<span class="str">"' + geo_audit.esc(src) + '"</span> '
        '<span class="attr">data-project</span>=<span class="str">"' + geo_audit.esc(project_id) + '"</span> '
        '<span class="attr">async</span>&gt;&lt;/<span class="tag">script</span>&gt;'
    )
    evento_grezzo = 'window.geoTrack("conversione", {valore: 100});'
    evento_colorato = (
        '<span class="tag">window</span>.geoTrack(<span class="str">"conversione"</span>, '
        '{valore: <span class="attr">100</span>});'
    )

    def blocco(id_, etichetta, html_colorato, testo_grezzo):
        return (
            '<div class="code-block">'
            '<div class="code-block-header">'
            f'<span class="code-block-label">{etichetta}</span>'
            f'<button class="copy-btn" data-copia="{id_}" data-testo="{geo_audit.esc(testo_grezzo)}">'
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
            '<rect x="9" y="9" width="13" height="13" rx="2"/>'
            '<path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>'
            '<span>Copia</span></button>'
            '</div>'
            f'<div class="code-content"><code id="{id_}">{html_colorato}</code></div>'
            '</div>'
        )

    return (
        '<p class="card-desc" style="margin-bottom:10px">Incolla questo snippet '
        'prima della chiusura di <code>&lt;/body&gt;</code> su ogni pagina del sito:</p>'
        + blocco("snippetTracking", "HTML", colorato, grezzo)
        + '<p class="card-desc" style="margin:14px 0 10px">Per registrare una conversione '
          '(invio form, prenotazione, acquisto):</p>'
        + blocco("snippetEvento", "JavaScript", evento_colorato, evento_grezzo)
        + """<script>
        document.querySelectorAll('.copy-btn[data-copia]').forEach(function(b){
          if (b.dataset.pronto) return;
          b.dataset.pronto = "1";
          b.addEventListener('click', function(){
            navigator.clipboard.writeText(b.dataset.testo).then(function(){
              const et = b.querySelector('span');
              const prima = et.textContent;
              et.textContent = '\u2713 Copiato';
              b.classList.add('copied');
              setTimeout(function(){ et.textContent = prima; b.classList.remove('copied'); }, 1800);
            });
          });
        });
        </script>"""
    )



def _colonne_giorni(daily: dict, giorni: int = 14, classe: str = "good") -> str:
    """Andamento a colonne degli ultimi giorni, SVG inline.

    Una tabella «Data | Eventi» costringe a leggere quattordici numeri per
    accorgersi di una salita: la forma si vede, i numeri si contano.
    """
    oggi = datetime.now(timezone.utc).date()
    serie = [(oggi - timedelta(days=i)) for i in range(giorni - 1, -1, -1)]
    valori = [daily.get(g.isoformat(), 0) for g in serie]
    massimo = max(valori) or 1

    larghezza_col = 100 / giorni
    barre = []
    for i, (giorno, v) in enumerate(zip(serie, valori)):
        h = (v / massimo) * 92 if v else 0
        x = i * larghezza_col
        # min-height a 1.5 per il giorno a zero: la colonna assente e quella a
        # zero devono restare distinguibili dal fondo.
        y = 100 - max(h, 1.5)
        barre.append(
            f'<rect x="{x + larghezza_col * 0.18:.2f}" y="{y:.2f}" '
            f'width="{larghezza_col * 0.64:.2f}" height="{max(h, 1.5):.2f}" rx="0.6" '
            f'class="{"col-piena" if v else "col-vuota"}">'
            f'<title>{_fmt_date(giorno.isoformat())}: {v}</title></rect>'
        )

    return (
        f'<div class="colonne-giorni colonne-{classe}">'
        f'<svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" '
        f'aria-label="Andamento degli ultimi {giorni} giorni">{"".join(barre)}</svg>'
        f'<div class="colonne-assi"><span>{_fmt_date(serie[0].isoformat())}</span>'
        f'<span>{_fmt_date(serie[-1].isoformat())}</span></div>'
        '</div>'
    )


def _righe_barre(conteggi: dict, classe: str = "good", limite: int = 12) -> str:
    """Classifica con barra proporzionale, riusando i componenti gia' a tema."""
    if not conteggi:
        return ''
    ordinati = sorted(conteggi.items(), key=lambda x: -x[1])[:limite]
    massimo = ordinati[0][1] or 1
    return "".join(
        f'<div class="engine-row"><div class="engine-name">{geo_audit.esc(str(nome))}</div>'
        f'{_barra_semplice(round(100 * v / massimo), classe)}'
        f'<div class="area-value">{v}</div></div>'
        for nome, v in ordinati
    )


def _tab_traffic(project: dict) -> str:
    """AI Traffic: i due fenomeni che prima erano uno solo.

    ⚠️ La scheda misurava soltanto i **referral** — le persone che arrivano da un
    assistente — e per questo sembrava sempre vuota: e' il fenomeno raro. Quello
    frequente, «gli assistenti stanno leggendo il tuo sito», non poteva vederlo
    perche' lo snippet e' JavaScript e **i crawler non eseguono JavaScript**.
    Adesso i due sono separati e dichiarati, e i passaggi dei crawler arrivano da
    chi puo' vederli: il plugin sul server del sito (vedi `POST /t`, campo `ua`).
    """
    events = _sb_tracking_events(project["id"], days=30)
    if not events:
        return (
            '<div class="alert alert--info"><div class="ic">i</div>'
            '<div>Nessun evento di tracking ancora ricevuto per questo progetto. '
            'Installa lo snippet qui sotto per iniziare a raccogliere le sessioni.</div></div>'
            f'<div class="card" style="margin-top:16px">{_tracking_snippet_html(project["id"])}</div>'
        )

    crawler_hits = [e for e in events if e.get("event_name") == "crawler"]
    visite = [e for e in events if e.get("event_name") != "crawler"]

    # ── chi ti legge ────────────────────────────────────────────────────────
    per_bot: dict = {}
    per_categoria: dict = {}
    crawler_daily: dict = {}
    per_pagina_bot: dict = {}
    for e in crawler_hits:
        bot = e.get("ai_source") or "Sconosciuto"
        per_bot[bot] = per_bot.get(bot, 0) + 1
        props = e.get("properties") if isinstance(e.get("properties"), dict) else {}
        cat = CRAWLER_CATEGORIE.get(props.get("categoria"), "Altro")
        per_categoria[cat] = per_categoria.get(cat, 0) + 1
        giorno = (e.get("created_at") or "")[:10]
        if giorno:
            crawler_daily[giorno] = crawler_daily.get(giorno, 0) + 1
        url = e.get("page_url") or "—"
        per_pagina_bot[url] = per_pagina_bot.get(url, 0) + 1

    # ── chi ti manda persone ────────────────────────────────────────────────
    sessions: dict = {}
    for e in visite:
        sid = e.get("session_id") or f"anon:{e.get('created_at')}"
        row = sessions.setdefault(sid, {"ai_source": None, "landing": e.get("page_url"),
                                        "first_at": e.get("created_at")})
        if e.get("ai_source"):
            row["ai_source"] = e["ai_source"]
        created = e.get("created_at") or ""
        if created and created < (row["first_at"] or ""):
            row["landing"] = e.get("page_url")
            row["first_at"] = created

    total_sessions = len(sessions)
    ai_sessions = [s for s in sessions.values() if s["ai_source"]]
    ai_count = len(ai_sessions)
    ai_pct = round(100 * ai_count / total_sessions) if total_sessions else 0

    by_source: dict = {}
    by_landing: dict = {}
    for s in ai_sessions:
        by_source[s["ai_source"]] = by_source.get(s["ai_source"], 0) + 1
        by_landing[s["landing"] or "—"] = by_landing.get(s["landing"] or "—", 0) + 1

    referral_daily: dict = {}
    for e in visite:
        if not e.get("ai_source"):
            continue
        giorno = (e.get("created_at") or "")[:10]
        if giorno:
            referral_daily[giorno] = referral_daily.get(giorno, 0) + 1

    # ── i numeri in testa ───────────────────────────────────────────────────
    # Qui c'erano `.mini-stat`/`.mini-stat-row`, che esistono ma sono definite in
    # un `<style>` dentro `templates/project.html`: vivono solo lì, e una scheda
    # che le usa non si può rendere fuori da quel template. Si usa `.kpi-strip`,
    # il componente equivalente del design system, che sta in `geo-ds.css` ed è
    # già responsive (4 → 2 colonne).
    kpi = (
        '<div class="kpi-strip">'
        + _kpi_semplice(len(crawler_hits), "Passaggi di crawler AI", "ultimi 30 giorni", "good")
        + _kpi_semplice(total_sessions, "Sessioni", "ultimi 30 giorni")
        + _kpi_semplice(ai_count, "Sessioni da AI", "arrivate da un assistente", "good")
        + _kpi_semplice(f"{ai_pct}%", "Quota AI", "sul totale delle sessioni")
        + '</div>'
    )

    # ── sezione crawler ─────────────────────────────────────────────────────
    if crawler_hits:
        pagine_bot = "".join(
            f'<tr><td data-label="Pagina">{geo_audit.esc(k)}</td><td data-label="Passaggi">{v}</td></tr>'
            for k, v in sorted(per_pagina_bot.items(), key=lambda x: -x[1])[:10]
        )
        sezione_crawler = (
            '<div class="card" style="margin-top:20px">'
            '<div class="card-title">Chi ti legge — crawler AI</div>'
            '<p class="card-sub">I bot degli assistenti che sono passati sul sito negli ultimi '
            '30 giorni. Non sono visite di persone: sono le AI che raccolgono i tuoi contenuti '
            'per poterti citare.</p>'
            f'<div style="margin-top:16px">{_righe_barre(per_bot, "good")}</div>'
            f'<div style="margin-top:18px">{_colonne_giorni(crawler_daily, 14, "good")}</div>'
            '<div class="card-title" style="margin:22px 0 10px">Per finalità</div>'
            f'<div>{_righe_barre(per_categoria, "warn")}</div>'
            '<div class="card-title" style="margin:22px 0 10px">Pagine più lette dai bot</div>'
            '<div class="tbl-wrap"><table class="tbl tbl-responsive">'
            '<thead><tr><th>Pagina</th><th>Passaggi</th></tr></thead>'
            f'<tbody>{pagine_bot}</tbody></table></div>'
            '</div>'
        )
    else:
        sezione_crawler = (
            '<div class="card" style="margin-top:20px">'
            '<div class="card-title">Chi ti legge — crawler AI</div>'
            '<div class="alert alert--info" style="margin-top:12px"><div class="ic">i</div>'
            '<div><b>Nessun passaggio di crawler registrato, e con il solo snippet non se ne '
            'registrerebbe mai uno.</b> Lo snippet è JavaScript e i bot degli assistenti '
            'non eseguono JavaScript: quando GPTBot o ClaudeBot leggono una pagina, nel browser '
            'non succede nulla da osservare. Per contarli serve chi sta sul server del sito — '
            'il plugin Vertical GEO, che li riconosce dallo User-Agent e li manda qui.</div></div>'
            '</div>'
        )

    # ── sezione referral ────────────────────────────────────────────────────
    if ai_sessions:
        landing_rows = "".join(
            f'<tr><td data-label="Pagina">{geo_audit.esc(k)}</td><td data-label="Sessioni">{v}</td></tr>'
            for k, v in sorted(by_landing.items(), key=lambda x: -x[1])[:10]
        )
        corpo_referral = (
            f'<div style="margin-top:16px">{_righe_barre(by_source, "good")}</div>'
            f'<div style="margin-top:18px">{_colonne_giorni(referral_daily, 14, "good")}</div>'
            '<div class="card-title" style="margin:22px 0 10px">Pagine di atterraggio</div>'
            '<div class="tbl-wrap"><table class="tbl tbl-responsive">'
            '<thead><tr><th>Pagina</th><th>Sessioni</th></tr></thead>'
            f'<tbody>{landing_rows}</tbody></table></div>'
        )
    else:
        corpo_referral = (
            '<p class="card-sub" style="margin-top:12px">Nessuna sessione arrivata da un '
            'assistente AI in questo periodo. È il fenomeno più raro dei due: '
            'prima le AI ti leggono, e solo dopo — se ti citano — ti mandano qualcuno.</p>'
        )

    sezione_referral = (
        '<div class="card" style="margin-top:20px">'
        '<div class="card-title">Chi ti manda persone — visite da AI</div>'
        '<p class="card-sub">Sessioni di persone vere arrivate da un assistente, riconosciute '
        'dal referrer o da <code>utm_source</code>.</p>'
        f'{corpo_referral}'
        '</div>'
    )

    # Un dato parziale non deve mai passare per completo: se il tetto di lettura
    # ha tagliato, la scheda lo dice invece di mostrare numeri piu' bassi del vero.
    avviso_parziale = ''
    if len(events) >= _TETTO_EVENTI:
        avviso_parziale = (
            '<div class="alert alert--warn" style="margin-bottom:16px"><div class="ic">!</div>'
            f'<div>Il progetto ha superato i {_TETTO_EVENTI:,} eventi in 30 giorni: '
            'i numeri qui sotto sono calcolati sui più recenti, non su tutto il periodo.</div></div>'
        ).replace(",", ".")

    return (
        avviso_parziale
        + kpi
        + sezione_crawler
        + sezione_referral
        + f'<div class="card" style="margin-top:20px">{_tracking_snippet_html(project["id"])}</div>'
    )

_SEV_ORDINE = ["critical", "high", "medium", "low", "info"]
_SEV_NOME = {"critical": "Critiche", "high": "Gravi", "medium": "Medie",
             "low": "Minori", "info": "Informative"}


def _plurale(n: int, singolare: str, plurale: str) -> str:
    """«1 visite da AI» si legge come una svista, e una svista fa dubitare anche
    del numero che le sta accanto."""
    return f"{n} {singolare if n == 1 else plurale}"


def _riepilogo_periodo(project: dict, giorni: int = 30) -> dict:
    """I numeri del rapporto, tutti misurati. Nessuna stima, nessun riempitivo.

    Dove un dato non c'e' resta None e chi rende il rapporto lo dice: una riga
    «nessun calo di traffico» scritta senza aver misurato il traffico e' peggio
    di una riga assente, perche' non si distingue da una misurata.
    """
    da = datetime.now(timezone.utc) - timedelta(days=giorni)
    da_iso = da.isoformat()

    storico = _sb_audits_by_project(project["id"], limit=260, full=False)
    nel_periodo = [a for a in storico if (a.get("created_at") or "") >= da_iso]

    punteggi = [a for a in storico if a.get("overall") is not None]
    attuale = punteggi[0]["overall"] if punteggi else None
    # Il confronto e' col primo audit del periodo, non con quello precedente:
    # un rapporto a 30 giorni deve dire quanto e' cambiato in 30 giorni, non
    # quanto e' cambiato dall'ultima volta che si e' guardato.
    dentro = [a for a in punteggi if (a.get("created_at") or "") >= da_iso]
    iniziale = dentro[-1]["overall"] if len(dentro) > 1 else None
    delta = (attuale - iniziale) if (attuale is not None and iniziale is not None) else None

    issues = _sb_issues_by_project(project["id"])
    aperte = [i for i in issues if i.get("status") == "open"]
    per_sev: dict = {}
    for i in aperte:
        s = i.get("severity") or "info"
        per_sev[s] = per_sev.get(s, 0) + 1
    risolte = [i for i in issues
               if i.get("status") in ("resolved", "resolved_manually")
               and (i.get("resolved_at") or "") >= da_iso]
    nuove = [i for i in aperte if (i.get("first_seen_at") or "") >= da_iso]

    # La voce con piu' impatto: la criticita' aperta piu' grave, e fra pari
    # gravita' quella che tocca piu' pagine — e' quella che, sistemata, sposta
    # di piu' il punteggio.
    per_check: dict = {}
    for i in aperte:
        k = (i.get("check_id"), i.get("title"), i.get("severity") or "info")
        per_check[k] = per_check.get(k, 0) + 1
    prioritaria = None
    if per_check:
        def peso(v):
            (_, _, sev), n = v
            return (_SEV_ORDINE.index(sev) if sev in _SEV_ORDINE else 9, -n)
        (check_id, titolo, sev), quante = sorted(per_check.items(), key=peso)[0]
        prioritaria = {"titolo": titolo or check_id, "severita": sev, "pagine": quante}

    eventi = _sb_tracking_events(project["id"], days=giorni)
    crawler = [e for e in eventi if e.get("event_name") == "crawler"]
    visite = [e for e in eventi if e.get("event_name") != "crawler"]
    sessioni_ai = {e.get("session_id") for e in visite
                   if e.get("ai_source") and e.get("session_id")}
    per_bot: dict = {}
    for e in crawler:
        b = e.get("ai_source") or "Sconosciuto"
        per_bot[b] = per_bot.get(b, 0) + 1

    return {
        "giorni": giorni,
        "audit_fatti": len(nel_periodo),
        "punteggio": attuale,
        "punteggio_iniziale": iniziale,
        "delta": delta,
        "aperte": len(aperte),
        "per_sev": per_sev,
        "risolte": len(risolte),
        "nuove": len(nuove),
        "prioritaria": prioritaria,
        # None, non 0: «nessun evento registrato» e «il tracking non e'
        # installato» sono due cose diverse e non vanno confuse in uno zero.
        "tracking": bool(eventi),
        "crawler": len(crawler) if eventi else None,
        "per_bot": per_bot,
        "sessioni_ai": len(sessioni_ai) if eventi else None,
    }


def _rapporto_testo(project: dict, r: dict) -> str:
    """Il rapporto in testo semplice, pronto da incollare in una email.

    Serve a chi lavora per conto terzi: il valore non e' la schermata, e' poter
    girare due paragrafi al proprio cliente senza riscriverli a mano.
    """
    dominio = project.get("domain") or project.get("name") or ""
    righe = [f"GEO Audit · {dominio} — ultimi {r['giorni']} giorni", ""]

    if r["punteggio"] is None:
        righe.append("Punteggio: nessun audit completato.")
    elif r["delta"] is None:
        righe.append(f"Punteggio GEO: {r['punteggio']}/100 "
                     "(un solo audit nel periodo: non c'è ancora un confronto).")
    else:
        verso = "salito" if r["delta"] > 0 else ("sceso" if r["delta"] < 0 else "rimasto")
        segno = f"{r['delta']:+d}" if r["delta"] else "invariato"
        righe.append(f"Punteggio GEO: {r['punteggio']}/100, {verso} da "
                     f"{r['punteggio_iniziale']} ({segno}).")

    if r["risolte"] or r["nuove"]:
        pezzi = []
        if r["risolte"]:
            pezzi.append(_plurale(r["risolte"], "criticità risolta", "criticità risolte"))
        if r["nuove"]:
            pezzi.append(_plurale(r["nuove"], "nuova", "nuove"))
        resta = _plurale(r["aperte"], "aperta", "aperte")
        righe.append(f"Criticità: {' e '.join(pezzi)}. Ne {'resta' if r['aperte'] == 1 else 'restano'} {resta}.")
    else:
        righe.append(f"Criticità aperte: {r['aperte']}, nessun cambiamento nel periodo.")

    if r["tracking"]:
        if r["crawler"]:
            top = sorted(r["per_bot"].items(), key=lambda x: -x[1])[:3]
            elenco = ", ".join(f"{b} ({n})" for b, n in top)
            righe.append(f"Crawler AI: {_plurale(r['crawler'], 'passaggio', 'passaggi')}. "
                         f"{'Il più assiduo' if len(top) == 1 else 'I più assidui'}: {elenco}.")
        else:
            righe.append("Crawler AI: nessun passaggio registrato nel periodo.")
        righe.append(f"Visite arrivate da un assistente AI: {r['sessioni_ai']}.")
    else:
        righe.append("Traffico AI: non misurato (tracking non ancora installato).")

    if r["prioritaria"]:
        p = r["prioritaria"]
        dove = f" su {p['pagine']} pagine" if p["pagine"] > 1 else ""
        righe += ["", f"Da fare per primo: {p['titolo']}{dove}."]

    return "\n".join(righe)


def _tab_reports(project: dict) -> str:
    """Rapporti: il punto del periodo, calcolato sui dati veri del progetto.

    ⚠️ Era una sezione dimostrativa, e non doveva restarlo: ogni numero del
    digest d'esempio — punteggio, criticità risolte, traffico AI — era già
    calcolabile. Quello che davvero manca non è il rapporto ma la **spedizione
    automatica**, che ha bisogno del cron e delle notifiche; per questo il
    rapporto qui si legge e si copia, e gli avvisi restano dichiarati come non
    attivi invece di essere interruttori che non accendono niente.
    """
    r = _riepilogo_periodo(project, 30)
    testo = _rapporto_testo(project, r)

    if r["delta"] is None:
        classe_delta, freccia = "", ""
    elif r["delta"] > 0:
        classe_delta, freccia = "good", "▲ "
    elif r["delta"] < 0:
        classe_delta, freccia = "critical", "▼ "
    else:
        classe_delta, freccia = "", ""

    kpi = (
        '<div class="kpi-strip">'
        + _kpi_semplice(r["punteggio"] if r["punteggio"] is not None else "—",
                        "Punteggio GEO",
                        (f'{freccia}{abs(r["delta"])} punti in {r["giorni"]} giorni'
                         if r["delta"] else f'{r["audit_fatti"]} audit nel periodo'),
                        classe_delta)
        + _kpi_semplice(r["risolte"], "Criticità risolte", f'negli ultimi {r["giorni"]} giorni', "good")
        + _kpi_semplice(r["aperte"], "Criticità aperte",
                        (_plurale(r["nuove"], "comparsa", "comparse") + " nel periodo")
                        if r["nuove"] else "nessuna nuova")
        + _kpi_semplice(r["crawler"] if r["crawler"] is not None else "—", "Passaggi di crawler AI",
                        "tracking non installato" if not r["tracking"]
                        else _plurale(r["sessioni_ai"], "visita da AI", "visite da AI"),
                        "good" if r["crawler"] else "")
        + '</div>'
    )

    sev_righe = "".join(
        f'<div class="engine-row"><div class="engine-name">{_SEV_NOME.get(s, s)}</div>'
        f'{_barra_semplice(round(100 * n / max(r["per_sev"].values())), _SEV_BARRA.get(s, "warn"))}'
        f'<div class="area-value">{n}</div></div>'
        for s, n in sorted(r["per_sev"].items(),
                           key=lambda x: _SEV_ORDINE.index(x[0]) if x[0] in _SEV_ORDINE else 9)
    ) or '<p class="card-sub">Nessuna criticità aperta.</p>'

    prossimo = ''
    if r["prioritaria"]:
        p = r["prioritaria"]
        dove = f' su {p["pagine"]} pagine' if p["pagine"] > 1 else ''
        prossimo = (
            '<div class="alert alert--info" style="margin-top:16px"><div class="ic">i</div>'
            f'<div><b>Da fare per primo:</b> {geo_audit.esc(p["titolo"] or "")}{dove}. '
            'È la criticità più grave fra quelle aperte, e fra pari gravità quella che '
            'tocca più pagine — sistemarla è ciò che sposta di più il punteggio.</div></div>'
        )

    return (
        kpi
        + '<div class="card" style="margin-top:20px">'
          '<div class="card-title">Il punto degli ultimi 30 giorni</div>'
          '<p class="card-sub">Calcolato sugli audit, sulle criticità e sul tracking di questo '
          'progetto. Copialo e giralo al cliente così com\'è.</p>'
          f'<div class="code-block" style="margin-top:14px">'
          '<div class="code-block-header"><span class="code-block-label">Rapporto</span>'
          f'<button class="copy-btn" data-copia="rapportoTesto" data-testo="{geo_audit.esc(testo)}">'
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
          '<rect x="9" y="9" width="13" height="13" rx="2"/>'
          '<path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>'
          '<span>Copia</span></button></div>'
          '<div class="code-content"><code id="rapportoTesto" style="white-space:pre-wrap">'
          f'{geo_audit.esc(testo)}</code></div></div>'
          f'{prossimo}'
          '</div>'

        + '<div class="card" style="margin-top:20px">'
          '<div class="card-title">Criticità aperte per gravità</div>'
          f'<div style="margin-top:14px">{sev_righe}</div></div>'

        + '<div class="card" style="margin-top:20px">'
          '<div class="card-title">Invio automatico</div>'
          '<p class="card-sub">Il rapporto qui sopra è pronto, ma per ora si legge e si copia: '
          '<b>non parte da solo</b>. La spedizione periodica e gli avvisi sulle variazioni '
          'richiedono il sistema di notifiche, che non è ancora attivo. Quando lo sarà, questa '
          'scheda avrà gli interruttori — metterli adesso vorrebbe dire promettere email che '
          'non arriverebbero.</p></div>'

        + _COPIA_JS
    )


def _tab_settings(project: dict) -> str:
    freq = project.get("scan_frequency") or "weekly"
    opzioni = "".join(
        f'<option value="{key}"{" selected" if key == freq else ""}>{label}</option>'
        for key, label in _SCAN_FREQUENCY_LABELS.items()
    )
    installato = _sb_has_tracking(project["id"])
    stato = ('<span class="badge good">Installato</span>' if installato
             else '<span class="badge neutral">Non ancora rilevato</span>')

    return (
        '<div class="settings-card">'
        '<div class="card-title">Informazioni progetto</div>'
        f'<form method="post" action="/project/{project["id"]}/settings">'
        '<div class="form-grid-2">'
        '<div class="form-row"><label class="form-label" for="name">Nome progetto</label>'
        f'<input class="form-input" id="name" name="name" '
        f'value="{geo_audit.esc(project.get("name") or "")}" required></div>'
        '<div class="form-row"><label class="form-label" for="sector">Settore (opzionale)</label>'
        f'<input class="form-input" id="sector" name="sector" '
        f'value="{geo_audit.esc(project.get("sector") or "")}" placeholder="es. Hospitality, Retail\u2026"></div>'
        '</div>'
        '<div class="form-grid-2">'
        '<div class="form-row"><label class="form-label">Dominio</label>'
        f'<input class="form-input" value="{geo_audit.esc(project.get("domain") or "")}" disabled>'
        '<div class="form-hint">Il dominio non si cambia: analizzarne un altro significa '
        'creare un progetto nuovo.</div></div>'
        '<div class="form-row"><label class="form-label" for="scan_frequency">Audit automatico</label>'
        f'<select class="form-select" id="scan_frequency" name="scan_frequency">{opzioni}</select>'
        f'<div class="form-hint">Prossimo: {geo_audit.esc(_fmt_date(project.get("next_scan_at")))}</div></div>'
        '</div>'
        '<button type="submit" class="btn btn-primary" style="margin-top:6px">Salva modifiche</button>'
        '</form></div>'

        '<div class="settings-card">'
        f'<div class="settings-head"><span class="card-title" style="margin:0">Tracking del traffico AI</span>{stato}</div>'
        f'{_tracking_snippet_html(project["id"])}'
        '</div>'
    )



def _project_actions(project: dict) -> str:
    freq = project.get("scan_frequency") or "weekly"
    freq_label = _SCAN_FREQUENCY_LABELS.get(freq, "Settimanale")
    next_scan = project.get("next_scan_at")
    next_txt = (f'Prossimo audit automatico: {_fmt_date(next_scan)} · {freq_label}'
                if next_scan else f'Audit automatico: {freq_label}')
    return (
        '<div class="project-actions">'
        f'<form method="post" action="/project/{project["id"]}/rerun" class="rerun-form" '
        'onsubmit="var b=this.querySelector(\'button\');b.disabled=true;'
        'b.textContent=\'Analisi in corso…\';">'
        '<button type="submit" class="btn btn--secondary btn--sm">↻ Rifai audit</button>'
        '</form>'
        f'<p class="next-scan-note">{geo_audit.esc(next_txt)}</p>'
        '</div>'
    )


# ── Dashboard: sintesi automatica e sparkline di portfolio ───────────────────
#
# Il documento funzionale lascia aperta la scelta fra una sintesi generata da
# regole e una scritta da un modello linguistico (§5.4). Qui è a regole: legge
# solo dati già presenti, non costa nulla e non può inventare. Se un domani si
# vorrà passare a un modello, il punto di innesto è questa sola funzione.

def _giorni_da(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return max(0, (datetime.now(timezone.utc) - d).days)
    except Exception:
        return None


def _dashboard_summary_banner(cards: list) -> str:
    """Banner di sintesi in cima alla dashboard, costruito sui dati reali."""
    if not cards:
        return ""

    tot = len(cards)
    con_critici = [c for c in cards if (c.get("critical_count") or 0) > 0]
    con_score = [c for c in cards if c.get("overall") is not None]
    da_rifare = [c for c in cards if c.get("status") == "Audit required"]

    frasi = []
    plurale = "progetti monitorati" if tot != 1 else "progetto monitorato"

    if con_critici:
        peggiore = min(con_critici,
                       key=lambda c: c["overall"] if c.get("overall") is not None else 999)
        quanti = len(con_critici)
        verbo = "ha" if quanti == 1 else "hanno"
        testa = (f'Su <b>{tot} {plurale}</b>, '
                 f'<span class="critical">{quanti} {verbo} almeno una criticità</span> aperta')
        if peggiore.get("overall") is not None:
            testa += (f' — il più urgente è <b>{geo_audit.esc(peggiore["domain"])}</b>'
                      f' (score {peggiore["overall"]}, {peggiore.get("critical_count")} criticità).')
        else:
            testa += "."
        frasi.append(testa)
    else:
        frasi.append(f'Su <b>{tot} {plurale}</b>, '
                     f'<span class="good">nessuna criticità aperta</span>.')

    if len(con_score) >= 2:
        migliori = sorted(con_score, key=lambda c: c["overall"], reverse=True)[:2]
        nomi = " e ".join(f'<b>{geo_audit.esc(m["domain"])}</b>' for m in migliori)
        punteggi = " e ".join(str(m["overall"]) for m in migliori)
        frasi.append(f'{nomi} restano i migliori del portfolio ({punteggi}).')

    if da_rifare:
        vecchio = min(da_rifare, key=lambda c: c.get("last_scan") or "")
        giorni = _giorni_da(vecchio.get("last_scan"))
        if giorni is not None:
            frasi.append(f'Nessun nuovo audit per <b>{geo_audit.esc(vecchio["domain"])}</b> '
                         f'da {giorni} giorni.')
        else:
            frasi.append(f'<b>{geo_audit.esc(vecchio["domain"])}</b> non è mai stato analizzato.')

    return (
        '<div class="ai-summary">'
        '<div class="ai-summary-icon">'
        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" '
        'stroke-width="2" aria-hidden="true">'
        '<path d="M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8z"/></svg>'
        '</div>'
        '<div class="ai-summary-body">'
        '<div class="ai-summary-label">Sintesi automatica</div>'
        f'<div class="ai-summary-text">{" ".join(frasi)}</div>'
        '</div></div>'
    )


def _portfolio_sparkline(projects: list) -> str:
    """Crescita del numero di progetti negli ultimi 6 mesi.

    E' l'unico dei quattro KPI di portfolio per cui esiste uno storico reale
    (le date di creazione dei progetti). Gli altri tre — critici, audit da
    rifare, tracking attivo — descrivono lo stato di oggi e non sono
    ricostruibili all'indietro: restano senza sparkline invece di riceverne una
    inventata.
    """
    date = []
    for p in projects:
        try:
            date.append(datetime.fromisoformat((p.get("created_at") or "").replace("Z", "+00:00")))
        except Exception:
            continue
    if len(date) < 2:
        return ""

    oggi = datetime.now(timezone.utc)
    tappe = [oggi - timedelta(days=30 * i) for i in range(5, -1, -1)]
    conteggi = [len([d for d in date if d <= t]) for t in tappe]
    if conteggi[0] == conteggi[-1]:
        return ""

    W, H, PAD = 70, 28, 3
    lo, hi = min(conteggi), max(conteggi)
    span = (hi - lo) or 1
    punti = " ".join(
        f'{i / (len(conteggi) - 1) * W:.1f},{H - PAD - (v - lo) / span * (H - PAD * 2):.1f}'
        for i, v in enumerate(conteggi)
    )
    return (f'<svg class="kpi-spark" viewBox="0 0 {W} {H}" aria-hidden="true">'
            f'<polyline points="{punti}" fill="none" stroke="var(--text-muted)" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>')


# ── Menu laterale della pagina di progetto ───────────────────────────────────
#
# Sostituisce le linguette orizzontali a doppio livello: le cinque categorie
# stanno nel menu a sinistra, i sotto-livelli dell'Audit restano linguette
# orizzontali sopra il contenuto (cosi' li vuole il prototipo).

_NAV_ICONS = {
    "overview": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/>'
                '<rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "audit":    '<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/>',
    "ai":       '<path d="M12 2a10 10 0 100 20 10 10 0 000-20z"/><path d="M12 6v6l4 2"/>',
    "growth":   '<path d="M3 3v18h18"/><path d="M18 17V9M13 17V5M8 17v-3"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06'
                'a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33'
                'l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09'
                'A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H9'
                'a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06'
                'a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09'
                'a1.65 1.65 0 00-1.51 1z"/>',
}


def _nav_icon(chiave: str) -> str:
    return ('<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="2" aria-hidden="true">{_NAV_ICONS.get(chiave, "")}</svg>')


def menu_utente(email: str, e_admin: bool = False, verso_basso: bool = False) -> str:
    """Le azioni sul proprio account: il pannello del team, e l'uscita.

    ⚠️ `e_admin` arriva da chi costruisce la pagina, che lo legge con la STESSA
    funzione che protegge il pannello (`_e_admin` in `db.py`). Non si ricava qui
    da un'euristica sull'email: due modi diversi di decidere chi è del team
    finirebbero per dire cose diverse, e quello sbagliato sarebbe questo —
    mostrare a un cliente un link che poi gli risponde «pagina non trovata».

    Nascondere il link NON è il controllo: il controllo è sulla route. Questo
    serve solo a non far vedere una porta che non si può aprire.
    """
    voci = []
    if e_admin:
        voci.append(
            '<a href="/admin">'
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1.5"/>'
            '<rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/>'
            '<rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>Pannello del team</a>')
    voci.append(
        '<a href="/auth/logout">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'aria-hidden="true"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/>'
        '<path d="M16 17l5-5-5-5M21 12H9"/></svg>Esci</a>')

    iniziale = geo_audit.esc((email or "?")[:1].upper())
    return (
        f'<details class="menu-utente{" giu" if verso_basso else ""}">'
        '<summary>'
        f'<div class="avatar">{iniziale}</div>'
        f'<span class="email" title="{geo_audit.esc(email)}">{geo_audit.esc(email)}</span>'
        '<svg class="freccia" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>'
        '</summary>'
        '<div class="menu-utente-voci">'
        f'<div class="menu-utente-email">{geo_audit.esc(email)}</div><hr>'
        + "".join(voci) +
        '</div></details>'
    )


def _sidebar(project: dict, latest: dict | None, open_issues: int,
             active_tab: str, user_email: str = "", e_admin: bool = False) -> str:
    """Il menu laterale: identita', progetto corrente, sezioni, utente."""
    pid = project["id"]
    attiva = _category_for_tab(active_tab)
    overall = latest.get("overall") if latest else None
    cls = _score_class(overall).replace("score-", "")
    cls = {"ottimo": "good", "migliorabile": "warn", "critico": "critical"}.get(cls, "unknown")
    punteggio = overall if overall is not None else "n.d."

    voci = []
    for chiave, etichetta, figli in _TAB_CATEGORIES:
        destinazione = chiave if figli is None else figli[0][0]
        soon = figli is not None and all(k in _COMING_SOON_TABS for k, _ in figli)
        classe = "nav-item" + (" active" if chiave == attiva else "")
        coda = ""
        if soon:
            coda = '<span class="nav-soon">SOON</span>'
        elif chiave == "audit" and open_issues:
            coda = f'<span class="nav-count">{open_issues}</span>'
        voci.append(
            f'<a class="{classe}" href="/project/{pid}?tab={destinazione}">'
            f'<span class="nav-item-label">{_nav_icon(chiave)}{geo_audit.esc(etichetta)}</span>'
            f'{coda}</a>'
        )

    return (
        '<aside class="sidebar" id="sidebar">'
        '<button class="sidebar-close" onclick="chiudiMenu()" aria-label="Chiudi il menu">'
        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">'
        '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>'

        '<a class="brand" href="/dashboard">'
        '<div class="brand-mark">V</div>'
        '<div class="brand-name">vertical<span>ai</span></div></a>'

        '<a class="back-link" href="/dashboard">\u2190 I tuoi progetti</a>'

        '<div class="project-switch">'
        f'<div class="project-switch-badge {cls}">{geo_audit.esc(punteggio)}</div>'
        '<div class="project-switch-text">'
        f'<div class="project-switch-name">{geo_audit.esc(project["name"])}</div>'
        f'<div class="project-switch-domain">{geo_audit.esc(project["domain"])}</div>'
        '</div></div>'

        '<div class="nav-group">'
        '<div class="nav-label">Progetto</div>'
        + "".join(voci) +
        '</div>'

        '<div class="nav-group">'
        '<div class="nav-label">Scorciatoie</div>'
        f'<a class="nav-item" href="/audit"><span class="nav-item-label">'
        '<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>Nuova analisi</span></a>'
        f'<a class="nav-item" href="/roadmap"><span class="nav-item-label">'
        '<svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
        'aria-hidden="true"><path d="M9 18l6-6-6-6"/></svg>Roadmap prodotto</span></a>'
        '</div>'

        '<div class="sidebar-footer">'
        # ⚠️ Qui prima c'erano avatar ed email e basta: da questa pagina non si
        # poteva uscire. Ora sono il bottone di un menu che contiene «Esci» —
        # e, per chi è del team, il passaggio al pannello.
        + menu_utente(user_email, e_admin)
        + 
        '<button class="theme-toggle" onclick="cambiaTema()" aria-label="Cambia tema">'
        '<svg class="icon-sun" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41'
        'M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>'
        '<svg class="icon-moon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg></button>'
        '</div>'
        '</aside>'
    )


def _subtabs(project_id: str, active_tab: str, conteggi: dict | None = None) -> str:
    """Sotto-linguette della categoria attiva. Vuoto se la categoria non ne ha."""
    attiva = _category_for_tab(active_tab)
    figli = next((f for k, _, f in _TAB_CATEGORIES if k == attiva), None)
    if not figli:
        return ""
    conteggi = conteggi or {}
    voci = []
    for chiave, etichetta in figli:
        classe = "subtab" + (" active" if chiave == active_tab else "")
        n = conteggi.get(chiave)
        badge = f'<span class="count">{n}</span>' if n else ""
        voci.append(f'<a class="{classe}" href="/project/{project_id}?tab={chiave}">'
                    f'{geo_audit.esc(etichetta)}{badge}</a>')
    return '<div class="subtabs">' + "".join(voci) + '</div>'


# ── Roadmap pubblica ─────────────────────────────────────────────────────────
#
# I contenuti stanno qui e si aggiornano a mano: e' una pagina di prodotto, non
# un dato calcolato. Gli identificativi (la prima voce di ogni tupla) sono la
# chiave con cui si contano i voti: **non vanno mai cambiati**, altrimenti i
# voti raccolti finiscono su una funzionalita' che non esiste piu'.

_ROADMAP_LIVE = [
    ("Analisi GEO del sito",
     "31 controlli su sei aree, punteggio da 0 a 100 e report completo con gli interventi da fare."),
    ("Storico e andamento",
     "Ogni sito diventa un progetto con la sua storia: si vede se il punteggio sale o scende nel tempo."),
    ("Criticità con ciclo di vita",
     "Un problema sa da quanti giorni è aperto, e si chiude da solo quando l'analisi non lo trova più."),
    ("Analisi automatica ricorrente",
     "Il sito viene ricontrollato da solo, ogni giorno, settimana o mese."),
    ("Traffico dagli assistenti AI",
     "Uno snippet da installare misura quante visite arrivano da ChatGPT, Perplexity, Gemini e gli altri."),
    ("Report condivisibile",
     "Un documento con punteggio, criticità e interventi, da girare a chi deve metterci mano."),
]

_ROADMAP_COLONNE = [
    ("In sviluppo", "Ci stiamo lavorando adesso", [
        ("visibilita-ai", "AI Visibility",
         "Quanto il sito viene citato nelle risposte di ChatGPT, Gemini e Perplexity, misurato su domande "
         "vere poste con regolarità.",
         '<path d="M12 2a10 10 0 100 20 10 10 0 000-20z"/><path d="M12 6v6l4 2"/>'),
        ("prompt", "Prompt e argomenti",
         "Su quali domande comparite e su quali no, argomento per argomento.",
         '<path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>'),
    ]),
    ("Pianificato", "Subito dopo", [
        ("competitor", "Confronto con i concorrenti",
         "Quanto spazio occupate voi e quanto loro nelle risposte delle AI, e su quali domande vi superano.",
         '<path d="M3 3v18h18"/><path d="M18 17V9M13 17V5M8 17v-3"/>'),
        ("citazioni", "Citazioni e fonti",
         "Quali vostre pagine vengono indicate come fonte, e chi altro parla di voi.",
         '<path d="M10 9V5a2 2 0 00-2-2H4a2 2 0 00-2 2v4a2 2 0 002 2h2l2 4M22 9V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v4a2 2 0 002 2h2l2 4"/>'),
        ("avvisi", "Avvisi e riepiloghi",
         "Una mail quando il punteggio cambia molto o compare un problema grave, e un riepilogo periodico.",
         '<path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/>'),
    ]),
    ("In esplorazione", "Ci stiamo ragionando", [
        ("accuratezza", "Accuratezza del racconto",
         "Verificare che le AI raccontino la vostra azienda in modo corretto, e correggere dove sbagliano.",
         '<path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><path d="M22 4L12 14.01l-3-3"/>'),
        ("fuori-sito", "Presenza fuori dal sito",
         "Wikipedia, Wikidata e le fonti indipendenti che le AI leggono parlando di voi.",
         '<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15 15 0 010 20 15 15 0 010-20"/>'),
        ("per-motore", "Punteggio per singolo motore",
         "Un punteggio distinto per ChatGPT, Gemini, Claude e Perplexity: hanno criteri diversi.",
         '<path d="M12 20V10M18 20V4M6 20v-4"/>'),
    ]),
]


def _roadmap_live_html() -> str:
    return "".join(
        '<div class="live-card">'
        '<div class="live-check">'
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" aria-hidden="true">'
        '<polyline points="20 6 9 17 4 12"/></svg></div>'
        '<div>'
        f'<div class="live-title">{geo_audit.esc(t)}</div>'
        f'<div class="live-desc">{geo_audit.esc(d)}</div>'
        '</div></div>'
        for t, d in _ROADMAP_LIVE
    )


def roadmap_nomi() -> dict:
    """Da chiave tecnica a nome leggibile, per chi deve mostrare i voti altrove.

    Il pannello del team non importa `views`: chiede questo dizionario a chi lo
    monta. Senza, nel conteggio dei voti comparirebbero le chiavi grezze
    («visibilita-ai») al posto dei nomi che il pubblico ha davvero votato.
    """
    return {chiave: nome
            for _, _, funzioni in _ROADMAP_COLONNE
            for chiave, nome, *_ in funzioni}


def _roadmap_colonne_html(voti: dict) -> str:
    colonne = []
    for titolo, sottotitolo, funzioni in _ROADMAP_COLONNE:
        schede = []
        for chiave, nome, descrizione, icona in funzioni:
            n = voti.get(chiave, 0)
            schede.append(
                '<div class="feature-card">'
                f'<div class="feature-icon"><svg width="18" height="18" viewBox="0 0 24 24" '
                f'fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">{icona}</svg></div>'
                f'<div class="feature-title">{geo_audit.esc(nome)}</div>'
                f'<div class="feature-desc">{geo_audit.esc(descrizione)}</div>'
                '<div class="feature-footer">'
                f'<button class="vote-btn" data-feature="{geo_audit.esc(chiave)}">'
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                'aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7"/></svg>'
                '<span>Mi interessa</span></button>'
                f'<span class="vote-count">{n} {"voto" if n == 1 else "voti"}</span>'
                '</div></div>'
            )
        colonne.append(
            '<div>'
            f'<div class="col-header"><div class="feature-title">{geo_audit.esc(titolo)}</div>'
            f'<div class="col-sub">{geo_audit.esc(sottotitolo)}</div></div>'
            + "".join(schede) +
            '</div>'
        )
    return "".join(colonne)
