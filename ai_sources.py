"""Riconoscimento delle AI: chi ti legge (crawler) e chi ti manda gente (referral).

Portato dal plugin GEO Suite di Octoplug (`includes/monitor.php`), dove queste
due liste sono in esercizio su siti veri da mesi e hanno già pagato — e chiuso —
gli errori che si fanno la prima volta. Qui sono tradotte in Python senza
cambiare le regole, perché il valore non sono i domini: sono i *criteri* con cui
si confrontano.

Modulo foglia: non importa nulla del progetto, così resta testabile da solo e
non tocca la direzione degli import (`server` → `views` → `db` → `config`).

## I due fenomeni, che non vanno confusi

| | Chi | Come si vede |
|---|---|---|
| **Crawler** | GPTBot, ClaudeBot, PerplexityBot… | User-Agent, **solo lato server** |
| **Referral** | una persona che clicca il link dentro ChatGPT | `Referer` / `utm_source` |

⚠️ **I crawler non eseguono JavaScript.** Uno snippet nel browser — cioè
`static/js/geo-track.js` — non ne vedrà mai nemmeno uno: quando il bot legge la
pagina non c'è nessun browser. È il motivo per cui la scheda AI Traffic sembrava
vuota pur essendo il tracking funzionante: misurava il fenomeno raro (qualcuno
arriva da un assistente) e non poteva vedere quello frequente (gli assistenti ti
stanno leggendo). Gli hit dei crawler li può mandare solo chi sta sul server del
sito: il plugin Vertical GEO, via `POST /t` con il campo `ua`.
"""

from urllib.parse import urlparse, parse_qs
import re


# ─────────────────────────────────────────────────────────────────────────────
# 1. I crawler: chi legge il sito
# ─────────────────────────────────────────────────────────────────────────────

# Il token si cerca *dentro* lo User-Agent, senza distinzione di maiuscole.
# La categoria dice a cosa serve il passaggio, ed è ciò che rende leggibile il
# dato: `training` non porta visite (ma decide se domani il modello ti conosce),
# `search` alimenta l'indice da cui l'assistente cita, `user` è un bot mandato lì
# da una persona che in quel momento sta chiedendo qualcosa — il più caldo dei tre.
AI_CRAWLERS = [
    ("GPTBot",            "OpenAI GPTBot",            "training"),
    ("OAI-SearchBot",     "OpenAI Search",            "search"),
    ("ChatGPT-User",      "ChatGPT (da utente)",      "user"),
    ("ClaudeBot",         "Anthropic ClaudeBot",      "training"),
    ("anthropic-ai",      "Anthropic AI",             "training"),
    ("Claude-Web",        "Claude Web",               "user"),
    ("PerplexityBot",     "PerplexityBot",            "search"),
    ("Perplexity-User",   "Perplexity (da utente)",   "user"),
    ("Google-Extended",   "Google-Extended (Gemini)", "training"),
    ("Applebot-Extended", "Applebot-Extended",        "training"),
    ("Bingbot",           "Bingbot (Copilot)",        "search"),
    ("CCBot",             "Common Crawl (CCBot)",     "training"),
    ("Bytespider",        "ByteDance Bytespider",     "training"),
]

# ⚠️ L'ordine conta: `Claude-Web` e `ClaudeBot` condividono il prefisso «Claude»,
# e `Perplexity-User` contiene «Perplexity». Si confronta dal token più lungo, o
# un bot finisce contato sotto il nome di un altro.
_CRAWLERS_ORDINATI = sorted(AI_CRAWLERS, key=lambda v: -len(v[0]))

CRAWLER_CATEGORIE = {
    "training": "Addestramento",
    "search": "Indicizzazione",
    "user": "Richiesta di una persona",
}


def detect_ai_crawler(user_agent: str) -> tuple[str, str] | None:
    """(etichetta, categoria) del crawler AI, o None se lo UA non è di uno noto."""
    if not user_agent:
        return None
    ua = user_agent.lower()
    for token, label, categoria in _CRAWLERS_ORDINATI:
        if token.lower() in ua:
            return label, categoria
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 2. Il referral: chi manda persone
# ─────────────────────────────────────────────────────────────────────────────

# Fonte → (etichetta mostrata, [(dominio, percorso richiesto | None), …]).
#
# ⚠️ Le etichette delle prime fonti sono **identiche a quelle già scritte nel
# database** («ChatGPT», «Perplexity», «Gemini», «Claude», «Copilot», «You.com»,
# «Meta AI»): `tracking_event.ai_source` è calcolato all'inserimento e non a
# query time, quindi cambiare una di queste stringhe spezzerebbe in due lo
# storico — lo stesso assistente comparirebbe come due righe diverse.
#
# ⚠️ Questa mappa invecchia più in fretta di qualunque altra cosa nel progetto.
# Nel plugin è già successo: per mesi mancava `claude.ai`, e le visite da Claude
# risultavano traffico diretto mentre ClaudeBot era regolarmente contato fra i
# crawler — sapevamo quando Claude ci leggeva, non quando ci mandava qualcuno.
AI_REFERRALS: dict[str, tuple[str, list[tuple[str, str | None]]]] = {
    "chatgpt": ("ChatGPT", [("chatgpt.com", None), ("chat.openai.com", None), ("openai.com", None)]),
    "claude": ("Claude", [("claude.ai", None), ("anthropic.com", None)]),
    "perplexity": ("Perplexity", [("perplexity.ai", None)]),
    # `vertexaisearch` è il redirect di grounding: i link delle fonti dentro
    # Gemini passano di lì invece di puntare al sito. Senza questa voce il
    # traffico da Gemini si perde quasi tutto — misurato su un caso vero.
    "gemini": ("Gemini", [("gemini.google.com", None), ("bard.google.com", None),
                          ("vertexaisearch.cloud.google.com", None)]),
    # Bing è un motore di ricerca: solo `/chat` è Copilot.
    "copilot": ("Copilot", [("copilot.microsoft.com", None), ("bing.com", "/chat")]),
    "grok": ("Grok", [("grok.com", None), ("x.ai", None)]),
    "mistral": ("Mistral", [("mistral.ai", None)]),
    "meta-ai": ("Meta AI", [("meta.ai", None)]),
    "poe": ("Poe", [("poe.com", None)]),
    "you-com": ("You.com", [("you.com", None)]),
    "phind": ("Phind", [("phind.com", None)]),
    "andi": ("Andi", [("andisearch.com", None)]),
    "komo": ("Komo", [("komo.ai", None)]),
    "iask": ("iAsk", [("iask.ai", None)]),
    "duck-ai": ("Duck.ai", [("duck.ai", None)]),
    "felo": ("Felo", [("felo.ai", None)]),
    "genspark": ("Genspark", [("genspark.ai", None)]),
    "scira": ("Scira", [("scira.ai", None)]),
    "liner": ("Liner", [("liner.com", None)]),
    "wrtn": ("Wrtn", [("wrtn.ai", None)]),
    # Due siti generici con un assistente dentro: senza il percorso conteremmo
    # come «visita da un'AI» una ricerca normale su Kagi o il download di un
    # modello da Hugging Face.
    "kagi": ("Kagi Assistant", [("kagi.com", "/assistant")]),
    "huggingface": ("HuggingChat", [("huggingface.co", "/chat")]),
    # Assistenti cinesi: sono i più usati al mondo per numero di utenti.
    "deepseek": ("DeepSeek", [("deepseek.com", None)]),
    "doubao": ("Doubao", [("doubao.com", None)]),
    "kimi": ("Kimi", [("kimi.com", None), ("moonshot.cn", None)]),
    "qwen": ("Qwen", [("qwen.ai", None), ("tongyi.com", None), ("tongyi.aliyun.com", None)]),
    "ernie": ("ERNIE", [("yiyan.baidu.com", None), ("chat.baidu.com", None)]),
    "yuanbao": ("Yuanbao", [("yuanbao.tencent.com", None), ("hunyuan.tencent.com", None)]),
    "chatglm": ("ChatGLM", [("chatglm.cn", None), ("zhipuai.cn", None), ("bigmodel.cn", None)]),
    "xinghuo": ("Xinghuo", [("xinghuo.xfyun.cn", None)]),
    "hailuo": ("Hailuo", [("hailuoai.com", None), ("minimaxi.com", None)]),
    "baichuan": ("Baichuan", [("baichuan-ai.com", None)]),
    "metaso": ("Metaso", [("metaso.cn", None)]),
    "360ai": ("360 AI", [("n.cn", None)]),
    "stepfun": ("StepFun", [("stepfun.com", None)]),
}

# Come la stessa fonte viene taggata quando il link lo mette qualcun altro: in
# una campagna si scrive il nome dell'azienda o del modello, non la nostra chiave.
UTM_ALIAS = {
    "chatgpt": ["openai", "gpt"],
    "claude": ["anthropic"],
    "gemini": ["bard"],
    "copilot": ["bingchat"],
    "grok": ["xai"],
    "meta-ai": ["metaai"],
    "mistral": ["lechat"],
    "you-com": ["youcom"],
    "duck-ai": ["duckai", "duckduckgoai"],
    "kimi": ["moonshot"],
    "qwen": ["tongyi", "qianwen"],
    "ernie": ["yiyan", "wenxin", "erniebot"],
    "yuanbao": ["hunyuan"],
    "chatglm": ["zhipu", "glm"],
    "xinghuo": ["iflytek", "spark"],
    "hailuo": ["minimax"],
    "360ai": ["360"],
}


def _utm_nomina(utm: str, chiave: str, alias: list) -> bool:
    """`utm_source` nomina questa fonte?

    ⚠️ Confronto per **parola intera**, mai per sottostringa. Con quattro fonti
    lunghe («chatgpt», «perplexity») bastava cercarle dentro; con questo elenco
    no: «poe» sta dentro «poesia», «andi» dentro «brandizzato», «you» dentro
    «youtube» — e ogni newsletter con `utm_source=youtube` sarebbe diventata una
    visita da un assistente. Il valore si spezza sui separatori tipici di una
    campagna e si confronta pezzo per pezzo.
    """
    pezzi = [p for p in re.split(r"[^a-z0-9]+", utm) if p]
    if not pezzi:
        return False
    nomi = {chiave.replace("-", "")} | {a.replace("-", "") for a in alias}
    return any(p in nomi for p in pezzi)


def detect_ai_referral(referrer: str, page_url: str = "") -> str | None:
    """Etichetta dell'assistente da cui arriva la visita, o None.

    ⚠️ Il dominio si confronta **col solo host e per suffisso**, mai cercandolo
    dentro l'URL intero. Cercarlo dentro l'URL è l'errore che il plugin ha fatto
    e misurato: `html.it/articoli/chatgpt-guida/` veniva contato come visita *da*
    ChatGPT, e `oroscopo.it/segni/gemini/` come visita da Gemini. Un articolo che
    *parla* di un assistente non è una visita mandata da quell'assistente — e il
    numero gonfiato era proprio quello presentato come «è questo che paga».

    Il secondo segnale è `utm_source`, letto dalla query di `page_url`: serve
    perché molti assistenti mandano traffico **senza `Referer`** — link copiato a
    mano, app mobile, passaggio da https a http. Lì il referral esiste ma è muto,
    e senza utm resterebbe traffico diretto.
    """
    host = ""
    path = ""
    if referrer:
        try:
            p = urlparse(referrer)
            host = (p.netloc or "").lower().split(":")[0]
            path = (p.path or "").lower()
        except Exception:
            pass

    utm = ""
    if page_url:
        try:
            valori = parse_qs(urlparse(page_url).query).get("utm_source") or []
            utm = (valori[0] if valori else "").lower()
        except Exception:
            pass

    if not host and not utm:
        return None

    for chiave, (label, voci) in AI_REFERRALS.items():
        if host:
            for dominio, percorso in voci:
                if host == dominio or host.endswith("." + dominio):
                    if percorso and not path.startswith(percorso):
                        continue
                    return label
        if utm and _utm_nomina(utm, chiave, UTM_ALIAS.get(chiave, [])):
            return label

    return None
