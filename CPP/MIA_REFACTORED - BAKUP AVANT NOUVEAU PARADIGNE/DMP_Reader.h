#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// DMP_Reader.h  —  MIA Data Dumper G3 : Section A — LECTURE SIERRA CHART
// ═══════════════════════════════════════════════════════════════════════════════
//
//  Rôle   : Lire TOUS les subgraphs nécessaires depuis Sierra Chart et les
//           stocker dans DMP_RawData. Aucun calcul ici — seulement de la
//           lecture robuste avec gestion des erreurs.
//
//  Règle  : UN seul endroit pour les Study IDs. Si Sierra Chart change un ID,
//           on modifie ici et ici seulement. Le reste du dumper ne connaît
//           que des noms symboliques.
//
//  Auteur : MIA Trading System
//  Date   : 2026-02-28
//  Build  : G3-Unifier v1.0
//
//  ⚠️  CE FICHIER EST PARTAGÉ BOT + DUMPER — Ne pas y mettre de logique trading.
//
// ═══════════════════════════════════════════════════════════════════════════════

#include "DMP_Config.h"     // sierrachart.h + constantes minimales du Dumper
#include <cfloat>           // FLT_MAX
#include <cmath>            // std::isfinite
#include <cstring>          // memset

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 1 — CONSTANTES CHARTS & STUDIES
// ═══════════════════════════════════════════════════════════════════════════════
// ⚠️  À synchroniser avec study_mapping.json pour les IDs partagés avec le bot.
//     Les IDs propres au dumper (Charts 26-31) sont définis ici uniquement.

namespace DMP_Charts {

    // ── Footprints ─────────────────────────────────────────────────────────────
    constexpr int ES_FP           =  1;   // ES Footprint - Bataille Navale
    constexpr int NQ_FP           =  2;   // NQ Footprint - Bataille Navale

    // ── Contexte global ────────────────────────────────────────────────────────
    constexpr int VIX_MQ          = 15;   // VIX avec MenthorQ Gamma

    // ── Daily (ATR + VWAP Weekly/Monthly) ──────────────────────────────────────
    constexpr int ES_DAILY        = 16;   // ES Daily — ATR, MA, VWAP W/M
    constexpr int NQ_DAILY        = 17;   // NQ Daily — ATR, MA, VWAP W/M

    // ── Barres 1min (MenthorQ + Blind Spots + VWAP + Session) ─────────────────
    constexpr int NQ_BARRES       = 23;   // NQ 1min Barres
    constexpr int ES_BARRES       = 25;   // ES 1min Barres

    // ── Volume Profile courant + Précédent ────────────────────────────────────
    constexpr int ES_VP           = 26;   // ES Volume Profile
    constexpr int NQ_VP           = 27;   // NQ Volume Profile

    // ── CVD + Swing + VP session ──────────────────────────────────────────────
    constexpr int ES_CVD          = 28;   // ES CVD & Swing
    constexpr int NQ_CVD          = 29;   // NQ CVD & Swing

    // ── Composite Profiles ───────────────────────────────────────────────────
    // ⚠️  CRITIQUE : Chart 30 = NQ (NQH26-CME), Chart 31 = ES (ESH26-CME)
    //     L'ordre est INVERSÉ par rapport à ce qu'on aurait pu supposer.
    //     Confirmé par le scan JSON (chart_30.json = NQH26, chart_31.json = ESH26).
    constexpr int ES_COMPOSITE    = 31;   // ES Composite Profiles + MQ Gamma ES
    constexpr int NQ_COMPOSITE    = 30;   // NQ Composite Profiles + MQ Blind Spots NQ !

} // namespace DMP_Charts

// ─────────────────────────────────────────────────────────────────────────────

namespace DMP_Studies {

    // ── Chart 1 ES_FOOTPRINT ──────────────────────────────────────────────────
    struct ES_FP {
        constexpr static int FPBS         = 31;   // Footprint Bar Study
        constexpr static int VWAP_DAY     = 62;   // VWAP journalier (sg0=V, sg1=+1σ, sg2=-1σ)
        constexpr static int ROTATION     = 12;   // Rotation Reversal Bar
        constexpr static int ROTATION_UP  = 19;   // [AV] Rotation Up
        constexpr static int ROTATION_DN  = 20;   // [AV] Rotation Down
        constexpr static int OPEN_830     = 14;   // Open 08h30 ET
        constexpr static int HH_SESSION   = 15;   // Higher High session (sg1=High)
        constexpr static int LL_SESSION   = 16;   // Lower Low session  (sg2=Low)
        constexpr static int COLOR_UP     = 56;   // [AV] Color Zone Up
        constexpr static int COLOR_DN     = 57;   // [AV] Color Zone Down
        constexpr static int ABSORB_ASK   = 25;   // [AV] Absorption Ask
        constexpr static int ABSORB_BID   = 26;   // [AV] Absorption Bid
        constexpr static int LONG_UP      = 21;   // [AV] Long Up Bar
        constexpr static int LONG_DN      = 22;   // [AV] Long Down Bar
        constexpr static int DOUBLE_ASK   = 28;   // [AV] Double Ask
        constexpr static int DOUBLE_BID   = 27;   // [AV] Double Bid
        constexpr static int ASK_100      = 40;   // Ask +100 lots (sg0-9)
        constexpr static int BID_100      = 41;   // Bid +100 lots (sg0-9)
        constexpr static int CLUSTER      = 10;   // Cluster Volume
    };

    // ── Chart 2 NQ_FOOTPRINT ──────────────────────────────────────────────────
    struct NQ_FP {
        constexpr static int FPBS         = 33;   // Footprint Bar Study
        constexpr static int VWAP_DAY     = 57;   // VWAP journalier
        constexpr static int ROTATION     = 14;   // Rotation Reversal Bar
        constexpr static int ROTATION_UP  = 21;   // [AV] Rotation Up
        constexpr static int ROTATION_DN  = 22;   // [AV] Rotation Down
        constexpr static int OPEN_830     = 16;   // Open 08h30 ET
        constexpr static int HH_SESSION   = 17;   // Higher High session
        constexpr static int LL_SESSION   = 18;   // Lower Low session
        constexpr static int COLOR_UP     = 53;   // [AV] Color Zone Up
        constexpr static int COLOR_DN     = 54;   // [AV] Color Zone Down
        constexpr static int ABSORB_ASK   = 29;   // [AV] Absorption Ask
        constexpr static int ABSORB_BID   = 30;   // [AV] Absorption Bid
        constexpr static int LONG_UP      = 23;   // [AV] Long Up Bar
        constexpr static int LONG_DN      = 24;   // [AV] Long Down Bar
        constexpr static int TRIPLE_ASK   = 28;   // [AV] Triple Ask (NQ = Triple, pas Double)
        constexpr static int TRIPLE_BID   = 27;   // [AV] Triple Bid
        constexpr static int MQ_GAMMA     =  6;   // MenthorQ Gamma (NQ)
        constexpr static int MQ_BLIND     =  7;   // MenthorQ Blind Spots (NQ)
        constexpr static int VWAP_NAMED   = 13;   // VWAP nommé (sg0=VWAP, sg1=SD+1...)
    };

    // ── Chart 15 VIX_MQ ───────────────────────────────────────────────────────
    struct VIX {
        constexpr static int MQ_GAMMA     =  2;   // MenthorQ Gamma sur VIX
                                                   // sg0=Call, sg1=Put, sg2=HVL
                                                   // sg9-sg18=GEX1-GEX10
    };

    // ── Chart 16 ES_DAILY ─────────────────────────────────────────────────────
    struct ES_DAILY {
        constexpr static int ATR          =  1;   // Average True Range (sg0)
        constexpr static int MA           =  3;   // Moving Averages (sg0=MA1, sg1=MA2)
        constexpr static int VWAP_WEEKLY  =  4;   // VWAP Semaine ⚠️ À confirmer Lundi
        constexpr static int VWAP_MONTHLY =  5;   // VWAP Mois    ⚠️ À confirmer Lundi
    };

    // ── Chart 17 NQ_DAILY ─────────────────────────────────────────────────────
    struct NQ_DAILY {
        constexpr static int ATR          =  1;   // Average True Range (sg0)
        constexpr static int MA           =  3;   // Moving Averages
        constexpr static int VWAP_WEEKLY  =  4;   // VWAP Semaine ⚠️ À confirmer Lundi
        constexpr static int VWAP_MONTHLY =  5;   // VWAP Mois    ⚠️ À confirmer Lundi
    };

    // ── Chart 25 ES_BARRES ────────────────────────────────────────────────────
    struct ES_BARRES {
        constexpr static int VWAP_DAY     =  1;   // VWAP journalier (sg0=V, sg1=+1σ, sg2=-1σ)
        constexpr static int MQ_GAMMA     =  2;   // MenthorQ Gamma ES
        constexpr static int MQ_BLIND     = 22;   // MenthorQ Blind Spots ES (sg0-9=BL1-10)
        constexpr static int HH_SESSION   =  8;   // Higher High session (sg1=High)
        constexpr static int LL_SESSION   =  9;   // Lower Low session   (sg2=Low)
        constexpr static int HH_CASH      = 12;   // Higher High CASH session (sg1=High)
        constexpr static int LL_CASH      = 13;   // Lower Low CASH session   (sg2=Low)
        constexpr static int OPEN_830     = 14;   // Open 08h30 ET (sg0=Open)
    };

    // ── Chart 23 NQ_BARRES ────────────────────────────────────────────────────
    struct NQ_BARRES {
        constexpr static int VWAP_DAY     =  1;   // VWAP journalier
        constexpr static int MQ_GAMMA     = 25;   // MenthorQ Gamma NQ (sg0-sg18)
        constexpr static int HH_SESSION   =  8;   // Higher High session (sg1)
        constexpr static int LL_SESSION   =  9;   // Lower Low session   (sg2)
        constexpr static int HH_CASH      = 12;   // Higher High CASH    (sg1)
        constexpr static int LL_CASH      = 13;   // Lower Low CASH      (sg2)
        constexpr static int OPEN_830     = 14;   // Open 08h30 ET
    };

    // ── Chart 26 ES_VP ────────────────────────────────────────────────────────
    struct ES_VP {
        constexpr static int VP_CURRENT   =  1;   // VP session courante sg1=VPOC, sg2=VAH, sg3=VAL, sg4=VWAP
        constexpr static int VP_PREVIOUS  =  2;   // VP session précédente (idem)
        constexpr static int VWAP_DAY     =  3;   // VWAP session courante sg0
        constexpr static int VP_PREV_WAPS =  4;   // Previous VWAP + SD+1/-1 sg4=+1, sg12=SD+1, sg13=SD-1
        constexpr static int OHLC_SESSION = 29;   // OHLC session courante sg0=O, sg1=H, sg2=L, sg3=C
    };

    // ── Chart 27 NQ_VP ────────────────────────────────────────────────────────
    struct NQ_VP {
        constexpr static int VP_CURRENT   =  1;
        constexpr static int VP_PREVIOUS  =  2;
        constexpr static int VWAP_DAY     =  3;
        constexpr static int VP_PREV_WAPS =  4;
        constexpr static int OHLC_SESSION = 29;
    };

    // ── Chart 28 ES_CVD ───────────────────────────────────────────────────────
    struct ES_CVD {
        constexpr static int CVD          =  1;   // Cumulative Delta sg0=CVD, sg1=CVD_High?, sg2=?, sg3=Close
        constexpr static int CVD_OHLC     =  2;   // CVD OHLC sg0=Open, sg1=High, sg2=Low, sg3=Close
        constexpr static int VWAP         = 19;   // VWAP sg0
        constexpr static int VP_SESSION   = 35;   // Volume Profile session sg1=VPOC, sg2=VAH, sg3=VAL
        constexpr static int SWING        =  6;   // Swing High/Low sg0=High, sg1=Low
        constexpr static int DELTA_DIV_BUY  = 31; // Delta Divergence Buy
        constexpr static int DELTA_DIV_SELL = 32; // Delta Divergence Sell
    };

    // ── Chart 29 NQ_CVD ───────────────────────────────────────────────────────
    struct NQ_CVD {
        constexpr static int CVD          =  1;
        constexpr static int CVD_OHLC     =  2;
        constexpr static int VWAP         = 19;
        constexpr static int VP_SESSION   = 35;
        constexpr static int SWING        =  6;
        constexpr static int DELTA_DIV_BUY  = 31;
        constexpr static int DELTA_DIV_SELL = 32;
    };

    // ── Chart 31 ES_COMPOSITE ─────────────────────────────────────────────────
    // ESH26-CME confirmé par scan JSON
    struct ES_COMPOSITE {
        // Composite Profiles — IDs confirmés scan chart_31.json
        constexpr static int COMP_PREV    = 34;   // 1J (= VPOC session précédente)
        constexpr static int COMP_20D     =  2;   // 20J  ✅ sg1=6945 / sg2=7015.5 / sg3=6909.75
        constexpr static int COMP_50D     =  3;   // 50J  ⚠️ NULL hors session — à confirmer Lundi
        constexpr static int COMP_100D    =  4;   // 100J ✅ sg1=6945 / sg2=7017.75 / sg3=6895.25
        constexpr static int COMP_200D    =  5;   // 200J ⚠️ NULL hors session — à confirmer Lundi
        // MenthorQ ES
        constexpr static int MQ_GAMMA     =  6;   // Gamma Levels ES (NULL hors session)
        constexpr static int MQ_BLIND     =  7;   // Blind Spots ES ⚠️ à confirmer Lundi (sur chart 31 ?)
        // Overnight ⚠️ à confirmer Lundi
        constexpr static int OVN_HIGH     = 10;
        constexpr static int OVN_LOW      = 11;
    };

    // ── Chart 30 NQ_COMPOSITE ─────────────────────────────────────────────────
    // NQH26-CME confirmé par scan JSON
    struct NQ_COMPOSITE {
        // Composite Profiles NQ
        constexpr static int COMP_PREV    = 34;   // 1J NQ ✅ (25370 = VPOC NQ)
        constexpr static int COMP_20D     =  2;   // 20J  ⚠️ NULL hors session
        constexpr static int COMP_50D     =  3;   // 50J  ⚠️ NULL hors session
        constexpr static int COMP_100D    =  4;   // 100J ⚠️ NULL hors session
        constexpr static int COMP_200D    =  5;   // 200J ⚠️ NULL hors session
        // MenthorQ NQ — CONFIRMÉ scan chart_30.json !
        constexpr static int MQ_BLIND     =  7;   // ✅ Blind Spots NQ BL1-10 (10 valeurs actives !)
        constexpr static int MQ_GAMMA     =  6;   // Gamma NQ (NULL hors session)
        // Overnight
        constexpr static int OVN_HIGH     = 10;   // ⚠️ à confirmer Lundi
        constexpr static int OVN_LOW      = 11;   // ⚠️ à confirmer Lundi
    };

} // namespace DMP_Studies

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 2 — STRUCTURE DMP_RawData
// ═══════════════════════════════════════════════════════════════════════════════
// Contient TOUS les prix bruts lus depuis Sierra Chart.
// Pas de calcul ici — uniquement du stockage. Les champs INVALIDES valent
// DMP_INVALID (= FLT_MAX) pour permettre la détection dans DMP_Transform.h.

constexpr float DMP_INVALID = FLT_MAX;    // Valeur sentinelle : donnée non-disponible
constexpr float DMP_BOOL_TRUE  = 1.0f;    // Signal booléen actif
constexpr float DMP_BOOL_FALSE = 0.0f;    // Signal booléen inactif

struct DMP_RawData {

    // ── IDENTIFICATION ─────────────────────────────────────────────────────────
    long long   timestamp_ms;             // Timestamp Unix millisecondes
    int         bar_index;                // Index de la barre courante
    bool        is_nq;                    // true=NQ, false=ES
    float       price_close;             // Prix de clôture de la barre
    float       price_open;              // Prix d'ouverture de la barre
    float       price_high;              // High de la barre
    float       price_low;               // Low de la barre
    float       tick_size;               // Taille du tick (0.25)

    // ─────────────────────────────────────────────────────────────────────────
    // A. FPBS / FOOTPRINT BAR STUDY
    // Source : Chart 1 (ES) Study 31 / Chart 2 (NQ) Study 33
    // ─────────────────────────────────────────────────────────────────────────
    float fpbs_delta;                    // sg0  — Delta barre (ask - bid)
    float fpbs_delta_change;             // sg2  — Variation delta vs barre précédente
    float fpbs_pos_delta;                // sg3  — Somme deltas positifs session
    float fpbs_neg_delta;                // sg4  — Somme deltas négatifs session
    float fpbs_max_delta;                // sg7  — Delta max de la barre
    float fpbs_min_delta;                // sg8  — Delta min de la barre
    float fpbs_delta_day;                // sg9  — Delta cumulatif journée
    float fpbs_volume;                   // sg12 — Volume total barre
    float fpbs_avg_size;                 // sg14 — Taille moyenne des trades ⭐
    float fpbs_ask_pct;                  // sg16 — % volume Ask
    float fpbs_bid_pct;                  // sg17 — % volume Bid
    float fpbs_cvd_day;                  // sg18 — CVD cumulatif journée (All)
    float fpbs_poc_vol;                  // sg19 — Volume au POC de la barre
    float fpbs_cvd_high;                 // sg20 — CVD High barre
    float fpbs_cvd_low;                  // sg21 — CVD Low barre
    float fpbs_bar_duration;             // sg29 — Durée barre en secondes
    float fpbs_finish;                   // sg33 — Finish (AskVol-BidVol final %)
    float fpbs_vol_per_sec;              // sg35 — Volume par seconde
    float fpbs_hl_range;                 // sg40 — Range High-Low barre
    float fpbs_poc_price;                // sg41 — Prix du POC intra-barre
    float fpbs_avg_bid_size;             // sg50 — Taille moy trades Bid ⭐
    float fpbs_avg_ask_size;             // sg51 — Taille moy trades Ask ⭐

    // ─────────────────────────────────────────────────────────────────────────
    // B. ROTATION & CLUSTER
    // Source : Chart 1/2 Study ROTATION, ROTATION_UP/DN
    // ─────────────────────────────────────────────────────────────────────────
    float rotation_value;                // sg0  — >0=pivot HIGH / <0=pivot LOW
    float rotation_zz_mid;              // sg6  — ZigZag Midpoint
    float rotation_zz_osc;              // sg8  — ZigZag Oscillateur
    float rotation_up_signal;           // ROTATION_UP sg0  — Signal rotation haussière
    float rotation_dn_signal;           // ROTATION_DN sg0  — Signal rotation baissière
    float cluster_0;                     // CLUSTER sg0 — Prix cluster #1 (0=inactif)
    float cluster_1;                     // CLUSTER sg1 — Prix cluster #2

    // ─────────────────────────────────────────────────────────────────────────
    // C. SIGNAUX BATAILLE NAVALE
    // Source : Chart 1 (ES) / Chart 2 (NQ)
    // ─────────────────────────────────────────────────────────────────────────
    float bn_color_up;                   // COLOR_UP sg0   — Zone bullish active
    float bn_color_dn;                   // COLOR_DN sg0   — Zone bearish active
    float bn_absorb_ask;                 // ABSORB_ASK sg0 — Absorption vendeurs (bullish)
    float bn_absorb_bid;                 // ABSORB_BID sg0 — Absorption acheteurs (bearish)
    float bn_long_up;                    // LONG_UP sg0    — Longue barre haussière
    float bn_long_dn;                    // LONG_DN sg0    — Longue barre baissière
    float bn_double_ask;                 // DOUBLE_ASK sg0 — Double pression Ask (ES)
    float bn_double_bid;                 // DOUBLE_BID sg0 — Double pression Bid (ES)
    float bn_triple_ask;                 // TRIPLE_ASK sg0 — Triple pression Ask (NQ)
    float bn_triple_bid;                 // TRIPLE_BID sg0 — Triple pression Bid (NQ)
    // Big Orders (10 niveaux, le plus proche sera calculé dans Transform)
    float bn_ask100[10];                 // ASK_100 sg0..9 — 10 niveaux Ask +100 lots
    float bn_bid100[10];                 // BID_100 sg0..9 — 10 niveaux Bid +100 lots

    // ─────────────────────────────────────────────────────────────────────────
    // D. VWAP JOURNALIER
    // Source : Chart 26 Study 3 (ES) / Chart 27 Study 3 (NQ) — VP Charts
    // ⚠️  Ancienne source Chart 1/2 retournait NULL — corrigé Bug #2
    // ─────────────────────────────────────────────────────────────────────────
    float vwap_day;                      // sg0 — VWAP journalier (reset 9h30 ET)
    float vwap_day_sd1u;                 // sg1 — VWAP +1σ
    float vwap_day_sd1d;                 // sg2 — VWAP -1σ
    float vwap_day_sd2u;                 // sg3 — VWAP +2σ
    float vwap_day_sd2d;                 // sg4 — VWAP -2σ
    // Pente VWAP — CRITIQUE Layer 3 : slope>0 AND delta>0 → long (82% WR ES)
    float vwap_slope_10;                 // (vwap_now - vwap_10bars_ago) / 10 pts/barre
    float vwap_slope_30;                 // (vwap_now - vwap_30bars_ago) / 30 pts/barre

    // ─────────────────────────────────────────────────────────────────────────
    // E. VWAP WEEKLY & MONTHLY
    // Source : Chart 16 (ES) / Chart 17 (NQ) — Studies 4/5
    // ⚠️  À confirmer Lundi (Study IDs 4/5 à valider)
    // ─────────────────────────────────────────────────────────────────────────
    float vwap_weekly;                   // VWAP semaine glissante
    float vwap_weekly_sd1u;              // VWAP Weekly +1σ
    float vwap_weekly_sd1d;              // VWAP Weekly -1σ
    float vwap_monthly;                  // VWAP mensuel glissant
    float vwap_monthly_sd1u;             // VWAP Monthly +1σ
    float vwap_monthly_sd1d;             // VWAP Monthly -1σ

    // ─────────────────────────────────────────────────────────────────────────
    // F. ATR & MOVING AVERAGES (Daily)
    // Source : Chart 16 (ES) / Chart 17 (NQ)
    // ─────────────────────────────────────────────────────────────────────────
    float atr_daily;                     // ATR daily (dénominateur normalisation)
    float ma_fast;                       // MA rapide (trend court terme)
    float ma_slow;                       // MA lente (trend long terme)

    // ─────────────────────────────────────────────────────────────────────────
    // G. MENTHORQ GAMMA & BLIND SPOTS
    // Source : Chart 25 Study 2 (ES) / Chart 23 Study 25 (NQ)
    //          Chart 30 Study 7 pour Blind Spots ES (valeurs actives !)
    // ─────────────────────────────────────────────────────────────────────────
    float mq_call;                       // sg0 — Call Resistance (mur Gamma Call)
    float mq_put;                        // sg1 — Put Support (mur Gamma Put)
    float mq_hvl;                        // sg2 — HVL (High Volume Level - point de flip)
    float mq_1d_min;                     // sg3 — Target BAS journée (MenthorQ daily range min)
    float mq_1d_max;                     // sg4 — Target HAUT journée (MenthorQ daily range max)
    float mq_gex[10];                    // sg9..18 — GEX niveaux 1 à 10
    float mq_blind[10];                  // sg0..9 — Blind Spots BL1 à BL10
    float mq_call_0dte;                  // sg5 — Call Resistance 0DTE
    float mq_put_0dte;                   // sg6 — Put Support 0DTE
    float mq_hvl_0dte;                   // sg7 — HVL 0DTE

    // ─────────────────────────────────────────────────────────────────────────
    // H. VIX
    // Source : Chart 15 prix courant + MenthorQ Gamma VIX
    // ─────────────────────────────────────────────────────────────────────────
    float vix_level;                     // Prix courant du VIX
    float vix_call;                      // sg0 VIX Chart15 — Résistance Call VIX
    float vix_put;                       // sg1 VIX Chart15 — Support Put VIX
    float vix_hvl;                       // sg2 VIX Chart15 — HVL VIX (zone de flip)

    // ─────────────────────────────────────────────────────────────────────────
    // I. VOLUME PROFILE — SESSION COURANTE
    // Source : Chart 26 Study 1 (ES) / Chart 27 Study 1 (NQ)
    // ─────────────────────────────────────────────────────────────────────────
    float cur_vpoc;                      // sg1 — VPOC session courante
    float cur_vah;                       // sg2 — VAH session courante
    float cur_val;                       // sg3 — VAL session courante
    float cur_vwap_vp;                   // sg4 — VWAP VP session courante

    // ─────────────────────────────────────────────────────────────────────────
    // J. VOLUME PROFILE — SESSION PRÉCÉDENTE
    // Source : Chart 26 Study 2 (ES) / Chart 27 Study 2 (NQ)
    // ⚠️  Valeurs nulles hors session — à rescanner Lundi 14h00 FR
    // ─────────────────────────────────────────────────────────────────────────
    float prev_vpoc;                     // sg1 — PVPOC (pivot central J-1)
    float prev_vah;                      // sg2 — PVAH (résistance VA J-1)
    float prev_val;                      // sg3 — PVAL (support VA J-1)
    float prev_vwap;                     // sg4 — PVWAP

    // ─────────────────────────────────────────────────────────────────────────
    // K. PREVIOUS VWAP SD+1/-1
    // Source : Chart 26 Study 4 (ES) / Chart 27 Study 4 (NQ)
    // ─────────────────────────────────────────────────────────────────────────
    float prev_vwap_sd1u;                // sg12 — PVWAP +1σ
    float prev_vwap_sd1d;                // sg13 — PVWAP -1σ

    // ─────────────────────────────────────────────────────────────────────────
    // L. SESSION IB & OHLC
    // Source : Chart 25/23 (barres) + Chart 26/27 Study 29 (OHLC)
    // ─────────────────────────────────────────────────────────────────────────
    float open_830;                      // Open 08h30 ET (pré-market tardif)
    float sess_high;                     // High session courante (RTH)
    float sess_low;                      // Low session courante (RTH)
    float ib_high;                       // IB High = Max(High 9h30-10h30) ← calculé
    float ib_low;                        // IB Low  = Min(Low  9h30-10h30) ← calculé
    float open_cash;                     // Open exact 9h30 ET ← calculé depuis OHLC session

    // ─────────────────────────────────────────────────────────────────────────
    // M. OVERNIGHT HIGH/LOW
    // Source : Chart 30/31 Studies 10/11 (HIGHER HIGH / LOWER LOW)
    // ─────────────────────────────────────────────────────────────────────────
    float ovn_high;                      // High session 18h00-9h29 ET
    float ovn_low;                       // Low session 18h00-9h29 ET

    // ─────────────────────────────────────────────────────────────────────────
    // N. CVD & SWING HIGH/LOW
    // Source : Chart 28 (ES) / Chart 29 (NQ)
    // ─────────────────────────────────────────────────────────────────────────
    float cvd_close;                     // CVD Study sg3 — CVD Close barre courante
    float cvd_ohlc_open;                 // CVD OHLC sg0 — Open CVD (contexte swing)
    float cvd_ohlc_high;                 // CVD OHLC sg1 — High CVD
    float cvd_ohlc_low;                  // CVD OHLC sg2 — Low CVD
    float swing_high;                    // SWING sg0 — Dernier Swing High validé
    float swing_low;                     // SWING sg1 — Dernier Swing Low validé
    float delta_div_buy;                 // DELTA_DIV_BUY sg0 — Divergence delta bullish
    float delta_div_sell;                // DELTA_DIV_SELL sg0 — Divergence delta bearish
    float vp_session_vpoc;               // VP_SESSION sg1 — VPOC session CVD chart

    // ─────────────────────────────────────────────────────────────────────────
    // O. COMPOSITE PROFILES (20/50/100/200 jours)
    // Source : Chart 30 (ES) / Chart 31 (NQ)
    // ─────────────────────────────────────────────────────────────────────────
    float comp_20d_vpoc;
    float comp_20d_vah;
    float comp_20d_val;
    float comp_50d_vpoc;
    float comp_50d_vah;
    float comp_50d_val;

    // ─────────────────────────────────────────────────────────────────────────
    // P. STATUS & DIAGNOSTICS
    // ─────────────────────────────────────────────────────────────────────────
    int     read_errors;                 // Nombre de lectures en erreur cette barre
    bool    is_rth_session;              // true si dans session RTH (9h30-16h00 ET)
    bool    ib_complete;                 // true si IB formée (heure >= 10h30 ET)
    char    error_detail[256];           // Détail erreurs pour diagnostic

};

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 3 — HELPER : LECTURE SÉCURISÉE
// ═══════════════════════════════════════════════════════════════════════════════

// Lecture d'une valeur d'une étude d'un autre chart.
// Retourne DMP_INVALID si le chart/study n'est pas disponible ou la valeur
// est NaN/Inf. Ne génère jamais d'exception.

inline float DMP_SafeRead(
    SCStudyInterfaceRef sc,
    int                 chart_number,
    int                 study_id,
    int                 subgraph_index,
    int                 bar_offset = 0)    // 0=barre courante, 1=barre précédente...
{
    if (study_id < 0) return DMP_INVALID;  // ID invalide (== -1 dans study_mapping)

    SCFloatArray arr;
    int result = sc.GetStudyArrayFromChartUsingID(chart_number, study_id, subgraph_index, arr);

    if (result == 0) return DMP_INVALID;   // Chart/Study pas disponible

    int idx = sc.Index - bar_offset;
    if (idx < 0 || idx >= (int)arr.Size()) return DMP_INVALID;

    float val = arr[idx];

    // Rejeter NaN, Inf, et la valeur sentinelle Sierra Chart (1e38)
    if (!std::isfinite(val)) return DMP_INVALID;
    if (val >= 1e37f)        return DMP_INVALID;   // Sentinel Sierra Chart

    return val;
}

// Version qui retourne 0.0f si invalide (pour les booléens/signaux)
inline float DMP_SafeReadBool(SCStudyInterfaceRef sc, int chart, int study, int sg) {
    float v = DMP_SafeRead(sc, chart, study, sg);
    return (v == DMP_INVALID) ? 0.0f : v;
}

// Vérification si une valeur est valide (non-sentinelle)
inline bool DMP_IsValid(float v) {
    return (v != DMP_INVALID) && std::isfinite(v);
}

// Vérification si un niveau de prix est cohérent (entre 100 et 100000)
inline bool DMP_IsPriceValid(float price) {
    return DMP_IsValid(price) && (price > 100.0f) && (price < 100000.0f);
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 4 — FONCTIONS DE LECTURE PAR SECTION
// ═══════════════════════════════════════════════════════════════════════════════

// ─────────────────────────────────────────────────────────────────────────────
// FPBS — Footprint Bar Study
// ─────────────────────────────────────────────────────────────────────────────

inline void DMP_ReadFPBS(SCStudyInterfaceRef sc, DMP_RawData& d) {
    const int chart = d.is_nq ? DMP_Charts::NQ_FP  : DMP_Charts::ES_FP;
    const int study = d.is_nq ? DMP_Studies::NQ_FP::FPBS : DMP_Studies::ES_FP::FPBS;

    d.fpbs_delta         = DMP_SafeRead(sc, chart, study,  0);
    d.fpbs_delta_change  = DMP_SafeRead(sc, chart, study,  2);
    d.fpbs_pos_delta     = DMP_SafeRead(sc, chart, study,  3);
    d.fpbs_neg_delta     = DMP_SafeRead(sc, chart, study,  4);
    d.fpbs_max_delta     = DMP_SafeRead(sc, chart, study,  7);
    d.fpbs_min_delta     = DMP_SafeRead(sc, chart, study,  8);
    d.fpbs_delta_day     = DMP_SafeRead(sc, chart, study,  9);
    d.fpbs_volume        = DMP_SafeRead(sc, chart, study, 12);
    d.fpbs_avg_size      = DMP_SafeRead(sc, chart, study, 14);
    d.fpbs_ask_pct       = DMP_SafeRead(sc, chart, study, 16);
    d.fpbs_bid_pct       = DMP_SafeRead(sc, chart, study, 17);
    d.fpbs_cvd_day       = DMP_SafeRead(sc, chart, study, 18);
    d.fpbs_poc_vol       = DMP_SafeRead(sc, chart, study, 19);
    d.fpbs_cvd_high      = DMP_SafeRead(sc, chart, study, 20);
    d.fpbs_cvd_low       = DMP_SafeRead(sc, chart, study, 21);
    d.fpbs_bar_duration  = DMP_SafeRead(sc, chart, study, 29);
    d.fpbs_finish        = DMP_SafeRead(sc, chart, study, 33);
    d.fpbs_vol_per_sec   = DMP_SafeRead(sc, chart, study, 35);
    d.fpbs_hl_range      = DMP_SafeRead(sc, chart, study, 40);
    d.fpbs_poc_price     = DMP_SafeRead(sc, chart, study, 41);
    d.fpbs_avg_bid_size  = DMP_SafeRead(sc, chart, study, 50);
    d.fpbs_avg_ask_size  = DMP_SafeRead(sc, chart, study, 51);
}

// ─────────────────────────────────────────────────────────────────────────────
// ROTATION & CLUSTER
// ─────────────────────────────────────────────────────────────────────────────

inline void DMP_ReadRotation(SCStudyInterfaceRef sc, DMP_RawData& d) {
    const int chart   = d.is_nq ? DMP_Charts::NQ_FP : DMP_Charts::ES_FP;
    const int rot_id  = d.is_nq ? DMP_Studies::NQ_FP::ROTATION    : DMP_Studies::ES_FP::ROTATION;
    const int rup_id  = d.is_nq ? DMP_Studies::NQ_FP::ROTATION_UP : DMP_Studies::ES_FP::ROTATION_UP;
    const int rdn_id  = d.is_nq ? DMP_Studies::NQ_FP::ROTATION_DN : DMP_Studies::ES_FP::ROTATION_DN;

    d.rotation_value     = DMP_SafeRead(sc, chart, rot_id, 0);
    d.rotation_zz_mid    = DMP_SafeRead(sc, chart, rot_id, 6);
    d.rotation_zz_osc    = DMP_SafeRead(sc, chart, rot_id, 8);
    d.rotation_up_signal = DMP_SafeReadBool(sc, chart, rup_id, 0);
    d.rotation_dn_signal = DMP_SafeReadBool(sc, chart, rdn_id, 0);

    // Cluster Volume (ES seulement)
    if (!d.is_nq) {
        d.cluster_0 = DMP_SafeRead(sc, chart, DMP_Studies::ES_FP::CLUSTER, 0);
        d.cluster_1 = DMP_SafeRead(sc, chart, DMP_Studies::ES_FP::CLUSTER, 1);
    } else {
        d.cluster_0 = DMP_INVALID;
        d.cluster_1 = DMP_INVALID;
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// SIGNAUX BATAILLE NAVALE
// ─────────────────────────────────────────────────────────────────────────────

inline void DMP_ReadBNSignals(SCStudyInterfaceRef sc, DMP_RawData& d) {
    const int chart = d.is_nq ? DMP_Charts::NQ_FP : DMP_Charts::ES_FP;

    d.bn_color_up   = DMP_SafeReadBool(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_FP::COLOR_UP   : DMP_Studies::ES_FP::COLOR_UP,   0);
    d.bn_color_dn   = DMP_SafeReadBool(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_FP::COLOR_DN   : DMP_Studies::ES_FP::COLOR_DN,   0);
    d.bn_absorb_ask = DMP_SafeReadBool(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_FP::ABSORB_ASK : DMP_Studies::ES_FP::ABSORB_ASK, 0);
    d.bn_absorb_bid = DMP_SafeReadBool(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_FP::ABSORB_BID : DMP_Studies::ES_FP::ABSORB_BID, 0);
    d.bn_long_up    = DMP_SafeReadBool(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_FP::LONG_UP    : DMP_Studies::ES_FP::LONG_UP,    0);
    d.bn_long_dn    = DMP_SafeReadBool(sc, chart,
                        d.is_nq ? DMP_Studies::NQ_FP::LONG_DN    : DMP_Studies::ES_FP::LONG_DN,    0);

    // ES = Double Ask/Bid — NQ = Triple Ask/Bid
    if (!d.is_nq) {
        d.bn_double_ask  = DMP_SafeReadBool(sc, chart, DMP_Studies::ES_FP::DOUBLE_ASK, 0);
        d.bn_double_bid  = DMP_SafeReadBool(sc, chart, DMP_Studies::ES_FP::DOUBLE_BID, 0);
        d.bn_triple_ask  = DMP_BOOL_FALSE;
        d.bn_triple_bid  = DMP_BOOL_FALSE;
    } else {
        d.bn_double_ask  = DMP_BOOL_FALSE;
        d.bn_double_bid  = DMP_BOOL_FALSE;
        d.bn_triple_ask  = DMP_SafeReadBool(sc, chart, DMP_Studies::NQ_FP::TRIPLE_ASK, 0);
        d.bn_triple_bid  = DMP_SafeReadBool(sc, chart, DMP_Studies::NQ_FP::TRIPLE_BID, 0);
    }

    // Big Orders ASK/BID +100 (10 niveaux) — ES seulement (NQ = -1 dans mapping)
    if (!d.is_nq) {
        for (int i = 0; i < 10; i++) {
            d.bn_ask100[i] = DMP_SafeRead(sc, chart, DMP_Studies::ES_FP::ASK_100, i);
            d.bn_bid100[i] = DMP_SafeRead(sc, chart, DMP_Studies::ES_FP::BID_100, i);
        }
    } else {
        for (int i = 0; i < 10; i++) {
            d.bn_ask100[i] = DMP_INVALID;
            d.bn_bid100[i] = DMP_INVALID;
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// VWAP JOURNALIER
// Source : Chart VP (26=ES / 27=NQ) Study 3 — c'est là que le VWAP journalier
//          a des valeurs actives. Chart FP (1/2) VWAP studies retournent null.
// ─────────────────────────────────────────────────────────────────────────────

inline void DMP_ReadVWAPDay(SCStudyInterfaceRef sc, DMP_RawData& d) {
    // VP Chart = source VWAP journalier fiable
    const int chart = d.is_nq ? DMP_Charts::NQ_VP : DMP_Charts::ES_VP;
    const int study = d.is_nq ? DMP_Studies::NQ_VP::VWAP_DAY : DMP_Studies::ES_VP::VWAP_DAY;

    d.vwap_day      = DMP_SafeRead(sc, chart, study, 0);
    d.vwap_day_sd1u = DMP_SafeRead(sc, chart, study, 1);
    d.vwap_day_sd1d = DMP_SafeRead(sc, chart, study, 2);
    d.vwap_day_sd2u = DMP_SafeRead(sc, chart, study, 3);
    d.vwap_day_sd2d = DMP_SafeRead(sc, chart, study, 4);

    // ── VWAP Slope (pente points/barre) ────────────────────────────────────
    // Formule identique à l'ancien dumper : (vwap_now - vwap_N_ago) / N
    // Critique pour Layer 3 : vwap_slope > 0 = contexte haussier
    if (DMP_IsValid(d.vwap_day) && d.vwap_day > 0.0f) {
        SCFloatArray vwap_arr;
        sc.GetStudyArrayFromChartUsingID(chart, study, 0, vwap_arr);

        // Slope 10 barres
        if (sc.Index >= 10) {
            float v10 = vwap_arr[sc.Index - 10];
            if (v10 > 0.0f && std::isfinite(v10))
                d.vwap_slope_10 = (d.vwap_day - v10) / 10.0f;
        }
        // Slope 30 barres
        if (sc.Index >= 30) {
            float v30 = vwap_arr[sc.Index - 30];
            if (v30 > 0.0f && std::isfinite(v30))
                d.vwap_slope_30 = (d.vwap_day - v30) / 30.0f;
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// VWAP WEEKLY & MONTHLY + ATR + MA (Daily Charts)
// ─────────────────────────────────────────────────────────────────────────────

inline void DMP_ReadDaily(SCStudyInterfaceRef sc, DMP_RawData& d) {
    const int chart = d.is_nq ? DMP_Charts::NQ_DAILY : DMP_Charts::ES_DAILY;

    // ATR
    d.atr_daily = DMP_SafeRead(sc, chart,
                    d.is_nq ? DMP_Studies::NQ_DAILY::ATR : DMP_Studies::ES_DAILY::ATR, 0);

    // Moving Averages
    const int ma_id = d.is_nq ? DMP_Studies::NQ_DAILY::MA : DMP_Studies::ES_DAILY::MA;
    d.ma_fast = DMP_SafeRead(sc, chart, ma_id, 0);
    d.ma_slow = DMP_SafeRead(sc, chart, ma_id, 1);

    // VWAP Weekly (Study 4) ⚠️ À confirmer Lundi
    const int vww_id = d.is_nq ? DMP_Studies::NQ_DAILY::VWAP_WEEKLY : DMP_Studies::ES_DAILY::VWAP_WEEKLY;
    d.vwap_weekly      = DMP_SafeRead(sc, chart, vww_id, 0);
    d.vwap_weekly_sd1u = DMP_SafeRead(sc, chart, vww_id, 1);
    d.vwap_weekly_sd1d = DMP_SafeRead(sc, chart, vww_id, 2);

    // VWAP Monthly (Study 5) ⚠️ À confirmer Lundi
    const int vwm_id = d.is_nq ? DMP_Studies::NQ_DAILY::VWAP_MONTHLY : DMP_Studies::ES_DAILY::VWAP_MONTHLY;
    d.vwap_monthly      = DMP_SafeRead(sc, chart, vwm_id, 0);
    d.vwap_monthly_sd1u = DMP_SafeRead(sc, chart, vwm_id, 1);
    d.vwap_monthly_sd1d = DMP_SafeRead(sc, chart, vwm_id, 2);
}

// ─────────────────────────────────────────────────────────────────────────────
// MENTHORQ — GAMMA LEVELS & BLIND SPOTS
// ─────────────────────────────────────────────────────────────────────────────

inline void DMP_ReadMenthorQ(SCStudyInterfaceRef sc, DMP_RawData& d) {

    // Chart ES_BARRES (25) Study 2 pour ES / Chart NQ_BARRES (23) Study 25 pour NQ
    const int chart_g  = d.is_nq ? DMP_Charts::NQ_BARRES : DMP_Charts::ES_BARRES;
    const int study_g  = d.is_nq ? DMP_Studies::NQ_BARRES::MQ_GAMMA : DMP_Studies::ES_BARRES::MQ_GAMMA;

    d.mq_call      = DMP_SafeRead(sc, chart_g, study_g, 0);
    d.mq_put       = DMP_SafeRead(sc, chart_g, study_g, 1);
    d.mq_hvl       = DMP_SafeRead(sc, chart_g, study_g, 2);
    // sg3=1d_min / sg4=1d_max — targets de range journalier MenthorQ
    // Confirmé dans l'ancien dumper (GetMenthorQGammaLevelType case 3/4)
    d.mq_1d_min    = DMP_SafeRead(sc, chart_g, study_g, 3);
    d.mq_1d_max    = DMP_SafeRead(sc, chart_g, study_g, 4);
    d.mq_call_0dte = DMP_SafeRead(sc, chart_g, study_g, 5);
    d.mq_put_0dte  = DMP_SafeRead(sc, chart_g, study_g, 6);
    d.mq_hvl_0dte  = DMP_SafeRead(sc, chart_g, study_g, 7);

    // GEX 1..10 → sg9..18
    for (int i = 0; i < 10; i++) {
        d.mq_gex[i] = DMP_SafeRead(sc, chart_g, study_g, 9 + i);
    }

    // Blind Spots
    // ES : Chart 31 Study 7 — ⚠️ à confirmer Lundi (scan montrait Chart 30 = NQ)
    // NQ : Chart 30 Study 7 — ✅ CONFIRMÉ scan JSON : 10 valeurs actives BL1-10
    if (!d.is_nq) {
        // ES Blind Spots — Study 7 sur Chart 31 (ES_COMPOSITE)
        // ⚠️ À vérifier Lundi : peut-être que les Blind Spots ES sont sur chart FP
        const int study_bs = DMP_Studies::ES_COMPOSITE::MQ_BLIND;
        for (int i = 0; i < 10; i++) {
            float v = DMP_SafeRead(sc, DMP_Charts::ES_COMPOSITE, study_bs, i);
            d.mq_blind[i] = DMP_IsPriceValid(v) ? v : DMP_INVALID;
        }
    } else {
        // NQ Blind Spots — Chart 30 Study 7 : CONFIRMÉ ✅
        const int study_bs = DMP_Studies::NQ_COMPOSITE::MQ_BLIND;
        for (int i = 0; i < 10; i++) {
            float v = DMP_SafeRead(sc, DMP_Charts::NQ_COMPOSITE, study_bs, i);
            d.mq_blind[i] = DMP_IsPriceValid(v) ? v : DMP_INVALID;
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// VIX
// ─────────────────────────────────────────────────────────────────────────────

inline void DMP_ReadVIX(SCStudyInterfaceRef sc, DMP_RawData& d) {
    // Prix courant VIX = Close du chart 15
    SCFloatArray close_arr;
    int r = sc.GetChartBaseData(DMP_Charts::VIX_MQ, SC_LAST, close_arr);
    d.vix_level = (r > 0 && sc.Index < (int)close_arr.Size())
                  ? close_arr[sc.Index] : DMP_INVALID;

    // Niveaux MenthorQ sur VIX
    d.vix_call = DMP_SafeRead(sc, DMP_Charts::VIX_MQ, DMP_Studies::VIX::MQ_GAMMA, 0);
    d.vix_put  = DMP_SafeRead(sc, DMP_Charts::VIX_MQ, DMP_Studies::VIX::MQ_GAMMA, 1);
    d.vix_hvl  = DMP_SafeRead(sc, DMP_Charts::VIX_MQ, DMP_Studies::VIX::MQ_GAMMA, 2);
}

// ─────────────────────────────────────────────────────────────────────────────
// VOLUME PROFILE — Session Courante & Précédente
// ─────────────────────────────────────────────────────────────────────────────

inline void DMP_ReadVolumeProfile(SCStudyInterfaceRef sc, DMP_RawData& d) {
    const int chart = d.is_nq ? DMP_Charts::NQ_VP : DMP_Charts::ES_VP;

    // VP Session courante
    const int vp_cur = d.is_nq ? DMP_Studies::NQ_VP::VP_CURRENT : DMP_Studies::ES_VP::VP_CURRENT;
    d.cur_vpoc     = DMP_SafeRead(sc, chart, vp_cur, 1);
    d.cur_vah      = DMP_SafeRead(sc, chart, vp_cur, 2);
    d.cur_val      = DMP_SafeRead(sc, chart, vp_cur, 3);
    d.cur_vwap_vp  = DMP_SafeRead(sc, chart, vp_cur, 4);

    // VP Session précédente (Previous)
    const int vp_prv = d.is_nq ? DMP_Studies::NQ_VP::VP_PREVIOUS : DMP_Studies::ES_VP::VP_PREVIOUS;
    d.prev_vpoc = DMP_SafeRead(sc, chart, vp_prv, 1);
    d.prev_vah  = DMP_SafeRead(sc, chart, vp_prv, 2);
    d.prev_val  = DMP_SafeRead(sc, chart, vp_prv, 3);
    d.prev_vwap = DMP_SafeRead(sc, chart, vp_prv, 4);

    // Previous VWAP SD+1/-1
    const int vp_pvw = d.is_nq ? DMP_Studies::NQ_VP::VP_PREV_WAPS : DMP_Studies::ES_VP::VP_PREV_WAPS;
    d.prev_vwap_sd1u = DMP_SafeRead(sc, chart, vp_pvw, 12);
    d.prev_vwap_sd1d = DMP_SafeRead(sc, chart, vp_pvw, 13);
}

// ─────────────────────────────────────────────────────────────────────────────
// SESSION — IB, OHLC, Open Cash
// ─────────────────────────────────────────────────────────────────────────────

inline void DMP_ReadSession(SCStudyInterfaceRef sc, DMP_RawData& d) {
    const int chart_b = d.is_nq ? DMP_Charts::NQ_BARRES : DMP_Charts::ES_BARRES;
    const int chart_v = d.is_nq ? DMP_Charts::NQ_VP     : DMP_Charts::ES_VP;

    // Open 8h30 ET
    const int open_id = d.is_nq ? DMP_Studies::NQ_BARRES::OPEN_830 : DMP_Studies::ES_BARRES::OPEN_830;
    d.open_830 = DMP_SafeRead(sc, chart_b, open_id, 0);

    // Session High / Low (Higher High / Lower Low session courante)
    const int hh_id = d.is_nq ? DMP_Studies::NQ_BARRES::HH_SESSION : DMP_Studies::ES_BARRES::HH_SESSION;
    const int ll_id = d.is_nq ? DMP_Studies::NQ_BARRES::LL_SESSION : DMP_Studies::ES_BARRES::LL_SESSION;
    d.sess_high = DMP_SafeRead(sc, chart_b, hh_id, 1);   // sg1 = High
    d.sess_low  = DMP_SafeRead(sc, chart_b, ll_id, 2);   // sg2 = Low

    // IB = HIGHER HIGH / LOWER LOW CASH SESSION (9h30-10h30)
    const int hh_cash = d.is_nq ? DMP_Studies::NQ_BARRES::HH_CASH : DMP_Studies::ES_BARRES::HH_CASH;
    const int ll_cash = d.is_nq ? DMP_Studies::NQ_BARRES::LL_CASH : DMP_Studies::ES_BARRES::LL_CASH;
    d.ib_high = DMP_SafeRead(sc, chart_b, hh_cash, 1);   // sg1 = High
    d.ib_low  = DMP_SafeRead(sc, chart_b, ll_cash, 2);   // sg2 = Low

    // Open Cash 9h30 ET = Open de la première barre OHLC session RTH
    const int ohlc_id = d.is_nq ? DMP_Studies::NQ_VP::OHLC_SESSION : DMP_Studies::ES_VP::OHLC_SESSION;
    d.open_cash = DMP_SafeRead(sc, chart_v, ohlc_id, 0);  // sg0 = Open session
}

// ─────────────────────────────────────────────────────────────────────────────
// OVERNIGHT HIGH/LOW
// ─────────────────────────────────────────────────────────────────────────────

inline void DMP_ReadOVN(SCStudyInterfaceRef sc, DMP_RawData& d) {
    // Chart 30/31 Studies 10/11 (Higher High / Lower Low 18h→9h29 ET)
    const int chart = d.is_nq ? DMP_Charts::NQ_COMPOSITE : DMP_Charts::ES_COMPOSITE;

    d.ovn_high = DMP_SafeRead(sc, chart, DMP_Studies::ES_COMPOSITE::OVN_HIGH, 1); // sg1=High
    d.ovn_low  = DMP_SafeRead(sc, chart, DMP_Studies::ES_COMPOSITE::OVN_LOW,  2); // sg2=Low

    // Validation cohérence par rapport au prix courant
    if (DMP_IsPriceValid(d.ovn_high) && DMP_IsPriceValid(d.price_close)) {
        float ratio = d.ovn_high / d.price_close;
        if (ratio < 0.8f || ratio > 1.2f) {
            // OVN aberrant (>20% d'écart) → invalider
            d.ovn_high = DMP_INVALID;
            d.ovn_low  = DMP_INVALID;
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// CVD & SWING HIGH/LOW
// ─────────────────────────────────────────────────────────────────────────────

inline void DMP_ReadCVD(SCStudyInterfaceRef sc, DMP_RawData& d) {
    const int chart    = d.is_nq ? DMP_Charts::NQ_CVD : DMP_Charts::ES_CVD;
    const int cvd_id   = d.is_nq ? DMP_Studies::NQ_CVD::CVD   : DMP_Studies::ES_CVD::CVD;
    const int ohlc_id  = d.is_nq ? DMP_Studies::NQ_CVD::CVD_OHLC : DMP_Studies::ES_CVD::CVD_OHLC;
    const int swing_id = d.is_nq ? DMP_Studies::NQ_CVD::SWING : DMP_Studies::ES_CVD::SWING;
    const int vp_id    = d.is_nq ? DMP_Studies::NQ_CVD::VP_SESSION : DMP_Studies::ES_CVD::VP_SESSION;
    const int div_buy  = d.is_nq ? DMP_Studies::NQ_CVD::DELTA_DIV_BUY  : DMP_Studies::ES_CVD::DELTA_DIV_BUY;
    const int div_sell = d.is_nq ? DMP_Studies::NQ_CVD::DELTA_DIV_SELL : DMP_Studies::ES_CVD::DELTA_DIV_SELL;

    // CVD Close (valeur cumulée)
    d.cvd_close     = DMP_SafeRead(sc, chart, cvd_id, 3);   // sg3=Close CVD

    // CVD OHLC (contexte swing)
    d.cvd_ohlc_open = DMP_SafeRead(sc, chart, ohlc_id, 0);
    d.cvd_ohlc_high = DMP_SafeRead(sc, chart, ohlc_id, 1);
    d.cvd_ohlc_low  = DMP_SafeRead(sc, chart, ohlc_id, 2);

    // Swing High/Low
    d.swing_high = DMP_SafeRead(sc, chart, swing_id, 0);
    d.swing_low  = DMP_SafeRead(sc, chart, swing_id, 1);

    // VPOC session courante (chart CVD)
    d.vp_session_vpoc = DMP_SafeRead(sc, chart, vp_id, 1);

    // Divergences Delta
    d.delta_div_buy  = DMP_SafeReadBool(sc, chart, div_buy,  0);
    d.delta_div_sell = DMP_SafeReadBool(sc, chart, div_sell, 0);
}

// ─────────────────────────────────────────────────────────────────────────────
// COMPOSITE PROFILES (contexte long terme)
// ─────────────────────────────────────────────────────────────────────────────

inline void DMP_ReadComposite(SCStudyInterfaceRef sc, DMP_RawData& d) {
    const int chart  = d.is_nq ? DMP_Charts::NQ_COMPOSITE : DMP_Charts::ES_COMPOSITE;
    const int id_20d = d.is_nq ? DMP_Studies::NQ_COMPOSITE::COMP_20D : DMP_Studies::ES_COMPOSITE::COMP_20D;
    const int id_50d = d.is_nq ? DMP_Studies::NQ_COMPOSITE::COMP_50D : DMP_Studies::ES_COMPOSITE::COMP_50D;

    d.comp_20d_vpoc = DMP_SafeRead(sc, chart, id_20d, 1);
    d.comp_20d_vah  = DMP_SafeRead(sc, chart, id_20d, 2);
    d.comp_20d_val  = DMP_SafeRead(sc, chart, id_20d, 3);
    d.comp_50d_vpoc = DMP_SafeRead(sc, chart, id_50d, 1);
    d.comp_50d_vah  = DMP_SafeRead(sc, chart, id_50d, 2);
    d.comp_50d_val  = DMP_SafeRead(sc, chart, id_50d, 3);
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 5 — FONCTION MAÎTRE : DMP_ReadAll()
// ═══════════════════════════════════════════════════════════════════════════════
// Remplit un DMP_RawData complet depuis la barre courante du chart hôte.
// Appeler une SEULE fois par barre (pattern Sierra Chart : if (sc.IsNewBar()) ).

inline void DMP_ReadAll(SCStudyInterfaceRef sc, DMP_RawData& d, bool is_nq) {

    // ── 0. Initialisation — TOUS les floats à DMP_INVALID ────────────────────
    // memset à 0 ne suffit pas : 0.0f est indistinguable d'une vraie valeur nulle.
    // Tous les floats prix/mesure → DMP_INVALID, booléens → 0 (BOOL_FALSE).
    // NON PAS memset : ça met les floats à 0.0f qui est une valeur valide.
    memset(&d, 0, sizeof(DMP_RawData));

    // Floats prix et mesures → DMP_INVALID (valeur sentinelle)
    d.atr_daily = d.ma_fast = d.ma_slow = DMP_INVALID;
    d.vwap_day = d.vwap_day_sd1u = d.vwap_day_sd1d = DMP_INVALID;
    d.vwap_day_sd2u = d.vwap_day_sd2d = DMP_INVALID;
    d.vwap_slope_10 = d.vwap_slope_30 = DMP_INVALID;
    d.vwap_weekly = d.vwap_weekly_sd1u = d.vwap_weekly_sd1d = DMP_INVALID;
    d.vwap_monthly = d.vwap_monthly_sd1u = d.vwap_monthly_sd1d = DMP_INVALID;
    d.mq_call = d.mq_put = d.mq_hvl = DMP_INVALID;
    d.mq_1d_min = d.mq_1d_max = DMP_INVALID;
    d.mq_call_0dte = d.mq_put_0dte = d.mq_hvl_0dte = DMP_INVALID;
    d.vix_level = d.vix_call = d.vix_put = d.vix_hvl = DMP_INVALID;
    d.cur_vpoc = d.cur_vah = d.cur_val = d.cur_vwap_vp = DMP_INVALID;
    d.prev_vpoc = d.prev_vah = d.prev_val = d.prev_vwap = DMP_INVALID;
    d.prev_vwap_sd1u = d.prev_vwap_sd1d = DMP_INVALID;
    d.ib_high = d.ib_low = d.open_cash = DMP_INVALID;
    d.open_830 = d.sess_high = d.sess_low = DMP_INVALID;
    d.ovn_high = d.ovn_low = DMP_INVALID;
    d.cvd_close = d.cvd_ohlc_open = d.cvd_ohlc_high = d.cvd_ohlc_low = DMP_INVALID;
    d.swing_high = d.swing_low = d.vp_session_vpoc = DMP_INVALID;
    d.comp_20d_vpoc = d.comp_20d_vah = d.comp_20d_val = DMP_INVALID;
    d.comp_50d_vpoc = d.comp_50d_vah = d.comp_50d_val = DMP_INVALID;
    d.fpbs_delta = d.fpbs_delta_change = d.fpbs_poc_price = DMP_INVALID;
    d.fpbs_avg_size = d.fpbs_avg_bid_size = d.fpbs_avg_ask_size = DMP_INVALID;
    d.fpbs_bar_duration = d.fpbs_vol_per_sec = d.fpbs_hl_range = DMP_INVALID;
    d.rotation_value = d.rotation_zz_mid = d.rotation_zz_osc = DMP_INVALID;
    d.cluster_0 = d.cluster_1 = DMP_INVALID;
    for (int i = 0; i < 10; i++) {
        d.mq_gex[i] = d.mq_blind[i] = DMP_INVALID;
        d.bn_ask100[i] = d.bn_bid100[i] = DMP_INVALID;
    }
    // Booléens BN → 0 (BOOL_FALSE) — laissés à 0 par memset, correct.

    // ── 1. Identification ──────────────────────────────────────────────────
    d.is_nq      = is_nq;
    d.bar_index  = sc.Index;
    d.price_close = (float)sc.Close[sc.Index];
    d.price_open  = (float)sc.Open[sc.Index];
    d.price_high  = (float)sc.High[sc.Index];
    d.price_low   = (float)sc.Low[sc.Index];
    d.tick_size   = (float)sc.TickSize;

    // Timestamp Unix ms — utiliser l'heure de la BARRE (données marché), pas l'heure PC
    // sc.BaseDateTimeIn[sc.Index] = datetime de la barre en cours
    SCDateTime bar_time = sc.BaseDateTimeIn[sc.Index];
    d.timestamp_ms = bar_time.GetAsSecondsSince1970() * 1000LL;

    // Session RTH ? — depuis l'heure de la BARRE (même cohérence que DMP_OpenType.h)
    int h = 0, m = 0, s = 0;
    bar_time.GetTimeHMS(h, m, s);
    int time_et = h * 60 + m;  // Sierra Chart configuré en ET (Eastern Time)
    d.is_rth_session = (time_et >= 9 * 60 + 30) && (time_et < 16 * 60);
    d.ib_complete    = (time_et >= 10 * 60 + 30);

    d.read_errors = 0;
    d.error_detail[0] = '\0';

    // ── 2. Lecture par sections ────────────────────────────────────────────
    DMP_ReadFPBS(sc, d);
    DMP_ReadRotation(sc, d);
    DMP_ReadBNSignals(sc, d);
    DMP_ReadVWAPDay(sc, d);
    DMP_ReadDaily(sc, d);
    DMP_ReadMenthorQ(sc, d);
    DMP_ReadVIX(sc, d);
    DMP_ReadVolumeProfile(sc, d);
    DMP_ReadSession(sc, d);
    DMP_ReadOVN(sc, d);
    DMP_ReadCVD(sc, d);
    DMP_ReadComposite(sc, d);

    // ── 3. Validation ATR (critique — dénominateur de toutes les normes) ──
    if (!DMP_IsValid(d.atr_daily) || d.atr_daily < 1.0f) {
        // Fallback : ATR estimé comme 1% du prix
        d.atr_daily = d.price_close * 0.01f;
        d.read_errors++;
        snprintf(d.error_detail, sizeof(d.error_detail),
                 "WARN: ATR_DAILY invalide → fallback %.2f", d.atr_daily);
    }

    // ── 4. Validation prix courant ─────────────────────────────────────────
    if (!DMP_IsPriceValid(d.price_close)) {
        d.read_errors++;
        // Pas de fallback possible pour le prix courant
        snprintf(d.error_detail + strlen(d.error_detail),
                 sizeof(d.error_detail) - strlen(d.error_detail),
                 " | ERR: PRICE_CLOSE invalide %.2f", d.price_close);
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTION 6 — DIAGNOSTIC (mode debug)
// ═══════════════════════════════════════════════════════════════════════════════

inline void DMP_LogStatus(SCStudyInterfaceRef sc, const DMP_RawData& d) {
    char msg[512];
    snprintf(msg, sizeof(msg),
        "[DMP_Reader] %s | Price=%.2f ATR=%.2f | "
        "VWAP_D=%s VWAP_W=%s VWAP_M=%s | "
        "PVPOC=%s PVAH=%s PVAL=%s | "
        "IB_H=%s IB_L=%s | OVN_H=%s OVN_L=%s | "
        "BN_UP=%.0f BN_DN=%.0f | DELTA=%.0f | Errors=%d",
        d.is_nq ? "NQ" : "ES",
        d.price_close,
        d.atr_daily,
        DMP_IsValid(d.vwap_day)     ? "OK" : "??",
        DMP_IsValid(d.vwap_weekly)  ? "OK" : "??",
        DMP_IsValid(d.vwap_monthly) ? "OK" : "??",
        DMP_IsValid(d.prev_vpoc)    ? "OK" : "??",
        DMP_IsValid(d.prev_vah)     ? "OK" : "??",
        DMP_IsValid(d.prev_val)     ? "OK" : "??",
        DMP_IsValid(d.ib_high)      ? "OK" : "??",
        DMP_IsValid(d.ib_low)       ? "OK" : "??",
        DMP_IsValid(d.ovn_high)     ? "OK" : "??",
        DMP_IsValid(d.ovn_low)      ? "OK" : "??",
        d.bn_color_up,
        d.bn_color_dn,
        DMP_IsValid(d.fpbs_delta) ? d.fpbs_delta : 0.0f,
        d.read_errors
    );
    sc.AddMessageToLog(msg, d.read_errors > 0 ? 1 : 0);
}

// ═══════════════════════════════════════════════════════════════════════════════
// FIN DMP_Reader.h
// ═══════════════════════════════════════════════════════════════════════════════
