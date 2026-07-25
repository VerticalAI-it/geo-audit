-- GEO Audit · Seed demo — progetto "demo-website" con storico in miglioramento
-- Da eseguire DOPO supabase_setup.sql (richiede project/audits/issue già presenti).
-- Popola 4 audit su date diverse per mostrare il trend storico in dashboard,
-- con dati "finti ma plausibili" per tutte le sezioni già coperte dall'audit
-- engine reale (aree, check, pagine, azioni, issue lifecycle).
--
-- Utente target: verticalai00@gmail.com (user_id 05ba0f8c-7856-43d2-a86e-9036601e1cc0)
-- Idempotente sul progetto (ON CONFLICT su user_id+domain); se rilanciato,
-- aggiunge comunque nuovi audit — rimuovi manualmente quelli vecchi se serve
-- un reset pulito (vedi query di cleanup in fondo, commentata).

WITH proj AS (
    INSERT INTO public.project (user_id, name, domain, sector, created_at, updated_at)
    VALUES ('05ba0f8c-7856-43d2-a86e-9036601e1cc0', 'demo-website', 'demo-website.it', 'Demo', NOW(), NOW())
    ON CONFLICT (user_id, domain) DO UPDATE SET updated_at = NOW()
    RETURNING id
),

-- ── Run 1 · 60 giorni fa · 58/100 · D · Da rafforzare ───────────────────────
a1 AS (
    INSERT INTO public.audits (
        user_id, project_id, url, status, domain, overall, grade, band, pages_count, html,
        engine_version, areas, site_checks, pages_detail, actions, issues_count, critical_count,
        created_at, started_at, completed_at
    )
    SELECT
        '05ba0f8c-7856-43d2-a86e-9036601e1cc0', proj.id, 'https://demo-website.it', 'done', 'demo-website.it',
        58, 'D', 'Da rafforzare', 3,
        '<!doctype html><html lang="it" data-theme="dark"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>GEO Audit — demo-website.it</title>'
        '<link rel="stylesheet" href="/static/css/design-system.css">'
        '<style>body{min-height:100vh;margin:0;background:radial-gradient(140% 100% at 70% -5%,#1E1A38 0%,#0B0A12 60%);'
        'display:flex;align-items:center;justify-content:center;padding:40px;font-family:var(--font-sans)}'
        '.sheet{background:var(--surface);max-width:480px;width:100%;border-radius:20px;padding:44px 40px;'
        'text-align:center;box-shadow:0 16px 48px rgba(0,0,0,.4)}'
        '.sheet h1{font-family:var(--font-display);font-size:24px;margin:0 0 20px;color:var(--ink)}'
        '.sheet .score{font-family:var(--font-display);font-size:64px;font-weight:700;line-height:1;color:#F5BE57}'
        '.sheet .band{font-family:var(--font-mono);color:var(--text-3);letter-spacing:.08em;text-transform:uppercase;font-size:12px;margin-top:10px}'
        '.sheet p.note{color:var(--text-2);margin-top:24px;font-size:14px;line-height:1.6}</style></head>'
        '<body><div class="sheet"><h1>demo-website.it</h1><div class="score">58</div>'
        '<div class="band">Da rafforzare · D</div>'
        '<p class="note">Report demo — prima analisi. Dati dimostrativi generati per mostrare lo storico del progetto.</p>'
        '</div></body></html>',
        '1.1.0',
        '[{"key":"Dati strutturati","score":18},{"key":"Autorità & trust","score":48},
          {"key":"Contenuti & answerability","score":52},{"key":"Meta & social","score":58},
          {"key":"HTML semantico","score":64},{"key":"Rendering & accesso","score":72}]'::jsonb,
        '[{"id":"crawl.ai","category":"Rendering & accesso","title":"Accesso crawler AI (robots.txt)","status":"ok","weight":12,"severity":"critical","detail":"Nessun blocco esplicito ai bot AI.","recommendation":""},
          {"id":"crawl.robots","category":"Rendering & accesso","title":"robots.txt","status":"ok","weight":5,"severity":"low","detail":"robots.txt trovato.","recommendation":""},
          {"id":"crawl.sitemap","category":"Rendering & accesso","title":"sitemap.xml","status":"warn","weight":5,"severity":"medium","detail":"sitemap.xml non aggiornata.","recommendation":"Rigenera e invia una sitemap.xml aggiornata."},
          {"id":"crawl.llms","category":"Rendering & accesso","title":"llms.txt","status":"fail","weight":5,"severity":"medium","detail":"llms.txt assente.","recommendation":"Pubblica un file llms.txt con le indicazioni per gli agenti AI."},
          {"id":"crawl.https","category":"Rendering & accesso","title":"HTTPS","status":"ok","weight":10,"severity":"high","detail":"Sito servito in HTTPS.","recommendation":""}]'::jsonb,
        '[{"url":"https://demo-website.it/","type":"home","title":"Home","score":55,"checks":[
             {"id":"sd.present","category":"Dati strutturati","title":"Dati strutturati (JSON-LD)","status":"fail","weight":18,"severity":"high","detail":"Nessun JSON-LD schema.org.","recommendation":"Aggiungi JSON-LD Organization/WebSite."},
             {"id":"meta.description","category":"Meta & social","title":"Meta description","status":"warn","weight":5,"severity":"medium","detail":"Meta description troppo corta.","recommendation":"Estendi la description a 120-160 caratteri."},
             {"id":"content.h1","category":"Contenuti & answerability","title":"H1 pagina","status":"ok","weight":8,"severity":"medium","detail":"H1 presente e coerente.","recommendation":""},
             {"id":"trust.contact","category":"Autorità & trust","title":"Contatti verificabili","status":"ok","weight":6,"severity":"medium","detail":"Pagina contatti trovata.","recommendation":""}]},
          {"url":"https://demo-website.it/chi-siamo","type":"generic","title":"Chi siamo","score":60,"checks":[
             {"id":"content.alt","category":"HTML semantico","title":"Testo alternativo immagini","status":"warn","weight":4,"severity":"low","detail":"3 immagini senza alt text.","recommendation":"Aggiungi alt text descrittivo alle immagini."},
             {"id":"sem.html","category":"HTML semantico","title":"HTML semantico","status":"ok","weight":6,"severity":"low","detail":"Struttura semantica corretta.","recommendation":""}]},
          {"url":"https://demo-website.it/servizi","type":"product","title":"Servizi","score":60,"checks":[
             {"id":"meta.description","category":"Meta & social","title":"Meta description","status":"fail","weight":5,"severity":"high","detail":"Meta description assente.","recommendation":"Scrivi una meta description unica per la pagina."},
             {"id":"sd.present","category":"Dati strutturati","title":"Dati strutturati (JSON-LD)","status":"fail","weight":18,"severity":"high","detail":"Nessun JSON-LD Service/Offer.","recommendation":"Aggiungi JSON-LD Service con le offerte."}]}]'::jsonb,
        '[{"check_id":"sd.present","title":"Dati strutturati (JSON-LD)","category":"Dati strutturati","recommendation":"Aggiungi JSON-LD Organization/Product alle pagine principali.","severity":"high","count":2,"urls":["https://demo-website.it/","https://demo-website.it/servizi"]},
          {"check_id":"meta.description","title":"Meta description","category":"Meta & social","recommendation":"Scrivi una meta description unica per pagina.","severity":"high","count":2,"urls":["https://demo-website.it/","https://demo-website.it/servizi"]},
          {"check_id":"crawl.llms","title":"llms.txt","category":"Rendering & accesso","recommendation":"Pubblica un file llms.txt.","severity":"medium","count":1,"urls":[]}]'::jsonb,
        8, 3,
        NOW() - interval '60 days', NOW() - interval '60 days', NOW() - interval '60 days'
    FROM proj
    RETURNING id, created_at
),

-- ── Run 2 · 40 giorni fa · 74/100 · C · Discreto ────────────────────────────
a2 AS (
    INSERT INTO public.audits (
        user_id, project_id, url, status, domain, overall, grade, band, pages_count, html,
        engine_version, areas, site_checks, pages_detail, actions, issues_count, critical_count,
        created_at, started_at, completed_at
    )
    SELECT
        '05ba0f8c-7856-43d2-a86e-9036601e1cc0', proj.id, 'https://demo-website.it', 'done', 'demo-website.it',
        74, 'C', 'Discreto', 3,
        '<!doctype html><html lang="it" data-theme="dark"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>GEO Audit — demo-website.it</title>'
        '<link rel="stylesheet" href="/static/css/design-system.css">'
        '<style>body{min-height:100vh;margin:0;background:radial-gradient(140% 100% at 70% -5%,#1E1A38 0%,#0B0A12 60%);'
        'display:flex;align-items:center;justify-content:center;padding:40px;font-family:var(--font-sans)}'
        '.sheet{background:var(--surface);max-width:480px;width:100%;border-radius:20px;padding:44px 40px;'
        'text-align:center;box-shadow:0 16px 48px rgba(0,0,0,.4)}'
        '.sheet h1{font-family:var(--font-display);font-size:24px;margin:0 0 20px;color:var(--ink)}'
        '.sheet .score{font-family:var(--font-display);font-size:64px;font-weight:700;line-height:1;color:#F5BE57}'
        '.sheet .band{font-family:var(--font-mono);color:var(--text-3);letter-spacing:.08em;text-transform:uppercase;font-size:12px;margin-top:10px}'
        '.sheet p.note{color:var(--text-2);margin-top:24px;font-size:14px;line-height:1.6}</style></head>'
        '<body><div class="sheet"><h1>demo-website.it</h1><div class="score">74</div>'
        '<div class="band">Discreto · C</div>'
        '<p class="note">Report demo — secondo giro. JSON-LD e meta description corrette in home.</p>'
        '</div></body></html>',
        '1.1.0',
        '[{"key":"Autorità & trust","score":66},{"key":"Contenuti & answerability","score":70},
          {"key":"Dati strutturati","score":55},{"key":"Meta & social","score":78},
          {"key":"HTML semantico","score":80},{"key":"Rendering & accesso","score":85}]'::jsonb,
        '[{"id":"crawl.ai","category":"Rendering & accesso","title":"Accesso crawler AI (robots.txt)","status":"ok","weight":12,"severity":"critical","detail":"Nessun blocco esplicito ai bot AI.","recommendation":""},
          {"id":"crawl.robots","category":"Rendering & accesso","title":"robots.txt","status":"ok","weight":5,"severity":"low","detail":"robots.txt trovato.","recommendation":""},
          {"id":"crawl.sitemap","category":"Rendering & accesso","title":"sitemap.xml","status":"ok","weight":5,"severity":"medium","detail":"sitemap.xml aggiornata.","recommendation":""},
          {"id":"crawl.llms","category":"Rendering & accesso","title":"llms.txt","status":"warn","weight":5,"severity":"low","detail":"llms.txt presente ma incompleto.","recommendation":"Completa le indicazioni in llms.txt."},
          {"id":"crawl.https","category":"Rendering & accesso","title":"HTTPS","status":"ok","weight":10,"severity":"high","detail":"Sito servito in HTTPS.","recommendation":""}]'::jsonb,
        '[{"url":"https://demo-website.it/","type":"home","title":"Home","score":78,"checks":[
             {"id":"sd.present","category":"Dati strutturati","title":"Dati strutturati (JSON-LD)","status":"ok","weight":18,"severity":"high","detail":"JSON-LD Organization presente.","recommendation":""},
             {"id":"meta.description","category":"Meta & social","title":"Meta description","status":"ok","weight":5,"severity":"medium","detail":"Meta description estesa e chiara.","recommendation":""},
             {"id":"content.h1","category":"Contenuti & answerability","title":"H1 pagina","status":"ok","weight":8,"severity":"medium","detail":"H1 presente e coerente.","recommendation":""},
             {"id":"trust.contact","category":"Autorità & trust","title":"Contatti verificabili","status":"ok","weight":6,"severity":"medium","detail":"Pagina contatti trovata.","recommendation":""}]},
          {"url":"https://demo-website.it/chi-siamo","type":"generic","title":"Chi siamo","score":82,"checks":[
             {"id":"content.alt","category":"HTML semantico","title":"Testo alternativo immagini","status":"warn","weight":4,"severity":"low","detail":"1 immagine senza alt text.","recommendation":"Aggiungi alt text descrittivo alle immagini rimanenti."},
             {"id":"sem.html","category":"HTML semantico","title":"HTML semantico","status":"ok","weight":6,"severity":"low","detail":"Struttura semantica corretta.","recommendation":""}]},
          {"url":"https://demo-website.it/servizi","type":"product","title":"Servizi","score":75,"checks":[
             {"id":"meta.description","category":"Meta & social","title":"Meta description","status":"ok","weight":5,"severity":"high","detail":"Meta description aggiunta.","recommendation":""},
             {"id":"sd.present","category":"Dati strutturati","title":"Dati strutturati (JSON-LD)","status":"warn","weight":18,"severity":"medium","detail":"JSON-LD Service incompleto.","recommendation":"Completa le proprietà offers/areaServed."}]}]'::jsonb,
        '[{"check_id":"sd.present","title":"Dati strutturati (JSON-LD)","category":"Dati strutturati","recommendation":"Completa le proprietà JSON-LD mancanti su /servizi.","severity":"medium","count":1,"urls":["https://demo-website.it/servizi"]},
          {"check_id":"crawl.llms","title":"llms.txt","category":"Rendering & accesso","recommendation":"Completa le indicazioni in llms.txt.","severity":"low","count":1,"urls":[]},
          {"check_id":"content.alt","title":"Testo alternativo immagini","category":"HTML semantico","recommendation":"Aggiungi alt text descrittivo alle immagini rimanenti.","severity":"low","count":1,"urls":["https://demo-website.it/chi-siamo"]}]'::jsonb,
        4, 1,
        NOW() - interval '40 days', NOW() - interval '40 days', NOW() - interval '40 days'
    FROM proj
    RETURNING id, created_at
),

-- ── Run 3 · 20 giorni fa · 88/100 · B · Buono ───────────────────────────────
a3 AS (
    INSERT INTO public.audits (
        user_id, project_id, url, status, domain, overall, grade, band, pages_count, html,
        engine_version, areas, site_checks, pages_detail, actions, issues_count, critical_count,
        created_at, started_at, completed_at
    )
    SELECT
        '05ba0f8c-7856-43d2-a86e-9036601e1cc0', proj.id, 'https://demo-website.it', 'done', 'demo-website.it',
        88, 'B', 'Buono', 3,
        '<!doctype html><html lang="it" data-theme="dark"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>GEO Audit — demo-website.it</title>'
        '<link rel="stylesheet" href="/static/css/design-system.css">'
        '<style>body{min-height:100vh;margin:0;background:radial-gradient(140% 100% at 70% -5%,#1E1A38 0%,#0B0A12 60%);'
        'display:flex;align-items:center;justify-content:center;padding:40px;font-family:var(--font-sans)}'
        '.sheet{background:var(--surface);max-width:480px;width:100%;border-radius:20px;padding:44px 40px;'
        'text-align:center;box-shadow:0 16px 48px rgba(0,0,0,.4)}'
        '.sheet h1{font-family:var(--font-display);font-size:24px;margin:0 0 20px;color:var(--ink)}'
        '.sheet .score{font-family:var(--font-display);font-size:64px;font-weight:700;line-height:1;color:#3DDC97}'
        '.sheet .band{font-family:var(--font-mono);color:var(--text-3);letter-spacing:.08em;text-transform:uppercase;font-size:12px;margin-top:10px}'
        '.sheet p.note{color:var(--text-2);margin-top:24px;font-size:14px;line-height:1.6}</style></head>'
        '<body><div class="sheet"><h1>demo-website.it</h1><div class="score">88</div>'
        '<div class="band">Buono · B</div>'
        '<p class="note">Report demo — terzo giro. Dati strutturati e llms.txt completati.</p>'
        '</div></body></html>',
        '1.1.0',
        '[{"key":"Autorità & trust","score":82},{"key":"Contenuti & answerability","score":85},
          {"key":"Dati strutturati","score":85},{"key":"HTML semantico","score":90},
          {"key":"Meta & social","score":92},{"key":"Rendering & accesso","score":95}]'::jsonb,
        '[{"id":"crawl.ai","category":"Rendering & accesso","title":"Accesso crawler AI (robots.txt)","status":"ok","weight":12,"severity":"critical","detail":"Nessun blocco esplicito ai bot AI.","recommendation":""},
          {"id":"crawl.robots","category":"Rendering & accesso","title":"robots.txt","status":"ok","weight":5,"severity":"low","detail":"robots.txt trovato.","recommendation":""},
          {"id":"crawl.sitemap","category":"Rendering & accesso","title":"sitemap.xml","status":"ok","weight":5,"severity":"medium","detail":"sitemap.xml aggiornata.","recommendation":""},
          {"id":"crawl.llms","category":"Rendering & accesso","title":"llms.txt","status":"ok","weight":5,"severity":"low","detail":"llms.txt completo.","recommendation":""},
          {"id":"crawl.https","category":"Rendering & accesso","title":"HTTPS","status":"ok","weight":10,"severity":"high","detail":"Sito servito in HTTPS.","recommendation":""}]'::jsonb,
        '[{"url":"https://demo-website.it/","type":"home","title":"Home","score":92,"checks":[
             {"id":"sd.present","category":"Dati strutturati","title":"Dati strutturati (JSON-LD)","status":"ok","weight":18,"severity":"high","detail":"JSON-LD Organization presente.","recommendation":""},
             {"id":"meta.description","category":"Meta & social","title":"Meta description","status":"ok","weight":5,"severity":"medium","detail":"Meta description estesa e chiara.","recommendation":""},
             {"id":"content.h1","category":"Contenuti & answerability","title":"H1 pagina","status":"ok","weight":8,"severity":"medium","detail":"H1 presente e coerente.","recommendation":""},
             {"id":"trust.contact","category":"Autorità & trust","title":"Contatti verificabili","status":"ok","weight":6,"severity":"medium","detail":"Pagina contatti trovata.","recommendation":""}]},
          {"url":"https://demo-website.it/chi-siamo","type":"generic","title":"Chi siamo","score":90,"checks":[
             {"id":"content.alt","category":"HTML semantico","title":"Testo alternativo immagini","status":"warn","weight":4,"severity":"low","detail":"1 immagine senza alt text.","recommendation":"Aggiungi alt text descrittivo all''ultima immagine rimasta."},
             {"id":"sem.html","category":"HTML semantico","title":"HTML semantico","status":"ok","weight":6,"severity":"low","detail":"Struttura semantica corretta.","recommendation":""}]},
          {"url":"https://demo-website.it/servizi","type":"product","title":"Servizi","score":88,"checks":[
             {"id":"meta.description","category":"Meta & social","title":"Meta description","status":"ok","weight":5,"severity":"high","detail":"Meta description presente.","recommendation":""},
             {"id":"sd.present","category":"Dati strutturati","title":"Dati strutturati (JSON-LD)","status":"ok","weight":18,"severity":"medium","detail":"JSON-LD Service completo.","recommendation":""}]}]'::jsonb,
        '[{"check_id":"content.alt","title":"Testo alternativo immagini","category":"HTML semantico","recommendation":"Aggiungi alt text descrittivo all''ultima immagine rimasta.","severity":"low","count":1,"urls":["https://demo-website.it/chi-siamo"]}]'::jsonb,
        1, 0,
        NOW() - interval '20 days', NOW() - interval '20 days', NOW() - interval '20 days'
    FROM proj
    RETURNING id, created_at
),

-- ── Run 4 · oggi · 99/100 · A · Eccellente ──────────────────────────────────
a4 AS (
    INSERT INTO public.audits (
        user_id, project_id, url, status, domain, overall, grade, band, pages_count, html,
        engine_version, areas, site_checks, pages_detail, actions, issues_count, critical_count,
        created_at, started_at, completed_at
    )
    SELECT
        '05ba0f8c-7856-43d2-a86e-9036601e1cc0', proj.id, 'https://demo-website.it', 'done', 'demo-website.it',
        99, 'A', 'Eccellente', 3,
        '<!doctype html><html lang="it" data-theme="dark"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>GEO Audit — demo-website.it</title>'
        '<link rel="stylesheet" href="/static/css/design-system.css">'
        '<style>body{min-height:100vh;margin:0;background:radial-gradient(140% 100% at 70% -5%,#1E1A38 0%,#0B0A12 60%);'
        'display:flex;align-items:center;justify-content:center;padding:40px;font-family:var(--font-sans)}'
        '.sheet{background:var(--surface);max-width:480px;width:100%;border-radius:20px;padding:44px 40px;'
        'text-align:center;box-shadow:0 16px 48px rgba(0,0,0,.4)}'
        '.sheet h1{font-family:var(--font-display);font-size:24px;margin:0 0 20px;color:var(--ink)}'
        '.sheet .score{font-family:var(--font-display);font-size:64px;font-weight:700;line-height:1;color:#3DDC97}'
        '.sheet .band{font-family:var(--font-mono);color:var(--text-3);letter-spacing:.08em;text-transform:uppercase;font-size:12px;margin-top:10px}'
        '.sheet p.note{color:var(--text-2);margin-top:24px;font-size:14px;line-height:1.6}</style></head>'
        '<body><div class="sheet"><h1>demo-website.it</h1><div class="score">99</div>'
        '<div class="band">Eccellente · A</div>'
        '<p class="note">Report demo — quarto giro. Praticamente tutti i check superati.</p>'
        '</div></body></html>',
        '1.1.0',
        '[{"key":"HTML semantico","score":97},{"key":"Contenuti & answerability","score":98},
          {"key":"Rendering & accesso","score":100},{"key":"Dati strutturati","score":100},
          {"key":"Meta & social","score":100},{"key":"Autorità & trust","score":100}]'::jsonb,
        '[{"id":"crawl.ai","category":"Rendering & accesso","title":"Accesso crawler AI (robots.txt)","status":"ok","weight":12,"severity":"critical","detail":"Nessun blocco esplicito ai bot AI.","recommendation":""},
          {"id":"crawl.robots","category":"Rendering & accesso","title":"robots.txt","status":"ok","weight":5,"severity":"low","detail":"robots.txt trovato.","recommendation":""},
          {"id":"crawl.sitemap","category":"Rendering & accesso","title":"sitemap.xml","status":"ok","weight":5,"severity":"medium","detail":"sitemap.xml aggiornata.","recommendation":""},
          {"id":"crawl.llms","category":"Rendering & accesso","title":"llms.txt","status":"ok","weight":5,"severity":"low","detail":"llms.txt completo.","recommendation":""},
          {"id":"crawl.https","category":"Rendering & accesso","title":"HTTPS","status":"ok","weight":10,"severity":"high","detail":"Sito servito in HTTPS.","recommendation":""}]'::jsonb,
        '[{"url":"https://demo-website.it/","type":"home","title":"Home","score":100,"checks":[
             {"id":"sd.present","category":"Dati strutturati","title":"Dati strutturati (JSON-LD)","status":"ok","weight":18,"severity":"high","detail":"JSON-LD Organization presente.","recommendation":""},
             {"id":"meta.description","category":"Meta & social","title":"Meta description","status":"ok","weight":5,"severity":"medium","detail":"Meta description estesa e chiara.","recommendation":""},
             {"id":"content.h1","category":"Contenuti & answerability","title":"H1 pagina","status":"ok","weight":8,"severity":"medium","detail":"H1 presente e coerente.","recommendation":""},
             {"id":"trust.contact","category":"Autorità & trust","title":"Contatti verificabili","status":"ok","weight":6,"severity":"medium","detail":"Pagina contatti trovata.","recommendation":""}]},
          {"url":"https://demo-website.it/chi-siamo","type":"generic","title":"Chi siamo","score":97,"checks":[
             {"id":"content.alt","category":"HTML semantico","title":"Testo alternativo immagini","status":"warn","weight":4,"severity":"low","detail":"1 immagine decorativa senza alt text.","recommendation":"Aggiungi alt=\"\" esplicito o una descrizione breve."},
             {"id":"sem.html","category":"HTML semantico","title":"HTML semantico","status":"ok","weight":6,"severity":"low","detail":"Struttura semantica corretta.","recommendation":""}]},
          {"url":"https://demo-website.it/servizi","type":"product","title":"Servizi","score":100,"checks":[
             {"id":"meta.description","category":"Meta & social","title":"Meta description","status":"ok","weight":5,"severity":"high","detail":"Meta description presente.","recommendation":""},
             {"id":"sd.present","category":"Dati strutturati","title":"Dati strutturati (JSON-LD)","status":"ok","weight":18,"severity":"medium","detail":"JSON-LD Service completo.","recommendation":""}]}]'::jsonb,
        '[{"check_id":"content.alt","title":"Testo alternativo immagini","category":"HTML semantico","recommendation":"Aggiungi alt=\"\" esplicito o una descrizione breve all''ultima immagine.","severity":"low","count":1,"urls":["https://demo-website.it/chi-siamo"]}]'::jsonb,
        1, 0,
        NOW(), NOW(), NOW()
    FROM proj
    RETURNING id, created_at
),

-- ── Issue lifecycle: risolte nel tempo + una minore ancora aperta ──────────
issues_ins AS (
    INSERT INTO public.issue (
        project_id, user_id, check_id, category, url, title, severity, fingerprint, status,
        first_seen_audit, last_seen_audit, first_seen_at, last_seen_at, resolved_at
    )
    SELECT proj.id, '05ba0f8c-7856-43d2-a86e-9036601e1cc0', v.check_id, v.category, v.url, v.title, v.severity,
           v.check_id || '|' || coalesce(v.url, ''), v.status,
           v.first_seen_audit, v.last_seen_audit, v.first_seen_at, v.last_seen_at, v.resolved_at
    FROM proj, a1, a2, a3, a4,
    LATERAL (VALUES
        -- risolta fra run1 e run2
        ('sd.present', 'Dati strutturati', 'https://demo-website.it/', 'Dati strutturati (JSON-LD)', 'high',
         'resolved', a1.id, a1.id, a1.created_at, a1.created_at, a2.created_at),
        ('meta.description', 'Meta & social', 'https://demo-website.it/', 'Meta description', 'medium',
         'resolved', a1.id, a1.id, a1.created_at, a1.created_at, a2.created_at),
        ('meta.description', 'Meta & social', 'https://demo-website.it/servizi', 'Meta description', 'high',
         'resolved', a1.id, a1.id, a1.created_at, a1.created_at, a2.created_at),
        -- risolta fra run2 e run3
        ('sd.present', 'Dati strutturati', 'https://demo-website.it/servizi', 'Dati strutturati (JSON-LD)', 'medium',
         'resolved', a1.id, a2.id, a1.created_at, a2.created_at, a3.created_at),
        ('crawl.llms', 'Rendering & accesso', NULL, 'llms.txt', 'medium',
         'resolved', a1.id, a2.id, a1.created_at, a2.created_at, a3.created_at),
        -- ancora aperta a oggi (coerente col "praticamente senza errori": 1 issue minore rimasta)
        ('content.alt', 'HTML semantico', 'https://demo-website.it/chi-siamo', 'Testo alternativo immagini', 'low',
         'open', a1.id, a4.id, a1.created_at, a4.created_at, NULL)
    ) AS v(check_id, category, url, title, severity, status, first_seen_audit, last_seen_audit, first_seen_at, last_seen_at, resolved_at)
    ON CONFLICT (project_id, fingerprint) DO UPDATE SET
        status = EXCLUDED.status, last_seen_audit = EXCLUDED.last_seen_audit,
        last_seen_at = EXCLUDED.last_seen_at, resolved_at = EXCLUDED.resolved_at
    RETURNING id
)
SELECT 'demo project + 4 audit + issue lifecycle inseriti' AS result;

-- Cleanup (se vuoi ripartire pulito prima di rilanciare questo file):
-- DELETE FROM public.issue   WHERE project_id = (SELECT id FROM public.project WHERE domain = 'demo-website.it' AND user_id = '05ba0f8c-7856-43d2-a86e-9036601e1cc0');
-- DELETE FROM public.audits  WHERE project_id = (SELECT id FROM public.project WHERE domain = 'demo-website.it' AND user_id = '05ba0f8c-7856-43d2-a86e-9036601e1cc0');
-- DELETE FROM public.project WHERE domain = 'demo-website.it' AND user_id = '05ba0f8c-7856-43d2-a86e-9036601e1cc0';
