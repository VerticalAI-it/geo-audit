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
from config import SITE_URL
from db import _sb_has_tracking, _sb_issues_by_project, _sb_recent_audits_by_user, _sb_tracking_events


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


def _ultimi_run_section(user_id: str) -> str:
    """Riquadro in fondo alla home con gli ultimi run dell'utente, manuali e
    automatici, per vedere a colpo d'occhio se l'automazione sta girando.

    Ritorna stringa vuota per i visitatori anonimi e in caso di errore: la home
    è la landing pubblica e non deve poter fallire per colpa di questo blocco."""
    try:
        runs = _sb_recent_audits_by_user(user_id, limit=10)
    except Exception as e:
        print(f"[/] riquadro ultimi run non disponibile: {e!r}")
        return ""
    if not runs:
        return ""

    rows = "".join(
        "<tr>"
        f'<td data-label="Data e ora"><b>{geo_audit.esc(_fmt_datetime(a.get("created_at")))}</b></td>'
        f'<td data-label="Origine">{_run_origin_badge(a.get("source"))}</td>'
        f'<td data-label="Sito"><a href="/r/{geo_audit.esc(str(a.get("id")))}">'
        f'{geo_audit.esc(a.get("domain") or a.get("url") or "—")}</a></td>'
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
        '<section class="section section--compact section--lav1" id="ultimi-run" '
        'aria-labelledby="ultimi-run-title">'
        '<div class="container">'
        '<div class="section-head">'
        '<h2 class="h2" id="ultimi-run-title">Ultimi run</h2>'
        "<p>Le analisi pi&#249; recenti sui tuoi siti, lanciate a mano o dal "
        "monitoraggio automatico settimanale.</p>"
        "</div>"
        '<div class="tbl-wrap"><table class="tbl tbl-responsive"><thead><tr>'
        "<th>Data e ora</th><th>Origine</th><th>Sito</th><th>Punteggio</th>"
        "</tr></thead><tbody>" + rows + "</tbody></table></div>"
        f'<p style="margin-top:14px;font-size:.86rem;color:var(--text-2)">{stato}</p>'
        "</div></section>"
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


def _tab_nav(project_id: str, active_tab: str) -> str:
    active_cat = _category_for_tab(active_tab)

    top = []
    for cat_key, cat_label, children in _TAB_CATEGORIES:
        target = cat_key if children is None else children[0][0]
        soon = children is not None and all(k in _COMING_SOON_TABS for k, _ in children)
        cls = "tab" + (" active" if cat_key == active_cat else "") + (" soon" if soon else "")
        badge = ' <span class="tab-soon">soon</span>' if soon else ""
        top.append(f'<a href="/project/{project_id}?tab={target}" class="{cls}">{geo_audit.esc(cat_label)}{badge}</a>')
    html = '<div class="tabs">' + "".join(top) + '</div>'

    active_children = next((c for k, _, c in _TAB_CATEGORIES if k == active_cat), None)
    if active_children:
        subs = []
        for key, label in active_children:
            soon = key in _COMING_SOON_TABS
            cls = "subtab" + (" active" if key == active_tab else "") + (" soon" if soon else "")
            badge = ' <span class="tab-soon">soon</span>' if soon else ""
            subs.append(f'<a href="/project/{project_id}?tab={key}" class="{cls}">{geo_audit.esc(label)}{badge}</a>')
        html += '<div class="subtabs">' + "".join(subs) + '</div>'
    return html


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


def _tab_overview(project_id: str, latest: dict | None, previous: dict | None,
                   open_issues: int, resolved_recent: int, history: list | None = None) -> str:
    sections_html = _overview_sections_grid(project_id, latest, open_issues, resolved_recent)

    if not latest:
        return (
            '<div class="alert alert--info"><div class="ic">i</div>'
            '<div>Nessun audit ancora eseguito per questo progetto. '
            '<a href="/audit">Avvia la prima analisi →</a></div></div>'
            + sections_html
        )

    overall = latest.get("overall")
    delta = None
    if previous and previous.get("overall") is not None and overall is not None:
        delta = overall - previous["overall"]
    delta_html = ""
    if delta is not None:
        cls = "delta-up" if delta > 0 else ("delta-down" if delta < 0 else "delta-flat")
        sign = "+" if delta > 0 else ""
        delta_html = (
            f'<div class="delta-block"><span class="delta-pill {cls}">{sign}{delta}</span>'
            '<span class="delta-text">vs audit precedente</span></div>'
        )

    areas = latest.get("areas") or []
    worst = areas[0] if areas else None
    best = areas[-1] if areas else None
    best_cls = _score_class(best["score"]).replace("score-", "txt-") if best else "txt-unknown"
    worst_cls = _score_class(worst["score"]).replace("score-", "txt-") if worst else "txt-unknown"
    best_txt = (f'<b>{geo_audit.esc(best["key"])}</b> <span class="{best_cls}">({best["score"]}/100)</span>'
                if best else "—")
    worst_txt = (f'<b>{geo_audit.esc(worst["key"])}</b> <span class="{worst_cls}">({worst["score"]}/100)</span>'
                 if worst else "—")

    issues_count = latest.get("issues_count")
    critical_count = latest.get("critical_count")

    def _count_cls(value, critical):
        if value is None:
            return "stat-neutral"
        if critical:
            return "stat-good" if value == 0 else "stat-bad"
        if value == 0:
            return "stat-good"
        return "stat-warn" if value <= 10 else "stat-bad"

    sc = _score_class(overall)
    return (
        '<div class="ov-grid">'
        '<div class="card"><div class="card-sub">GEO Score</div>'
        f'<div class="ov-score-row"><div class="score-block {sc}" style="width:72px;height:72px">'
        f'<span class="num" style="font-size:24px">{overall if overall is not None else "—"}</span>'
        f'<span class="grd">{geo_audit.esc(latest.get("grade") or "—")}</span></div>{delta_html}</div>'
        f'<p class="card-sub" style="margin-top:10px">Ultimo audit: {_fmt_date(latest.get("created_at"))}</p></div>'

        '<div class="card"><div class="card-sub">Salute issue</div>'
        '<div class="mini-stat-row">'
        f'<div class="mini-stat {_count_cls(issues_count, False)}"><span class="mini-stat-num">{issues_count if issues_count is not None else "—"}</span>'
        '<span class="mini-stat-label">problemi totali</span></div>'
        f'<div class="mini-stat {_count_cls(critical_count, True)}"><span class="mini-stat-num">{critical_count if critical_count is not None else "—"}</span>'
        '<span class="mini-stat-label">critici</span></div>'
        '</div>'
        f'<p style="margin:10px 0 0"><b>{open_issues}</b> issue aperte in Opportunities</p></div>'

        '<div class="card"><div class="card-sub">Area migliore / peggiore</div>'
        f'<p style="margin:6px 0">✓ {best_txt}</p>'
        f'<p style="margin:6px 0">⚠ {worst_txt}</p></div>'

        f'<div class="card"><div class="card-sub">Tracking</div>'
        f'<p style="margin:6px 0">{_tracking_badge(project_id)}</p>'
        '<p class="card-sub" style="margin-top:8px">Vedi la tab AI Traffic per sessioni, provider e landing page.</p></div>'
        '</div>'

        + _score_history_chart(project_id, history or [])
        + sections_html
    )


def _tab_audit(latest: dict | None, history: list) -> str:
    if not latest:
        return ('<div class="alert alert--info"><div class="ic">i</div>'
                '<div>Nessun audit ancora eseguito. <a href="/audit">Avvia la prima analisi →</a></div></div>')

    areas = latest.get("areas") or []
    area_rows = "".join(
        f'<div class="area-row"><span class="area-label">{geo_audit.esc(a["key"])}</span>'
        f'<div class="area-bar-track"><div class="area-bar-fill {_score_class(a["score"])}" '
        f'style="width:{a["score"]}%"></div></div><span class="area-score">{a["score"]}</span></div>'
        for a in areas
    )

    issues_count = latest.get("issues_count")
    critical_count = latest.get("critical_count")
    total_checks = len(latest.get("site_checks") or []) + sum(
        len(p.get("checks") or []) for p in (latest.get("pages_detail") or []))
    pct_ok = round(100 * (total_checks - (issues_count or 0)) / total_checks) if total_checks else None

    actions = (latest.get("actions") or [])[:8]
    actions_html = "".join(
        f'<li class="action-row">{_sev_badge(a["severity"])} <b>{geo_audit.esc(a["title"])}</b>'
        f'<p class="card-sub" style="margin:4px 0 0">{geo_audit.esc(a["recommendation"])} — '
        f'{a["count"]} pagin{"a" if a["count"] == 1 else "e"} interessate</p></li>'
        for a in actions
    ) or '<li class="card-sub">Nessun intervento prioritario: tutti i check principali sono superati.</li>'

    history_html = "".join(
        f'<tr><td data-label="Data">{_fmt_date(h.get("created_at"))}</td>'
        f'<td data-label="Score"><b>{h.get("overall") if h.get("overall") is not None else "—"}</b></td>'
        f'<td data-label="Grade">{geo_audit.esc(h.get("grade") or "—")}</td>'
        f'<td data-label="Critici">{h.get("critical_count") if h.get("critical_count") is not None else "—"}</td></tr>'
        for h in history
    )

    sc = _score_class(latest.get("overall"))
    return (
        '<div class="card"><div class="audit-head-row">'
        f'<div class="score-block {sc}" style="width:72px;height:72px">'
        f'<span class="num" style="font-size:24px">{latest.get("overall") if latest.get("overall") is not None else "—"}</span>'
        f'<span class="grd">{geo_audit.esc(latest.get("grade") or "—")}</span></div>'
        f'<div><p style="margin:0"><b>{issues_count if issues_count is not None else "—"}</b> problemi · '
        f'<b>{critical_count if critical_count is not None else "—"}</b> critici · '
        f'<b>{pct_ok if pct_ok is not None else "—"}%</b> controlli superati</p>'
        f'<a href="/r/{latest.get("id", "")}" class="btn btn--sm" style="margin-top:8px">Apri report completo →</a>'
        '</div></div></div>'

        f'<div class="card" style="margin-top:16px"><div class="card-title">Punteggio per area</div>{area_rows}</div>'
        f'<div class="card" style="margin-top:16px"><div class="card-title">Interventi prioritari</div>'
        f'<ul class="action-list">{actions_html}</ul></div>'
        '<div class="card" style="margin-top:16px"><div class="card-title">Storico audit</div>'
        '<div class="tbl-wrap"><table class="tbl tbl-responsive"><thead><tr>'
        f'<th>Data</th><th>Score</th><th>Grade</th><th>Critici</th></tr></thead>'
        f'<tbody>{history_html}</tbody></table></div></div>'
    )


def _tab_pages(latest: dict | None) -> str:
    if not latest:
        return '<p class="card-sub">Nessun audit ancora eseguito.</p>'
    pages = latest.get("pages_detail") or []
    rows_html = "".join(
        f'<tr><td data-label="URL"><a href="{geo_audit.esc(p.get("url", ""))}" target="_blank" '
        f'rel="noopener">{geo_audit.esc(p.get("url", ""))}</a></td>'
        f'<td data-label="Tipo">{geo_audit.esc(p.get("type") or "—")}</td>'
        f'<td data-label="Score"><b>{p.get("score") if p.get("score") is not None else "—"}</b></td>'
        f'<td data-label="Issue">{len([c for c in (p.get("checks") or []) if c.get("status") in ("warn", "fail")])}</td>'
        f'<td data-label="Critici">{len([c for c in (p.get("checks") or []) if c.get("status") == "fail"])}</td></tr>'
        for p in pages
    )
    return (
        '<div class="card" style="margin-bottom:16px">'
        f'<a href="/r/{latest.get("id", "")}" class="btn btn--sm">Apri report completo per il dettaglio pagina-per-pagina →</a>'
        '</div>'
        '<div class="tbl-wrap"><table class="tbl tbl-responsive"><thead><tr>'
        '<th>URL</th><th>Tipo</th><th>Score</th><th>Issue</th><th>Critici</th>'
        f'</tr></thead><tbody>{rows_html}</tbody></table></div>'
    )


def _tab_technical(latest: dict | None) -> str:
    if not latest:
        return '<p class="card-sub">Nessun audit ancora eseguito.</p>'

    site_checks = [c for c in (latest.get("site_checks") or []) if c.get("id", "").startswith("crawl.")]
    rows_access = [{"title": c["title"], "status": c["status"], "detail": c.get("detail"),
                     "recommendation": c.get("recommendation")} for c in site_checks]

    pages_detail = latest.get("pages_detail") or []
    for check_id in ("meta.canonical", "render.parity"):
        agg = _aggregate_page_check(pages_detail, check_id)
        if agg.get("total"):
            rows_access.append({"title": agg["title"], "status": agg["status"],
                                 "detail": f'{agg["ok"]}/{agg["total"]} pagine OK',
                                 "recommendation": agg.get("recommendation")})

    rows_structured = []
    for check_id in ("sd.present", "sd.valid", "sd.highvalue", "sd.completeness", "sd.sameas",
                      "trust.contact", "trust.social", "trust.author", "sem.html"):
        agg = _aggregate_page_check(pages_detail, check_id)
        if agg.get("total"):
            rows_structured.append({"title": agg["title"], "status": agg["status"],
                                     "detail": f'{agg["ok"]}/{agg["total"]} pagine OK',
                                     "recommendation": agg.get("recommendation")})

    return (
        f'<div class="card-title" style="margin-bottom:10px">Accesso crawler e infrastruttura</div>{_checks_table(rows_access)}'
        f'<div class="card-title" style="margin:20px 0 10px">Dati strutturati ed entity signals</div>{_checks_table(rows_structured)}'
    )


def _tab_opportunities(project_id: str) -> str:
    issues = _sb_issues_by_project(project_id)
    if not issues:
        return '<p class="card-sub">Nessuna issue registrata: esegui un audit per popolare questa sezione.</p>'

    open_issues = [i for i in issues if i["status"] == "open"]
    resolved_issues = [i for i in issues if i["status"] != "open"]

    def row(i):
        return (f'<tr><td data-label="Check"><b>{geo_audit.esc(i.get("title") or i.get("check_id"))}</b></td>'
                f'<td data-label="Severità">{_sev_badge(i.get("severity"))}</td>'
                f'<td data-label="URL">{geo_audit.esc(i.get("url") or "sito")}</td>'
                f'<td data-label="Prima vista">{_fmt_date(i.get("first_seen_at"))}</td>'
                f'<td data-label="Ultima vista">{_fmt_date(i.get("last_seen_at"))}</td>'
                f'<td data-label="Stato">{_status_badge("fail" if i["status"] == "open" else "ok")}</td></tr>')

    thead = '<thead><tr><th>Check</th><th>Severità</th><th>URL</th><th>Prima vista</th><th>Ultima vista</th><th>Stato</th></tr></thead>'
    open_html = "".join(row(i) for i in open_issues) or '<tr><td colspan="6" class="card-sub">Nessuna issue aperta 🎉</td></tr>'
    out = (f'<div class="card-title" style="margin-bottom:10px">Issue aperte ({len(open_issues)})</div>'
           f'<div class="tbl-wrap"><table class="tbl tbl-responsive">{thead}<tbody>{open_html}</tbody></table></div>')

    if resolved_issues:
        resolved_html = "".join(row(i) for i in resolved_issues[:20])
        out += (f'<div class="card-title" style="margin:20px 0 10px">Risolte di recente ({len(resolved_issues)})</div>'
                f'<div class="tbl-wrap"><table class="tbl tbl-responsive">{thead}<tbody>{resolved_html}</tbody></table></div>')
    return out


def _tracking_badge(project_id: str) -> str:
    return ('<span class="badge badge--success"><span class="dot"></span>Tracking attivo</span>'
            if _sb_has_tracking(project_id) else
            '<span class="badge badge--neutral">Tracking not installed</span>')


def _tracking_snippet_html(project_id: str) -> str:
    tag = (f'&lt;script src="{SITE_URL}/static/js/geo-track.js" '
           f'data-project="{project_id}" async&gt;&lt;/script&gt;')
    return (
        '<div class="card-title" style="margin-bottom:8px">Snippet di tracking</div>'
        '<p class="card-sub" style="margin-bottom:10px">Incolla questo tag prima della chiusura di '
        '<code>&lt;/head&gt;</code> sul tuo sito. Gli eventi compaiono qui entro pochi minuti dalla prima visita.</p>'
        '<pre style="background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-md);'
        f'padding:12px 14px;overflow-x:auto;font-family:var(--font-mono);font-size:12.5px;color:var(--text-2);'
        f'margin:0">{tag}</pre>'
        '<p class="card-sub" style="margin-top:10px">Per registrare una conversione (es. invio form, prenotazione): '
        '<code>window.geoTrack("nome_evento")</code>.</p>'
    )


def _tab_traffic(project: dict) -> str:
    events = _sb_tracking_events(project["id"], days=30, limit=5000)
    if not events:
        return (
            '<div class="alert alert--info"><div class="ic">i</div>'
            '<div>Nessun evento di tracking ancora ricevuto per questo progetto. '
            'Installa lo snippet qui sotto per iniziare a raccogliere le sessioni.</div></div>'
            f'<div class="card" style="margin-top:16px">{_tracking_snippet_html(project["id"])}</div>'
        )

    sessions = {}
    for e in events:
        sid = e.get("session_id") or e.get("created_at")
        row = sessions.setdefault(sid, {"ai_source": None, "landing": e.get("page_url"), "first_at": e.get("created_at")})
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
    for s in ai_sessions:
        by_source[s["ai_source"]] = by_source.get(s["ai_source"], 0) + 1
    source_rows = "".join(
        f'<tr><td data-label="Provider"><b>{geo_audit.esc(k)}</b></td><td data-label="Sessioni">{v}</td></tr>'
        for k, v in sorted(by_source.items(), key=lambda x: -x[1])
    ) or '<tr><td colspan="2" class="card-sub">Nessuna sessione da AI nel periodo.</td></tr>'

    by_landing: dict = {}
    for s in ai_sessions:
        url = s["landing"] or "—"
        by_landing[url] = by_landing.get(url, 0) + 1
    landing_rows = "".join(
        f'<tr><td data-label="Pagina">{geo_audit.esc(k)}</td><td data-label="Sessioni">{v}</td></tr>'
        for k, v in sorted(by_landing.items(), key=lambda x: -x[1])[:10]
    ) or '<tr><td colspan="2" class="card-sub">Nessuna landing page da AI nel periodo.</td></tr>'

    daily: dict = {}
    for e in events:
        if not e.get("ai_source"):
            continue
        day = (e.get("created_at") or "")[:10]
        if day:
            daily[day] = daily.get(day, 0) + 1
    trend_rows = "".join(
        f'<tr><td data-label="Data">{_fmt_date(day)}</td><td data-label="Eventi AI">{count}</td></tr>'
        for day, count in sorted(daily.items(), reverse=True)[:14]
    ) or '<tr><td colspan="2" class="card-sub">Nessun evento AI negli ultimi 14 giorni.</td></tr>'

    return (
        '<div class="mini-stat-row">'
        f'<div class="mini-stat"><span class="mini-stat-num">{total_sessions}</span><span class="mini-stat-label">sessioni (30gg)</span></div>'
        f'<div class="mini-stat stat-good"><span class="mini-stat-num">{ai_count}</span><span class="mini-stat-label">sessioni da AI</span></div>'
        f'<div class="mini-stat"><span class="mini-stat-num">{ai_pct}%</span><span class="mini-stat-label">quota AI</span></div>'
        '</div>'

        '<div class="card-title" style="margin:20px 0 10px">Per provider</div>'
        '<div class="tbl-wrap"><table class="tbl tbl-responsive"><thead><tr><th>Provider</th><th>Sessioni</th></tr></thead>'
        f'<tbody>{source_rows}</tbody></table></div>'

        '<div class="card-title" style="margin:20px 0 10px">Landing page più visitate da AI</div>'
        '<div class="tbl-wrap"><table class="tbl tbl-responsive"><thead><tr><th>Pagina</th><th>Sessioni</th></tr></thead>'
        f'<tbody>{landing_rows}</tbody></table></div>'

        '<div class="card-title" style="margin:20px 0 10px">Andamento (ultimi 14 giorni)</div>'
        '<div class="tbl-wrap"><table class="tbl tbl-responsive"><thead><tr><th>Data</th><th>Eventi AI</th></tr></thead>'
        f'<tbody>{trend_rows}</tbody></table></div>'

        f'<div class="card" style="margin-top:20px">{_tracking_snippet_html(project["id"])}</div>'
    )


def _tab_settings(project: dict) -> str:
    freq = project.get("scan_frequency") or "weekly"
    freq_options = "".join(
        f'<option value="{key}"{" selected" if key == freq else ""}>{label}</option>'
        for key, label in _SCAN_FREQUENCY_LABELS.items()
    )
    tracking_installed = _sb_has_tracking(project["id"])
    tracking_status = ('<span class="badge badge--success"><span class="dot"></span>Installato</span>'
                        if tracking_installed else
                        '<span class="badge badge--neutral">Non ancora rilevato</span>')
    return (
        '<div class="card"><div class="card-title">Informazioni progetto</div>'
        f'<form method="post" action="/project/{project["id"]}/settings" class="settings-form">'
        '<div class="field"><label for="name">Nome progetto</label>'
        f'<input class="input" id="name" name="name" value="{geo_audit.esc(project.get("name") or "")}" required></div>'
        '<div class="field"><label for="sector">Settore (opzionale)</label>'
        f'<input class="input" id="sector" name="sector" value="{geo_audit.esc(project.get("sector") or "")}" '
        'placeholder="es. Hospitality, Retail…"></div>'
        '<div class="field"><label>Dominio</label>'
        f'<input class="input" value="{geo_audit.esc(project.get("domain") or "")}" disabled></div>'
        '<div class="field"><label for="scan_frequency">Audit automatico</label>'
        f'<select class="input" id="scan_frequency" name="scan_frequency">{freq_options}</select>'
        f'<span class="hint">Prossimo audit automatico: {geo_audit.esc(_fmt_date(project.get("next_scan_at")))}</span></div>'
        '<button type="submit" class="btn btn--primary" style="margin-top:8px">Salva</button>'
        '</form></div>'

        f'<div class="card" style="margin-top:16px">'
        f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">'
        f'<span class="card-title" style="margin:0">Tracking</span>{tracking_status}</div>'
        f'{_tracking_snippet_html(project["id"])}</div>'

        '<div class="card coming-soon-card" style="margin-top:16px">'
        '<span class="badge badge--neutral"><span class="dot"></span>Coming soon</span>'
        '<h2 class="card-title" style="margin-top:12px">Conversion event personalizzati</h2>'
        '<p class="card-sub">Configurazione guidata degli eventi di conversione (oggi disponibile solo via '
        '<code>window.geoTrack()</code> lato codice) non ancora disponibile da qui.</p></div>'
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
