# -*- coding: utf-8 -*-
"""Le schermate del monitoraggio AI: quattro per il cliente, due per l'admin.

Il documento del 4 settembre (`GEO_Audit_PromptMonitoring_COMPLETO`) le
descrive una per una; qui c'e' l'HTML, i numeri arrivano da `ai_dati`.

Le quattro schede cliente hanno tre stati (§4.1):
  A · monitoraggio non attivo   → pannello con «contatta VerticalAI», niente self-service
  B · in attesa dei primi dati  → attivo, ma nessuna risposta completata ancora
  C · dati reali                → la dashboard

⚠️ Nessuna delle quattro fa self-service sul monitoraggio: l'unica eccezione,
voluta dal documento, sono i concorrenti — il cliente conosce il suo mercato
meglio di chiunque, quindi puo' aggiungerli e toglierli.
"""
from __future__ import annotations

import json

import ai_dati
from geo_audit import esc

_LUCCHETTO = ('<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
              'stroke-width="2" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2"/>'
              '<path d="M7 11V7a5 5 0 0110 0v4"/></svg>')
_CHEVRON = ('<svg class="chev" width="14" height="14" viewBox="0 0 24 24" fill="none" '
            'stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M9 18l6-6-6-6"/></svg>')
_FONTE = {"ai_suggested": ("AI", "badge--neutral"), "admin_added": ("TEAM", "badge--warning"),
          "client_added": ("TU", "badge--success"),
          "auto_generated": ("AUTO", "badge--neutral"), "manual": ("MANUALE", "badge--warning")}
_FREQ = (("weekly", "Settimanale"), ("monthly", "Mensile"), ("custom", "Personalizzata"))


def _badge_fonte(fonte: str) -> str:
    testo, cls = _FONTE.get(fonte, (fonte or "?", "badge--neutral"))
    return f'<span class="badge {cls}" style="font-size:9px;letter-spacing:.04em">{esc(testo)}</span>'


def _classe_pct(v: int) -> str:
    return "good" if v >= 50 else "warn" if v >= 25 else "critical"


def _vuoto(titolo: str, testo: str) -> str:
    return f'<div class="empty-state"><b>{esc(titolo)}</b><p>{testo}</p></div>'


# ── Stati A e B, comuni alle quattro schede ─────────────────────────────────

def stato_non_attivo(project: dict) -> str:
    dominio = esc(project.get("domain") or "")
    return (
        '<div class="card coming-soon-card" style="text-align:center;padding:44px 28px">'
        '<span class="badge badge--neutral"><span class="dot"></span>Non attivo</span>'
        f'<h2 style="margin:14px 0 8px">Il monitoraggio AI di {dominio} non è attivo</h2>'
        '<p class="card-sub" style="max-width:520px;margin:0 auto 18px">Per questo progetto il '
        'monitoraggio delle risposte di ChatGPT, Gemini, Perplexity e Claude è stato '
        'disattivato dal team. Se vuoi riattivarlo, scrivici: non serve nessuna configurazione '
        'da parte tua.</p>'
        '<a class="btn btn-primary" href="mailto:info@verticalai.it?subject='
        f'Monitoraggio%20AI%20per%20{dominio}">Contatta VerticalAI →</a>'
        '</div>')


def stato_in_attesa(project: dict, imp: dict, da_approvare: int = 0) -> str:
    dominio = esc(project.get("domain") or "")
    freq = dict(_FREQ).get(imp.get("schedule_frequency") or "weekly", "Settimanale").lower()
    if da_approvare:
        # ⚠️ e' la ragione vera per cui non ci sono dati: dirla evita che il
        # cliente aspetti qualcosa che senza un'azione del team non arriva
        motivo = (f'Le {da_approvare} domande su cui misurare la visibilità sono state '
                  'preparate e sono <b>in revisione dal team VerticalAI</b>: il primo giro parte '
                  'appena approvate.')
    else:
        motivo = ('Il primo giro di domande ai quattro assistenti è in coda e parte al '
                  'prossimo passaggio automatico, di norma <b>entro 24 ore</b>.')
    return (
        '<div class="card" style="text-align:center;padding:44px 28px">'
        '<div class="ring-wrap" style="margin:0 auto 14px;width:56px;height:56px">'
        '<svg viewBox="0 0 36 36" width="56" height="56" aria-hidden="true">'
        '<circle cx="18" cy="18" r="15.5" fill="none" stroke="var(--bg-surface-raised)" stroke-width="3"/>'
        '<circle cx="18" cy="18" r="15.5" fill="none" stroke="var(--accent-primary)" stroke-width="3" '
        'stroke-dasharray="30 70" stroke-linecap="round">'
        '<animateTransform attributeName="transform" type="rotate" from="0 18 18" to="360 18 18" '
        'dur="1.6s" repeatCount="indefinite"/></circle></svg></div>'
        f'<h2 style="margin:0 0 8px">In attesa dei primi dati per {dominio}</h2>'
        f'<p class="card-sub" style="max-width:560px;margin:0 auto 6px">{motivo}</p>'
        f'<p class="card-sub" style="max-width:560px;margin:0 auto">Poi il monitoraggio si ripete '
        f'con frequenza {esc(freq)}, e qui compaiono punteggio, andamento e confronto con i '
        'concorrenti.</p></div>')


# ── AI Visibility ───────────────────────────────────────────────────────────

def _gauge(punteggio: int) -> str:
    # 204 e' la lunghezza del semicerchio (pi greco per il raggio 65): l'arco
    # pieno deve essere il punteggio per cento di quella lunghezza.
    offset = round(204 * (1 - max(0, min(100, punteggio)) / 100))
    return (
        '<div class="gauge-wrap"><svg viewBox="0 0 150 90" width="150" height="90" aria-hidden="true">'
        '<defs><linearGradient id="gaugeGrad" x1="0%" y1="0%" x2="100%" y2="0%">'
        '<stop offset="0%" stop-color="var(--state-critical)"/>'
        '<stop offset="55%" stop-color="var(--state-warn)"/>'
        '<stop offset="100%" stop-color="var(--state-good)"/></linearGradient></defs>'
        '<path d="M 10 85 A 65 65 0 0 1 140 85" fill="none" stroke="var(--bg-surface-raised)" '
        'stroke-width="14" stroke-linecap="round"/>'
        '<path d="M 10 85 A 65 65 0 0 1 140 85" fill="none" stroke="url(#gaugeGrad)" '
        f'stroke-width="14" stroke-linecap="round" stroke-dasharray="204" stroke-dashoffset="{offset}"/>'
        '</svg><div class="gauge-center"><div class="gauge-score">'
        f'{punteggio}<span class="gauge-max">/100</span></div></div></div>')


def _grafico_trend(trend: list, dominio: str) -> str:
    """La linea del progetto. Le linee «miglior competitor» e «media di settore»
    del prototipo restano bloccate col lucchetto (decisione del documento §5)."""
    if len(trend) < 2:
        grafico = ('<div class="chart-empty">Serve più di un giro per disegnare '
                   'l’andamento: la prima fotografia è '
                   f'{esc(trend[0]["quando"]) if trend else "in arrivo"}.</div>')
    else:
        n = len(trend)
        punti = " ".join(f"{round(i * 600 / (n - 1))},{round(125 - t['valore'] * 1.15)}"
                         for i, t in enumerate(trend))
        cerchi = "".join(
            f'<circle cx="{round(i * 600 / (n - 1))}" cy="{round(125 - t["valore"] * 1.15)}" r="4" '
            f'fill="var(--accent-primary)"><title>{esc(t["quando"])}: {t["valore"]}</title></circle>'
            for i, t in enumerate(trend))
        grafico = ('<div class="chart"><svg viewBox="-6 0 612 130" preserveAspectRatio="none" '
                   'aria-label="Andamento della visibilità">'
                   '<line x1="0" y1="125" x2="600" y2="125" stroke="var(--border-subtle)"/>'
                   f'<polyline points="{punti}" fill="none" stroke="var(--accent-primary)" stroke-width="2.5"/>'
                   f'{cerchi}</svg></div>')
    return (
        f'{grafico}'
        '<div class="chart-legend">'
        f'<div class="legend-item"><span class="legend-dot" style="background:var(--accent-primary)"></span>{esc(dominio)}</div>'
        '<div class="legend-item" style="opacity:.55;cursor:not-allowed" '
        'title="Il confronto con i concorrenti nel grafico arriva con i prossimi giri: serve uno storico anche per loro">'
        f'<span class="legend-dot" style="background:var(--text-muted)"></span>Confronto competitor {_LUCCHETTO}</div>'
        '</div>')


def tab_ai_visibility(project: dict, d: dict) -> str:
    dominio = project.get("domain") or ""
    p = d["punteggio"]
    etichetta, cls = ai_dati.fascia(p)
    if d["delta"] is None:
        nota = f'Calcolato su {d["risposte"]} risposte dei quattro assistenti negli ultimi 30 giorni.'
    else:
        segno = "+" if d["delta"] > 0 else ""
        nota = (f'{segno}{d["delta"]} punti rispetto al giro precedente'
                + (f', su {d["domande_contate"]} domande comuni a tutti i motori.' if d["domande_contate"] else '.'))

    motori = "".join(
        f'<div class="engine-row"><div class="engine-name"><span class="legend-dot" '
        f'style="background:{m["colore"]};margin-right:6px"></span>{esc(m["nome"])}</div>'
        f'<div class="area-track"><div class="area-fill" style="--w:{m["percentuale"]}%;background:{m["colore"]}"></div></div>'
        f'<div class="area-value" title="{m["citati"]} risposte su {m["risposte"]}">{m["percentuale"]}%</div></div>'
        for m in d["motori"])

    if d["argomenti"]:
        righe = "".join(
            f'<tr><td class="topic-name">{esc(a["nome"])}</td>'
            f'<td><span class="score-cell {_classe_pct(a["percentuale"])}">{a["percentuale"]}%</span></td>'
            f'<td><span class="issue-count">{a["risposte"]}</span></td></tr>'
            for a in d["argomenti"])
        tabella = ('<div class="table-scroll"><table class="data-grid"><thead><tr>'
                   '<th>Argomento</th><th>Visibilità</th><th>Risposte analizzate</th>'
                   f'</tr></thead><tbody>{righe}</tbody></table></div>')
    else:
        tabella = _vuoto("Nessun argomento ancora", "Compaiono dopo il primo giro.")

    return (
        '<div class="hero-row"><div class="hero-card">'
        f'{_gauge(p or 0)}'
        f'<div class="gauge-label {cls}">{esc(etichetta)}</div>'
        f'<div class="hero-note">{nota}</div></div>'
        '<div class="card"><div class="hero-side-top"><div class="hero-side-title">Andamento visibilità</div></div>'
        f'{_grafico_trend(d["trend"], dominio)}</div></div>'
        '<div class="data-card"><div class="section-header"><div class="section-title">Distribuzione per motore AI</div>'
        '<div class="card-desc">In quante risposte di ciascun assistente il sito compare come fonte</div></div>'
        f'<div style="padding:8px 20px 16px">{motori}</div></div>'
        '<div class="data-card"><div class="section-header"><div class="section-title">Argomenti monitorati</div>'
        '<div class="card-desc">Su quali temi il sito viene citato di più</div></div>'
        f'{tabella}</div>')


# ── Prompts & Queries ───────────────────────────────────────────────────────

def _barra_intent(intent: dict) -> str:
    tot = sum(intent.values()) or 1
    colori = {"informativo": "var(--accent-primary)", "transazionale": "var(--state-good)",
              "comparativo": "var(--state-warn)", "navigazionale": "var(--text-muted)"}
    pezzi = "".join(
        f'<span title="{esc(k)}: {v}" style="display:inline-block;height:6px;width:{round(v * 100 / tot)}%;'
        f'background:{colori.get(k, "var(--text-muted)")}"></span>'
        for k, v in sorted(intent.items(), key=lambda kv: -kv[1]))
    return f'<div style="display:flex;gap:2px;border-radius:3px;overflow:hidden;min-width:90px">{pezzi}</div>'


def _dettaglio_esempio(es: dict | None, testo_domanda: str) -> str:
    if not es:
        return '<p class="card-desc">Nessuna risposta ancora per questa domanda.</p>'
    nome = ai_dati.PROVIDER_NOME.get(es.get("provider") or "", es.get("provider") or "")
    stato = ('<span class="badge badge--success">sito citato</span>' if es.get("citato")
             else '<span class="badge badge--neutral">sito non citato</span>')
    return (f'<div class="detail-text" style="margin-bottom:6px"><b>Domanda</b> — {esc(testo_domanda)}</div>'
            f'<div class="detail-text"><b>Risposta di {esc(nome)}</b> {stato}</div>'
            f'<p class="card-desc" style="white-space:pre-wrap;margin-top:6px">{esc(es.get("testo") or "")}'
            + ("…" if len(es.get("testo") or "") >= 900 else "") + '</p>')


def tab_prompts(project: dict, d: dict) -> str:
    righe_arg = ""
    for a in d["argomenti"]:
        prompt_del_topic = [p for p in d["prompt"] if p["topic_id"] == a["topic_id"]]
        es = next((p["esempio"] for p in prompt_del_topic if p["esempio"] and p["esempio"].get("citato")), None) \
            or next((p["esempio"] for p in prompt_del_topic if p["esempio"]), None)
        testo = prompt_del_topic[0]["testo"] if prompt_del_topic else ""
        righe_arg += (
            f'<tr class="riga-apri" data-apri="arg-{esc(a["topic_id"])}" style="cursor:pointer">'
            f'<td class="topic-name">{_CHEVRON} {esc(a["nome"])} <span class="url-type">{a["domande"]} {"domanda" if a["domande"] == 1 else "domande"}</span></td>'
            f'<td><span class="score-cell {_classe_pct(a["percentuale"])}">{a["percentuale"]}%</span></td>'
            f'<td><span class="issue-count">{a["menzioni"]}</span></td>'
            f'<td><span class="issue-count">{a["volume"]}</span></td>'
            f'<td>{_barra_intent(a["intent"])}</td></tr>'
            f'<tr id="arg-{esc(a["topic_id"])}" hidden><td colspan="5" style="background:var(--bg-surface-raised)">'
            f'{_dettaglio_esempio(es, testo)}</td></tr>')

    righe_pr = ""
    for p in d["prompt"]:
        if not p["attiva"]:
            continue
        righe_pr += (
            f'<tr class="riga-apri" data-apri="pr-{esc(p["id"])}" style="cursor:pointer">'
            f'<td class="topic-name">{_CHEVRON} {esc(p["testo"])}</td>'
            f'<td><span class="url-type">{esc(p["intent"] or "—")}</span></td>'
            f'<td><span class="score-cell {_classe_pct(p["percentuale"])}">{p["percentuale"]}%</span></td>'
            f'<td><span class="issue-count">{p["menzioni"]}</span></td>'
            f'<td><span class="issue-count">{p["volume"]}</span></td></tr>'
            f'<tr id="pr-{esc(p["id"])}" hidden><td colspan="5" style="background:var(--bg-surface-raised)">'
            f'{_dettaglio_esempio(p["esempio"], p["testo"])}</td></tr>')

    if not d["prompt"]:
        return _vuoto("Nessuna domanda monitorata", "Le domande vengono preparate dal team dopo l’attivazione.")

    js = """<script>
(function(){
  document.querySelectorAll('.riga-apri').forEach(function(r){
    r.addEventListener('click', function(){
      var det = document.getElementById(r.dataset.apri);
      if(!det) return;
      det.hidden = !det.hidden;
      var c = r.querySelector('.chev'); if(c) c.style.transform = det.hidden ? '' : 'rotate(90deg)';
    });
  });
  var vt = document.querySelectorAll('[data-vista]');
  vt.forEach(function(b){ b.addEventListener('click', function(){
    vt.forEach(function(x){ x.classList.toggle('active', x === b); });
    document.getElementById('vista-argomenti').hidden = b.dataset.vista !== 'argomenti';
    document.getElementById('vista-prompt').hidden = b.dataset.vista !== 'prompt';
  });});
})();
</script>"""
    return (
        '<div class="data-card"><div class="section-header" style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap">'
        '<div><div class="section-title">Cosa chiediamo agli assistenti</div>'
        '<div class="card-desc">Domande <b>non di marca</b>, quelle che un cliente farebbe prima di conoscervi. '
        'Sono scelte e riviste dal team VerticalAI.</div></div>'
        '<div class="range-toggle">'
        f'<button type="button" class="range-btn active" data-vista="argomenti">Argomenti <span class="issue-count">{d["n_argomenti"]}</span></button>'
        f'<button type="button" class="range-btn" data-vista="prompt">Prompt <span class="issue-count">{d["n_prompt"]}</span></button>'
        '</div></div>'
        '<div id="vista-argomenti"><div class="table-scroll"><table class="data-grid"><thead><tr>'
        '<th>Argomento</th><th>Visibilità</th><th>Tue menzioni</th><th>Risposte analizzate</th><th>Intento</th>'
        f'</tr></thead><tbody>{righe_arg}</tbody></table></div></div>'
        '<div id="vista-prompt" hidden><div class="table-scroll"><table class="data-grid"><thead><tr>'
        '<th>Prompt</th><th>Intento</th><th>Visibilità</th><th>Tue menzioni</th><th>Risposte analizzate</th>'
        f'</tr></thead><tbody>{righe_pr}</tbody></table></div></div>'
        '</div>' + js)


# ── Competitors ─────────────────────────────────────────────────────────────

def tab_competitors(project: dict, d: dict) -> str:
    pid = esc(project.get("id") or "")
    chips = ""
    for r in d["righe"]:
        if r["tuo"]:
            chips += (f'<span class="filter-chip active" style="cursor:default">{esc(r["dominio"])} '
                      '<span class="badge badge--neutral" style="font-size:9px">tu</span></span>')
        else:
            chips += (f'<span class="filter-chip" style="cursor:default;display:inline-flex;align-items:center;gap:6px">'
                      f'{esc(r["dominio"])} {_badge_fonte(r["fonte"])}'
                      # ⚠️ non `row-action`: quella classe e' invisibile finche' non si
                      # passa col mouse su una RIGA di tabella, e questi sono chip —
                      # il bottone non compariva mai (trovato dallo screenshot)
                      f'<button type="button" data-rimuovi="{esc(r["dominio"])}" '
                      f'title="Rimuovi {esc(r["dominio"])}" aria-label="Rimuovi {esc(r["dominio"])}" '
                      'style="border:none;background:none;cursor:pointer;color:var(--text-muted);padding:0 2px;font-size:14px;line-height:1">×</button></span>')
    # ⚠️ niente `display` inline sull'elemento nascosto: vincerebbe su
    # [hidden] e il modulo comparirebbe sempre. I figli sono inline per natura.
    chips += ('<span class="filter-chip" id="chip-aggiungi" style="cursor:pointer" role="button" tabindex="0">+ Aggiungi competitor</span>'
              '<span id="campo-aggiungi" hidden>'
              '<input class="form-input" id="nuovo-competitor" placeholder="dominio.it" style="width:190px;padding:6px 10px;margin-right:6px" autocomplete="off">'
              '<button type="button" class="btn btn-primary" id="conferma-aggiungi" style="padding:6px 10px;margin-right:6px">Aggiungi</button>'
              '<button type="button" class="btn" id="annulla-aggiungi" style="padding:6px 10px">Annulla</button></span>')

    insight = "".join(f'<li class="detail-text" style="margin:4px 0">{esc(t)}</li>' for t in d["insight"])

    # confronto a barre: share of voice, la riga del cliente evidenziata
    massimo = max((r["sov"] for r in d["righe"]), default=0) or 1
    barre = "".join(
        f'<div class="engine-row"><div class="engine-name" style="{"font-weight:600" if r["tuo"] else ""}">{esc(r["dominio"])}</div>'
        f'<div class="area-track"><div class="area-fill" style="--w:{round(r["sov"] * 100 / massimo)}%;'
        f'background:{"var(--accent-primary)" if r["tuo"] else "var(--text-muted)"}"></div></div>'
        f'<div class="area-value">{r["sov"]}%</div></div>'
        for r in d["righe"][:12])

    righe = "".join(
        f'<tr><td class="check-name">{esc(r["dominio"])}'
        + (' <span class="badge badge--neutral">tu</span>' if r["tuo"] else f' {_badge_fonte(r["fonte"])}') + '</td>'
        f'<td><span class="score-cell {_classe_pct(r["sov"])}">{r["sov"]}%</span></td>'
        f'<td><span class="url-type">{esc(r["sentiment"] or "—")}</span></td>'
        f'<td><span class="issue-count">{r["menzioni"]}</span></td></tr>'
        for r in d["righe"])

    js = """<script>
(function(){
  var PID = %s;
  function manda(url, corpo){
    return fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(corpo)})
      .then(function(r){ if(!r.ok) throw new Error('HTTP '+r.status); location.reload(); })
      .catch(function(){ alert('Non sono riuscito a salvare: riprova fra poco.'); });
  }
  document.querySelectorAll('[data-rimuovi]').forEach(function(b){
    b.addEventListener('click', function(){
      if(confirm('Togliere ' + b.dataset.rimuovi + ' dai concorrenti monitorati?'))
        manda('/project/' + PID + '/competitors/rimuovi', {dominio: b.dataset.rimuovi});
    });
  });
  var chip = document.getElementById('chip-aggiungi'), campo = document.getElementById('campo-aggiungi');
  function apri(){ chip.hidden = true; campo.hidden = false; document.getElementById('nuovo-competitor').focus(); }
  chip.addEventListener('click', apri);
  chip.addEventListener('keydown', function(e){ if(e.key==='Enter'||e.key===' ') apri(); });
  document.getElementById('annulla-aggiungi').addEventListener('click', function(){ campo.hidden = true; chip.hidden = false; });
  function conferma(){
    var v = document.getElementById('nuovo-competitor').value.trim();
    if(v) manda('/project/' + PID + '/competitors/aggiungi', {dominio: v});
  }
  document.getElementById('conferma-aggiungi').addEventListener('click', conferma);
  document.getElementById('nuovo-competitor').addEventListener('keydown', function(e){ if(e.key==='Enter') conferma(); });
})();
</script>""" % json.dumps(project.get("id") or "")

    return (
        '<div class="data-card"><div class="section-header"><div class="section-title">Concorrenti monitorati</div>'
        '<div class="card-desc">Proposti dal motore in base a chi compare nelle risposte, integrati dal team e da te. '
        'Puoi aggiungerne o toglierne: il tuo mercato lo conosci tu.</div></div>'
        f'<div class="filter-bar" style="padding:12px 20px 16px;flex-wrap:wrap;gap:8px">{chips}</div></div>'
        '<div class="data-card"><div class="section-header"><div class="section-title">Cosa emerge</div></div>'
        f'<ul style="padding:10px 20px 14px 36px;margin:0">{insight}</ul></div>'
        '<div class="data-card"><div class="section-header"><div class="section-title">Share of voice</div>'
        f'<div class="card-desc">In quante delle {d["risposte"]} risposte analizzate compare ciascun sito</div></div>'
        f'<div style="padding:8px 20px 16px">{barre}</div></div>'
        '<div class="data-card"><div class="section-header"><div class="section-title">Confronto dettagliato</div></div>'
        '<div class="table-scroll"><table class="data-grid"><thead><tr>'
        '<th>Dominio</th><th>Share of voice</th><th>Sentiment</th><th>Risposte in cui compare</th>'
        f'</tr></thead><tbody>{righe}</tbody></table></div></div>' + js)


# ── Citations ───────────────────────────────────────────────────────────────

def tab_citations(project: dict, d: dict) -> str:
    sent = d["sentiment"] or "—"
    cls_sent = {"positivo": "good", "negativo": "critical"}.get(d["sentiment"], "")
    kpi = (
        '<div class="kpi-strip">'
        '<div class="kpi"><div class="kpi-top"><span class="kpi-label">Citazioni dirette (30gg)</span></div>'
        f'<div class="kpi-value">{d["dirette"]}</div><div class="kpi-sub">in {d["citate_in"]} risposte su {d["risposte"]}</div></div>'
        '<div class="kpi"><div class="kpi-top"><span class="kpi-label">Pagine citate</span></div>'
        f'<div class="kpi-value">{d["n_pagine"]}</div><div class="kpi-sub">pagine diverse indicate come fonte</div></div>'
        '<div class="kpi"><div class="kpi-top"><span class="kpi-label">Argomenti coperti</span></div>'
        f'<div class="kpi-value">{len([a for a in d["argomenti"] if a["citati"]])}</div>'
        f'<div class="kpi-sub">su {len(d["argomenti"])} monitorati</div></div>'
        '<div class="kpi"><div class="kpi-top"><span class="kpi-label">Sentiment medio</span></div>'
        f'<div class="kpi-value {cls_sent}">{esc(sent)}</div>'
        f'<div class="kpi-sub">{"su " + str(d["voti"]) + " menzioni" if d["voti"] else "non ancora valutato"}</div></div>'
        '</div>')

    if d["pagine"]:
        righe_p = "".join(
            f'<tr><td class="url-main">{esc(p["pagina"])}</td>'
            f'<td><span class="issue-count">{p["n"]}</span></td>'
            f'<td class="detail-text">{esc(", ".join(p["motori"]))}</td></tr>'
            for p in d["pagine"])
        tab_pagine = ('<div class="table-scroll"><table class="data-grid"><thead><tr>'
                      '<th>Pagina</th><th>Citazioni</th><th>Da quali assistenti</th>'
                      f'</tr></thead><tbody>{righe_p}</tbody></table></div>')
    else:
        tab_pagine = _vuoto("Nessuna citazione diretta negli ultimi 30 giorni",
                            "Nessun assistente ha indicato una pagina del sito come fonte. "
                            "Gli argomenti qui sotto dicono dove il sito è assente.")

    righe_a = "".join(
        f'<tr><td class="topic-name">{esc(a["nome"])}</td>'
        f'<td><span class="issue-count">{a["citati"]}</span> <span class="url-type">su {a["risposte"]}</span></td>'
        f'<td><span class="score-cell {_classe_pct(a["percentuale"])}">{a["percentuale"]}%</span></td></tr>'
        for a in d["argomenti"])

    return (
        kpi +
        '<div class="data-card"><div class="section-header"><div class="section-title">Citazioni dirette del sito</div>'
        '<div class="card-desc">Quando un assistente indica una vostra pagina come fonte della risposta</div></div>'
        f'{tab_pagine}</div>'
        '<div class="data-card"><div class="section-header"><div class="section-title">Argomenti di discussione</div>'
        '<div class="card-desc">Su quali temi il sito viene citato e su quali resta fuori: '
        'è la mappa di dove lavorare</div></div>'
        '<div class="table-scroll"><table class="data-grid"><thead><tr>'
        '<th>Argomento</th><th>Risposte con citazione</th><th>Copertura</th>'
        f'</tr></thead><tbody>{righe_a}</tbody></table></div></div>')


# ── Le schede cliente, con i tre stati ──────────────────────────────────────

def scheda_cliente(tab: str, project: dict) -> str:
    """Il punto d'ingresso unico per le quattro schede: decide lo stato e rende."""
    from db import _sb_ai_impostazioni, _sb_ai_domande_da_approvare
    pid = project["id"]
    st = ai_dati.stato(pid)
    if st == "non_attivo":
        return stato_non_attivo(project)
    if st == "in_attesa":
        return stato_in_attesa(project, _sb_ai_impostazioni(pid),
                               len(_sb_ai_domande_da_approvare(pid)))
    if tab == "ai-visibility":
        return tab_ai_visibility(project, ai_dati.visibilita(pid))
    if tab == "prompts":
        return tab_prompts(project, ai_dati.prompt_e_argomenti(pid))
    if tab == "competitors":
        return tab_competitors(project, ai_dati.concorrenti(pid, project.get("domain") or ""))
    if tab == "citations":
        return tab_citations(project, ai_dati.citazioni(pid))
    return ""


# ═══════════════════════════════════════════════════════════════ ADMIN
# ⚠️ Il pannello NON carica il CSS del prodotto: qui si usano solo le classi
# `ai-*` definite in `templates/admin.html` piu' quelle native dell'admin
# (`btn`, `pill`, `avviso`). La prima versione usava `card`, `alert-row`,
# `toggle-switch`: nel pannello non esistono, e la pagina usciva senza stile —
# trovato dagli screenshot, non dai test funzionali.

_PROVIDER_CARD = (
    ("openai", "OpenAI", "ChatGPT", "#10A37F", "O"),
    ("anthropic", "Anthropic", "Claude", "#D97757", "A"),
    ("gemini", "Google", "Gemini", "#4285F4", "G"),
    ("perplexity", "Perplexity", "Sonar", "#20808D", "P"),
)
_TAG = {"ai_suggested": ("AI", "auto"), "admin_added": ("TEAM", "manual"),
        "client_added": ("CLIENTE", "cliente"),
        "auto_generated": ("AUTO", "auto"), "manual": ("MANUALE", "manual")}


def _tag(fonte: str) -> str:
    testo, cls = _TAG.get(fonte, (fonte or "?", "auto"))
    return f'<span class="ai-tag {cls}">{esc(testo)}</span>'


def _toggle(campo: str, acceso: bool, etichetta: str, grande: bool = False) -> str:
    return (f'<button type="button" class="ai-toggle{" on" if acceso else ""}{" grande" if grande else ""}" '
            f'data-imp="{campo}" aria-pressed="{"true" if acceso else "false"}" aria-label="{esc(etichetta)}"></button>')


def admin_configurazione_ai(config: dict, modelli: dict, cifratura_ok: bool,
                            mascherate: dict) -> str:
    """Pagina globale: chiavi e modello di default per i quattro provider.

    `config` = {provider: riga}, `modelli` = {provider: [righe]},
    `mascherate` = {provider: 'sk-…a83f'} gia' pronte (la decifratura sta in
    `ai_chiavi`, non qui: questa funzione non vede mai una chiave in chiaro).
    """
    if not cifratura_ok:
        avviso = ('<div class="avviso"><div>\U0001f512</div><div><b>Le chiavi non si possono salvare.</b> '
                  'Manca la variabile <code>CHIAVE_CIFRATURA</code> sul server: senza, il prodotto non '
                  'pu\u00f2 custodire una chiave in modo sicuro, e piuttosto che salvarla in chiaro non la '
                  'salva. Va impostata su Vercel.</div></div>')
    else:
        avviso = ('<div class="avviso"><div>\U0001f512</div><div><b>Solo admin.</b> Le chiavi sono '
                  'cifrate a riposo e non vengono mai mostrate per intero: qui vedi solo gli ultimi '
                  'caratteri di ciascuna chiave gi\u00e0 salvata. Una chiave viene provata sul provider '
                  'prima di essere salvata.</div></div>')

    cards = ""
    for pid, nome, sotto, colore, lettera in _PROVIDER_CARD:
        c = config.get(pid) or {}
        ha_chiave = bool(mascherate.get(pid))
        lista = modelli.get(pid) or []
        modello = c.get("default_model") or ""
        stato = ('<span class="pill ok">Configurato</span>' if ha_chiave
                 else '<span class="pill bad">Non configurato</span>')
        if lista:
            opzioni = "".join(
                f'<option value="{esc(m["model_id"])}"{" selected" if m["model_id"] == modello else ""}>'
                f'{esc(m["model_id"])}{"" if m.get("supports_web_search") else " \u2014 senza ricerca web"}</option>'
                for m in lista)
            select = f'<select class="ai-select" data-modello="{pid}" style="width:100%">{opzioni}</select>'
            nota_web = ('<div class="ai-nota ok">\u2713 Un modello senza ricerca web risponde a memoria e '
                        'non cita nessuno: darebbe zero per sempre. Scegli uno senza la nota.</div>')
            ultimo = lista[0].get("fetched_at") or ""
            info_lista = f'Lista aggiornata il {esc(ultimo[:10])}' if ultimo else 'Lista disponibile'
        else:
            select = ('<select class="ai-select" disabled style="width:100%"><option>'
                      + ('\u2014 Aggiorna la lista dei modelli \u2014' if ha_chiave else '\u2014 Salva prima la chiave API \u2014')
                      + '</option></select>')
            nota_web = ""
            info_lista = "Nessuna lista disponibile"
        cards += (
            '<div class="ai-card" style="margin:0"><div class="ai-card-corpo">'
            '<div style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:16px">'
            f'<div style="display:flex;align-items:center;gap:11px"><div class="ai-logo" style="background:{colore}">{lettera}</div>'
            f'<div><div class="ai-titolo">{esc(nome)}</div><div class="ai-sotto">{esc(sotto)}</div></div></div>{stato}</div>'
            '<label class="ai-etichetta">Chiave API</label>'
            '<div style="display:flex;gap:8px;margin-bottom:14px">'
            f'<input class="ai-input mono" type="password" data-chiave="{pid}" autocomplete="off" '
            f'placeholder="{esc(mascherate.get(pid) or "Incolla la chiave API…")}" style="flex:1;min-width:0"'
            f'{"" if cifratura_ok else " disabled"}>'
            f'<button type="button" class="btn ai-btn-primary" data-salva-chiave="{pid}"{"" if cifratura_ok else " disabled"}>'
            f'{"Aggiorna" if ha_chiave else "Salva"}</button></div>'
            '<label class="ai-etichetta">Modello di default (monitoraggio)</label>'
            f'{select}{nota_web}'
            '<div style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:14px;padding-top:14px;border-top:1px solid var(--border-subtle)">'
            f'<span class="ai-nota" style="margin:0" data-info-lista="{pid}">{info_lista}</span>'
            f'<button type="button" class="btn" data-aggiorna-modelli="{pid}"{"" if ha_chiave else " disabled"}>\u21bb Aggiorna lista modelli</button>'
            '</div></div></div>')

    js = """<script>
(function(){
  function manda(url, corpo, bottone, poi){
    var t = bottone ? bottone.textContent : '';
    if(bottone){ bottone.disabled = true; bottone.textContent = 'Salvo…'; }
    fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(corpo)})
      .then(function(r){ return r.json().then(function(j){ return {ok: r.ok, j: j}; }); })
      .then(function(x){
        if(!x.ok){ throw new Error(x.j && x.j.esito || 'errore'); }
        if(poi) poi(x.j); else location.reload();
      })
      .catch(function(e){ alert('Non sono riuscito: ' + e.message); if(bottone){ bottone.disabled=false; bottone.textContent=t; } });
  }
  document.querySelectorAll('[data-salva-chiave]').forEach(function(b){
    b.addEventListener('click', function(){
      var p = b.dataset.salvaChiave, inp = document.querySelector('[data-chiave="'+p+'"]');
      var v = (inp.value||'').trim(); if(!v){ inp.focus(); return; }
      manda('/admin/ai/chiave', {provider: p, chiave: v}, b);
    });
  });
  document.querySelectorAll('[data-modello]').forEach(function(s){
    s.addEventListener('change', function(){ manda('/admin/ai/modello', {provider: s.dataset.modello, modello: s.value}, null, function(){}); });
  });
  document.querySelectorAll('[data-aggiorna-modelli]').forEach(function(b){
    b.addEventListener('click', function(){ manda('/admin/ai/modelli-aggiorna', {provider: b.dataset.aggiornaModelli}, b); });
  });
})();
</script>"""
    return avviso + f'<div class="ai-griglia" style="margin-top:18px">{cards}</div>' + js


def admin_monitoraggio_progetto(project: dict, cliente: dict, imp: dict, dati: dict,
                                concorrenti: list, sov: dict, giro_in_corso: bool = False) -> str:
    """Per singolo progetto: impostazioni, domande (con approvazione), concorrenti."""
    dominio = esc(project.get("domain") or "")
    attivo = imp.get("is_active", True) is not False
    freq = imp.get("schedule_frequency") or "weekly"
    ultimo = (imp.get("last_run_at") or "")[:16].replace("T", " ")
    attive = [p for p in dati["prompt"] if p["attiva"]]
    n_auto = len([p for p in attive if p["fonte"] == "auto_generated"])
    da_appr = dati["da_approvare"]

    testata = (
        f'<div class="ai-briciole"><a href="/admin/clienti">Clienti</a> / '
        f'<a href="/admin/clienti/{esc(cliente.get("id") or "")}">{esc(cliente.get("email") or dominio)}</a> / Monitoraggio AI</div>'
        '<div class="ai-card"><div class="ai-card-corpo" style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:14px">'
        f'<div><div class="ai-titolo" style="font-size:18px">Monitoraggio AI \u2014 {dominio}</div>'
        f'<div class="ai-sotto">{len(attive)} domande attive \u00b7 '
        + (f'ultimo giro completo {esc(ultimo)}' if ultimo else 'nessun giro completo ancora') + '</div></div>'
        '<div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">'
        '<button type="button" class="btn" data-giro="1" title="Mette il progetto in testa alla coda: il giro parte al prossimo passaggio automatico, entro un\u2019ora">\u25b6 Esegui un giro adesso</button>'
        '<span style="display:flex;align-items:center;gap:10px;font-weight:600;font-size:13px">Monitoraggio attivo '
        f'{_toggle("is_active", attivo, "Monitoraggio attivo", grande=True)}</span>'
        '</div></div></div>')

    opz = "".join(f'<option value="{k}"{" selected" if k == freq else ""}>{n}</option>' for k, n in _FREQ)
    impostazioni = (
        '<div class="ai-card"><div class="ai-card-testa"><div class="ai-titolo">Impostazioni</div></div>'
        '<div class="ai-riga"><div class="ai-riga-info"><b>Frequenza esecuzione</b><p>Ogni quanto si ripete il giro di domande ai quattro assistenti</p></div>'
        f'<select class="ai-select" data-imp="schedule_frequency">{opz}</select></div>'
        '<div class="ai-riga"><div class="ai-riga-info"><b>Analisi sentiment</b><p>Classifica il tono di ogni menzione del sito (positivo, neutro, negativo). Costa una chiamata in pi\u00f9 per risposta citata.</p></div>'
        f'{_toggle("sentiment_enabled", bool(imp.get("sentiment_enabled", True)), "Analisi sentiment")}</div>'
        '</div>')

    righe = ""
    for p in attive:
        appr = '' if p["approvata"] is not False else ' <span class="ai-tag attesa">DA APPROVARE</span>'
        righe += (
            f'<div class="ai-riga" data-riga-prompt="{esc(p["id"])}">'
            f'<span class="ai-argomento" title="{esc(p["argomento"])}">{esc(p["argomento"] or "\u2014")}</span>'
            f'<span class="ai-testo" data-testo>{esc(p["testo"])}</span>'
            f'{_tag(p["fonte"])}{appr}'
            '<span class="ai-azioni">'
            + (f'<button type="button" class="btn" data-approva="{esc(p["id"])}" style="padding:4px 9px;font-size:11.5px">Approva</button>'
               if p["approvata"] is False else '')
            + f'<button type="button" class="ai-icona" data-modifica="{esc(p["id"])}" title="Modifica" aria-label="Modifica">\u270e</button>'
              f'<button type="button" class="ai-icona pericolo" data-elimina="{esc(p["id"])}" title="Togli dal monitoraggio" aria-label="Togli dal monitoraggio">\u2715</button>'
            '</span></div>')
    if not righe:
        righe = '<div class="ai-vuoto"><b>Nessuna domanda</b>Genera le proposte o aggiungine una a mano.</div>'

    domande = (
        '<div class="ai-card"><div class="ai-card-testa">'
        f'<div><div class="ai-titolo">Domande monitorate</div><div class="ai-sotto">{len(attive)} attive \u00b7 {n_auto} generate, {len(attive) - n_auto} manuali'
        + (f' \u00b7 <b style="color:var(--state-warn)">{da_appr} da approvare</b>' if da_appr else '') + '</div></div>'
        '<div style="display:flex;gap:8px;flex-wrap:wrap">'
        + (f'<button type="button" class="btn ai-btn-primary" data-approva-tutte="1">\u2713 Approva le {da_appr} in attesa</button>' if da_appr else '')
        + '<button type="button" class="btn" data-rigenera="prompt" title="Aggiunge nuove proposte lette dal sito; non tocca quelle esistenti">\u21bb Genera proposte</button>'
          '<button type="button" class="btn" data-aggiungi-prompt="1">+ Aggiungi domanda</button></div></div>'
        '<div class="ai-modulo" id="nuovo-prompt" hidden>'
        '<input class="ai-input" id="np-argomento" placeholder="Argomento (es. selle da dressage)" style="width:220px">'
        '<input class="ai-input" id="np-testo" placeholder="La domanda, come la farebbe un cliente" style="flex:1;min-width:240px">'
        '<button type="button" class="btn ai-btn-primary" id="np-salva">Salva</button></div>'
        f'{righe}</div>')

    righe_c = ""
    for c in concorrenti:
        d = c["domain"]
        righe_c += (
            '<div class="ai-riga">'
            f'<span style="flex-shrink:0;min-width:180px;font-weight:600">{esc(d)}</span>'
            f'<span class="ai-testo">Share of voice {sov.get(d, 0)}%</span>'
            f'{_tag(c.get("source") or "")}'
            f'<span class="ai-azioni"><button type="button" class="ai-icona pericolo" data-rimuovi-comp="{esc(d)}" title="Rimuovi" aria-label="Rimuovi">\u2715</button></span></div>')
    if not righe_c:
        righe_c = '<div class="ai-vuoto"><b>Nessun concorrente</b>Si popolano da soli al primo giro, dai siti che ricorrono nelle risposte.</div>'
    per_fonte = {}
    for c in concorrenti:
        per_fonte[c.get("source")] = per_fonte.get(c.get("source"), 0) + 1
    comp = (
        '<div class="ai-card"><div class="ai-card-testa">'
        f'<div><div class="ai-titolo">Concorrenti monitorati</div><div class="ai-sotto">{len(concorrenti)} \u00b7 '
        f'{per_fonte.get("ai_suggested", 0)} proposti dal motore, {per_fonte.get("client_added", 0)} dal cliente, {per_fonte.get("admin_added", 0)} dal team</div></div>'
        '<div style="display:flex;gap:8px;flex-wrap:wrap">'
        '<button type="button" class="btn" data-rigenera="competitor" title="Ripropone i domini che ricorrono nelle risposte; non ripropone quelli esclusi">\u21bb Rigenera suggerimenti</button>'
        '<button type="button" class="btn" data-aggiungi-comp="1">+ Aggiungi concorrente</button></div></div>'
        '<div class="ai-modulo" id="nuovo-comp" hidden>'
        '<input class="ai-input" id="nc-dominio" placeholder="dominio.it" style="width:260px">'
        '<button type="button" class="btn ai-btn-primary" id="nc-salva">Salva</button></div>'
        f'{righe_c}</div>')

    js = """<script>
(function(){
  var BASE = '/admin/progetti/' + %s + '/ai';
  function manda(url, corpo, bottone){
    var t = bottone ? bottone.textContent : '';
    if(bottone){ bottone.disabled = true; bottone.textContent = '…'; }
    return fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(corpo)})
      .then(function(r){ if(!r.ok) throw new Error('HTTP ' + r.status); location.reload(); })
      .catch(function(e){ alert('Non sono riuscito: ' + e.message); if(bottone){ bottone.disabled=false; bottone.textContent=t; } });
  }
  document.querySelectorAll('.ai-toggle[data-imp]').forEach(function(b){
    b.addEventListener('click', function(){ manda(BASE + '/impostazioni', {campo: b.dataset.imp, valore: !b.classList.contains('on')}); });
  });
  document.querySelectorAll('select[data-imp]').forEach(function(s){
    s.addEventListener('change', function(){ manda(BASE + '/impostazioni', {campo: s.dataset.imp, valore: s.value}); });
  });
  var g = document.querySelector('[data-giro]'); if(g) g.addEventListener('click', function(){
    fetch(BASE + '/giro', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'})
      .then(function(r){ if(!r.ok) throw new Error('HTTP '+r.status); g.textContent = '\\u2713 In coda: parte entro un\\u2019ora'; g.disabled = true; })
      .catch(function(e){ alert('Non sono riuscito: ' + e.message); });
  });
  document.querySelectorAll('[data-approva]').forEach(function(b){ b.addEventListener('click', function(){ manda(BASE + '/prompt/approva', {ids: [b.dataset.approva]}, b); }); });
  var at = document.querySelector('[data-approva-tutte]'); if(at) at.addEventListener('click', function(){ manda(BASE + '/prompt/approva', {tutte: true}, at); });
  document.querySelectorAll('[data-elimina]').forEach(function(b){ b.addEventListener('click', function(){
    if(confirm('Togliere questa domanda dal monitoraggio? Lo storico resta.')) manda(BASE + '/prompt/elimina', {id: b.dataset.elimina}, b);
  }); });
  document.querySelectorAll('[data-modifica]').forEach(function(b){ b.addEventListener('click', function(){
    var riga = document.querySelector('[data-riga-prompt="' + b.dataset.modifica + '"]');
    var attuale = riga.querySelector('[data-testo]').textContent;
    var nuovo = prompt('Nuovo testo della domanda:', attuale);
    if(nuovo && nuovo.trim() && nuovo.trim() !== attuale) manda(BASE + '/prompt/modifica', {id: b.dataset.modifica, testo: nuovo.trim()}, b);
  }); });
  document.querySelectorAll('[data-rigenera]').forEach(function(b){ b.addEventListener('click', function(){
    manda(BASE + (b.dataset.rigenera === 'prompt' ? '/prompt/rigenera' : '/competitor/rigenera'), {}, b);
  }); });
  function mostra(id, campo){ var f = document.getElementById(id); f.hidden = !f.hidden; if(!f.hidden) document.getElementById(campo).focus(); }
  var ap = document.querySelector('[data-aggiungi-prompt]'); if(ap) ap.addEventListener('click', function(){ mostra('nuovo-prompt', 'np-argomento'); });
  var nps = document.getElementById('np-salva'); if(nps) nps.addEventListener('click', function(){
    var a = document.getElementById('np-argomento').value.trim(), t = document.getElementById('np-testo').value.trim();
    if(!t){ document.getElementById('np-testo').focus(); return; }
    manda(BASE + '/prompt/aggiungi', {argomento: a, testo: t}, nps);
  });
  var ac = document.querySelector('[data-aggiungi-comp]'); if(ac) ac.addEventListener('click', function(){ mostra('nuovo-comp', 'nc-dominio'); });
  var ncs = document.getElementById('nc-salva'); if(ncs) ncs.addEventListener('click', function(){
    var d = document.getElementById('nc-dominio').value.trim(); if(!d) return;
    manda(BASE + '/competitor/aggiungi', {dominio: d}, ncs);
  });
  document.querySelectorAll('[data-rimuovi-comp]').forEach(function(b){ b.addEventListener('click', function(){
    if(confirm('Togliere ' + b.dataset.rimuoviComp + '? Non verr\\u00e0 riproposto.')) manda(BASE + '/competitor/rimuovi', {dominio: b.dataset.rimuoviComp}, b);
  }); });
})();
</script>""" % json.dumps(project["id"])
    return testata + impostazioni + domande + comp + js
