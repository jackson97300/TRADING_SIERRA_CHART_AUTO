# Recap Dashboard MIA — A transmettre a l'agent Media

Date : 04/04/2026
Auteur : Agent Trading (Claude Code)

---

## Ce qui a ete construit (plan valide, pret a executer)

### Le Dashboard MIA — Plateforme live

Un dashboard temps reel qui affiche les donnees du bot de trading MIA.
- **377 features** affichees en temps reel (actualisees toutes les 5 secondes)
- **6 panels** : Bot Status, Contexte Marche, Order Flow, Options & Gamma, Intermarket ES/NQ, Signaux & Journal
- **Design** : fond #0A0E17, glass cards, cyan #00B4DC + gold #D4AF37 (meme charte que le site existant)
- **Responsive** : 2 colonnes desktop + sidebar, 1 colonne mobile

### Le Briefing MIA — Produit premium phare

Analyse quotidienne publiee chaque matin avant l'ouverture US (8h30 ET) :
- Contexte macro (VIX, ATR, overnight range)
- Niveaux cles (Call/Put walls, GEX levels, VWAP bands, Initial Balance)
- Biais directionnel (Open Type, AMD Power of 3, VWAP triple alignement)
- Positionnement institutionnel (GEX clusters, SMT divergence, correlation ES/NQ)

---

## URLs et liens a utiliser

### Liens existants (deja en place)

| Plateforme | URL | Statut |
|------------|-----|--------|
| Site principal | https://mia-ia-system.com | EN LIGNE (Cloudflare) |
| Education (40 lecons) | https://mia-ia-system.com/education/ | EN LIGNE |
| Discord | https://discord.gg/mia-ia-system | EN LIGNE |
| YouTube | https://youtube.com/@mia-ia-system | EN LIGNE |
| TikTok | https://tiktok.com/@mia_ia_system | EN LIGNE |
| Instagram | https://instagram.com/mia.ia.system | EN LIGNE |
| X (Twitter) | https://x.com/@mia_ia_system | EN LIGNE |
| GitHub site | https://github.com/jackson97300/mia-website | Public |

### Liens a venir (une fois deploye)

| Page | URL prevue | Contenu |
|------|-----------|---------|
| Dashboard | https://mia-ia-system.com/dashboard | 6 panels temps reel |
| Briefing du jour | https://mia-ia-system.com/briefing | Analyse quotidienne |
| Tarifs | https://mia-ia-system.com/pricing | 3 plans (Gratuit/Starter/Premium) |
| Login | https://mia-ia-system.com/login | Connexion compte |
| Inscription | https://mia-ia-system.com/register | Creation compte |

> **Note:** Tant que le Caddy HTTPS n'est pas configure, le dashboard est accessible via `http://212.28.179.199:8000` (IP directe). Le site principal sur Cloudflare reste separe.

---

## Monetisation — 3 tiers

| Plan | Prix | Ce qu'il inclut |
|------|------|-----------------|
| **Gratuit** | 0 EUR/mois | Status bot (running/stopped), VIX, ATR, VWAP slope, correlation ES/NQ basique, apercu briefing (3 lignes) |
| **Starter** | 19 EUR/mois | + Contexte marche complet (Open Type, Day Type, IB, Market Profile), + Intermarket complet (AMD, SMT, PO3), + Briefing complet |
| **Premium** | 49 EUR/mois | + Order Flow (delta, CVD, RVOL, absorption), + Options & Gamma (murs, GEX, 0DTE, VIX), + Signaux & Journal (score ML, SL/TP, trades), + Alertes Discord temps reel |

---

## Comment l'agent Media peut promouvoir le dashboard

### 1. Videos a creer (prioritaire)

| Video | Type | CTA dans la video |
|-------|------|-------------------|
| "Mon bot de trading a un dashboard en temps reel" | YouTube long (5-8min) | Lien dashboard dans description |
| "377 features en 1 ecran — Comment je lis le marche" | YouTube long (5-8min) | Lien dashboard + Discord |
| "Le VIX explique en 60 secondes" | Short/Reel | "Voir le VIX live sur MIA → lien bio" |
| "Les Market Makers ne veulent pas que tu voies ca" (GEX/Gamma) | Short/Reel | "Niveaux Gamma live → lien bio" |
| "Comment je detecte les Judas Swings" (AMD/PO3) | Short/Reel | "MIA detecte ca automatiquement → lien bio" |
| "Order Flow : acheter quand les institutions achetent" | YouTube long | Lien dashboard Premium |
| "Briefing MIA — Mon analyse du marche en 3 minutes" | YouTube recurrent (quotidien/hebdo) | Lien briefing + inscription |

### 2. Descriptions YouTube / fiches publication

Ajouter dans chaque description video :

```
---
Dashboard MIA (temps reel) : https://mia-ia-system.com/dashboard
Briefing quotidien : https://mia-ia-system.com/briefing
Discord gratuit : https://discord.gg/mia-ia-system
Education trading (40 lecons gratuites) : https://mia-ia-system.com/education/
Lucid Trading (prop firm) : [LIEN AFFILIATION ICI]
---
```

### 3. Strategie TikTok / Reels

| Hook | Contenu | CTA |
|------|---------|-----|
| "Mon IA analyse 377 features par minute" | Screencast dashboard en dark mode | "Lien en bio" |
| "Ce mur d'options a $5850 bloque le prix" | Zoom sur panel Options & Gamma | "Dashboard gratuit → bio" |
| "Signal BUY detecte par MIA — voici pourquoi" | Screencast toast notification + panel signals | "Premium → bio" |
| "RVOL a 4.2x — qu'est-ce que ca veut dire ?" | Zoom sur gauge RVOL qui monte | "Explication complete → education" |
| "ES et NQ ne sont plus correles — danger" | Panel Intermarket avec correlation rouge | "Alerte Discord en temps reel" |

### 4. Discord — integration

- Creer un canal **#briefing-mia** (read-only) ou le briefing est poste chaque matin
- FREE : voit le titre + 3 lignes
- STARTER+ : voit tout via un role Discord lie au tier Stripe
- Creer un canal **#signals-live** avec les toasts (BUY/SELL detecte)
- FREE : retardees de 15min
- PREMIUM : temps reel

### 5. Newsletter — funnel

```
Video YouTube/TikTok
  → "Lien en bio" ou description
    → Page dashboard (gratuit)
      → Voit les panels bloques (FOMO)
        → Sidebar "Newsletter MIA — briefing chaque matin"
          → S'inscrit avec email
            → Recoit le briefing apercu + CTA "Debloquer pour 19EUR"
              → Stripe Checkout → Starter ou Premium
```

### 6. Affiliation Lucid Trading

- Configurer le lien affiliation (12% par vente)
- Placer dans :
  - Sidebar du dashboard
  - Descriptions YouTube
  - Fiches publication TikTok/Reels
  - Page education (lecons "Prop Firms", "Money Management")
  - Footer du site

---

## Calendrier de lancement

| Semaine | Action |
|---------|--------|
| S1 (07-11/04) | Dashboard code + deploye sur VPS |
| S2 (14-18/04) | Auth + Stripe + Briefing MIA operationnel |
| S3 (21-25/04) | Video "Mon bot a un dashboard" + annonce Discord |
| S4 (28/04-02/05) | Serie de 5 shorts "377 features", "GEX", "RVOL", "Judas Swing", "VIX" |
| Continu | 1 briefing/jour + 2-3 shorts/semaine + 1 long-form/semaine |

---

## Charte visuelle pour les videos (coherence avec le dashboard)

| Element | Valeur | Usage video |
|---------|--------|-------------|
| Fond | #0A0E17 | Background de tous les screencasts |
| Cyan | #00B4DC | Highlights, fleches, annotations |
| Gold | #D4AF37 | Logo, premium, prix |
| Vert | #00C853 | Signaux haussiers, P&L positif |
| Rouge | #FF5252 | Signaux baissiers, P&L negatif |
| Police | Inter | Titres et texte |
| Police mono | JetBrains Mono | Valeurs numeriques |
| Watermark | "MIA IA SYSTEM" bas-centre | Deja en place dans le moteur video |

---

## Fichiers de reference

| Fichier | Emplacement | Contenu |
|---------|-------------|---------|
| Plan complet (11 tasks) | `D:\TRADING_SIERRA_CHART_AUTO\docs\plans\2026-04-04-mia-dashboard-website.md` | Code, architecture, CTA |
| Palette couleurs | `D:\MIA-MEDIA-PROJET\branding\palettes\mia-colors.md` | Tokens design |
| Planning videos | `D:\MIA-MEDIA-PROJET\planning\series-video-plan.md` | Series 0/1/2 |
| Site actuel | `D:\mia-website\` | Export Next.js statique |
| Dashboard JSON (bot) | `D:\TRADING_SIERRA_CHART_AUTO\DASHBOARD\MIA_AutoTrader_Dashboard.json` | Donnees live du bot |
