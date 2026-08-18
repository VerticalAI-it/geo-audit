# 07 · Design system

> **Questo documento è una sintesi orientativa. La fonte di verità normativa è
> [`design_system/DESIGN_SYSTEM.md`](../design_system/DESIGN_SYSTEM.md), e la regola
> in [`CLAUDE.md`](../CLAUDE.md) è vincolante: ogni modifica a UX/UI deve
> rispettarla. Leggi quel file prima di toccare HTML, CSS o email.**

Riferimento visivo: [`design_system/ds_components/ds.html`](../design_system/ds_components/ds.html)
(1190 righe, showcase di tutti i componenti).

---

## Token

Definiti in [`static/css/design-system.css`](../static/css/design-system.css) —
581 righe, `:root` per il tema chiaro e `[data-theme="dark"]` per lo scuro.

### Colori

| Gruppo | Token |
|---|---|
| Brand viola | `--violet-50` → `--violet-950`, alias `--brand`, `--brand-hover`, `--brand-soft`, `--brand-text` |
| Teal (segnale dati) | `--teal-50` → `--teal-700` |
| Palette dati categorica | `--data-1` → `--data-7` (per i grafici) |
| Semantici | `--success`, `--warning`, `--danger`, `--info` (ognuno con `-bg` e `-border`) |
| Superfici | `--canvas`, `--surface`, `--surface-2`, `--surface-3`, `--overlay` |
| Bordi | `--border`, `--border-strong` |
| Testi | `--ink`, `--text`, `--text-2`, `--text-3`, `--text-on-brand` |

### Altri token

- **Spaziatura** base 4px: `--sp-1` (4px) → `--sp-24` (96px)
- **Raggi**: `--r-sm` 6px · `--r-md` 10px · `--r-lg` 14px · `--r-xl` 20px · `--r-2xl` 28px · `--r-pill`
- **Ombre**: `--sh-xs` → `--sh-lg`, più `--sh-brand` (glow viola per le CTA)
- **Motion**: `--t-fast` 120ms · `--t-base` 200ms · `--t-slow` 320ms, con `--ease-out`

### Mappatura dai token legacy

Nel codice più vecchio si trovano ancora i nomi della prima versione. **Usa sempre
la colonna di destra:**

| Legacy | Token DS | Valore dark |
|---|---|---|
| `--bg: #0B0B16` | `--canvas` | `#0B0A12` |
| `--card: #17152A` | `--surface` | `#131220` |
| `--line: #2A2640` | `--border` | `#272636` |
| `--violet: #6C5CE7` | `--brand` | `#7C6BEC` |
| `--vbright: #9B8CFF` | `--brand-text` / `--brand-hover` | `#B3A8F7` |
| `--text: #F2F1F8` | `--text` / `--ink` | `#F4F3F8` |
| `--muted: #9C99B5` | `--text-2` | `#BCBBCB` |

---

## Tipografia

| Ruolo | Font | Variabile | Sostituisce |
|---|---|---|---|
| Display / titoli | **Space Grotesk** | `--font-display` | Archivo |
| Body / UI | **Inter** | `--font-sans` | Hanken Grotesk |
| Mono / dati | **JetBrains Mono** | `--font-mono` | IBM Plex Mono |

I numeri (punteggi, metriche, snippet di codice) usano il mono: è ciò che dà al
prodotto l'aria da strumento di misura invece che da brochure.

Caricamento: `@import` da Google Fonts in testa a `design-system.css`. Le email li
ricaricano da sé (`_EMAIL_FONTS`) perché non possono linkare il CSS condiviso.

---

## Soglie colore del punteggio

**Normative su tutto il prodotto:**

| Range | Label | Token |
|---|---|---|
| 75-100 | Ottimo | `--success` (`#0E9F6E` light · `#3DDC97` dark) |
| 50-74 | Migliorabile | `--warning` (`#C77700` light · `#F5BE57` dark) |
| 0-49 | Critico | `--danger` (`#D92D34` light · `#FF6B70` dark) |

Implementazioni: `_score_class()` e `_score_band()` in `server.py` — entrambe
corrette.

> ⚠️ **`geo_audit.barcol()` ([geo_audit.py:473](../geo_audit.py#L473)) usa 55
> invece di 50** come soglia intermedia. Un punteggio di 52 risulta giallo nella
> dashboard e rosso nel report. Bug noto
> ([doc 10](10-stato-e-debito-tecnico.md#soglie-colore-incoerenti)).

---

## Componenti disponibili

Sezioni di `design-system.css`:

| Sezione | Classi principali |
|---|---|
| Bottoni | `.btn` + `--primary` `--secondary` `--ghost` `--soft` `--danger` `--sm` `--lg` `--icon` `--block` |
| Form | `.field`, `.input`, `.input--err`, `.hint`, `.input-group` |
| Badge | `.badge` + `--neutral` `--brand` `--success` `--warning` `--danger` `--analisi`, `.badge .dot` |
| Score badge | `.score-badge` + `--ottimo` `--migliorabile` `--critico` |
| Theme toggle | switch chiaro/scuro |
| Card | `.card`, `.card-title`, `.card-sub` |
| Tabs | `.tabs`, `.subtabs`, `.tab`, `.subtab`, `.tab-soon` |
| Tabelle | `.tbl`, `.tbl-responsive`, `.tbl-wrap` (con `data-label` per il mobile) |
| Alert | `.alert` + `--info` `--success` `--warning` `--danger`, `.ic` |
| Score gauge | anello di punteggio — *signature del prodotto* |
| Teaser / gate | blur + overlay per il report bloccato |
| Dashboard / storico | `.hist-row`, mini-stat, grafico storico |
| Eyebrow | `.eyebrow` — etichetta mono maiuscola sopra i titoli |
| Spinner | `.spin` — stato di scansione |
| Responsive | utility di breakpoint |

Le tabelle usano il pattern `data-label`: su mobile ogni cella mostra
l'intestazione di colonna come etichetta inline invece di scrollare orizzontalmente.

---

## Tema chiaro/scuro

Attivato con `data-theme="dark"` su `<html>`. Preferenza in `localStorage`, chiave
**`geo-theme`**.

Ogni pagina ha uno script inline **in testa al `<head>`**, prima di qualsiasi
rendering, per evitare il flash di tema sbagliato:

```html
<script>try{var _t=localStorage.getItem('geo-theme');
if(_t)document.documentElement.setAttribute('data-theme',_t);}catch(e){}</script>
```

Il toggle è presente su tutte le pagine di prodotto **e sul report completo**, che
pur avendo stili propri è stato riallineato mantenendo intatta la resa in
stampa/PDF (commit `4ea97a9`).

> ⚠️ **Default incoerente.** Le pagine di prodotto, senza preferenza salvata,
> restano sul **chiaro** (`:root` è light). Il report generato da `geo_audit.py`
> parte invece dallo **scuro**: `<html data-theme="dark">` e
> `localStorage.getItem('geo-theme') || 'dark'`
> ([geo_audit.py:710-712](../geo_audit.py#L710-L712)). Un utente nuovo che passa
> dalla dashboard al report vede il tema cambiare sotto i piedi.

---

## Due mondi CSS, deliberatamente separati

| | Pagine di prodotto | Report generato |
|---|---|---|
| **CSS** | `<link>` a `/static/css/design-system.css` | Stili **inline** (`CSS` in `geo_audit.py:553`) |
| **File** | `templates/*.html` | Prodotto da `render_report()` |
| **Regola** | Usa i token DS | **Non toccare** |

Il motivo: il report viene **salvato integralmente** nella colonna `audits.html` e
servito così com'è mesi dopo. Deve restare autoconsistente e riprodurre esattamente
com'era il giorno in cui è stato generato. Se dipendesse da un CSS esterno, una
modifica al design system riscriverebbe retroattivamente tutti i report storici.

È una regola esplicita di [CLAUDE.md](../CLAUDE.md):

> Le pagine in `templates/` linkano `static/css/design-system.css` — usa i token DS.
> I report generati da `geo_audit.py` hanno stili inline propri: **non toccarli**.

---

## Email

Le email non possono usare le variabili CSS: **tutti i colori sono hardcoded**
nelle funzioni `_send_*`. Cambiare un token in `design-system.css` non aggiorna le
email. Vedi [06 · Email](06-email.md).

---

## Checklist prima di toccare la UI

1. Hai letto [`design_system/DESIGN_SYSTEM.md`](../design_system/DESIGN_SYSTEM.md)?
2. Stai usando i token DS e non i valori legacy hardcoded?
3. Il componente esiste già in `design-system.css`? Riusalo invece di reinventarlo.
4. Funziona in **entrambi** i temi?
5. Se hai toccato il report, hai verificato che gli stili restino inline?
6. Se hai toccato un'email, hai replicato la modifica in **`server.py` e
   `api/cron.py`**?

---

## Nota sui path nella documentazione del design system

`DESIGN_SYSTEM.md` cita `docs/design-system/ds.html` come fonte di verità visiva,
ma il file reale è in `design_system/ds_components/ds.html`. È un riferimento
rimasto indietro a una riorganizzazione delle cartelle
([doc 10](10-stato-e-debito-tecnico.md#documentazione-disallineata)).
