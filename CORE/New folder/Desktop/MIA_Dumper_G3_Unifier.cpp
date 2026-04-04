// (Déplacé plus bas après les définitions Sierra/SCString et caches)
// === MIA_Dumper_G3_Core - unifier.cpp (header inlined - Approach 1) ===
// Utilities previously in "mia_dump_utils.hpp" are embedded below to allow
// single-file remote builds on Sierra Chart.
// NOUVEAU: Dumper unifie pour collecter TOUTES les donnees sur Chart 3

// --- MIA local config (optional) -------------------------------------------
#if defined(__has_include)
  #if __has_include("mia_local_config.h")
    #include "mia_local_config.h"
  #endif
#endif
// ---------------------------------------------------------------------------

// Protection contre les conflits de macros Sierra Chart - AVANT tout include
#ifdef max
#undef max
#endif
#ifdef min
#undef min
#endif

#include <time.h>
#include <cmath>
#include <unordered_map>
#include <string>
#include <vector>
#include <algorithm>
#include <deque>
#include <optional>
#include <cstring>
#include <chrono>
#include <array>
#include <limits>
#include <cfloat>


// Ré-inclure les protections après les headers C++
#ifdef max
#undef max
#endif
#ifdef min
#undef min
#endif

#include "sierrachart.h"
#ifdef _WIN32
  #include <windows.h>
#endif

// ZMQ opt-in: uniquement si MIA_HAVE_ZMQ est défini
#ifdef MIA_HAVE_ZMQ
  #include <zmq.h>
#endif

// === PATCH 1: includes & helpers START ===
#include <limits>
#include <mutex>

// Safe clamp for NaN/Inf
template<typename T>
static inline T clampFinite(T v, T fallback = (T)0) {
  if (std::isnan((double)v) || !std::isfinite((double)v)) return fallback;
  return v;
}
// Convert Sierra days to unix ms if needed
static inline long long daysToMs(double days) {
  // Sierra: days since 1899-12-30
  // Safer: always use sc.CurrentSystemDateTime.GetAsSecondsSince1970() instead
  const double seconds = (days * 86400.0);
  return (long long)std::llround(seconds * 1000.0);
}
// === PATCH 1: includes & helpers END ===

// Helper: crée récursivement les répertoires du chemin fourni (parent du fichier)
static void EnsureDirForFile(const char* fullPath) {
  if (!fullPath || !*fullPath) return;
  // Copie modifiable
  std::string p(fullPath);
  // Remplacer '/' par '\\' pour CreateDirectoryA
  for (auto& ch : p) if (ch == '/') ch = '\\';
  // Trouver dernier séparateur (répertoire parent)
  size_t pos = p.find_last_of('\\');
  if (pos == std::string::npos) return;
  std::string dir = p.substr(0, pos);
  // Créer récursivement
  std::string cur;
  for (size_t i = 0; i < dir.size(); ++i) {
    cur.push_back(dir[i]);
    if (dir[i] == '\\') {
      if (cur.size() > 3) CreateDirectoryA(cur.c_str(), NULL); // éviter "C:\"/"D:\"
    }
  }
  if (!dir.empty()) CreateDirectoryA(dir.c_str(), NULL);
}

// --- Helpers ML -------------------------------------------------------------
static inline double mia_clip(double x, double lo, double hi) {
  if (!std::isfinite(x)) return x;
  return (x < lo) ? lo : (x > hi ? hi : x);
}
static inline double mia_tanh(double x) {
  // std::tanh wrapper (assure la présence de <cmath>)
  return std::tanh(x);
}

using std::fabs;
using std::max;
using std::min;

// Forward decl for local static function defined later in file
static void WriteToDebugFile(const SCString& debugLine);

SCDLLName("MIA_Dumper_G3_Unifier")

// ========================= ML_READY — HELPERS =========================
// (Isolés: n'altèrent pas Unified JSON. Utilisent uniquement l'état/caches déjà présents.)

// === PATCH START: helpers & validator ======================================
static inline int sgn(double x) { return (x > 0) - (x < 0); }

static inline bool approx_eq(double a, double b, double eps=1e-6) {
    return std::fabs(a - b) <= eps;
}

static inline std::string json_num_or_null_safe(double v) {
    if (std::isfinite(v)) {
        char buf[64];
        std::snprintf(buf, sizeof(buf), "%.6f", v);
        return std::string(buf);
    }
    return "null";
}

// --- Precision helpers ------------------------------------------------------
inline double roundN(double x, int n) {
    if (!std::isfinite(x)) return x;
    const double p = std::pow(10.0, n);
    return std::round(x * p) / p;
}
// Anciens helpers supprimés - remplacés par format_* dans BuildMLReadyJSON15

// Validation forte de la cohérence ligne (L1 & ratios) + garde-fous dataset clean.
static inline bool ValidatePreWrite(
    double dom_bid1, double dom_ask1,
    double mid, double spread, int spread_ticks,
    int dom_bq1, int dom_aq1,
    double microprice, double askPct, double bidPct, double deltaPct,
    double tick, double total_volume, double volume_bar,
    // Nouveaux paramètres pour validation DOM vs BBO
    double best_bid, double best_ask, int q_bq1, int q_aq1
){
    // Validation L1 & ratios (existante)
    if (!approx_eq(mid, (dom_bid1 + dom_ask1) * 0.5)) return false;
    if (!approx_eq(spread, dom_ask1 - dom_bid1)) return false;
    if ( (int) llround(spread / tick) != spread_ticks ) return false;

    int sz = dom_bq1 + dom_aq1;
    if (sz > 0) {
        double mp = (dom_bid1 * (double)dom_aq1 + dom_ask1 * (double)dom_bq1) / (double)sz;
        if (!approx_eq(microprice, mp)) return false;
    }

    if (!std::isfinite(askPct) || !std::isfinite(bidPct) || !std::isfinite(deltaPct)) return false;
    if (!approx_eq(askPct + bidPct, 1.0, 1e-9)) return false;
    if (!approx_eq(deltaPct, askPct - bidPct, 1e-9)) return false;

    // === GARDE-FOUS DATASET CLEAN ===
    // 1. Cohérence total_volume vs volume_bar
    if (std::fabs(total_volume - volume_bar) > 0.0) return false;

    // 2. Validation DOM vs BBO (quasi-égalité ±1 tick max)
    double dom_bid_diff_ticks = std::fabs(dom_bid1 - best_bid) / tick;
    double dom_ask_diff_ticks = std::fabs(dom_ask1 - best_ask) / tick;
    if (dom_bid_diff_ticks > 1.0 || dom_ask_diff_ticks > 1.0) return false;

    // 3. Éviter DOM trop divergent du BBO (spread diff > 2 ticks)
    double dom_spread_ticks = (dom_ask1 - dom_bid1) / tick;
    double bbo_spread_ticks = (best_ask - best_bid) / tick;
    if (std::fabs(dom_spread_ticks - bbo_spread_ticks) > 2.0) return false;

    // === CHECKS EXPRESS POUR VALEURS RÉELLES SIERRA ===
    // 4. Ticking : spread doit être multiple de tick
    if (std::fabs(std::fmod(best_ask - best_bid, tick)) > 1e-6) return false;

    // 5. Microprice cohérence (tolérance 0.1 tick)
    if (q_bq1 > 0 || q_aq1 > 0) {
        double expected_microprice = (best_bid * (double)q_aq1 + best_ask * (double)q_bq1) / (double)(q_bq1 + q_aq1);
        if (std::fabs(microprice - expected_microprice) > 0.1 * tick) return false;
    }

    // 6. VWAPs cohérence (vwap_upN > vwap_dnN) - à ajouter si disponible
    // 7. Value Area cohérence (val < vpoc < vah) - à ajouter si disponible
    // 8. Échelles cohérentes (price_scale, point_value) - à ajouter si disponible

    return true;
}

// === PATCH END: helpers & validator ========================================

struct MLDepthFeatures {
  // bruts cumulés & par niveau
  int depth_bid_1=0, depth_ask_1=0;
  int depth_bid_2=0, depth_ask_2=0;
  int depth_bid_3=0, depth_ask_3=0;
  int depth_bid_5=0, depth_ask_5=0;
  int depth_bid_10=0, depth_ask_10=0;
  // normalisés (sur total 10 niveaux)
  double depth_bid_1_n=0, depth_ask_1_n=0;
  double depth_bid_2_n=0, depth_ask_2_n=0;
  double depth_bid_3_n=0, depth_ask_3_n=0;
  double depth_bid_5_n=0, depth_ask_5_n=0;
  double depth_bid_10_n=0, depth_ask_10_n=0;
  // rings (1), (2–3), (4–5), (6–10)
  int ring_bid_1=0, ring_ask_1=0;
  int ring_bid_2_3=0, ring_ask_2_3=0;
  int ring_bid_4_5=0, ring_ask_4_5=0;
  int ring_bid_6_10=0, ring_ask_6_10=0;
  double ring_imb_1=0, ring_imb_2_3=0, ring_imb_4_5=0, ring_imb_6_10=0;
  // imbalances par profondeur cumulée
  double imb_1=0, imb_2=0, imb_3=0, imb_5=0, imb_10=0;
  // slopes 1→3
  int    slope_bid_1_3=0, slope_ask_1_3=0;
  double slope_bid_1_3_n=0, slope_ask_1_3_n=0;
};

static inline double ml_safe_div(double a, double b) { return (b!=0.0 ? (a/b) : 0.0); }

// --- NEW: formateurs Month/Quarter pour meta MenthorQ
static inline void ML_FormatMonthQuarter(long long t_ms, SCString& month, SCString& quarter){
  // t_ms -> UTC
  time_t sec = (time_t)(t_ms/1000);
  struct tm gm{};
#ifdef _WIN32
  gmtime_s(&gm, &sec);
#else
  gmtime_r(&sec, &gm);
#endif
  char bufm[16]; snprintf(bufm, sizeof(bufm), "%04d-%02d", gm.tm_year+1900, gm.tm_mon+1);
  int q = (gm.tm_mon/3)+1;
  char bufq[16]; snprintf(bufq, sizeof(bufq), "%04dQ%d", gm.tm_year+1900, q);
  month = bufm; quarter = bufq;
}

// PATCH >>> includes & helpers
// --- Helpers JSON: bool, number or null
static inline std::string json_bool(bool v){ return v ? "true":"false"; }
static inline std::string json_num_or_null(double v){
    if (std::isfinite(v)) { std::ostringstream s; s.setf(std::ios::fixed); s<<std::setprecision(6)<<v; return s.str(); }
    return "null";
}
static inline std::string json_int_or_null(int v, bool valid){
    return valid ? std::to_string(v) : "null";
}

// PATCH >>> JSON helpers (précision stable & nulls strict)
static inline void j_null(std::ostringstream& os, const char* k){
  os << "\"" << k << "\":null";
}
static inline void j_str(std::ostringstream& os, const char* k, const char* v){
  os << "\"" << k << "\":\"" << v << "\"";
}
static inline void j_bool(std::ostringstream& os, const char* k, bool v){
  os << "\"" << k << "\":" << (v ? "true":"false");
}
static inline void j_int(std::ostringstream& os, const char* k, long long v){
  os << "\"" << k << "\":" << v;
}
static inline void j_price(std::ostringstream& os, const char* k, double v, int price_scale){
  if (std::isnan(v)) return j_null(os,k);
  std::ostringstream t; t.setf(std::ios::fixed); t.precision( (price_scale>0)?2:2 );
  t << v;
  os << "\"" << k << "\":" << t.str();
}
static inline void j_ratio(std::ostringstream& os, const char* k, double v, int decimals=6){
  if (std::isnan(v)) return j_null(os,k);
  std::ostringstream t; t.setf(std::ios::fixed); t.precision(decimals);
  t << v;
  os << "\"" << k << "\":" << t.str();
}
static inline double clamp01(double x){ return std::max(-1.0,std::min(1.0,x)); }
// PATCH <<< JSON helpers

// --- Division sûre pour features ML (pas de 0 silencieux)
static inline double ml_div_or_nan(double a, double b){
    return (b!=0.0 ? (a/b) : std::numeric_limits<double>::quiet_NaN());
}

// --- ML cache par (sym, chart)  — évite le mélange multi-charts
struct MLReadyCache {
    double ema_tick_rate_3s {0.0};
    double ema_trade_rate_3s{0.0};
    double ema_delta_rate_3s{0.0};
    double last10_delta[10]{0.0};
    int idx10{0};
    double sum10{0.0};
};
struct CacheKey {
    std::string sym;
    int chart;
    bool operator==(const CacheKey& other) const {
        return sym == other.sym && chart == other.chart;
    }
};
struct CacheKeyHash {
    size_t operator()(const CacheKey& k) const {
        return std::hash<std::string>()(k.sym) ^ (std::hash<int>()(k.chart)<<1);
    }
};
static std::unordered_map<CacheKey, MLReadyCache, CacheKeyHash> g_mlready_caches;

static inline double ema_update(double prev, double x, double alpha){
    return alpha*x + (1.0 - alpha)*prev;
}
// PATCH <<< includes & helpers

// ---------- Ancien cache global supprimé (remplacé par cache multi-charts) ----------

// EMA simple: y = alpha*x + (1-alpha)*y (déjà défini plus haut)

// Compte les niveaux dans ±R ticks autour d'un prix mid
inline int count_nearby_levels(const std::vector<double>& lvls, double mid, double R_ticks, double tick) {
    if (tick <= 0) return 0;
    int c = 0;
    for (double p : lvls) {
        if (std::fabs(p - mid) <= R_ticks * tick) ++c;
    }
    return c;
}

// Somme pondérée  Σ w/(1+|dist_ticks|)
inline double confluence_strength_sum(
    const std::vector<double>& lvls, double mid, double tick, double w,
    double R_ticks /*utilisé pour limiter si tu veux*/) {
    if (tick <= 0) return 0.0;
    double s = 0.0;
    for (double p : lvls) {
        double dt = std::fabs(p - mid) / tick;
        s += w / (1.0 + dt);
    }
    return s;
}

inline double min_proximity_ticks_multi(
    const std::vector<std::vector<double>>& groups, double mid, double tick) {
    if (tick <= 0) return 0.0;
    double best = std::numeric_limits<double>::infinity();
    for (const auto& g : groups) {
        for (double p : g) {
            best = std::min(best, std::fabs(p - mid)/tick);
        }
    }
    if (!std::isfinite(best)) return 0.0;
    return best;
}

inline bool has_pair_within_R(const std::vector<double>& A,
                              const std::vector<double>& B,
                              double R_ticks, double tick) {
    if (tick <= 0) return false;
    for (double a : A)
        for (double b : B)
            if (std::fabs(a - b) <= R_ticks * tick)
                return true;
    return false;
}

// json_bool déjà défini plus haut

// Retourne une ligne JSON (terminée par '\n') avec les 15 features ML_READY.
std::string BuildMLReadyJSON15(
    // L1
    double best_bid, double best_ask, double bid_size, double ask_size, double tick,

    // VWAP / VP / VVA / ATR
    double vwap_v, double vpoc, double vva_val, double vva_vah, double atr_price,
    double vwap_weekly, double vwap_monthly,  // NEW: VWAP Weekly & Monthly
    double w_up1, double w_dn1,  // NEW: VWAP Weekly Bands (SD+1, SD-1 seulement)

    // DOM10 (tailles par niveau, index 0 = L1, 1 = L2, ..., 9 = L10)
    const std::array<double,10>& dom_bid_qty,
    const std::array<double,10>& dom_ask_qty,

    // Compteurs 1s (déjà calculés ailleurs)
    double tick_rate_1s, double trade_rate_1s, double delta_rate_1s,

    // Niveaux MenthorQ autour du mid (en prix)
    const std::vector<double>& mq_gamma_walls,
    const std::vector<double>& mq_call_res,
    const std::vector<double>& mq_put_sup,
    const std::vector<double>& mq_hvl,
    const std::vector<double>& mq_blind_spots,

    // Fraîcheur MenthorQ et DOM (true si à jour)
    bool use_mq_structural, bool is_dom_fresh, bool has_any_mq_levels,
    bool is_mq_realtime_fresh, double mq_snapshot_age_s, const char* mq_valid_for_session,

    // Cache ML pour rates lissés
    const MLReadyCache& cache,
    int real_delta_cum_10s,

    // === NOUVEAUX PARAMÈTRES POUR ML_READY COMPLET ===
    // Données de base
    long long t_ms, const char* sym, int chart,
    double total_vol, double delta,

    // Données MenthorQ complètes
    const std::unordered_map<std::string,double>& menthorq_data,

    // Features DOM détaillées
    const MLDepthFeatures& dom_features,

    // Distances MenthorQ
    long near_gex_up, long near_gex_dn, long near_blind,
    long dist_1d_max, long dist_1d_min,

    // Métadonnées
    const char* session_id, int session_elapsed_s, double session_progress,
    const char* month, const char* quarter,
    int dom_age_ms, const char* sizes_source,

    // Données supplémentaires
    double point_value, int price_scale, double pvwap_source,
    double level1_imbalance, double tsec,
    const char* emit_reason, unsigned seq_unified,

    // Données UnifiedState manquantes
    int bar_index, double open, double high, double low, double close, double volume,
    double bidvol, double askvol,
    double dom_bid1, double dom_ask1, int dom_bq1, int dom_aq1,
    double up1, double dn1, double up2, double dn2, double up3, double dn3,
    double p_up1, double p_dn1, double p_up2, double p_dn2,
    double cum_delta_day, double cum_delta_session,
    double corr, double vix,
    double deltaPct, double askPct, double bidPct, int pressure,

    // Données session et MenthorQ manquantes
    int elapsed_s, double progress01, long long last_mq_update_ms,

    // Données principales manquantes
    double askVolume, double bidVolume, double delta_vol, double totalVolume_vol,

    // Distances MenthorQ manquantes
    long dist_gamma0, long dist_call0, long dist_put0, long dist_hvl0,
    long dist_call, long dist_put, long dist_hvl,

    // === [ADD] Game Changers ===
    double es_nq_lead_ms_120s, double es_nq_lead_cc, double nq_es_rs_z_120s, int divergence_flag,
    double onh, double onl, long long on_fix_ts, double ibh, double ibl,
    double awap_onh, double awap_onl, double awap_ibo, long long awap_ibo_ts,
    double next_wall_price, const char* next_wall_side, double next_wall_dist_pts, long next_wall_dist_ticks,
    double next_wall_strength, int next_wall_age_min,

    // === PATCH V3.5: Session Price Features ===
    double distance_to_high_pct, double distance_to_low_pct,
    double day_range_pct, double position_in_range
){
  // === PATCH START: L1-derived recompute & _atr units ========================
  // Recalculs L1 → dérivés (cohérence garantie)
  const double mid   = (best_bid + best_ask) * 0.5;
  const double spread= best_ask - best_bid;
  const int    spread_ticks = (int) llround(spread / tick);

  const int    l1_sz = bid_size + ask_size;
  const double microprice = (l1_sz > 0)
      ? (best_bid * (double)ask_size + best_ask * (double)bid_size) / (double)l1_sz
      : mid;
  const double microgap_signed = (microprice - mid);
  const double microgap    = std::fabs(microgap_signed);
  const double atr_ticks   = (atr_price > 0.0) ? (atr_price / tick) : std::numeric_limits<double>::quiet_NaN();
  const double microgap_n  = (std::isfinite(atr_ticks) && atr_ticks > 0.0)
      ? ((microprice - mid) / tick) / atr_ticks
      : std::numeric_limits<double>::quiet_NaN();

  // ================= QUOTE FALLBACK / DOM NEUTRALISÉ ==================
  const bool is_quote_fallback = (!is_dom_fresh) ||
                                 (sizes_source && strncmp(sizes_source, "QUOTE", 5) == 0);

  // Variables pour neutralisation DOM
  double microprice_final = microprice;
  double microgap_final = microgap;
  double microgap_signed_final = microgap_signed;
  double microgap_n_final = microgap_n;
  double level1_imbalance_final = std::numeric_limits<double>::quiet_NaN();
  double micro_imb_final = std::numeric_limits<double>::quiet_NaN();
  double pressure_strength_final = 0.0;
  double pressure_strength_depth_final = std::numeric_limits<double>::quiet_NaN();
  double pressure_strength_atr_final = 0.0;

  if (is_quote_fallback) {
    // Microstructure neutre
    microprice_final = mid;
    microgap_final = 0.0;
    microgap_signed_final = 0.0;
    microgap_n_final = 0.0;

    // Imbalances DOM -> null
    level1_imbalance_final = std::numeric_limits<double>::quiet_NaN();
    micro_imb_final = std::numeric_limits<double>::quiet_NaN();

    // Pressions dépendantes DOM -> null (ou 0 selon schéma JSON)
    pressure_strength_final = 0.0;
    pressure_strength_depth_final = std::numeric_limits<double>::quiet_NaN();
    pressure_strength_atr_final = 0.0;
  } else {
    // DOM frais - calculer les valeurs réelles
    level1_imbalance_final = level1_imbalance;
    // micro_imb sera calculé plus tard dans le code
    micro_imb_final = std::numeric_limits<double>::quiet_NaN();
    pressure_strength_final = std::fabs(level1_imbalance) * (total_vol / 1000.0);
    // pressure_strength_depth et pressure_strength_atr seront calculés plus tard
  }

  // ratios
  const double tv = (double) (std::max<long long>(1, (long long)total_vol));
  const double calc_askPct   = (double)askVolume / tv;
  const double calc_bidPct   = (double)bidVolume / tv;
  const double calc_deltaPct = calc_askPct - calc_bidPct;

  // === PATCH V1: Advanced Metrics (7 features) ===
  // Aliases sémantiques (rétro-compatibilité totale)
  const double calc_sell_pct = calc_askPct;
  const double calc_buy_pct  = calc_bidPct;

  // Delta burst & flip (utiliser delta courant vs précédent approximé)
  const double delta_burst = std::abs(delta);
  const bool delta_flip = (sgn(delta) != sgn(cum_delta_session)) && (cum_delta_session != 0);

  // Wicks (depuis OHLC)
  const double upper_wick_ticks = (high > low && tick > 0) ? std::max(0.0, (high - std::max(open, close)) / tick) : 0.0;
  const double lower_wick_ticks = (high > low && tick > 0) ? std::max(0.0, (std::min(open, close) - low) / tick) : 0.0;
  const double total_range_ticks = (high > low && tick > 0) ? ((high - low) / tick) : 0.0;

  // MIA Bullish Score (sera calculé plus bas après d_vwap_atr)
  double mia_bullish_score = 0.0;

  // === DISTANCES COHÉRENTES (points & ticks) ===
  auto dist_pts = [&](double ref)->double {
      return (std::isfinite(ref) ? (mid - ref) : std::numeric_limits<double>::quiet_NaN());
  };
  auto dist_ticks = [&](double ref)->double {
      if (!std::isfinite(ref) || tick<=0) return std::numeric_limits<double>::quiet_NaN();
      return (mid - ref) / tick;
  };
  // VWAP / PVWAP / VP / VA
  const double d_vwap_pts   = dist_pts(vwap_v);
  const double d_vwap_ticks = dist_ticks(vwap_v);
  const double d_pvwap_pts  = dist_pts(pvwap_source);
  const double d_pvwap_ticks= dist_ticks(pvwap_source);
  const double d_vpoc_pts   = dist_pts(vpoc);
  const double d_vpoc_ticks = dist_ticks(vpoc);
  const double d_vah_pts    = dist_pts(vva_vah);
  const double d_vah_ticks  = dist_ticks(vva_vah);
  const double d_val_pts    = dist_pts(vva_val);
  const double d_val_ticks  = dist_ticks(vva_val);
  const double d_vwap_atr   = (std::isfinite(atr_price) && atr_price>0.0) ? (d_vwap_pts / atr_price) : std::numeric_limits<double>::quiet_NaN();
  const double d_vpoc_atr   = (std::isfinite(atr_price) && atr_price>0.0) ? (d_vpoc_pts / atr_price) : std::numeric_limits<double>::quiet_NaN();

  // VWAP Weekly & Monthly distances
  const double d_vwap_weekly_pts   = dist_pts(vwap_weekly);
  const double d_vwap_weekly_ticks = dist_ticks(vwap_weekly);
  const double d_vwap_monthly_pts   = dist_pts(vwap_monthly);
  const double d_vwap_monthly_ticks = dist_ticks(vwap_monthly);

  // === PRECISION CLAMPING HELPERS ===
  auto roundN = [](double x, int n) -> double {
      if (!std::isfinite(x)) return x;
      const double p = std::pow(10.0, n);
      return std::round(x * p) / p;
  };

  // Helpers pour formater avec la bonne précision
  auto format_price = [&roundN](double x) -> std::string {
      if (!std::isfinite(x)) return "null";
      std::ostringstream oss;
      oss << std::fixed << std::setprecision(2) << roundN(x, 2);
      return oss.str();
  };
  auto format_ratio = [&roundN](double x) -> std::string {
      if (!std::isfinite(x)) return "null";
      std::ostringstream oss;
      oss << std::fixed << std::setprecision(6) << roundN(x, 6);
      return oss.str();
  };
  auto format_size = [&roundN](double x) -> std::string {
      if (!std::isfinite(x)) return "null";
      std::ostringstream oss;
      oss << std::fixed << std::setprecision(0) << roundN(x, 0);
      return oss.str();
  };
  auto format_ms = [](int64_t tms) -> std::string {
      return std::to_string(tms);
  };


    // pression fallback (discret: -1/0/+1)
    const int pressure_sign = sgn(calc_deltaPct);

    // === PATCH V1: Calcul MIA Bullish Score ===
    // Formule: 40% VWAP + 30% Delta Session + 20% DeltaPct + 10% VA
    {
        // 1. Composante VWAP (40%)
        double vwap_normalized = 0.0;
        if (std::isfinite(d_vwap_atr)) {
            vwap_normalized = std::max(-1.0, std::min(1.0, d_vwap_atr / 5.0));
        }
        double vwap_contrib = vwap_normalized * 0.4;

        // 2. Composante Delta Session (30%)
        double delta_normalized = std::max(-1.0, std::min(1.0, cum_delta_session / 500.0));
        double delta_contrib = delta_normalized * 0.3;

        // 3. Composante DeltaPct (20%)
        double deltapct_contrib = calc_deltaPct * 0.2;

        // 4. Composante Value Area (10%)
        double va_contrib = 0.0;
        if (mid < vva_val) {
            va_contrib = -0.1;
        } else if (mid > vva_vah) {
            va_contrib = 0.1;
        }

        // Score final
        mia_bullish_score = vwap_contrib + delta_contrib + deltapct_contrib + va_contrib;
        mia_bullish_score = std::max(-1.0, std::min(1.0, mia_bullish_score));
    }

    // === PATCH V2: Stacked Imbalance (sera calculé après DOM disponible) ===
    int stacked_imbalance_bid_rows = 0;
    int stacked_imbalance_ask_rows = 0;

    // === PATCH V2: Gamma Flip ROBUSTE (state machine + hystérésis + cooldown) ===
    // State machine pour éviter doubles signaux
    enum class GammaSide { Unknown, Below, Above };
    static std::unordered_map<std::string, GammaSide> g_last_gamma_side;
    static std::unordered_map<std::string, int64_t> g_last_flip_ts_ms;

    // Paramètres robustesse
    const double HYST_TICKS = 1.0;        // Hystérésis: exige 1 tick de marge
    const int64_t COOLDOWN_MS = 5000;     // Cooldown: 5 secondes entre flips
    const double EPS = 1e-9;              // Tolérance float

    std::string sym_key(sym);
    GammaSide prev_side = g_last_gamma_side[sym_key];
    GammaSide curr_side = GammaSide::Unknown;

    bool gamma_flip_up = false;
    bool gamma_flip_down = false;

    // Sera calculé plus tard (après récupération gamma_wall_0dte)
    double current_gamma_wall = 0.0;

    // Base features
    bool   in_value_area = (vva_val <= mid && mid <= vva_vah);
    bool   is_1tick_spread = (tick>0 && std::fabs(spread - tick) < 1e-12);
    // === PATCH END: L1-derived recompute & _atr units ==========================

    // DOM compact (NULL si pas frais)
    double ob_total=0.0, num_center=0.0, sum13=0.0, sum610=0.0;
    for (int k=0;k<10;k++){
        ob_total += dom_bid_qty[k] + dom_ask_qty[k];
        double kk = (double)(k+1);
        num_center += kk*dom_bid_qty[k] - kk*dom_ask_qty[k];
        if (k<=2)  sum13  += dom_bid_qty[k] + dom_ask_qty[k];
        if (k>=5)  sum610 += dom_bid_qty[k] + dom_ask_qty[k];
    }
    double ob_center = (ob_total>0.0 ? num_center/ob_total : std::numeric_limits<double>::quiet_NaN());
    double top_heavy = (ob_total>0.0 ? (sum13 - sum610)/ob_total : std::numeric_limits<double>::quiet_NaN());
    if (!is_dom_fresh) { ob_center = std::numeric_limits<double>::quiet_NaN(); top_heavy = std::numeric_limits<double>::quiet_NaN(); }

    // PATCH A: Confluence - Ne plus "gater" par 5s, + flags realtime/structural
    // Utiliser le paramètre 'has_any_mq_levels' passé par l'appelant (pas de redéclaration locale)

    // B. Calculer la confluence si on a des niveaux (peu importe la fraicheur 5s)
    int    confluence_density = 0;
    double confluence_strength = std::numeric_limits<double>::quiet_NaN();
    double confluence_proximity = std::numeric_limits<double>::quiet_NaN();
    bool   gamma_call_confluence=false, gamma_put_confluence=false, blind_spot_confluence=false;

    if (use_mq_structural && has_any_mq_levels && tick>0.0) {
        constexpr double R_CONFLUENCE = 5.0;
        constexpr double R_TIGHT = 3.0;
        constexpr double W_GAMMA=1.5, W_CALL=1.0, W_PUT=1.0, W_HVL=0.8, W_BLIND=0.7;

        auto count_nearby = [&](const std::vector<double>& lvls)->int{
            int c=0; for (double p: lvls) if (std::fabs(p-mid) <= R_CONFLUENCE*tick) ++c; return c;
        };
        confluence_density =
            count_nearby(mq_gamma_walls)+count_nearby(mq_call_res)+count_nearby(mq_put_sup)+count_nearby(mq_hvl)+count_nearby(mq_blind_spots);

        auto strength = [&](const std::vector<double>& lvls, double w)->double{
            double s=0.0; for(double p: lvls){ double dt=std::fabs(p-mid)/tick; s += w/(1.0+dt);} return s;
        };
        double s = 0.0;
        s += strength(mq_gamma_walls,W_GAMMA);
        s += strength(mq_call_res   ,W_CALL);
        s += strength(mq_put_sup    ,W_PUT );
        s += strength(mq_hvl        ,W_HVL );
        s += strength(mq_blind_spots,W_BLIND);
        confluence_strength = std::min(s, 10.0); // clipping soft

        auto min_prox = [&](const std::vector<std::vector<double>>& groups)->double{
            double best = std::numeric_limits<double>::infinity();
            for (auto& g: groups) for (double p: g) best = std::min(best, std::fabs(p-mid)/tick);
            return std::isfinite(best) ? best : std::numeric_limits<double>::quiet_NaN();
        };
        confluence_proximity = min_prox({mq_gamma_walls, mq_call_res, mq_put_sup, mq_hvl, mq_blind_spots});

        // Confluence sémantique locale : seulement si au moins un niveau est proche du prix
        auto withinR_near_price = [&](const std::vector<double>& A, const std::vector<double>& B)->bool{
            for (double a: A) {
                if (std::fabs(a-mid) <= R_CONFLUENCE*tick) {  // A proche du prix
                    for (double b: B) {
                        if (std::fabs(a-b) <= R_TIGHT*tick) return true;  // A et B proches
                    }
                }
            }
            for (double b: B) {
                if (std::fabs(b-mid) <= R_CONFLUENCE*tick) {  // B proche du prix
                    for (double a: A) {
                        if (std::fabs(a-b) <= R_TIGHT*tick) return true;  // A et B proches
                    }
                }
            }
            return false;
        };
        gamma_call_confluence = withinR_near_price(mq_gamma_walls, mq_call_res);
        gamma_put_confluence  = withinR_near_price(mq_gamma_walls, mq_put_sup );
        blind_spot_confluence = withinR_near_price(mq_blind_spots, mq_gamma_walls) ||
                               withinR_near_price(mq_blind_spots, mq_call_res) ||
                               withinR_near_price(mq_blind_spots, mq_put_sup);
    }


    // === PATCH START: JSON build (fields, mq gating, dom features mapping) =====
    std::ostringstream os; // Pas de setprecision global - on utilise les clamps individuels

    // === HELPER POUR NaN → null ===
    auto write_num_or_null = [&](double x){
      if (std::isnan(x)) os << "null";
      else os << format_price(x);
    };

    // -- unifie le sens du delta partout --
#ifdef MIA_DELTA_BID_MINUS_ASK
    const int delta_top = (int)(bidVolume - askVolume);
#else
    const int delta_top = (int)(askVolume - bidVolume);
#endif
    const double smart_money_flow_signed = (double)delta_top / std::max(1.0, (double)total_vol);
    const double institutional_pressure_abs = std::fabs((double)delta_top) / std::max(1.0, (double)total_vol);
    const double pressure_signed = (total_vol > 0 ? (double)delta_top / (double)total_vol : 0.0);

    // Appliquer les clamps de précision (utiliser les valeurs finales)
    const std::string mid_formatted = format_price(mid);
    const std::string spread_formatted = format_price(spread);
    const std::string microprice_formatted = format_price(microprice_final);
    const std::string microgap_formatted = format_price(microgap_final);
    const std::string microgap_n_formatted = format_ratio(microgap_n_final);
    const std::string microgap_signed_formatted = format_price(microgap_signed_final);
    const std::string best_bid_formatted = format_price(best_bid);
    const std::string best_ask_formatted = format_price(best_ask);
    const std::string q_bq1_formatted = format_size(bid_size);
    const std::string q_aq1_formatted = format_size(ask_size);

    // Clamps pour ratios et pourcentages
    const std::string calc_askPct_formatted = format_ratio(calc_askPct);
    const std::string calc_bidPct_formatted = format_ratio(calc_bidPct);
    const std::string calc_deltaPct_formatted = format_ratio(calc_deltaPct);
    // micro_imb cohérent avec dom_imb_l1 (même signe/échelle) - null si DOM pas frais
    double micro_imb_calc = std::numeric_limits<double>::quiet_NaN();
    if (is_dom_fresh && (bid_size + ask_size) > 0) {
        micro_imb_calc = clamp01((bid_size - ask_size) / (ask_size + bid_size));
    }
    // Mettre à jour micro_imb_final avec la valeur calculée
    if (!is_quote_fallback) {
        micro_imb_final = micro_imb_calc;
    }
    const std::string micro_imb_formatted = format_ratio(micro_imb_calc);

    // level1_imbalance cohérent avec micro_imb - null si DOM pas frais
    double level1_imbalance_calc = std::numeric_limits<double>::quiet_NaN();
    if (is_dom_fresh && (bid_size + ask_size) > 0) {
        level1_imbalance_calc = clamp01((bid_size - ask_size) / (ask_size + bid_size));
    }
    const std::string level1_imbalance_formatted = format_ratio(level1_imbalance_calc);

    // (SUPPR) Variables formatées orphelines - remplacées par format_price() direct

    // Clamps pour features DOM
    const std::string ob_center_formatted = format_ratio(ob_center);
    const std::string top_heavy_formatted = format_ratio(top_heavy);

    // Clamps pour confluence
    const std::string confluence_strength_formatted = format_ratio(confluence_strength);
    const std::string confluence_proximity_formatted = format_price(confluence_proximity);

    // Helper pour écrire champs MQ sans ternaires répétitifs (avec clamp de précision)
    auto WriteNumOrNull = [&](const char* k, const std::unordered_map<std::string, double>& data, bool enable, bool is_price = true){
        os << "\"" << k << "\":";
        if (enable && data.count(k) && std::isfinite(data.at(k))) {
            std::string formatted_val = is_price ? format_price(data.at(k)) : format_ratio(data.at(k));
            os << formatted_val;
        } else {
            os << "null";
        }
        os << ",";
    };
    os << "{"
       // === DONNÉES DE BASE ===
       << "\"t_ms\":" << format_ms(t_ms) << ","
       << "\"sym\":\"" << sym << "\","
       << "\"chart\":" << chart << ","

       // L1 + dérivés (toujours ceux recalculés ici)
       << "\"mid\":" << mid_formatted << ","
       << "\"spread\":" << spread_formatted << ","
       << "\"spread_ticks\":" << spread_ticks << ","
       << "\"microprice\":" << microprice_formatted << ","
       << "\"microgap\":" << microgap_formatted << ","
       << "\"microgap_n\":" << microgap_n_formatted << ","
       << "\"microgap_signed\":" << microgap_signed_formatted << ","

       // Quote L1 brute (pour validation microprice)
       << "\"best_bid\":" << best_bid_formatted << ","
       << "\"best_ask\":" << best_ask_formatted << ",";

       if (is_dom_fresh) {
           os << "\"q_bq1\":" << q_bq1_formatted << ","
              << "\"q_aq1\":" << q_aq1_formatted << ",";
       } else {
           os << "\"q_bq1\":null,"
              << "\"q_aq1\":null,";
       }

       // Métriques écart DOM↔BBO (pour debug) - null si DOM pas frais
       if (is_dom_fresh) {
           os << "\"dom_bbo_mid_diff\":" << format_price((dom_bid1 + dom_ask1) * 0.5 - mid) << ","
              << "\"dom_bbo_spread_diff_ticks\":" << (int)llround((dom_ask1 - dom_bid1) / tick - spread_ticks) << ",";
       } else {
           os << "\"dom_bbo_mid_diff\":null,"
              << "\"dom_bbo_spread_diff_ticks\":null,";
       }

       // Distances (points + ticks) — convention: (mid - ref)
       os << "\"d_vwap\":"        << format_price(d_vwap_pts)   << ","
          << "\"d_vwap_ticks\":"  << format_ratio(d_vwap_ticks) << ","
          << "\"d_vwap_weekly\":"         << format_price(d_vwap_weekly_pts)     << ","
          << "\"d_vwap_weekly_ticks\":"   << format_ratio(d_vwap_weekly_ticks)   << ","
          << "\"d_vwap_monthly\":"        << format_price(d_vwap_monthly_pts)    << ","
          << "\"d_vwap_monthly_ticks\":"  << format_ratio(d_vwap_monthly_ticks)  << ","
          << "\"d_w_up1\":"               << format_price(dist_pts(w_up1))      << ","
          << "\"d_w_up1_ticks\":"        << format_ratio(dist_ticks(w_up1))     << ","
          << "\"d_w_dn1\":"               << format_price(dist_pts(w_dn1))      << ","
          << "\"d_w_dn1_ticks\":"        << format_ratio(dist_ticks(w_dn1))     << ","
          << "\"d_pvwap\":"       << format_price(d_pvwap_pts)  << ","
          << "\"d_pvwap_ticks\":" << format_ratio(d_pvwap_ticks)<< ","
          << "\"d_vpoc\":"        << format_price(d_vpoc_pts)   << ","
          << "\"d_vpoc_ticks\":"  << format_ratio(d_vpoc_ticks) << ","
          << "\"d_vah\":"         << format_price(d_vah_pts)    << ","
          << "\"d_vah_ticks\":"   << format_ratio(d_vah_ticks)  << ","
          << "\"d_val\":"         << format_price(d_val_pts)    << ","
          << "\"d_val_ticks\":"   << format_ratio(d_val_ticks)  << ","
       << "\"level1_imbalance\":" << level1_imbalance_formatted << ","
       << "\"point_value\":" << format_price(point_value) << ","
       << "\"price_scale\":" << price_scale << ","
       << "\"tsec\":" << format_price(tsec) << ","
       << "\"emit_reason\":\"" << emit_reason << "\","
       << "\"seq_unified\":" << seq_unified << ","

       // === VWAP/VVA/ATR bruts ===
       << "\"vwap\":" << format_price(vwap_v) << ","
       << "\"vwap_weekly\":"   << format_price(vwap_weekly)   << ","
       << "\"vwap_monthly\":"  << format_price(vwap_monthly)  << ","
       << "\"atr\":"  << format_price(atr_price) << ","
       << "\"pvwap\":"<< format_price(pvwap_source) << ","
       << "\"vva\":{"
          << "\"vah\":" << format_price(vva_vah) << ","
          << "\"val\":" << format_price(vva_val) << ","
          << "\"vpoc\":"<< format_price(vpoc)
       << "},"

       // Normalisation ATR (points)
       << "\"d_vwap_atr\":" << format_ratio(d_vwap_atr) << ","
       << "\"d_vpoc_atr\":" << format_ratio(d_vpoc_atr) << ","
       << "\"micro_imb\":"  << micro_imb_formatted << ","

       // === DONNÉES BASEDATA ===
       << "\"bar_index\":" << bar_index << ","
       << "\"open\":" << format_price(open) << ","
       << "\"high\":" << format_price(high) << ","
       << "\"low\":" << format_price(low) << ","
       << "\"close\":" << format_price(close) << ","
       << "\"volume\":" << format_size(volume) << ","
       << "\"bidvol\":" << format_size(bidvol) << ","
       << "\"askvol\":" << format_size(askvol) << ",";

       // === DONNÉES DOM L1 (neutralisées en fallback) ===
       if (is_quote_fallback) {
         os << "\"dom_bid1\":null,"
            << "\"dom_ask1\":null,"
            << "\"dom_bq1\":null,"
            << "\"dom_aq1\":null,";
       } else {
         os << "\"dom_bid1\":" << format_price(dom_bid1) << ","
            << "\"dom_ask1\":" << format_price(dom_ask1) << ","
            << "\"dom_bq1\":" << dom_bq1 << ","
            << "\"dom_aq1\":" << dom_aq1 << ",";
       }

       // === VWAP BANDS ===
       os << "\"vwap_up1\":" << format_price(up1) << ","
       << "\"vwap_dn1\":" << format_price(dn1) << ","
       << "\"vwap_up2\":" << format_price(up2) << ","
       << "\"vwap_dn2\":" << format_price(dn2) << ","
       << "\"vwap_up3\":" << format_price(up3) << ","
       << "\"vwap_dn3\":" << format_price(dn3) << ","

       // === VWAP WEEKLY BANDS (SD+1, SD-1 seulement) ===
       << "\"vwap_weekly_up1\":";
       write_num_or_null(w_up1);
       os << ","
       << "\"vwap_weekly_dn1\":";
       write_num_or_null(w_dn1);
       os << ","

       // === PVWAP BANDS ===
       << "\"pvwap_up1\":";
       write_num_or_null(p_up1);
       os << ","
       << "\"pvwap_dn1\":";
       write_num_or_null(p_dn1);
       os << ","
       << "\"pvwap_up2\":";
       write_num_or_null(p_up2);
       os << ","
       << "\"pvwap_dn2\":";
       write_num_or_null(p_dn2);
       os << ","

       // === CUMULATIVE DELTA ===
       << "\"cum_delta_day\":" << format_size(cum_delta_day) << ","
       << "\"cum_delta_session\":" << format_size(cum_delta_session) << ","

      // volumes & ratios (une seule clé pour le total)
      << "\"nbcv\":{"
      << "\"ask_volume\":" << (int)askVolume << ","
      << "\"bid_volume\":" << (int)bidVolume << ","
      << "\"delta\":" << (int)(-delta_top) << ","
      << "\"total_volume\":" << (int)total_vol << "},"
      << "\"askPct\":" << calc_askPct_formatted << ","
      << "\"bidPct\":" << calc_bidPct_formatted << ","
      << "\"deltaPct\":" << format_ratio(-calc_deltaPct) << ","

       // pression normalisée (discret = sgn(deltaPct))
       << "\"pressure\":" << (int)pressure_signed << ","

       // === MÉTRIQUES DE MARCHÉ ===
       << "\"corr\":" << format_ratio(corr) << ","
       << "\"vix\":" << format_price(vix) << ","

       // === DONNÉES SESSION ET MENTHORQ MANQUANTES ===
       << "\"elapsed_s\":" << elapsed_s << ","
       << "\"progress01\":" << format_ratio(progress01) << ","
       << "\"last_mq_update_ms\":" << last_mq_update_ms << ","

       // (déplacé plus haut: vwap/atr/pvwap/vva + d_*_atr)

       // === 15 FEATURES ML_READY ===
       << "\"is_1tick_spread\":" << json_bool(is_1tick_spread) << ","
       << "\"in_value_area\":"   << json_bool(in_value_area)   << ","
       << "\"ob_center\":"       << ob_center_formatted << ","
       << "\"top_heavy\":"       << top_heavy_formatted << ","
       << "\"tick_rate_3s\":"    << json_num_or_null_safe(cache.ema_tick_rate_3s)  << ","
       << "\"delta_cum_10s\":"   << real_delta_cum_10s << ",";

       // === CONFLUENCES - PATCH: Toujours inclure tous les champs ===
       // Garantir des sorties complètes même si MenthorQ indisponible
       os << "\"confluence_density\":" << confluence_density << ","
          << "\"confluence_strength\":" << confluence_strength_formatted << ","
          << "\"confluence_proximity\":" << confluence_proximity_formatted << ","
          << "\"gamma_call_confluence\":" << json_bool(gamma_call_confluence) << ","
          << "\"gamma_put_confluence\":" << json_bool(gamma_put_confluence) << ","
          << "\"blind_spot_confluence\":" << json_bool(blind_spot_confluence) << ",";

       // === DONNÉES DE MARCHÉ ===
      os << "\"delta\":" << format_size(-delta_top) << ","
      << "\"tick_rate_1s\":" << (int)tick_rate_1s << ","
      << "\"trade_rate_1s\":" << (int)trade_rate_1s << ","
      << "\"delta_rate_1s\":" << (int)delta_rate_1s << ",";

       // === DONNÉES MENTHORQ COMPLÈTES ===
       // Niveaux (prix) - écriture simplifiée avec helper
       WriteNumOrNull("gex_1", menthorq_data, use_mq_structural, true);
       WriteNumOrNull("gex_2", menthorq_data, use_mq_structural, true);
       WriteNumOrNull("gex_3", menthorq_data, use_mq_structural, true);
       WriteNumOrNull("gex_4", menthorq_data, use_mq_structural, true);
       WriteNumOrNull("gex_5", menthorq_data, use_mq_structural, true);
       WriteNumOrNull("gex_6", menthorq_data, use_mq_structural, true);
       WriteNumOrNull("gex_7", menthorq_data, use_mq_structural, true);
       WriteNumOrNull("gex_8", menthorq_data, use_mq_structural, true);
       WriteNumOrNull("gex_9", menthorq_data, use_mq_structural, true);
       WriteNumOrNull("gex_10", menthorq_data, use_mq_structural, true);
       WriteNumOrNull("call_resistance", menthorq_data, use_mq_structural, true);
       WriteNumOrNull("put_support", menthorq_data, use_mq_structural, true);
       WriteNumOrNull("hvl", menthorq_data, use_mq_structural, true);
       // === AJOUT 05/12/2025: Champs 0DTE pour niveaux intraday ===
       WriteNumOrNull("call_resistance_0dte", menthorq_data, use_mq_structural, true);
       WriteNumOrNull("put_support_0dte", menthorq_data, use_mq_structural, true);
       WriteNumOrNull("hvl_0dte", menthorq_data, use_mq_structural, true);
       WriteNumOrNull("gamma_wall_0dte", menthorq_data, use_mq_structural, true);
       // ==========================================================
       WriteNumOrNull("1d_max", menthorq_data, use_mq_structural, true);
       WriteNumOrNull("1d_min", menthorq_data, use_mq_structural, true);
       // (SUPPR) Pas de doublon d1_max/d1_min

       // === BLIND SPOTS ===
       WriteNumOrNull("blind_spot_0", menthorq_data, use_mq_structural, true);
       WriteNumOrNull("blind_spot_1", menthorq_data, use_mq_structural, true);
       WriteNumOrNull("blind_spot_2", menthorq_data, use_mq_structural, true);
       WriteNumOrNull("blind_spot_3", menthorq_data, use_mq_structural, true);
       WriteNumOrNull("blind_spot_4", menthorq_data, use_mq_structural, true);
       WriteNumOrNull("blind_spot_5", menthorq_data, use_mq_structural, true);
       WriteNumOrNull("blind_spot_6", menthorq_data, use_mq_structural, true);
       WriteNumOrNull("blind_spot_7", menthorq_data, use_mq_structural, true);
       WriteNumOrNull("blind_spot_8", menthorq_data, use_mq_structural, true);

  // === DOM 10 NIVEAUX COMPLETS - PATCH: Toujours inclure tous les champs ===
  // Garantir des sorties complètes même si certaines valeurs sont 0
  os << "\"dom_bid_1\":" << format_size(dom_bid_qty[0]) << ","
     << "\"dom_bid_2\":" << format_size(dom_bid_qty[1]) << ","
     << "\"dom_bid_3\":" << format_size(dom_bid_qty[2]) << ","
     << "\"dom_bid_4\":" << format_size(dom_bid_qty[3]) << ","
     << "\"dom_bid_5\":" << format_size(dom_bid_qty[4]) << ","
     << "\"dom_bid_6\":" << format_size(dom_bid_qty[5]) << ","
     << "\"dom_bid_7\":" << format_size(dom_bid_qty[6]) << ","
     << "\"dom_bid_8\":" << format_size(dom_bid_qty[7]) << ","
     << "\"dom_bid_9\":" << format_size(dom_bid_qty[8]) << ","
     << "\"dom_bid_10\":" << format_size(dom_bid_qty[9]) << ","
     << "\"dom_ask_1\":" << format_size(dom_ask_qty[0]) << ","
     << "\"dom_ask_2\":" << format_size(dom_ask_qty[1]) << ","
     << "\"dom_ask_3\":" << format_size(dom_ask_qty[2]) << ","
     << "\"dom_ask_4\":" << format_size(dom_ask_qty[3]) << ","
     << "\"dom_ask_5\":" << format_size(dom_ask_qty[4]) << ","
     << "\"dom_ask_6\":" << format_size(dom_ask_qty[5]) << ","
     << "\"dom_ask_7\":" << format_size(dom_ask_qty[6]) << ","
     << "\"dom_ask_8\":" << format_size(dom_ask_qty[7]) << ","
     << "\"dom_ask_9\":" << format_size(dom_ask_qty[8]) << ","
     << "\"dom_ask_10\":" << format_size(dom_ask_qty[9]) << ",";

      // === FEATURES DOM (pré-calc, réutilisé au root) =======================
      // depth = somme L1..L10 ; rings = nb de niveaux non nuls ; depth_imb = (B − A)/(B + A)
      int depth_bid_10 = 0, depth_ask_10 = 0;
      int rings_bid = 0, rings_ask = 0;
      double depth_imb = std::numeric_limits<double>::quiet_NaN();
      if (is_dom_fresh) {
        for (int k=0;k<10;k++){
          depth_bid_10 += (int)std::max(0.0, dom_bid_qty[k]);
          depth_ask_10 += (int)std::max(0.0, dom_ask_qty[k]);
          if (dom_bid_qty[k] > 0) ++rings_bid;
          if (dom_ask_qty[k] > 0) ++rings_ask;
        }
        const int depth_sum = depth_bid_10 + depth_ask_10;
        if (depth_sum > 0) depth_imb = (double)(depth_bid_10 - depth_ask_10) / (double)depth_sum;

        // === PATCH V2: Stacked Imbalance Calculation ===
        // Compter les niveaux consécutifs avec ratio >= 3.0
        for (int k=1; k<10; k++) {  // Start at 1 (skip L1)
          double bid_ratio = (dom_ask_qty[k] > 0) ? (dom_bid_qty[k] / dom_ask_qty[k]) : 0.0;
          double ask_ratio = (dom_bid_qty[k] > 0) ? (dom_ask_qty[k] / dom_bid_qty[k]) : 0.0;

          if (bid_ratio >= 3.0) {
            stacked_imbalance_bid_rows++;
          }
          if (ask_ratio >= 3.0) {
            stacked_imbalance_ask_rows++;
          }
        }
      }

      // === FEATURES DOM DÉTAILLÉES - PATCH: Toujours inclure l'objet complet ===
       // Calculer les features même si DOM pas frais (valeurs 0 au lieu de null)
       os << "\"dom_features\":{"
          << "\"depth_bid\":" << format_size(depth_bid_10) << ","
          << "\"depth_ask\":" << format_size(depth_ask_10) << ","
          << "\"rings_bid\":" << format_size(rings_bid) << ","
          << "\"rings_ask\":" << format_size(rings_ask) << ","
          << "\"imbalance_1_3\":" << format_ratio(dom_features.imb_3) << ","
          << "\"imbalance_6_10\":" << format_ratio(dom_features.ring_imb_6_10) << ","
          << "\"slope_bid_1_3\":" << format_size(dom_features.slope_bid_1_3) << ","
          << "\"slope_ask_1_3\":" << format_size(dom_features.slope_ask_1_3) << ","
          << "\"slope_bid_1_3_n\":" << format_ratio(dom_features.slope_bid_1_3_n) << ","
          << "\"slope_ask_1_3_n\":" << format_ratio(dom_features.slope_ask_1_3_n) << "},";

       // === DISTANCES MENTHORQ COMPLÈTES - PATCH: Toujours inclure l'objet complet ===
       // Garantir des sorties complètes même si MenthorQ indisponible
       os << "\"menthor_distances\":{"
          << "\"gamma0\":" << (dist_gamma0 == -1 ? "null" : std::to_string(dist_gamma0)) << ","
          << "\"call0\":" << (dist_call0 == -1 ? "null" : std::to_string(dist_call0)) << ","
          << "\"put0\":" << (dist_put0 == -1 ? "null" : std::to_string(dist_put0)) << ","
          << "\"hvl0\":" << (dist_hvl0 == -1 ? "null" : std::to_string(dist_hvl0)) << ","
          << "\"call\":" << (dist_call == -1 ? "null" : std::to_string(dist_call)) << ","
          << "\"put\":" << (dist_put == -1 ? "null" : std::to_string(dist_put)) << ","
          << "\"hvl\":" << (dist_hvl == -1 ? "null" : std::to_string(dist_hvl)) << ","
          << "\"dist_1d_max\":" << dist_1d_max << ","
          << "\"dist_1d_min\":" << dist_1d_min << ","
          << "\"near_gex_up\":" << near_gex_up << ","
          << "\"near_gex_dn\":" << near_gex_dn << ","
          << "\"near_blind\":" << near_blind
          << "},";

       // === MÉTADONNÉES ===
       os << "\"session_id\":\"" << session_id << "\","
       << "\"session_elapsed_s\":" << session_elapsed_s << ","
       << "\"session_progress\":" << format_ratio(session_progress) << ","
       << "\"menthor_meta\":{"
       << "\"month\":\"" << month << "\","
       << "\"quarter\":\"" << quarter << "\""
       << "},"

       // === FLAGS / QUALITÉ ===
       << "\"is_dom_fresh\":" << json_bool(is_dom_fresh) << ","
       << "\"dom_age_ms\":" << dom_age_ms << ","
       << "\"sizes_source\":\"" << sizes_source << "\",";

       // data_quality cohérente
       const char* dq =
           (strcmp(sizes_source,"QUOTE")==0) ? "QUOTE_FALLBACK"
         : (is_dom_fresh ? "OK"
                         : (dom_age_ms>300 ? "WARN" : "QUOTE_FALLBACK"));
       os << "\"data_quality\":\"" << dq << "\",";

       // === [ADD] FEATURES ML STABLES / BORNEES ==============================
       // Clip & tanh pour ob_center - GESTION CORRECTE DES NaN
       double ob_center_b = std::numeric_limits<double>::quiet_NaN();
       double ob_center_tanh = std::numeric_limits<double>::quiet_NaN();

       if (std::isfinite(ob_center)) {
         ob_center_b = mia_clip(ob_center, -1.0, 1.0);
         ob_center_tanh = mia_tanh(0.75 * ob_center);
       }

       // Pressure strength - variantes robustes (utiliser les valeurs finales)
       // - ps_depth : |imbalance L1| * (bq1+aq1) / (depth_bid_10 + depth_ask_10)
       // - ps_atr   : |imbalance L1| * |microprice - mid| / ATR
       double ps_depth = pressure_strength_depth_final;
       double ps_atr   = pressure_strength_atr_final;

       if (!is_quote_fallback) {
         // DOM frais - calculer les valeurs réelles
         const double l1_sum = (double)(dom_bq1 + dom_aq1);
         const double depth_sum10 = (double)(depth_bid_10 + depth_ask_10);
         if (is_dom_fresh && depth_sum10 > 0.0) {
           ps_depth = std::fabs(level1_imbalance_final) * (l1_sum / depth_sum10);
         }
         if (std::isfinite(atr_price) && atr_price > 0.0) {
           ps_atr = std::fabs(level1_imbalance_final) * (std::fabs(microprice_final - mid) / atr_price);
         }
       }

       // Export des features bornées / normalisées
       os << "\"ob_center_b\":" << format_ratio(ob_center_b) << ","
          << "\"ob_center_tanh\":" << format_ratio(ob_center_tanh) << ",";

       // === NOUVELLES FEATURES ML (VALEURS RÉELLES) ===
       os
       << "\"battle_navale_signal_strength\":" << format_ratio(confluence_strength) << ","
       << "\"battle_navale_confidence\":" << format_ratio(std::min(1.0, confluence_strength * 1.2)) << ","
       << "\"menthorq_impact_score\":" << format_ratio(confluence_proximity / 1000.0) << ","
       << "\"menthorq_proximity_strength\":" << format_ratio(std::min(1.0, confluence_proximity / 500.0)) << ","
       << "\"smart_money_flow\":" << format_ratio(smart_money_flow_signed) << ","
          << "\"institutional_pressure\":" << format_ratio(institutional_pressure_abs) << ","
          << "\"tick_momentum\":" << format_ratio((microprice_final - mid) / std::max(0.25, tick)) << ","
       // Imbalances et pressions DOM (neutralisées en fallback)
       << "\"level1_imbalance\":"
       << (is_quote_fallback ? std::string("null") : format_ratio(level1_imbalance_final)) << ","
       << "\"depth_imbalance\":"
       << (is_dom_fresh ? format_ratio(depth_imb) : std::string("null")) << ",";
       // Pressure strength (neutralisée en fallback)
       if (is_quote_fallback) {
         os << "\"pressure_strength\":0.0,"
            << "\"pressure_strength_depth\":null,"
            << "\"pressure_strength_atr\":0.0,";
       } else {
         os << "\"pressure_strength\":" << format_ratio(pressure_strength_final) << ","
            << "\"pressure_strength_depth\":" << format_ratio(ps_depth) << ","
            << "\"pressure_strength_atr\":" << format_ratio(ps_atr) << ",";
       }
       // Discret 3 niveaux (compat)
       const double vol_regime3 =
           (vix > 30.0) ? 3.0 :
           (vix > 20.0) ? 2.0 : 1.0;

       // Discret 5 niveaux (plus granulaire)
       const double vol_regime5 =
           (vix > 40.0) ? 5.0 :
           (vix > 30.0) ? 4.0 :
           (vix > 20.0) ? 3.0 :
           (vix > 15.0) ? 2.0 : 1.0;

       // Continu [0,1] ~ linéaire de 12 -> 48 (cap aux bornes)
       const double vol_regime_cont = std::min(1.0, std::max(0.0, (vix - 12.0) / 36.0));

       os << "\"volatility_regime\":"      << format_ratio(vol_regime3)  << ","
          << "\"volatility_regime5\":"     << format_ratio(vol_regime5)  << ","
          << "\"volatility_regime_cont\":" << format_ratio(vol_regime_cont) << ","
       << "\"atr_ratio\":" << format_ratio(atr_price / std::max(0.25, tick)) << ","
#ifdef MIA_EXPORT_ATR_IN_TICKS_ALIAS
       << "\"atr_in_ticks\":" << format_ratio(atr_price / std::max(0.25, tick)) << ","
#endif

       // === [ADD] Intermarkets ===
       << "\"intermarkets\":{"
       << "\"es_nq_lead_ms_120s\":" << format_ratio(es_nq_lead_ms_120s) << ","
       << "\"es_nq_lead_cc\":" << format_ratio(es_nq_lead_cc) << ","
       << "\"nq_es_rs_z_120s\":" << format_ratio(nq_es_rs_z_120s) << ","
       << "\"divergence_flag\":" << divergence_flag
       << "},"

       // === [ADD] Structure (ON, IB, AWAP) ===
       << "\"structure\":{"
       << "\"onh\":" << format_price(onh) << ","
       << "\"onl\":" << format_price(onl) << ","
       << "\"on_fix_ts\":" << on_fix_ts << ","
       << "\"ibh\":" << format_price(ibh) << ","
       << "\"ibl\":" << format_price(ibl) << ","
       << "\"awap_onh\":" << format_price(awap_onh) << ","
       << "\"awap_onl\":" << format_price(awap_onl) << ","
       << "\"awap_ibo\":" << format_price(awap_ibo) << ","
       << "\"awap_ibo_ts\":" << awap_ibo_ts
       << "},"

       // === [ADD] Next Wall ===
      << "\"next_wall\":{"
      << "\"price\":" << format_price(next_wall_price) << ","
      << "\"side\":\"" << next_wall_side << "\","
      << "\"dist_pts\":" << format_price(next_wall_dist_pts) << ","
      << "\"dist_ticks\":" << next_wall_dist_ticks << ","
      << "\"strength\":" << format_ratio(next_wall_strength) << ","
      << "\"age_min\":" << next_wall_age_min
      << "},"

      // === PATCH V1: Advanced Metrics ===
      << "\"mia_bullish_score\":" << format_ratio(mia_bullish_score) << ","
      << "\"sell_pct\":" << format_ratio(calc_sell_pct) << ","
      << "\"buy_pct\":" << format_ratio(calc_buy_pct) << ","
      << "\"delta_burst\":" << format_size(delta_burst) << ","
      << "\"delta_flip\":" << (delta_flip ? "true" : "false") << ","
      << "\"upper_wick_ticks\":" << format_ratio(upper_wick_ticks) << ","
      << "\"lower_wick_ticks\":" << format_ratio(lower_wick_ticks) << ","
      << "\"total_range_ticks\":" << format_ratio(total_range_ticks) << ","

      // === PATCH V2: Stacked Imbalance ===
      << "\"stacked_imbalance_bid_rows\":" << format_size(stacked_imbalance_bid_rows) << ","
      << "\"stacked_imbalance_ask_rows\":" << format_size(stacked_imbalance_ask_rows) << ",";

      // === PATCH V2: Gamma Flip ROBUSTE (calcul avant export) ===
      // Récupérer gamma wall depuis MenthorQ data
      auto lv_gw = menthorq_data.find("gamma_wall_0dte");
      double gamma_wall_level = (lv_gw != menthorq_data.end() && std::isfinite(lv_gw->second) && lv_gw->second > 0) ? lv_gw->second : 0.0;

      // State machine et cooldown
      auto valid_gw = [](double x) { return std::isfinite(x) && x > 0.0; };

      if (valid_gw(mid) && valid_gw(gamma_wall_level)) {
        // Déterminer côté actuel avec hystérésis
        double hyst_dist = HYST_TICKS * tick;

        if (mid <= gamma_wall_level - hyst_dist) {
          curr_side = GammaSide::Below;
        } else if (mid >= gamma_wall_level + hyst_dist) {
          curr_side = GammaSide::Above;
        } else {
          // Zone neutre: garder l'état précédent
          curr_side = prev_side;
        }

        // Détecter transitions avec cooldown
        int64_t now_ms = t_ms;
        int64_t last_flip_ms = g_last_flip_ts_ms[sym_key];
        bool cooled = (now_ms - last_flip_ms >= COOLDOWN_MS);

        if (cooled) {
          if (prev_side == GammaSide::Below && curr_side == GammaSide::Above) {
            gamma_flip_up = true;
            g_last_flip_ts_ms[sym_key] = now_ms;
          } else if (prev_side == GammaSide::Above && curr_side == GammaSide::Below) {
            gamma_flip_down = true;
            g_last_flip_ts_ms[sym_key] = now_ms;
          }
        }

        // Mise à jour de l'état
        g_last_gamma_side[sym_key] = curr_side;
        current_gamma_wall = gamma_wall_level;
      }

     os << "\"gamma_flip_up\":" << (gamma_flip_up ? "true" : "false") << ","
     << "\"gamma_flip_down\":" << (gamma_flip_down ? "true" : "false") << ","
     << "\"gamma_side\":\"" << (curr_side == GammaSide::Above ? "above" : curr_side == GammaSide::Below ? "below" : "unknown") << "\","
     << "\"gamma_wall_level\":" << format_price(current_gamma_wall) << ","

     // === PATCH V3.5: Session Price Features (4 features) ===
     << "\"distance_to_high_pct\":" << format_ratio(distance_to_high_pct) << ","
     << "\"distance_to_low_pct\":" << format_ratio(distance_to_low_pct) << ","
     << "\"day_range_pct\":" << format_ratio(day_range_pct) << ","
     << "\"position_in_range\":" << format_ratio(position_in_range) << ","

       << "\"feature_version\":\"v3.5.23_awap_corruption_fixed\""
      << "}\n";
   return os.str();
    // PATCH <<< build JSON
}

// Fonction getTopKDom déplacée ici pour être accessible
static void getTopKDom(const SCStudyInterfaceRef& sc, int K, std::vector<std::pair<double,int>>& bids, std::vector<std::pair<double,int>>& asks) {
    bids.clear(); asks.clear();
    s_MarketDepthEntry md;

    // Récupérer les K meilleurs bids
    for (int i = 1; i <= K; i++) {
        if (sc.GetBidMarketDepthEntryAtLevel(md, i)) {
            bids.push_back({md.Price, (int)md.Quantity});
        }
    }

    // Récupérer les K meilleurs asks
    for (int i = 1; i <= K; i++) {
        if (sc.GetAskMarketDepthEntryAtLevel(md, i)) {
            asks.push_back({md.Price, (int)md.Quantity});
        }
    }
}

// Extrait et agrège DOM top-K depuis Sierra (utilise getTopKDom(...) déjà présent)
static void ML_ComputeDepthFeatures(SCStudyInterfaceRef sc, int K,
                                    MLDepthFeatures& F)
{
  std::vector<std::pair<double,int>> bids, asks;
  getTopKDom(sc, K, bids, asks);
  auto qty_at = [&](const std::vector<std::pair<double,int>>& v, int lvl)->int {
    return (lvl-1>=0 && lvl-1<(int)v.size()) ? std::max(0, v[lvl-1].second) : 0;
  };
  auto sum_range = [&](const std::vector<std::pair<double,int>>& v, int a, int b)->int {
    int s=0; if (a<1) a=1; if (b>K) b=K;
    for (int i=a;i<=b;i++) s += qty_at(v,i);
    return s;
  };
  // bruts
  F.depth_bid_1  = qty_at(bids,1); F.depth_ask_1  = qty_at(asks,1);
  F.depth_bid_2  = qty_at(bids,2); F.depth_ask_2  = qty_at(asks,2);
  F.depth_bid_3  = qty_at(bids,3); F.depth_ask_3  = qty_at(asks,3);
  F.depth_bid_5  = sum_range(bids,1,5); F.depth_ask_5  = sum_range(asks,1,5);
  F.depth_bid_10 = sum_range(bids,1,10);F.depth_ask_10 = sum_range(asks,1,10);
  // rings
  F.ring_bid_1    = qty_at(bids,1);    F.ring_ask_1    = qty_at(asks,1);
  F.ring_bid_2_3  = sum_range(bids,2,3); F.ring_ask_2_3  = sum_range(asks,2,3);
  F.ring_bid_4_5  = sum_range(bids,4,5); F.ring_ask_4_5  = sum_range(asks,4,5);
  F.ring_bid_6_10 = sum_range(bids,6,10);F.ring_ask_6_10 = sum_range(asks,6,10);
  auto imb = [](int b, int a)->double { int s=b+a; return (s>0) ? (double)(b-a)/(double)s : 0.0; };
  F.ring_imb_1    = imb(F.ring_bid_1,   F.ring_ask_1);
  F.ring_imb_2_3  = imb(F.ring_bid_2_3, F.ring_ask_2_3);
  F.ring_imb_4_5  = imb(F.ring_bid_4_5, F.ring_ask_4_5);
  F.ring_imb_6_10 = imb(F.ring_bid_6_10,F.ring_ask_6_10);
  // imbalances cumulées
  F.imb_1  = imb(F.depth_bid_1 , F.depth_ask_1);
  F.imb_2  = imb(F.depth_bid_2 , F.depth_ask_2);
  // imb_3 = imbalance sur les 3 premiers niveaux cumulés (pas le niveau 3 seul)
  int depth_bid_1_3 = F.depth_bid_1 + F.depth_bid_2 + F.depth_bid_3;
  int depth_ask_1_3 = F.depth_ask_1 + F.depth_ask_2 + F.depth_ask_3;
  F.imb_3  = imb(depth_bid_1_3, depth_ask_1_3);
  F.imb_5  = imb(F.depth_bid_5 , F.depth_ask_5);
  F.imb_10 = imb(F.depth_bid_10, F.depth_ask_10);
  // normalisations (utiliser ml_div_or_nan pour éviter les 0 "faux")
  double tot10 = (double)(F.depth_bid_10 + F.depth_ask_10);
  F.depth_bid_1_n  = 100.0 * ml_div_or_nan(F.depth_bid_1 , tot10);
  F.depth_ask_1_n  = 100.0 * ml_div_or_nan(F.depth_ask_1 , tot10);
  F.depth_bid_2_n  = 100.0 * ml_div_or_nan(F.depth_bid_2 , tot10);
  F.depth_ask_2_n  = 100.0 * ml_div_or_nan(F.depth_ask_2 , tot10);
  F.depth_bid_3_n  = 100.0 * ml_div_or_nan(F.depth_bid_3 , tot10);
  F.depth_ask_3_n  = 100.0 * ml_div_or_nan(F.depth_ask_3 , tot10);
  F.depth_bid_5_n  = 100.0 * ml_div_or_nan(F.depth_bid_5 , tot10);
  F.depth_ask_5_n  = 100.0 * ml_div_or_nan(F.depth_ask_5 , tot10);
  F.depth_bid_10_n = 100.0 * ml_div_or_nan(F.depth_bid_10, tot10);
  F.depth_ask_10_n = 100.0 * ml_div_or_nan(F.depth_ask_10, tot10);
  // slopes 1→3 (approche discrète)
  F.slope_bid_1_3 = std::max(0, F.depth_bid_2 - F.depth_bid_1) + std::max(0, F.depth_bid_3 - F.depth_bid_2);
  F.slope_ask_1_3 = std::max(0, F.depth_ask_2 - F.depth_ask_1) + std::max(0, F.depth_ask_3 - F.depth_ask_2);
  double s13 = (double)(F.depth_bid_1 + F.depth_bid_2 + F.depth_bid_3 +
                        F.depth_ask_1 + F.depth_ask_2 + F.depth_ask_3);
  F.slope_bid_1_3_n = 100.0 * ml_safe_div((double)F.slope_bid_1_3, std::max(1.0, s13));
  F.slope_ask_1_3_n = 100.0 * ml_safe_div((double)F.slope_ask_1_3, std::max(1.0, s13));
}

// -------- MenthorQ distances (à partir des caches écrasés par AppendMenthorQFlatFields) ------
static inline double ML_DistTicks(double level_px, double mid, double tick) {
  if (!(level_px>0 && tick>0)) return NAN;
  return (level_px - mid)/tick;
}

// Structure LastMenthorQContent déplacée ici pour être accessible
struct LastMenthorQContent {
    std::unordered_map<std::string, double> last_values;
    long long last_update_ms = 0;
    double last_timestamp = 0.0;
    int last_bar_index = -1;
};

// Déclaration de g_LastMenthorQBySymType déplacée ici
static std::unordered_map<std::string, LastMenthorQContent> g_LastMenthorQBySymType;

static void ML_BuildMenthorLevelMapForSym(const char* sym, std::unordered_map<std::string,double>& out) {
  // relit les caches "gamma/blind/meta" utilisés par AppendMenthorQFlatFields
  const std::string k_gamma = std::string(sym) + std::string("|menthorq_gamma");
  const std::string k_blind = std::string(sym) + std::string("|menthorq_blind_spots");
  const std::string k_meta  = std::string(sym) + std::string("|menthorq_meta");
  auto itg = g_LastMenthorQBySymType.find(k_gamma);
  auto itb = g_LastMenthorQBySymType.find(k_blind);
  auto itm = g_LastMenthorQBySymType.find(k_meta);
  out.clear();
  if (itg!=g_LastMenthorQBySymType.end()) for (auto& kv: itg->second.last_values) out[kv.first]=kv.second;
  if (itb!=g_LastMenthorQBySymType.end()) for (auto& kv: itb->second.last_values) out[kv.first]=kv.second;
  if (itm!=g_LastMenthorQBySymType.end()) for (auto& kv: itm->second.last_values) out[kv.first]=kv.second;
}
static void ML_NearestGexDists(const std::unordered_map<std::string,double>& L, double mid, double tick,
                               long& up_ticks, long& dn_ticks) {
  up_ticks=0; dn_ticks=0;
  double best_up = 1e18, best_dn=1e18;
  for (int k=1;k<=10;k++){
    char kbuf[16]; sprintf(kbuf,"gex_%d",k);
    auto it=L.find(kbuf); if (it==L.end()) continue;
    double dist = it->second - mid;
    if (dist>=0 && dist<best_up) best_up=dist;
    if (dist<0 && -dist<best_dn) best_dn=-dist;
  }
  up_ticks = (tick>0 && best_up<1e18) ? (long)llround(best_up/tick) : 0;
  dn_ticks = (tick>0 && best_dn<1e18) ? (long)llround(best_dn/tick) : 0;
}
static long ML_NearestBlindDist(const std::unordered_map<std::string,double>& L, double mid, double tick) {
  double best = 1e18;
  for (int k=0;k<=8;k++){
    char kbuf[32]; sprintf(kbuf,"blind_spot_%d",k);
    auto it=L.find(kbuf); if (it==L.end()) continue;
    double d = fabs(it->second - mid);
    if (d<best) best=d;
  }
  return (tick>0 && best<1e18) ? (long)llround(best/tick) : 0;
}

// -------- Session (approx NY/UTC) -------------------------------------------
static void ML_SessionBounds_NY(const SCStudyInterfaceRef& sc, int& out_start_h, int& out_start_m, int& out_end_h, int& out_end_m) {
  // Simple: US session 09:30–16:00 NY
  out_start_h = 9; out_start_m=30; out_end_h=16; out_end_m=0;
}
static void ML_SessionProgress(const SCStudyInterfaceRef& sc, int& elapsed_s, double& progress01) {
  SCDateTime dt = sc.CurrentSystemDateTime;
  int y=dt.GetYear(), mo=dt.GetMonth(), d=dt.GetDay();
  int h=dt.GetHour(), mi=dt.GetMinute(), s=dt.GetSecond();
  int sh,sm,eh,em; ML_SessionBounds_NY(sc, sh,sm,eh,em);
  int t_now = h*3600 + mi*60 + s;
  int t_start = sh*3600 + sm*60;
  int t_end   = eh*3600 + em*60;
  if (t_now<t_start){ elapsed_s=0; progress01=0.0; return; }
  if (t_now>t_end){ elapsed_s=t_end-t_start; progress01=1.0; return; }
  elapsed_s = t_now - t_start;
  progress01 = (t_end>t_start)? ml_safe_div((double)elapsed_s, (double)(t_end-t_start)) : 0.0;
}

// -------- Rates 1s alignés temps réel (anneau 10 secondes) -----------------
struct MLRealTimeRing {
  std::array<int, 10> tick_counts{};   // nombre d'événements tick par seconde
  std::array<int, 10> trade_counts{};  // nombre d'événements trade par seconde
  std::array<int, 10> delta_sums{};    // delta cumulé par seconde
  long long last_second = -1;          // dernière seconde traitée
  int current_idx = 0;                 // index courant dans l'anneau
};

static std::unordered_map<std::string, MLRealTimeRing> g_ml_rings_by_key; // key: chart|sym
static inline std::string ML_RateKey(int chart, const char* sym){ return std::to_string(chart)+"|"+std::string(sym); }

static void ML_AccTick(int chart, const char* sym, const SCStudyInterfaceRef& sc){
  auto& ring = g_ml_rings_by_key[ML_RateKey(chart,sym)];
  const long long now_ms = (long long)std::llround(sc.CurrentSystemDateTime.GetAsDouble() * 86400000.0);
  const long long current_second = now_ms / 1000;

  // Si nouvelle seconde, avancer l'anneau et combler les gaps
  if (ring.last_second >= 0 && current_second > ring.last_second) {
    int gaps = (int)(current_second - ring.last_second);
    for (int i = 0; i < gaps && i < 10; ++i) {
      ring.tick_counts[ring.current_idx] = 0;
      ring.trade_counts[ring.current_idx] = 0;
      ring.delta_sums[ring.current_idx] = 0;
      ring.current_idx = (ring.current_idx + 1) % 10;
    }
  }
  ring.last_second = current_second;

  // Incrémenter le compteur de la seconde courante
  ring.tick_counts[ring.current_idx]++;
}

static void ML_AccTrade(int chart, const char* sym, int qty, int delta_sign, const SCStudyInterfaceRef& sc){
  auto& ring = g_ml_rings_by_key[ML_RateKey(chart,sym)];
  const long long now_ms = (long long)std::llround(sc.CurrentSystemDateTime.GetAsDouble() * 86400000.0);
  const long long current_second = now_ms / 1000;

  // Si nouvelle seconde, avancer l'anneau et combler les gaps
  if (ring.last_second >= 0 && current_second > ring.last_second) {
    int gaps = (int)(current_second - ring.last_second);
    for (int i = 0; i < gaps && i < 10; ++i) {
      ring.tick_counts[ring.current_idx] = 0;
      ring.trade_counts[ring.current_idx] = 0;
      ring.delta_sums[ring.current_idx] = 0;
      ring.current_idx = (ring.current_idx + 1) % 10;
    }
  }
  ring.last_second = current_second;

  // Incrémenter les compteurs de la seconde courante
  ring.trade_counts[ring.current_idx]++;  // nombre d'événements trade
  ring.delta_sums[ring.current_idx] += (delta_sign >= 0 ? qty : -qty);  // delta signé
}

static void ML_ReadRates1s(int chart, const char* sym, int& tick_rate, int& trade_rate, int& delta_rate){
  auto it = g_ml_rings_by_key.find(ML_RateKey(chart,sym));
  if (it == g_ml_rings_by_key.end()){ tick_rate=0; trade_rate=0; delta_rate=0; return; }

  const auto& ring = it->second;
  tick_rate = ring.tick_counts[ring.current_idx];   // événements tick dernière seconde
  trade_rate = ring.trade_counts[ring.current_idx]; // nombre de trades dernière seconde
  delta_rate = ring.delta_sums[ring.current_idx];   // delta dernière seconde
}

static int ML_ReadDeltaCum10s(int chart, const char* sym){
  auto it = g_ml_rings_by_key.find(ML_RateKey(chart,sym));
  if (it == g_ml_rings_by_key.end()) return 0;

  const auto& ring = it->second;
  int sum = 0;
  for (int i = 0; i < 10; ++i) {
    sum += ring.delta_sums[i];
  }
  return sum;
}

// Fonction CleanSymbol déplacée ici pour être accessible
static SCString CleanSymbol(const char* sym) {
    if (!sym) return SCString("");
    return SCString(sym);
}

// -------- Fichier ML_READY --------------------------------------------------
static SCString ML_FilePath(int chart, const char* sym){
#ifdef _WIN32
  time_t now = time(NULL); tm* lt = localtime(&now);
  int y = lt? (lt->tm_year+1900):1970;
  int m = lt? (lt->tm_mon+1):1;
  int d = lt? lt->tm_mday:1;
  const char* monthNames[]={"JANVIER","FEVRIER","MARS","AVRIL","MAI","JUIN","JUILLET","AOUT","SEPTEMBRE","OCTOBRE","NOVEMBRE","DECEMBRE"};
  char path[512];
  sprintf(path, "D:\\MIA_IA_system\\DATA_SIERRA_CHART\\DATA_%d\\%s\\%04d%02d%02d\\CHART_%d\\ML_READY",
          y, monthNames[m-1], y,m,d, chart);
  CreateDirectoryA(path, NULL);
  SCString clean = CleanSymbol(sym);
  SCString file; file.Format("%s\\ml_%s_%d.jsonl", path, clean.GetChars(), chart);
  return file;
#else
  return SCString("");
#endif
}

// === MenthorQ Freshness - Simple 24h threshold =============================
static long long g_mq_last_update_ms = 0;  // Mis à jour à la réception d'un snapshot MQ

inline void MQ_MarkUpdate(long long t_ms) {
  g_mq_last_update_ms = t_ms;
}

struct MQSimpleFresh {
  bool   is_struct_fresh;    // true si age <= 24h
  bool   is_rt_fresh;        // false (pas de flux temps réel MQ)
  double age_s;              // âge en secondes ( -1 si inconnu )
  long long last_ms;         // timestamp ms du dernier snapshot (0 si inconnu)
  const char* valid_for_session; // "Current" si frais, sinon "None"
};

inline MQSimpleFresh MQ_ComputeFresh24h(long long now_ms, const char* session_id ) {
  MQSimpleFresh r{};
  r.last_ms = g_mq_last_update_ms;

  if (r.last_ms <= 0) {
    r.is_struct_fresh   = false;
    r.is_rt_fresh       = false;
    r.age_s             = -1.0;
    r.valid_for_session = nullptr; // null si inconnu
    return r;
  }

  r.age_s = (double)(now_ms - r.last_ms) / 1000.0;
  const double THRESH_S = 24.0 * 3600.0;

  r.is_struct_fresh   = (r.age_s <= THRESH_S);
  r.is_rt_fresh       = false;          // pas de MQ temps réel dans ce mode
  r.valid_for_session = r.is_struct_fresh ? session_id : nullptr; // session courante si frais, null sinon

  return r;
}

// ================== Writer ML_READY: n'altère pas Unified ===================
// Déclaration déplacée après la définition de UnifiedState

// ========== DÉCLARATIONS MANQUANTES ==========
// Fonction getTopKDom déplacée plus haut

// Fonction CleanSymbol déplacée plus haut

// Fonction GetPointValue manquante
static double GetPointValue(const SCString& sym) {
    // Valeurs par défaut pour les principaux instruments
    const char* s = sym.GetChars();
    if (strstr(s, "ES") != nullptr) return 50.0;
    if (strstr(s, "NQ") != nullptr) return 20.0;
    if (strstr(s, "YM") != nullptr) return 5.0;
    if (strstr(s, "RTY") != nullptr) return 50.0;
    if (strstr(s, "GC") != nullptr) return 100.0;  // Gold: $100 per point ($10 per tick, tick=0.10)
    if (strstr(s, "CL") != nullptr) return 1000.0; // Crude Oil: $1000 per point ($10 per tick, tick=0.01)
    return 1.0; // valeur par défaut
}

// Fonction GetPriceScale manquante
static int GetPriceScale(const SCString& sym) {
    // Échelles de prix par défaut
    const char* s = sym.GetChars();
    if (strstr(s, "ES") != nullptr) return 2;
    if (strstr(s, "NQ") != nullptr) return 2;
    if (strstr(s, "YM") != nullptr) return 0;
    if (strstr(s, "RTY") != nullptr) return 2;
    if (strstr(s, "GC") != nullptr) return 1;  // Gold: 1 décimale (tick = 0.10)
    if (strstr(s, "CL") != nullptr) return 2;  // Crude Oil: 2 décimales (tick = 0.01)
    return 2; // valeur par défaut
}

// ========== VARIABLES GLOBALES POUR DOUBLE CUMULATIVE DELTA ==========

// Accumulateurs pour le double cumulative delta
static std::unordered_map<std::string, double> g_CumDeltaDay;        // Reset Ã  23:00 UTC (minuit FR)
static std::unordered_map<std::string, double> g_CumDeltaSession;    // Reset aux sessions Asia/London/US
static std::unordered_map<std::string, std::string> g_CurrentSession; // Session courante par symbole
static std::unordered_map<std::string, int> g_LastDayReset;          // YYYYMMDD pour cum_delta_day
static std::unordered_map<std::string, int> g_LastSessionReset;      // YYYYMMDDhhmm pour cum_delta_session

// === FONCTIONS DE RESET AUTOMATIQUE ===
static inline void ResetCumulativeDeltasIfNeeded(const char* sym, long long t_ms) {
    // Conversion UTC
    time_t sec = (time_t)(t_ms / 1000);
    struct tm gm{};
#ifdef _WIN32
    gmtime_s(&gm, &sec);
#else
    gmtime_r(&sec, &gm);
#endif

    // Date actuelle (YYYYMMDD)
    int current_date = (gm.tm_year + 1900) * 10000 + (gm.tm_mon + 1) * 100 + gm.tm_mday;

    // Convertir UTC vers NY (UTC-5 en hiver, UTC-4 en été)
    // Simplification : utiliser UTC-5 (hiver) pour la cohérence
    int ny_hour = (gm.tm_hour - 5 + 24) % 24;
    int current_hour = ny_hour;

    // Reset cum_delta_day à 23:00 UTC (minuit FR)
    if (g_LastDayReset.find(sym) == g_LastDayReset.end() || g_LastDayReset[sym] != current_date) {
        if (gm.tm_hour >= 23 || g_LastDayReset.find(sym) == g_LastDayReset.end()) {
            g_CumDeltaDay[sym] = 0.0;
            g_LastDayReset[sym] = current_date;
        }
    }

    // Détection de session et reset cum_delta_session (logique NY)
    std::string new_session;
    if (current_hour >= 18 || current_hour < 3) {
        new_session = "Asia";    // 18:00-03:00 NY
    } else if (current_hour >= 3 && current_hour < 9) {
        new_session = "London";  // 03:00-09:00 NY
    } else if (current_hour >= 9 && current_hour < 18) {
        new_session = "US";      // 09:00-18:00 NY
    } else {
        new_session = "Asia";    // fallback
    }

    // Reset si changement de session
    if (g_CurrentSession.find(sym) == g_CurrentSession.end() || g_CurrentSession[sym] != new_session) {
        g_CumDeltaSession[sym] = 0.0;
        g_CurrentSession[sym] = new_session;
        g_LastSessionReset[sym] = current_date * 100 + current_hour;
    }
}

// === CALCUL DES MÉTRIQUES DE SESSION ===
static inline void CalculateSessionMetrics(long long t_ms, int& session_elapsed_s, double& session_progress) {
    time_t sec = (time_t)(t_ms / 1000);
    struct tm gm{};
#ifdef _WIN32
    gmtime_s(&gm, &sec);
#else
    gmtime_r(&sec, &gm);
#endif

    // Convertir UTC vers NY (UTC-5 en hiver, UTC-4 en été)
    // Simplification : utiliser UTC-5 (hiver) pour la cohérence
    int ny_hour = (gm.tm_hour - 5 + 24) % 24;
    int current_hour = ny_hour;
    int session_start_hour, session_end_hour;

    // Déterminer les heures de session (basées sur NY)
    if (current_hour >= 18 || current_hour < 3) {
        session_start_hour = 18;  // Asia: 18:00-03:00 NY
        session_end_hour = 3;
    } else if (current_hour >= 3 && current_hour < 9) {
        session_start_hour = 3;   // London: 03:00-09:00 NY
        session_end_hour = 9;
    } else {
        session_start_hour = 9;   // US: 09:00-18:00 NY
        session_end_hour = 18;
    }

    // Calculer le temps écoulé dans la session (version seconds/seconds)
    int session_duration_s;
    if (session_start_hour > session_end_hour) {
        // Session qui traverse minuit (Asia: 18:00-03:00)
        session_duration_s = (24 - session_start_hour + session_end_hour) * 3600;
    } else {
        // Session normale
        session_duration_s = (session_end_hour - session_start_hour) * 3600;
    }

    int elapsed_hours = current_hour - session_start_hour;
    if (elapsed_hours < 0) elapsed_hours += 24; // Gestion du passage de minuit

    session_elapsed_s = elapsed_hours * 3600 + gm.tm_min * 60 + gm.tm_sec;
    session_progress = (session_duration_s > 0) ?
        std::min(1.0, (double)session_elapsed_s / (double)session_duration_s) : 0.0;
}

// ========== VARIABLES GLOBALES MENTHORQ ==========
// Structure pour stocker les dernières valeurs MenthorQ par symbole
// LastMenthorQContent déplacé plus haut
// g_LastMenthorQBySymType déplacé plus haut

// ========== CACHE L2 ==========
// Structure pour le cache L2 des données DOM
struct L2TopCache {
    double t_bid1 = NAN, t_ask1 = NAN;  // timestamps Sierra days
    double bid1 = 0.0, ask1 = 0.0;      // prix L1
    int bq1 = 0, aq1 = 0;               // quantités L1
    long long last_update_ms = 0;       // timestamp ms pour age
};
static std::unordered_map<std::string, L2TopCache> g_l2_by_key;

static inline std::string l2_key(int chart, const char* sym) {
    return std::to_string(chart) + std::string("|") + std::string(sym ? sym : "");
}

static inline L2TopCache& get_l2(int chart, const char* sym) {
    return g_l2_by_key[l2_key(chart, sym)];
}

// ========== ÉTAT UNIFIÉ POUR SNAPSHOTS COMPLETS ==========

// Structure pour mémoriser l'état complet par symbole (snapshot unifié)
struct UnifiedState {
  // Horodatage dernier update (Sierra days), utile pour cadence/heartbeat
  double t_days = 0.0;
  // === PATCH 2A: Ajout des champs manquants START ===
  double last_update_days = 0.0;
  double last_quote_unix_s = 0.0;
  double last_dom_unix_s = 0.0;
  // === PATCH 2A: Ajout des champs manquants END ===

  // BASEDATA
  int i = -1; double o=0, h=0, l=0, c=0; double v=0, bidvol=0, askvol=0;

  // QUOTE (L1)
  double bid=0, ask=0; int bq=0, aq=0;

  // DEPTH L1 (si différencié du L1 "quote")
  double dom_bid1=0, dom_ask1=0; int dom_bq1=0, dom_aq1=0;

  // VWAP & PVWAP
  double vwap=0, up1=0, dn1=0, up2=0, dn2=0, up3=0, dn3=0;
  double pvwap=0, p_up1=0, p_dn1=0, p_up2=0, p_dn2=0;

  // VWAP Weekly & Monthly
  double vwap_weekly=std::numeric_limits<double>::quiet_NaN();
  double w_up1=std::numeric_limits<double>::quiet_NaN(), w_dn1=std::numeric_limits<double>::quiet_NaN();  // SD+1, SD-1 seulement
  double vwap_monthly=std::numeric_limits<double>::quiet_NaN();
  bool monthly_weekly_identical = false;  // CORRECTION: Flag pour Monthly=Weekly

  // VVA
  double vah=0, val=0, vpoc=0;


  // ATR / Corrélation / VIX
  double atr=0, corr=0, vix=0;

  // Cum Delta
  double cum_delta_day=0, cum_delta_session=0; std::string session_id="";

  // Télémetrie (optionnel)
  unsigned seq = 0;

  // === [ADD] Qualité & Confluence ===
  bool is_dom_fresh = false;
  std::string data_quality = "";
  double confluence_strength = 0.0;

  // === [ADD] Next wall ===
  std::string next_wall_side = "";
  double next_wall_price = 0.0;
  double next_wall_strength = 0.0;

  // === [ADD] MenthorQ niveaux ===
  double hvl = 0.0;
  double gex_1 = 0.0, gex_2 = 0.0, gex_3 = 0.0, gex_4 = 0.0, gex_5 = 0.0,
         gex_6 = 0.0, gex_7 = 0.0, gex_8 = 0.0, gex_9 = 0.0, gex_10 = 0.0;
  double call_resistance = 0.0, put_support = 0.0;
  double call_resistance_0dte = 0.0, put_support_0dte = 0.0, hvl_0dte = 0.0, gamma_wall_0dte = 0.0;

  // === [ADD] Blind spots ===
  double blind_spot_0=0.0, blind_spot_1=0.0, blind_spot_2=0.0, blind_spot_3=0.0, blind_spot_4=0.0,
         blind_spot_5=0.0, blind_spot_6=0.0, blind_spot_7=0.0, blind_spot_8=0.0;
};

// ================== Structures et caches pour ML_READY ===================
struct LastNBCV {
  double askVolume=0, bidVolume=0, delta=0, totalVolume=0;
  double deltaPct=0, askPct=0, bidPct=0;
  int pressure=0;
};

// ================== Structure LIVE (32 champs optimisés) ===================
struct LiveRec {
  // Meta
  long long t_ms;
  std::string sym;
  std::string session_id;

  // Prix
  double best_bid, best_ask, mid, spread, microprice;
  int spread_ticks;

  // Volume
  int volume, bid_size, ask_size;
  double cum_delta_day, cum_delta_session;

  // VWAP/VVA
  double vwap, vah, val, vpoc;
  double d_vwap_ticks, d_vpoc_ticks;

  // VWAP Weekly & Monthly
  double vwap_weekly, vwap_monthly;
  double d_vwap_weekly_ticks, d_vwap_monthly_ticks;

  // VWAP Weekly Bands (SD+1, SD-1 seulement)
  double w_up1, w_dn1;
  double d_w_up1_ticks, d_w_dn1_ticks;  // Distances en ticks

  // Structure
  std::string next_wall_side;
  double next_wall_dist_ticks, next_wall_strength;
  double confluence_strength;

  // MenthorQ
  double hvl;
  double gex_1, gex_2, gex_3;
  double gex_4, gex_5, gex_6, gex_7, gex_8, gex_9, gex_10;
  double call_resistance, put_support;
  double call_resistance_0dte, put_support_0dte, hvl_0dte, gamma_wall_0dte;
  double blind_spot_0, blind_spot_1, blind_spot_2, blind_spot_3, blind_spot_4,
         blind_spot_5, blind_spot_6, blind_spot_7, blind_spot_8;

  // Qualité
  bool is_dom_fresh, is_1tick_spread, in_value_area;
  std::string data_quality;

  // Microstructure
  double level1_imbalance, microgap_n;

  // Volatilité
  double vix, atr;
};
static std::unordered_map<std::string, LastNBCV> g_LastNBCVBySym;

// ========= [ADD] STATE & HELPERS GAME CHANGERS =============================

// --- Intermarkets buffers (rolling ~120s)
struct RetPoint { long long t_ms; double r; };
struct InterMkState {
  std::deque<RetPoint> nq, es;
  double last_mid_nq = NAN;
  double last_mid_es = NAN;
  // RS (spread) stats
  std::deque<std::pair<long long,double>> spread; // time, spread
};
static InterMkState g_ims;

// --- Overnight / IB & Anchored VWAP
struct AnchoredVWAP {
  bool   active=false;
  long long t0=0;
  double sum_pv=0.0, sum_v=0.0;
  double last_v_seen=0.0; // pour incrémenter
  double value= NAN;
  void reset(long long t){ active=true; t0=t; sum_pv=0; sum_v=0; last_v_seen=0; value=NAN; }
  void push(double price, double v_delta){
    if (v_delta<=0) return;

    // PATCH V3.5.22: Validation de cohérence AWAP vs prix actuel
    // Problème détecté : AWAP peut rester figé à des valeurs anciennes (ex: CL @ 77.27 vs 60.30)
    // Cause : Rollover de contrat ou reset partiel laissant des valeurs stales
    // Solution : Détecter divergence excessive et forcer reset
    if (std::isfinite(value) && std::isfinite(price) && price > 0) {
      double ratio = value / price;
      // Si AWAP diverge de plus de 30% du prix actuel, reset complet
      if (ratio < 0.70 || ratio > 1.30) {
        // AWAP corrompu détecté - réinitialiser avec le prix actuel
        sum_pv = price * v_delta;
        sum_v = v_delta;
        value = price;
        return;
      }
    }

    sum_pv += price * v_delta;
    sum_v  += v_delta;
    value   = (sum_v>0)? (sum_pv/sum_v) : NAN;
  }
};

struct StructureState {
  // ON range (depuis RTH close -> jusqu'à RTH open)
  double onh = NAN, onl = NAN;
  long long on_fix_ts = 0; // timestamp de gel à l'ouverture RTH
  bool on_frozen = false;

  // IB (1ère heure RTH)
  double ibh = NAN, ibl = NAN;
  long long ib_start_ts = 0;
  long long ib_end_ts   = 0;
  bool ib_frozen = false;

  // Anchored VWAPs
  AnchoredVWAP awap_onh, awap_onl, awap_ibo;
  long long awap_ibo_ts = 0; // ancre IBO (ouverture RTH)

  // volumétrie (pour increments AWAP)
  double last_total_volume = 0.0; // proxy : volume bar cumul approximé
};
// État Structure par symbole (évite le mélange ES/NQ)
static std::unordered_map<std::string, StructureState> g_struct_by_sym;
static inline StructureState& get_struct(const char* sym){
    // PATCH: Garantir l'isolation des données StructureState par symbole
    const char* safe_sym = (sym && sym[0] != '\0') ? sym : "UNKNOWN";

    // PATCH: Validation stricte de l'isolation
    auto& S = g_struct_by_sym[safe_sym];

    // Debug: Vérifier que les valeurs sont cohérentes avec le symbole
    if (strstr(safe_sym, "NQ") && (S.ibh > 0 && (S.ibh < 20000 || S.ibh > 30000))) {
        // Contamination détectée : NQ avec valeurs ES, reset
        S.ibh = NAN; S.ibl = NAN; S.ib_start_ts = 0; S.ib_end_ts = 0; S.ib_frozen = false;
    } else if (strstr(safe_sym, "ES") && (S.ibh > 0 && (S.ibh < 5000 || S.ibh > 8000))) {
        // Contamination détectée : ES avec valeurs NQ, reset
        S.ibh = NAN; S.ibl = NAN; S.ib_start_ts = 0; S.ib_end_ts = 0; S.ib_frozen = false;
    }

    return S;
}

// --- Next Wall (proche du mid) ---------------------------------------------
struct NextWall { double price=NAN; const char* side="call"; double dist_pts=NAN; long dist_ticks=0; double strength=NAN; int age_min=0; };

// --- Outils temps/horaires simples -----------------------------------------
static inline int HHMM_from_tsNY(const SCDateTime& dt) {
  // dt est en tz de Sierra; si tu as NY déjà, utilise le convertisseur du projet
  int hh = dt.GetHour(); int mm = dt.GetMinute();
  return hh*100 + mm;
}
static inline bool is_rth_open(const SCDateTime& dt, int open_hhmm, int close_hhmm) {
  const int hhmm = HHMM_from_tsNY(dt);
  // autorise chevauchements simples (open < close)
  return hhmm >= open_hhmm && hhmm < close_hhmm;
}

// --- Corrélation rapide -----------------------------------------------------
static inline double mean_of(const std::vector<double>& x){ if(x.empty()) return NAN; double s=0; for(double v:x) s+=v; return s/x.size(); }
static inline double corr_of(const std::vector<double>& x, const std::vector<double>& y){
  size_t n = std::min(x.size(), y.size()); if (n<3) return NAN;
  double mx=0,my=0; for(size_t i=0;i<n;i++){ mx+=x[i]; my+=y[i]; } mx/=n; my/=n;
  double num=0, dx=0, dy=0;
  for(size_t i=0;i<n;i++){ double ax=x[i]-mx; double ay=y[i]-my; num+=ax*ay; dx+=ax*ax; dy+=ay*ay; }
  if (dx<=0 || dy<=0) return NAN;
  return num / std::sqrt(dx*dy);
}

// --- Calcule le lead ES->NQ en ms (fenêtre 120s, lags +/-3000ms) -----------
static inline void compute_lead_and_rs(long long now_ms, double &lead_ms, double &lead_cc, double &rs_z){
  // 1) purge >120s
  const long long horizon = 120000;
  while(!g_ims.nq.empty() && now_ms - g_ims.nq.front().t_ms > horizon) g_ims.nq.pop_front();
  while(!g_ims.es.empty() && now_ms - g_ims.es.front().t_ms > horizon) g_ims.es.pop_front();
  while(!g_ims.spread.empty() && now_ms - g_ims.spread.front().first > horizon) g_ims.spread.pop_front();

  // 2) lead
  lead_ms = NAN; lead_cc = NAN;
  // PATCH: Réduire le seuil minimum pour plus de données
  if (g_ims.nq.size()<5 || g_ims.es.size()<5) return;
  // Échantillonne les séries sur une grille commune (coarse) pour robustesse
  const int step_ms = 100;
  std::vector<double> r_nq, r_es_shift;
  // re-échantillonne NQ sur pas 100ms
  long long t0 = std::max(g_ims.nq.front().t_ms, g_ims.es.front().t_ms);
  long long t1 = std::min(g_ims.nq.back().t_ms,  g_ims.es.back().t_ms);
  if (t1 - t0 < 3000) return;
  auto sample = [&](const std::deque<RetPoint>& s){
    std::vector<double> out;
    size_t j=0;
    for(long long t=t0; t<=t1; t+=step_ms){
      while (j+1<s.size() && s[j+1].t_ms<=t) ++j;
      out.push_back(s[j].r);
    }
    return out;
  };
  std::vector<double> base_es = sample(g_ims.es);
  std::vector<double> base_nq = sample(g_ims.nq);
  // PATCH: Réduire le seuil minimum pour plus de données
  if (base_es.size()<10 || base_nq.size()<10) return;

  int best_tau=0; double best_cc=-2;
  for(int tau=-3000; tau<=3000; tau+=100){
    // shift NQ de tau (corr ES(t) vs NQ(t+tau))
    std::vector<double> shifted; shifted.reserve(base_nq.size());
    int shift = tau/step_ms;
    for (int i=0;i<(int)base_nq.size();++i){
      int k = i+shift;
      if (k<0 || k>=(int)base_nq.size()) continue;
      shifted.push_back(base_nq[k]);
    }
    std::vector<double> es_cut; es_cut.reserve(shifted.size());
    // aligne ES sur même longueur
    int cut_begin = (shift>0? shift:0);
    int cut_end   = (int)base_es.size() - (shift<0? -shift:0);
    for (int i=cut_begin;i<cut_end;i++) es_cut.push_back(base_es[i]);
    // PATCH: Réduire le seuil minimum pour plus de données
    if (es_cut.size()<10 || shifted.size()!=es_cut.size()) continue;
    double cc = corr_of(es_cut, shifted);
    if (std::isfinite(cc) && cc>best_cc){ best_cc=cc; best_tau=tau; }
  }
  if (best_cc>-2) { lead_ms = (double)best_tau; lead_cc = best_cc; }

  // 3) Relative Strength z (modèle beta simple)
  // spread = NQ - beta*ES, beta ~ std(NQ)/std(ES) * corr
  if (g_ims.spread.size()>=2){
    std::vector<double> z; z.reserve(g_ims.spread.size());
    double m=0,s2=0; int n=0;
    for (auto &p:g_ims.spread){ double v=p.second; m+=v; s2+=v*v; n++; }
    if (n>=2){
      m/=n; double var = s2/n - m*m; double sd = (var>0)? std::sqrt(var):NAN;
      double last = g_ims.spread.back().second;
      rs_z = (std::isfinite(sd) && sd>0)? ((last - m)/sd) : NAN;
    }
  }
}

// --- Met à jour retours & spread pour NQ / ES -------------------------------
static inline void push_mid_for_RS(long long t_ms, double mid_nq, double mid_es){
  // returns simples (Δmid) ; tu peux standardiser si besoin
  if (std::isfinite(mid_nq)){
    if (std::isfinite(g_ims.last_mid_nq)){
      g_ims.nq.push_back({t_ms, mid_nq - g_ims.last_mid_nq});
    }
    g_ims.last_mid_nq = mid_nq;
  }
  if (std::isfinite(mid_es)){
    if (std::isfinite(g_ims.last_mid_es)){
      g_ims.es.push_back({t_ms, mid_es - g_ims.last_mid_es});
    }
    g_ims.last_mid_es = mid_es;
  }
  // Spread t : NQ - beta*ES (beta ≈ ratio d'écart-type simple sur fenêtre courte)
  if (g_ims.nq.size()>=2 && g_ims.es.size()>=2){
    // calcule beta rough sur derniers 120s (std ratio)
    auto mkvec=[&](const std::deque<RetPoint>& d){
      std::vector<double> v; v.reserve(d.size());
      for (auto &x:d) v.push_back(x.r);
      return v;
    };
    auto vN = mkvec(g_ims.nq); auto vE = mkvec(g_ims.es);
    auto stdv=[&](const std::vector<double>& v){ double m=mean_of(v); double s=0; for(double x:v){ double d=x-m; s+=d*d; } return (v.size()>1)? std::sqrt(s/(v.size()-1)):1.0;};
    double sdN=stdv(vN), sdE=stdv(vE);
    double cc = corr_of(vN,vE); if (!std::isfinite(cc)) cc=0.0;
    double beta = (sdE>1e-9)? (sdN/sdE)*cc : 0.0;
    double spread_t = mid_nq - beta*mid_es;
    if (std::isfinite(spread_t)) {
      g_ims.spread.push_back({t_ms, spread_t});
    }
  }
}

// --- Structure ON/IB & ancrages --------------------------------------------
static inline void update_ON_IB_AWAP(const SCStudyInterfaceRef& sc, long long t_ms, double mid, double bar_volume, StructureState& S, const char* sym){
  const int open_hhmm = sc.Input[93].GetInt();
  const int close_hhmm= sc.Input[94].GetInt();
  const SCDateTime now = sc.CurrentSystemDateTime; // suppose tz alignée
  const bool in_rth = is_rth_open(now, open_hhmm, close_hhmm);

  // PATCH: Validation stricte des valeurs StructureState pour éviter la contamination
  // Si les valeurs IB sont incohérentes avec le mid, les reset
  if (std::isfinite(S.ibh) && std::isfinite(mid)) {
    double ratio = S.ibh / mid;
    if (ratio < 0.5 || ratio > 2.0) {
      // Valeur aberrante détectée, reset IB
      S.ibh = NAN; S.ibl = NAN; S.ib_start_ts = 0; S.ib_end_ts = 0; S.ib_frozen = false;
    }
  }

  // Debug RTH: vérifier que Input[93]=930, Input[94]=1600 et que le fuseau est NY
  // Si on_fix_ts reste à 0, c'est que la détection RTH ne fonctionne pas

  // Overnight range : actif tant que RTH pas ouvert (pas frozen)
  if (!S.on_frozen){
    // init avec seed propre
    if (!std::isfinite(S.onh)) S.onh = mid;
    if (!std::isfinite(S.onl)) S.onl = mid;

    // Garde-fous anti-poubelle : si onl/onh aberrants, reseed
    if (S.onl < 0.2 * mid || S.onh > 2.0 * mid) {
      S.onh = mid;
      S.onl = mid;
    }

    // Mise à jour normale
    S.onh = std::max(S.onh, mid);
    S.onl = std::min(S.onl, mid);

    // PATCH: Activer on_frozen si on a des données ON valides (même en dehors de RTH)
    if (std::isfinite(S.onh) && std::isfinite(S.onl) && S.onh > S.onl) {
      S.on_frozen = true;
      S.on_fix_ts = t_ms;
    }
  } else {
    // PATCH: Si on_frozen mais onh/onl sont NAN, les initialiser avec des valeurs par défaut
    // Cela peut arriver si la structure a été reset ou si on a manqué la session ON
    if (!std::isfinite(S.onh) || !std::isfinite(S.onl)) {
      S.onh = mid;
      S.onl = mid;
    }
  }
  // IB (1ère heure RTH) - UNIQUEMENT pendant RTH
  if (in_rth){
    if (!S.ib_frozen){
      if (S.ib_start_ts==0){ // RTH vient d'ouvrir
        S.ib_start_ts = t_ms;
        S.ib_end_ts   = t_ms + 60*60*1000LL; // 60 min
        // PATCH: Initialisation sécurisée avec validation du symbole
        S.ibh = mid; S.ibl = mid;
        // Debug: Vérifier que les valeurs sont cohérentes avec le symbole
        // NQ: ~25000-26000, ES: ~6500-7000
        if (strstr(sym, "NQ") && (mid < 20000 || mid > 30000)) {
          // Valeur aberrante pour NQ, corriger
          S.ibh = 25000.0; S.ibl = 25000.0;
        } else if (strstr(sym, "ES") && (mid < 5000 || mid > 8000)) {
          // Valeur aberrante pour ES, corriger
          S.ibh = 6700.0; S.ibl = 6700.0;
        }
        // freeze ON à l'ouverture
        S.on_frozen = true; S.on_fix_ts = t_ms;

        // PATCH: Activer AWAP ONH/ONL AVANT de reset ONH/ONL
        if (std::isfinite(S.onh) && !S.awap_onh.active) S.awap_onh.reset(t_ms);
        if (std::isfinite(S.onl) && !S.awap_onl.active) S.awap_onl.reset(t_ms);

        // ancrer AWAP IBO
        S.awap_ibo.reset(t_ms);
        S.awap_ibo_ts = t_ms;

        // PATCH: NE PAS reset onh/onl - conserver les valeurs ON pour l'affichage
        // Les valeurs ON sont nécessaires pour l'analyse technique même après ouverture RTH
        // S.onh = NAN;  // SUPPRIMÉ : conserver onh
        // S.onl = NAN;  // SUPPRIMÉ : conserver onl
        // PATCH: Ne pas désactiver on_frozen immédiatement pour préserver AWAP
        // S.on_frozen = false; // sera réactivé à la prochaine session
      }
      // met à jour ibh/ibl tant que < ib_end_ts
      if (t_ms <= S.ib_end_ts){
        // PATCH: Validation des valeurs avant mise à jour pour éviter la contamination
        double new_ibh = std::max(S.ibh, mid);
        double new_ibl = std::min(S.ibl, mid);

        // Vérifier la cohérence avec le symbole
        bool is_nq = strstr(sym, "NQ") != nullptr;
        bool is_es = strstr(sym, "ES") != nullptr;

        if (is_nq && (new_ibh < 20000 || new_ibh > 30000 || new_ibl < 20000 || new_ibl > 30000)) {
          // Valeur aberrante pour NQ, ignorer cette mise à jour
          // Garder les valeurs précédentes
        } else if (is_es && (new_ibh < 5000 || new_ibh > 8000 || new_ibl < 5000 || new_ibl > 8000)) {
          // Valeur aberrante pour ES, ignorer cette mise à jour
          // Garder les valeurs précédentes
        } else {
          // Valeurs cohérentes, appliquer la mise à jour
          S.ibh = new_ibh;
          S.ibl = new_ibl;
        }
      } else {
        S.ib_frozen = true;
      }
    }
  } else {
    // hors RTH : reset IB pour prochaine séance
    S.ib_frozen = false; S.ib_start_ts = 0; S.ib_end_ts=0;
  }

  // Anchored VWAP ONH/ONL : ancre quand on fige ON (RTH ou session active)
  // PATCH: Activer AWAP même en dehors de RTH si ON est figé
  if (S.on_frozen && !S.awap_onh.active && std::isfinite(S.onh)) S.awap_onh.reset(S.on_fix_ts);
  if (S.on_frozen && !S.awap_onl.active && std::isfinite(S.onl)) S.awap_onl.reset(S.on_fix_ts);

  // PATCH: Activer AWAP IBO même en dehors de RTH (session active)
  if (!S.awap_ibo.active && (in_rth || S.on_frozen)) {
    S.awap_ibo.reset(t_ms);
    S.awap_ibo_ts = t_ms;
  }

  // Incrément AWAPs (proxy volume = bar_volume delta ; prix = mid)
  double vdelta = 0.0;
  if (bar_volume >= S.last_total_volume){
    vdelta = bar_volume - S.last_total_volume;
  }
  S.last_total_volume = bar_volume;

  if (S.awap_onh.active) S.awap_onh.push(mid, vdelta);
  if (S.awap_onl.active) S.awap_onl.push(mid, vdelta);
  if (S.awap_ibo.active) S.awap_ibo.push(mid, vdelta);
}

// --- Next Wall (proche du mid) ---------------------------------------------
static inline NextWall compute_next_wall(double mid, double tick,
  double call_resistance, double put_support,
  const std::vector<double>& gex_levels, // optionnel
  double confluence_strength, int age_min // si tu as l'âge des données options
){
  NextWall nw;
  auto consider=[&](double px, const char* sd){
    if (!std::isfinite(px) || px<=0) return;
    double d = std::fabs(px - mid);
    if (!std::isfinite(nw.price) || d < std::fabs(nw.price - mid)){
      nw.price = px; nw.side = sd;
    }
  };
  consider(call_resistance,"call");
  consider(put_support,"put");
  for (double g: gex_levels) consider(g, (g>=mid?"call":"put"));

  if (std::isfinite(nw.price)){
    nw.dist_pts = nw.price - mid;
    nw.dist_ticks = (long) llround(nw.dist_pts / tick);
    // strength basique + bonus confluence (Option A: fine)
    double base = 1.0 / (1.0 + std::fabs((double)nw.dist_ticks));
    double bonus = std::max(0.0, std::min(0.3, confluence_strength)); // borne réduite
    nw.strength = std::max(0.0, std::min(1.0, base + bonus));
    nw.age_min  = std::max(0, age_min);
  }
  return nw;
}

// ================== GARDE-FOUS POUR DONNÉES DE QUALITÉ ===================
// Détection des conditions de marché fermé/stale
static inline bool is_closed_or_stale(const UnifiedState& U, int tick_rate_1s, int trade_rate_1s,
                                     double session_progress, bool is_dom_fresh, long dom_age_ms,
                                     double best_bid, double best_ask, const char* sizes_source,
                                     int dom_bq1, int dom_aq1) {
  int still = (tick_rate_1s == 0 && trade_rate_1s == 0);
  int edges = (session_progress == 0.0 || session_progress == 1.0);
  int stale = (!is_dom_fresh || dom_age_ms > 1500);
  int badbb = (best_bid <= 0.0 || best_ask <= 0.0 || best_ask <= best_bid);
  int weakq = (strcmp(sizes_source, "QUOTE") == 0 && dom_bq1 == 0 && dom_aq1 == 0);
  int score = still + edges + stale + badbb + weakq;
  return score >= 2;
}

// Cache pour last_good_bbo
static double g_last_good_bid = 0.0;
static double g_last_good_ask = 0.0;
static long long g_last_ok_ms = 0;

// Réparation BBO si possible
static bool repair_bbo(double& bid, double& ask, const UnifiedState& U, long long now_ms) {
  // Tentative de réparation via DOM
  if (ask <= 0.0 && U.dom_ask1 > 0.0) ask = U.dom_ask1;
  if (bid <= 0.0 && U.dom_bid1 > 0.0) bid = U.dom_bid1;

  // Vérification de validité
  bool bbo_ok = (bid > 0.0 && ask > bid);

  // Fallback sur cache si toujours invalide (10s max)
  if (!bbo_ok && (now_ms - g_last_ok_ms) <= 10000 && g_last_good_ask > g_last_good_bid) {
    bid = g_last_good_bid;
    ask = g_last_good_ask;
    bbo_ok = true;
  }

  // Mise à jour du cache si valide
  if (bbo_ok) {
    g_last_good_bid = bid;
    g_last_good_ask = ask;
    g_last_ok_ms = now_ms;
  }

  return bbo_ok;
}

// ================== Writer LIVE: ultra-léger pour l'algo ===================
static void WriteLiveLine(const SCStudyInterfaceRef& sc,
                          const char* sym,
                          int chart,
                          const UnifiedState& U,
                          long long t_ms,
                          const char* emit_reason,
                          unsigned seq_unified)
{
  // Vérifier si le writer LIVE est activé
  if (sc.Input[90].GetInt() == 0) return;

  // Créer la structure LIVE
  LiveRec live{};

  // Meta
  live.t_ms = t_ms;
  live.sym = std::string(sym);
  live.session_id = (U.session_id.size() ? U.session_id : std::string("US"));

  // Prix
  live.best_bid = U.bid;
  live.best_ask = U.ask;
  live.mid = (U.bid + U.ask) / 2.0;
  live.spread = U.ask - U.bid;
  live.spread_ticks = (int)std::round(live.spread / sc.TickSize);
  live.microprice = live.mid; // Simplifié pour LIVE

  // Volume
  live.volume = (int)U.v;
  live.bid_size = (U.dom_bq1 > 0) ? U.dom_bq1 : U.bq;
  live.ask_size = (U.dom_aq1 > 0) ? U.dom_aq1 : U.aq;
  live.cum_delta_day = U.cum_delta_day;
  live.cum_delta_session = U.cum_delta_session;

  // VWAP/VVA
  live.vwap = U.vwap;
  live.vah = U.vah;
  live.val = U.val;
  live.vpoc = U.vpoc;

  // VWAP Weekly & Monthly
  live.vwap_weekly = U.vwap_weekly;
  live.vwap_monthly = U.vwap_monthly;

  // VWAP Weekly Bands (SD+1, SD-1 seulement)
  live.w_up1 = U.w_up1;
  live.w_dn1 = U.w_dn1;

  // Calculer les distances en ticks
  const double tick = sc.TickSize > 0.0 ? sc.TickSize : 0.25;
  live.d_vwap_ticks = (live.vwap > 0.0) ? (live.mid - live.vwap) / tick : 0.0;
  live.d_vpoc_ticks = (live.vpoc > 0.0) ? (live.mid - live.vpoc) / tick : 0.0;
  live.d_vwap_weekly_ticks = (live.vwap_weekly > 0.0) ? (live.mid - live.vwap_weekly) / tick : 0.0;
  live.d_vwap_monthly_ticks = (live.vwap_monthly > 0.0) ? (live.mid - live.vwap_monthly) / tick : 0.0;

  // Distances VWAP Weekly Bands (SD+1, SD-1)
  live.d_w_up1_ticks = (live.w_up1 > 0.0) ? (live.mid - live.w_up1) / tick : 0.0;
  live.d_w_dn1_ticks = (live.w_dn1 > 0.0) ? (live.mid - live.w_dn1) / tick : 0.0;

  // Confluence & Next wall
  live.confluence_strength = U.confluence_strength;
  live.next_wall_side = U.next_wall_side.size() ? U.next_wall_side : "none";
  live.next_wall_strength = U.next_wall_strength;
  {
    const double tick2 = sc.TickSize > 0.0 ? sc.TickSize : 0.25;
    const double nw_price = U.next_wall_price;
    live.next_wall_dist_ticks = (nw_price != 0.0) ? ((live.mid - nw_price) / tick2) : 0.0;
  }

  // MenthorQ complet
  live.hvl = U.hvl;
  live.gex_1 = U.gex_1; live.gex_2 = U.gex_2; live.gex_3 = U.gex_3;
  live.gex_4 = U.gex_4; live.gex_5 = U.gex_5; live.gex_6 = U.gex_6;
  live.gex_7 = U.gex_7; live.gex_8 = U.gex_8; live.gex_9 = U.gex_9; live.gex_10 = U.gex_10;
  live.call_resistance = U.call_resistance;
  live.put_support = U.put_support;
  live.call_resistance_0dte = U.call_resistance_0dte;
  live.put_support_0dte = U.put_support_0dte;
  live.hvl_0dte = U.hvl_0dte;
  live.gamma_wall_0dte = U.gamma_wall_0dte;
  live.blind_spot_0 = U.blind_spot_0; live.blind_spot_1 = U.blind_spot_1; live.blind_spot_2 = U.blind_spot_2;
  live.blind_spot_3 = U.blind_spot_3; live.blind_spot_4 = U.blind_spot_4; live.blind_spot_5 = U.blind_spot_5;
  live.blind_spot_6 = U.blind_spot_6; live.blind_spot_7 = U.blind_spot_7; live.blind_spot_8 = U.blind_spot_8;

  // Qualité & flags
  live.is_dom_fresh = U.is_dom_fresh;
  live.data_quality = U.data_quality.size() ? U.data_quality : "OK";
  live.is_1tick_spread = (live.spread > 0.0) && (live.spread_ticks == 1);
  live.in_value_area = (live.mid >= live.val && live.mid <= live.vah);

  // Microstructure
  {
    const int bs = std::max(0, live.bid_size);
    const int as = std::max(0, live.ask_size);
    const int den = std::max(1, bs + as);
    const double mpw = (as>0 && bs>0) ? ((U.ask * bs + U.bid * as) / double(den)) : live.mid;
    live.microprice = mpw;
    const double atr_d = (U.atr > 1e-9) ? U.atr : 1.0;
    live.microgap_n = (mpw - live.mid) / atr_d;
    live.level1_imbalance = double(as - bs) / double(den);
  }

  // Volatilité
  live.vix = U.vix;
  live.atr = U.atr;

  // Construire le JSON LIVE compact
  SCString live_json;
  live_json.Format(
    R"({"t_ms":%lld,"sym":"%s","session_id":"%s",)"
    R"("best_bid":%.2f,"best_ask":%.2f,"mid":%.2f,"spread":%.2f,"spread_ticks":%d,"microprice":%.2f,)"
    R"("volume":%d,"bid_size":%d,"ask_size":%d,"cum_delta_day":%.1f,"cum_delta_session":%.1f,)"
    R"("vwap":%.2f,"vah":%.2f,"val":%.2f,"vpoc":%.2f,"d_vwap_ticks":%.2f,"d_vpoc_ticks":%.2f,)"
    R"("next_wall_side":"%s","next_wall_dist_ticks":%.2f,"next_wall_strength":%.2f,"confluence_strength":%.2f,)"
    R"("gex_1":%.2f,"gex_2":%.2f,"gex_3":%.2f,"gex_4":%.2f,"gex_5":%.2f,"gex_6":%.2f,"gex_7":%.2f,"gex_8":%.2f,"gex_9":%.2f,"gex_10":%.2f,)"
    R"("call_resistance":%.2f,"put_support":%.2f,"call_resistance_0dte":%.2f,"put_support_0dte":%.2f,"hvl":%.2f,"hvl_0dte":%.2f,"gamma_wall_0dte":%.2f,)"
    R"("blind_spot_0":%.2f,"blind_spot_1":%.2f,"blind_spot_2":%.2f,"blind_spot_3":%.2f,"blind_spot_4":%.2f,"blind_spot_5":%.2f,"blind_spot_6":%.2f,"blind_spot_7":%.2f,"blind_spot_8":%.2f,)"
    R"("is_dom_fresh":%s,"data_quality":"%s","is_1tick_spread":%s,"in_value_area":%s,)"
    R"("level1_imbalance":%.3f,"microgap_n":%.3f,"vix":%.2f,"atr":%.2f})",
    live.t_ms, live.sym.c_str(), live.session_id.c_str(),
    live.best_bid, live.best_ask, live.mid, live.spread, live.spread_ticks, live.microprice,
    live.volume, live.bid_size, live.ask_size, live.cum_delta_day, live.cum_delta_session,
    live.vwap, live.vah, live.val, live.vpoc, live.d_vwap_ticks, live.d_vpoc_ticks,
    live.next_wall_side.c_str(), live.next_wall_dist_ticks, live.next_wall_strength, live.confluence_strength,
    live.gex_1, live.gex_2, live.gex_3, live.gex_4, live.gex_5, live.gex_6, live.gex_7, live.gex_8, live.gex_9, live.gex_10,
    live.call_resistance, live.put_support, live.call_resistance_0dte, live.put_support_0dte, live.hvl, live.hvl_0dte, live.gamma_wall_0dte,
    live.blind_spot_0, live.blind_spot_1, live.blind_spot_2, live.blind_spot_3, live.blind_spot_4, live.blind_spot_5, live.blind_spot_6, live.blind_spot_7, live.blind_spot_8,
    live.is_dom_fresh ? "true" : "false", live.data_quality.c_str(),
    live.is_1tick_spread ? "true" : "false", live.in_value_area ? "true" : "false",
    live.level1_imbalance, live.microgap_n, live.vix, live.atr
  );

  // Écrire dans le fichier LIVE (assure le répertoire)
  const char* live_path = sc.Input[91].GetString();
  EnsureDirForFile(live_path);
  FILE* f = fopen(live_path, "a");
  if (f) {
    fprintf(f, "%s\n", live_json.GetChars());
    fclose(f);
  }
}

// ================== Writer ML_READY: n'altère pas Unified ===================
static void WriteMLReadyLine(const SCStudyInterfaceRef& sc,
                             const char* sym,
                             int chart,
                             const UnifiedState& U,
                             long long t_ms,
                             const char* emit_reason,
                             unsigned seq_unified)
{
  if (!(t_ms>0)) return;
  const double tick = (sc.TickSize>0.0 ? sc.TickSize : 0.25);
  const double tsec = (double)t_ms / 1000.0;

  // ================== PATCH V3.4: ARRÊT AUTOMATIQUE MARCHÉ FERMÉ ===================
  // Calcul RÉEL des rates 1s et session progress pour détection marché fermé
  int tick_rate_1s_int=0, trade_rate_1s_int=0, delta_rate_1s_int=0;
  ML_ReadRates1s(chart, sym, tick_rate_1s_int, trade_rate_1s_int, delta_rate_1s_int);

  int elapsed_s=0;
  double progress01=0.0;
  CalculateSessionMetrics(t_ms, elapsed_s, progress01);

  // Détection des conditions de marché fermé/stale AVEC LES VRAIES VALEURS
  // Note: is_dom_fresh calculé plus tard, on passe false pour l'instant
  bool closed = is_closed_or_stale(U, tick_rate_1s_int, trade_rate_1s_int,
                                   progress01, false, 0, U.bid, U.ask,
                                   "QUOTE", U.dom_bq1, U.dom_aq1);

  // Si marché fermé (score >= 2) → ARRÊT COMPLET (pas d'écriture, même pas heartbeat)
  // Critères: tick_rate=0 + trade_rate=0 + DOM stale + session edges + weak quote
  if (closed) {
    return;  // ✅ NOUVEAU: Arrêt automatique si marché fermé/inactif
  }
  // ================== FIN PATCH V3.4 ===================

  // Tentative de réparation BBO
  double bid = U.bid, ask = U.ask;
  bool bbo_repaired = repair_bbo(bid, ask, U, t_ms);

  // ================== PATCH V3.5.17: CL BBO/DOM ×100 FIX COMPLET ===================
  // PROBLÈME V3.5.16 : dom_bid1/dom_ask1 normalisés MAIS best_bid/best_ask restaient en ×100
  // CAUSE : BuildMLReadyJSON15() recevait U.bid/U.ask au lieu de bid/ask locaux normalisés
  // SOLUTION : Passer bid/ask locaux (ligne 3005) au lieu de U.bid/U.ask
  // RÉSULTAT : Tous les prix CL cohérents (60.xx), toutes distances correctes
  // ================== FIN PATCH V3.5.17 ===================

  // ================== PATCH V3.5.16: CL BBO/DOM ×100 FIX ===================
  // PROBLÈME : CL a best_bid=6013, best_ask=6014 au lieu de 60.13/60.14
  // CAUSE : BBO/DOM CL arrivent en format ×100 mais ne passent pas par NormalizePx()
  // SOLUTION : Détecter CL par symbole ET prix > 1000 → Diviser par 100
  // NOTE : U est const, on travaille sur des copies locales
  double dom_bid1 = U.dom_bid1;  // Copie locale
  double dom_ask1 = U.dom_ask1;  // Copie locale

  // Détecter CL par symbole (plus fiable que mult)
  bool is_cl = (strncmp(sym, "CL", 2) == 0);  // Symbole commence par "CL"

  if (is_cl && bid > 1000.0) {
    // CL en format ×100 détecté
    bid /= 100.0;
    ask /= 100.0;

    // Normaliser DOM L1 aussi
    if (dom_bid1 > 1000.0) dom_bid1 /= 100.0;
    if (dom_ask1 > 1000.0) dom_ask1 /= 100.0;
  }
  // ================== FIN PATCH V3.5.16 ===================

  // Si BBO non réparable → pas d'écriture (plus de heartbeat)
  if (!bbo_repaired) {
    return; // ✅ MODIFIÉ: Pas de heartbeat si BBO invalide (marché probablement fermé)
  }

  // Recalculer mid/spread après réparation
  const double mid = 0.5*(bid + ask);
  const double spread = std::max(0.0, ask - bid);
  const int    spread_ticks = (int)llround(ml_safe_div(spread, tick));
  const double microprice = (bid*U.aq + ask*U.bq) > 0 ? ( (bid*(double)U.aq + ask*(double)U.bq)/ (double)(U.aq+U.bq) ) : mid;
  const double microgap_n = (U.atr>0 && tick>0) ? ( (microprice - mid) / (U.atr) ) : 0.0;
  const double microgap   = fabs(microprice - mid);

  // === [ADD] Intermarkets: lire mid ES si configuré ===
  double es_mid = NAN;
  const int esChart = sc.Input[92].GetInt();
  if (esChart>0){
    SCGraphData esData;
    sc.GetChartBaseData(esChart, esData);
    int i = esData[SC_LAST].GetArraySize()-1;
    if (i>=0){
      double es_bid = esData[SC_BIDNT].GetAt(i);
      double es_ask = esData[SC_ASKNT].GetAt(i);
      if (es_bid>0 && es_ask>es_bid) es_mid = 0.5*(es_bid+es_ask);
      else es_mid = esData[SC_LAST].GetAt(i);
    }
  }
  // push retours pour RS/lead
  push_mid_for_RS(t_ms, mid, es_mid);

  // === [ADD] Structure (ON/IB/AWAP) ===
  // proxy bar_volume : valeur courante cumulée (ou remplace par sc.Volume cumulative si dispo)
  double bar_volume = (double)U.v; // ok pour incrément approx

  // PATCH: Vérification de sécurité pour éviter la contamination ES/NQ
  const char* safe_sym = (sym && sym[0] != '\0') ? sym : "UNKNOWN";
  auto& S = get_struct(safe_sym);
  update_ON_IB_AWAP(sc, t_ms, mid, bar_volume, S, sym);

  // (SUPPR) Anciens calculs de distances obsolètes - remplacés par dist_pts/dist_ticks

  // DOM features
  MLDepthFeatures DF{}; ML_ComputeDepthFeatures(sc, 10, DF);

  // MenthorQ distances (depuis les caches écrasés par AppendMenthorQFlatFields)
  std::unordered_map<std::string,double> L;
  ML_BuildMenthorLevelMapForSym(sym, L);

  long dist_gamma0=0, dist_call0=0, dist_put0=0, dist_hvl0=0;
  long dist_call=0, dist_put=0, dist_hvl=0;
  long dist_1d_max, dist_1d_min;
  long near_gex_up=0, near_gex_dn=0, near_blind=0;

  // Distances aux niveaux MenthorQ (en ticks)
  ML_NearestGexDists(L, mid, tick, near_gex_up, near_gex_dn);
  near_blind = ML_NearestBlindDist(L, mid, tick);

  // Calcul des distances 1D max/min
  auto lv_1d_max = L.find("1d_max");
  auto lv_1d_min = L.find("1d_min");
  dist_1d_max = (lv_1d_max != L.end() && lv_1d_max->second > 0) ? (long)llround((lv_1d_max->second - mid) / tick) : 0;
  dist_1d_min = (lv_1d_min != L.end() && lv_1d_min->second > 0) ? (long)llround((lv_1d_min->second - mid) / tick) : 0;

  // Calcul des distances aux niveaux MenthorQ spécifiques
  auto lv_gamma_wall = L.find("gamma_wall_0dte");  // CORRECTION : Utiliser gamma_wall_0dte
  auto lv_call_resistance = L.find("call_resistance");
  auto lv_put_support = L.find("put_support");
  auto lv_hvl = L.find("hvl");

  // === CORRECTION : Utiliser -1 pour indiquer "non disponible" au lieu de 0 ===
  dist_gamma0 = (lv_gamma_wall != L.end() && lv_gamma_wall->second > 0) ? (long)llround((lv_gamma_wall->second - mid) / tick) : -1;
  dist_call0 = (lv_call_resistance != L.end() && lv_call_resistance->second > 0) ? (long)llround((lv_call_resistance->second - mid) / tick) : -1;
  dist_put0 = (lv_put_support != L.end() && lv_put_support->second > 0) ? (long)llround((lv_put_support->second - mid) / tick) : -1;
  dist_hvl0 = (lv_hvl != L.end() && lv_hvl->second > 0) ? (long)llround((lv_hvl->second - mid) / tick) : -1;

  // Distances aux niveaux 0DTE (si disponibles)
  auto lv_call_0dte = L.find("call_resistance_0dte");
  auto lv_put_0dte = L.find("put_support_0dte");
  auto lv_hvl_0dte = L.find("hvl_0dte");

  dist_call = (lv_call_0dte != L.end() && lv_call_0dte->second > 0) ? (long)llround((lv_call_0dte->second - mid) / tick) : -1;
  dist_put = (lv_put_0dte != L.end() && lv_put_0dte->second > 0) ? (long)llround((lv_put_0dte->second - mid) / tick) : -1;
  dist_hvl = (lv_hvl_0dte != L.end() && lv_hvl_0dte->second > 0) ? (long)llround((lv_hvl_0dte->second - mid) / tick) : -1;

  // DOM age & source - PATCH: Ordre correct pour garantir L2 fiable
  auto& l2d = get_l2(chart, sym);

  // 1. Mettre à jour last_update_ms EN PREMIER pour éviter les calculs d'âge incorrects
  l2d.last_update_ms = t_ms;

  // 2. Calculer dom_age_ms après la mise à jour (sera toujours 0 pour données fraîches)
  int dom_age_ms = 0;
  if (l2d.last_update_ms > 0) {
    dom_age_ms = (int)(t_ms - l2d.last_update_ms);
  }

  // 3. PATCH: Déterminer sizes_source basé sur L1 seulement (L2-L10 seront vérifiés plus tard)
  // Vérifier si on a des données DOM L1 valides
  bool has_real_dom_data = (U.dom_bq1 > 0 || U.dom_aq1 > 0);

  // 4. Déterminer sizes_source : L2 si données DOM valides, sinon QUOTE
  const char* sizes_source = has_real_dom_data ? "L2" : "QUOTE";

  // SUPPRIMÉ: Rates 1s et session metrics déjà calculés plus haut (patch V3.4 ligne 2444-2449)
  // Les variables tick_rate_1s_int, trade_rate_1s_int, delta_rate_1s_int existent déjà
  // Les variables elapsed_s et progress01 existent déjà

  // Conversion en double pour BuildMLReadyJSON15
  double tick_rate_1s = (double)tick_rate_1s_int;
  double trade_rate_1s = (double)trade_rate_1s_int;
  double delta_rate_1s = (double)delta_rate_1s_int;

  // DOM imbalance L1
  const double level1_imbalance = ((U.dom_bq1 + U.dom_aq1) > 0)
    ? (double)(U.dom_bq1 - U.dom_aq1) / (double)(U.dom_bq1 + U.dom_aq1)
    : 0.0;

  // ================== PATCH V3.5.12: CORRECTION FINALE PVWAP/OHLC RTY/CL/GC ===================
  // PROBLÈME V3.5.11 : La condition `mult < 0.1 && px > 1000 && px < 10000` divisait RTY par 100
  // CAUSE : RTY (~2422) tombait dans cette condition destinée à CL (~68)
  // SOLUTION : Supprimer la condition intermédiaire, ne garder que `px > 10000` pour diviser
  //            → RTY (2422) : pas de division supplémentaire après auto-detect ×100 ✅
  //            → CL (68) : pas de division supplémentaire après auto-detect ×100 ✅
  //            → GC (26400) : division par 10 après auto-detect ×100 ✅
  // ================== FIN PATCH V3.5.12 ===================

  // ================== PATCH V3.5.19: NQ DAY_CHANGE_PCT FIX FINAL ===================
  // PROBLÈME V3.5.18 : Patch ne fonctionnait pas car NQ a HistoricalPriceMultiplier=0.01
  // CAUSE : Condition `mult < 1.0 && raw < 10000` capturait NQ (mult=0.01, raw=254)
  //         → Pas de multiplication ×100, même si raw était dans gamme 100-30000
  // SOLUTION : Détecter gamme 100-30000 EN PREMIER (avant check mult < 1.0)
  // RÉSULTAT : NQ/ES/RTY normalisés correctement même avec différents multipliers
  // ================== FIN PATCH V3.5.19 ===================

  // ================== PATCH V3.5.21: SUPPRESSION DAY_CHANGE_PCT ===================
  // DÉCISION : Supprimer day_change_pct (non utilisé par les pros, problèmes de normalisation)
  // GARDER : distance_to_high/low_pct, position_in_range (métriques institutionnelles)
  // ================== FIN PATCH V3.5.21 ===================

  // ================== PATCH V3.5.9: 4 FEATURES PRIX JOURNALIER ===================
  // PROBLÈME DÉTECTÉ : sc.High[i]/Low[i]/Open[i] peuvent être en unités brutes (×100 ou avec multiplier)
  // SOLUTION : Normaliser manuellement avec la même logique que NormalizePx() (défini plus bas)

  // Helper local pour normalisation (inline, même logique que NormalizePx)
  auto normalize_price = [&sc](double raw) -> double {
    // PATCH V3.5.20: Correction définitive pour NQ avec HistoricalPriceMultiplier=0.01
    // PROBLÈME V3.5.19 : La multiplication ×100 (ligne 2671) était ANNULÉE par la division
    //                    finale (ligne 2690) car mult=0.01 <= 0.1 ET px=25410 > 10000
    // SOLUTION : Utiliser un flag pour éviter la division finale si déjà multiplié ×100
    const double mult = (sc.HistoricalPriceMultiplier != 0.0 ? sc.HistoricalPriceMultiplier : 1.0);
    double px = raw;
    bool already_multiplied_by_100 = false;  // Flag pour éviter double normalisation

    // PATCH V3.5.20: Détection PRIORITAIRE de la gamme "déjà divisée par 100"
    // Si 100 <= raw < 30000 (NQ=254, ES=67, RTY=24), c'est déjà divisé → Multiplier ×100
    if (raw >= 100.0 && raw < 30000.0) {
      // Cas ES/NQ/RTY où sc.Open[i] arrive DÉJÀ divisé par 100
      px = raw * 100.0;
      already_multiplied_by_100 = true;  // Marquer qu'on a déjà appliqué la correction
    } else if (mult < 1.0 && raw < 10000.0) {
      // Prix déjà normalisé pour GC/CL (ex: GC=3948.6, CL=68.5) → NE PAS diviser
      px = raw;
    } else {
      // Prix brut (ex: ES=675650, NQ=2531775, RTY=242440) → Diviser par mult
      px = raw / mult;
    }

    // 2) Auto-détection format ×100 (ES/NQ/RTY typiquement > 100000)
    if (sc.Input[47].GetYesNo()) {
      px /= 100.0;
    } else if (px > 100000.0) {
      px /= 100.0;
    }

    // 3) Cas spécial pour multiplier <= 0.1 (GC=0.1, RTY=0.01, CL=0.01) :
    // Si après auto-detect, px > 10000, appliquer division finale
    // SAUF si on a déjà appliqué la multiplication ×100 (pour éviter d'annuler la correction)
    if (!already_multiplied_by_100 && mult <= 0.1 && px > 10000.0) {
      px /= (mult == 0.1 ? 10.0 : 100.0);  // ÷10 pour GC (mult=0.1), ÷100 pour RTY (mult=0.01)
    }

    // 4) Arrondi au tick
    return sc.RoundToTickSize(px, sc.TickSize);
  };

  // Initialiser avec les valeurs du dernier bar (déjà normalisées)
  double day_open = U.o;
  double day_high = U.h;
  double day_low = U.l;

  // Scanner les dernières 2000 barres (~33min si 1s bars) pour trouver High/Low
  // ET la première barre de session pour Open
  const int lookback = std::min(2000, sc.ArraySize);
  if (lookback > 0 && sc.ArraySize > 0) {
    const int startIdx = sc.ArraySize - lookback;

    // Obtenir le temps de début de session pour trouver day_open
    int sessionStartTimeInt = sc.SessionStartTime();
    bool foundSessionStart = false;

    for (int i = startIdx; i < sc.ArraySize; ++i) {
      // Normaliser High/Low (même logique que NormalizePx)
      double normalized_high = normalize_price(sc.High[i]);
      double normalized_low = normalize_price(sc.Low[i]);

      if (normalized_high > day_high) day_high = normalized_high;
      if (normalized_low < day_low) day_low = normalized_low;

      // Chercher la première barre de session pour day_open (tolérance 60s)
      if (!foundSessionStart) {
        int barTimeInt = sc.BaseDateTimeIn[i].GetTime();
        if (abs(barTimeInt - sessionStartTimeInt) <= 60) {
          day_open = normalize_price(sc.Open[i]);  // NORMALISER
          foundSessionStart = true;
        }
      }
    }
  }

  // Prix actuel (close du dernier bar unifié)
  const double current_price = U.c;

  // 1. Distance au plus haut (resistance proximity)
  const double distance_to_high = (day_high > 0.0) ? (day_high - current_price) : 0.0;
  const double distance_to_high_pct = (day_high > 0.0) ? (distance_to_high / day_high) * 100.0 : 0.0;

  // 2. Distance au plus bas (support proximity)
  const double distance_to_low = (day_low > 0.0) ? (current_price - day_low) : 0.0;
  const double distance_to_low_pct = (day_low > 0.0) ? (distance_to_low / day_low) * 100.0 : 0.0;

  // 3. Range du jour (volatility measure)
  const double day_range = (day_high > day_low) ? (day_high - day_low) : 0.0;
  const double day_range_pct = (day_open > 0.0 && day_range > 0.0) ? (day_range / day_open) * 100.0 : 0.0;

  // 4. Position dans le range (0-100%, mean reversion signal)
  const double position_in_range = (day_range > 0.0)
    ? ((current_price - day_low) / day_range) * 100.0
    : 50.0;

  // Notes ML:
  // - distance_to_high_pct < 0.2% → proche résistance (probable rejet)
  // - distance_to_low_pct < 0.2% → proche support (probable rebond)
  // - day_range_pct < 0.3% → compression (éviter trades)
  // - position_in_range > 90% → sur-extension haussière (signal short)
  // - position_in_range < 10% → sur-extension baissière (signal long)
  // ================== FIN PATCH V3.5 ===================

  // PATCH: Améliorer la collecte L1 avec fallback DOM si nécessaire
  const double bid_size = (U.bq > 0) ? U.bq : ((U.dom_bq1 > 0) ? U.dom_bq1 : 0.0);
  const double ask_size = (U.aq > 0) ? U.aq : ((U.dom_aq1 > 0) ? U.dom_aq1 : 0.0);

  // Récupérer les données NBCV depuis le cache
  std::string symKey = std::string(sym);
  LastNBCV& lnb = g_LastNBCVBySym[symKey];
  const double askVolume = lnb.askVolume;
  const double bidVolume = lnb.bidVolume;
  const double totalVolume = lnb.totalVolume;

  // Total volume
  const double total_vol = askVolume + bidVolume;

  // Delta depuis NBCV
  const double delta = lnb.delta;

  // Pourcentages & pression (utiliser source NBCV quand disponible)
  double calc_bidPct = 0.0, calc_askPct = 0.0, calc_deltaPct = 0.0;
  int calc_pressure = 0; // -1,0,+1 (utiliser of_pressure NBCV si dispo)

  // Calculer les pourcentages depuis les volumes NBCV
  const double tot_nb = askVolume + bidVolume;
  if (tot_nb > 0.0) {
    calc_bidPct = bidVolume / tot_nb;
    calc_askPct = askVolume / tot_nb;
    calc_deltaPct = (askVolume - bidVolume) / tot_nb;
  }

  // Utiliser la pression NBCV source si disponible, sinon fallback calculé
  if (lnb.pressure != 0) {
    calc_pressure = lnb.pressure; // source NBCV
  } else if (tot_nb > 0.0) {
    // Fallback: calculer pression depuis deltaPct si source NBCV muette
    calc_pressure = (calc_deltaPct > 0.0 ? 1 : (calc_deltaPct < 0.0 ? -1 : 0));
  }

  // MenthorQ metadata
  SCString month, quarter;
  ML_FormatMonthQuarter(t_ms, month, quarter);

  // File path
  SCString filepath = ML_FilePath(chart, sym);
  if (filepath.GetLength() == 0) return;

  // Point value & price scale
  const double point_value = GetPointValue(SCString(sym));
  const int    price_scale = GetPriceScale(SCString(sym));

  // Ouverture fichier
  FILE* f = fopen(filepath.GetChars(), "a");
  if (!f) return;

  // ML_READY COMPLET contient maintenant TOUTES les données (plus besoin de ligne UNIFIER séparée)

  // ====== ML_READY 15 FEATURES : ajout des features avancées =================
  // PATCH >>> DOM10 + fraîcheur
  std::array<double,10> dom_bid_qty{};
  std::array<double,10> dom_ask_qty{};

  // Récupère DOM 1..10 (utilise ton utilitaire existant getTopKDom)
  std::vector<std::pair<double,int>> bids, asks;
  getTopKDom(sc, 10, bids, asks);

  auto qty_at = [&](const auto& v, int lvl)->double {
      return (lvl-1>=0 && lvl-1<(int)v.size()) ? std::max(0, v[lvl-1].second) : 0;
  };
  for (int k=0;k<10;++k){
      dom_bid_qty[k] = qty_at(bids,k+1);
      dom_ask_qty[k] = qty_at(asks,k+1);
  }

  // PATCH: Vérification complète des données DOM après remplissage des tableaux
  // Mettre à jour has_real_dom_data avec les données L2-L10 maintenant disponibles
  bool has_real_dom_data_complete = has_real_dom_data ||
                                   std::any_of(dom_bid_qty.begin(), dom_bid_qty.end(), [](double q) { return q > 0; }) ||
                                   std::any_of(dom_ask_qty.begin(), dom_ask_qty.end(), [](double q) { return q > 0; });

  // Fraîcheur DOM - PATCH: Logique simplifiée et fiable
  // Si on a des données DOM réelles ET que sizes_source = L2, alors DOM est frais
  const bool is_dom_fresh = (sizes_source && strncmp(sizes_source, "L2", 2) == 0) && has_real_dom_data_complete;
  // Si pas frais → on calculera des NULL (pas des zéros trompeurs)
  // PATCH <<< DOM10 + fraîcheur

  // PATCH >>> MenthorQ levels & freshness
  auto lv = [&](const char* k)->double {
      auto it = L.find(k);
      return (it==L.end() ? std::numeric_limits<double>::quiet_NaN() : it->second);
  };

  // Niveaux MQ (prix) : gex_1-10 / call_resistance / put_support / hvl / blind_spot_0-8
  std::vector<double> mq_gamma_walls, mq_call_res, mq_put_sup, mq_hvl, mq_blind_spots;

  // GEX 1-10 (gamma walls)
  for (int i=1;i<=10;i++){
      char key[32];
      std::sprintf(key,"gex_%d",i);
      double v = lv(key); if (std::isfinite(v)) mq_gamma_walls.push_back(v);
  }

  // Niveaux clés MenthorQ
  double call_res = lv("call_resistance"); if (std::isfinite(call_res)) mq_call_res.push_back(call_res);
  double put_sup = lv("put_support"); if (std::isfinite(put_sup)) mq_put_sup.push_back(put_sup);
  double hvl_val = lv("hvl"); if (std::isfinite(hvl_val)) mq_hvl.push_back(hvl_val);

  // Blind spots exacts (pas d'approx depuis un "near_*")
  for (int k=0; k<=8; k++) {
      char key[32]; std::sprintf(key, "blind_spot_%d", k);
      double v = lv(key);
      if (std::isfinite(v)) mq_blind_spots.push_back(v);
  }

  // Détecter la présence de niveaux MQ
  const bool has_any_mq_levels =
    (!mq_gamma_walls.empty() || !mq_call_res.empty() ||
     !mq_put_sup.empty()     || !mq_hvl.empty()      ||
     !mq_blind_spots.empty());

  // PATCH: Améliorer la collecte MenthorQ avec fallback
  MQSimpleFresh mq = MQ_ComputeFresh24h(t_ms, U.session_id.c_str());
  const long long last_mq_update_ms = (mq.last_ms > 0) ? mq.last_ms : t_ms;
  const bool is_mq_realtime_fresh   = mq.is_rt_fresh;
  const bool is_mq_structural_fresh = mq.is_struct_fresh;
  const double mq_snapshot_age_s     = mq.age_s;
  // PATCH <<< MenthorQ levels & freshness

  // PATCH >>> récupérer le cache dédié à (sym, chart)
  CacheKey ck{std::string(sym), chart};
  MLReadyCache& cache = g_mlready_caches[ck];

  // Mise à jour EMA 3s avec les compteurs 1s réels
  cache.ema_tick_rate_3s  = ema_update(cache.ema_tick_rate_3s , tick_rate_1s , 0.5);
  cache.ema_trade_rate_3s = ema_update(cache.ema_trade_rate_3s, trade_rate_1s, 0.5);
  cache.ema_delta_rate_3s = ema_update(cache.ema_delta_rate_3s, delta_rate_1s, 0.5);

  // delta_cum_10s maintenant calculé depuis l'anneau temps réel
  const int real_delta_cum_10s = ML_ReadDeltaCum10s(chart, sym);
  // PATCH <<< récupérer le cache

  // === PATCH: Désactiver gating MQ - logique basée sur présence de niveaux ===
  static constexpr bool IGNORE_MQ_FRESHNESS = true; // Switch pour réactiver TTL si besoin

  // Logique d'autorisation MQ = "présence de niveaux", pas "âge"
  const bool has_gex = (L.count("gex_1") || L.count("gex_2") ||
                       L.count("gex_3") || L.count("gex_4") ||
                       L.count("gex_5") || L.count("gex_6") ||
                       L.count("gex_7") || L.count("gex_8") ||
                       L.count("gex_9") || L.count("gex_10"));
  const bool has_blind = (L.count("blind_spot_0") || L.count("blind_spot_1") ||
                         L.count("blind_spot_2") || L.count("blind_spot_3") ||
                         L.count("blind_spot_4") || L.count("blind_spot_5") ||
                         L.count("blind_spot_6") || L.count("blind_spot_7") ||
                         L.count("blind_spot_8"));
  const bool has_other = (L.count("call_resistance") || L.count("put_support") ||
                         L.count("hvl") || L.count("1d_max") ||
                         L.count("1d_min"));

  const bool has_any_mq_levels_new = has_gex || has_blind || has_other;

  // NOUVELLE règle : on ignore complètement l'âge
  const bool use_mq_structural = IGNORE_MQ_FRESHNESS
                                 ? has_any_mq_levels_new  // TRUE si on a au moins un niveau
                                 : (is_mq_structural_fresh && has_any_mq_levels); // Ancienne logique TTL

  // === PATCH START: validate or drop ========================================
  // Recalculer les valeurs pour le validator
  const double mid_val = (U.bid + U.ask) * 0.5;
  const double spread_val = U.ask - U.bid;
  const int spread_ticks_val = (int)llround(spread_val / tick);
  const int l1_sz_val = U.bq + U.aq;
  const double microprice_val = (l1_sz_val > 0)
      ? (U.bid * (double)U.aq + U.ask * (double)U.bq) / (double)l1_sz_val
      : mid_val;

  // === NEUTRALISATION DOM SI DIVERGENCE TROP IMPORTANTE ===
  bool dom_neutralized = false;
  double dom_bid_diff_ticks = std::fabs(U.dom_bid1 - U.bid) / tick;
  double dom_ask_diff_ticks = std::fabs(U.dom_ask1 - U.ask) / tick;

  // Variables locales pour DOM neutralisé (U est const)
  double dom_bid1_final = U.dom_bid1;
  double dom_ask1_final = U.dom_ask1;
  int dom_bq1_final = U.dom_bq1;
  int dom_aq1_final = U.dom_aq1;
  bool is_dom_fresh_final = is_dom_fresh;
  const char* sizes_source_final = sizes_source;

  // Tableaux DOM neutralisés (copies des originaux)
  std::array<double,10> dom_bid_qty_final = dom_bid_qty;
  std::array<double,10> dom_ask_qty_final = dom_ask_qty;

  if (dom_bid_diff_ticks > 1.0 || dom_ask_diff_ticks > 1.0) {
    // Neutraliser le DOM : remplacer par BBO L1
    dom_bid1_final = U.bid;
    dom_ask1_final = U.ask;
    dom_bq1_final = U.bq;
    dom_aq1_final = U.aq;
    dom_neutralized = true;
    // PATCH: Ne pas forcer is_dom_fresh_final = false si on a des données L2 valides
    // Seulement neutraliser si on est vraiment en fallback QUOTE
    if (sizes_source_final && strncmp(sizes_source_final, "QUOTE", 5) == 0) {
        is_dom_fresh_final = false;
    }
    // PATCH: Ne pas forcer QUOTE si on a des données L2 valides
    // sizes_source_final = "QUOTE";  // Supprimé pour préserver L2

    // Neutraliser les tableaux DOM : mettre L1 à BBO, autres niveaux à 0
    dom_bid_qty_final[0] = U.bq;  // L1 = BBO bid size
    dom_ask_qty_final[0] = U.aq;  // L1 = BBO ask size
    for (int k = 1; k < 10; k++) {
      dom_bid_qty_final[k] = 0.0;  // L2-L10 = 0
      dom_ask_qty_final[k] = 0.0;  // L2-L10 = 0
    }
  }

  const bool ok = ValidatePreWrite(
    dom_bid1_final, dom_ask1_final,  // DOM L1 final (neutralisé si nécessaire)
    mid_val, spread_val, spread_ticks_val,
    dom_bq1_final, dom_aq1_final,    // DOM L1 sizes final (neutralisé si nécessaire)
    microprice_val, calc_askPct, calc_bidPct, calc_deltaPct,
    tick, total_vol, total_vol,  // total_vol = askVolume + bidVolume (cohérent avec volume bar)
    // Nouveaux paramètres pour validation DOM vs BBO
    U.bid, U.ask, U.bq, U.aq  // BBO L1 pour comparaison
  );

  if (!ok) {
    // Option A (recommandée pour un dataset 100% propre) : SKIP/ DROP la ligne
    fclose(f);
    return;  // ou continue; selon ton flux

    // Option B : taguer et émettre quand même (moins propre pour le training)
    // j["validation_failed"] = true;
  }
  // === PATCH END: validate or drop ==========================================

  // === [ADD] lead/rs & next_wall ===
  double es_nq_lead_ms_120s = NAN, es_nq_lead_cc = NAN, nq_es_rs_z_120s = NAN;
  compute_lead_and_rs(t_ms, es_nq_lead_ms_120s, es_nq_lead_cc, nq_es_rs_z_120s);

  // divergence simple (HH/LL 120s) - logique basée sur RS + flux
  int divergence_flag = 0;
  if (std::isfinite(nq_es_rs_z_120s) && std::fabs(nq_es_rs_z_120s) >= 1.5) {
    // micro_imbalance (L1) et deltaPct expriment la pression
    double sign_flow = (level1_imbalance * (calc_askPct - calc_bidPct));
    if (sign_flow < 0) divergence_flag = 1; // spread haussier mais pression vendeuse, ou inversement
  }

  // Next wall (utilise tes niveaux déjà présents dans L)
  std::vector<double> gex_levels;
  for (int i=1;i<=10;i++){
      char key[32];
      std::sprintf(key,"gex_%d",i);
      double v = lv(key); if (std::isfinite(v)) gex_levels.push_back(v);
  }

  int wall_age_min = 0; // si tu as l'info, remplace-la
  double call_resistance = lv("call_resistance");
  double put_support = lv("put_support");
  double confluence_strength = lv("confluence_strength");
  NextWall nw = compute_next_wall(
    mid, tick,
    call_resistance, put_support,
    gex_levels, confluence_strength, wall_age_min
  );

  // Construire la ligne JSON des 15 features
  std::string ml15_line = BuildMLReadyJSON15(
    bid, ask, U.bq, U.aq, tick,  // ✅ PATCH V3.5.16: Utiliser bid/ask locaux (normalisés pour CL)
    U.vwap, U.vpoc, U.val, U.vah, U.atr,
    U.vwap_weekly, U.vwap_monthly,   // NEW: VWAP Weekly & Monthly
    U.w_up1, U.w_dn1,  // NEW: VWAP Weekly Bands (SD+1, SD-1 seulement)
    dom_bid_qty_final, dom_ask_qty_final,
    tick_rate_1s, trade_rate_1s, delta_rate_1s,
    mq_gamma_walls, mq_call_res, mq_put_sup, mq_hvl, mq_blind_spots,
    use_mq_structural, is_dom_fresh_final, has_any_mq_levels, is_mq_realtime_fresh, mq_snapshot_age_s, mq.valid_for_session, cache, real_delta_cum_10s,

    // === NOUVEAUX PARAMÈTRES POUR ML_READY COMPLET ===
    t_ms, sym, sc.ChartNumber, // Données de base
    total_vol, delta, // Données de marché
    L, // Données MenthorQ complètes
    DF, // Features DOM détaillées
    near_gex_up, near_gex_dn, near_blind, // Distances MenthorQ
    dist_1d_max, dist_1d_min,
    U.session_id.c_str(), elapsed_s, progress01, // Métadonnées
    month.GetChars(), quarter.GetChars(),
    dom_age_ms, sizes_source_final, // Flags et validation
    point_value, price_scale, U.pvwap, // Données supplémentaires
    level1_imbalance, tsec, // Imbalance DOM et timestamp
    emit_reason, seq_unified, // Raison et séquence

    // Données UnifiedState manquantes
    U.i, U.o, U.h, U.l, U.c, U.v, // Basedata
    U.bidvol, U.askvol, // Volumes bid/ask
    dom_bid1, dom_ask1, U.dom_bq1, U.dom_aq1, // DOM L1 (dom_bid1/ask1 normalisés pour CL)
    U.up1, U.dn1, U.up2, U.dn2, U.up3, U.dn3, // VWAP bands
    // PATCH 2: PVWAP bands → null (pas 0.0) quand indisponible
    (U.pvwap > 0 ? U.p_up1 : std::numeric_limits<double>::quiet_NaN()),
    (U.pvwap > 0 ? U.p_dn1 : std::numeric_limits<double>::quiet_NaN()),
    (U.pvwap > 0 ? U.p_up2 : std::numeric_limits<double>::quiet_NaN()),
    (U.pvwap > 0 ? U.p_dn2 : std::numeric_limits<double>::quiet_NaN()),
    U.cum_delta_day, U.cum_delta_session, // Cumulative delta
    U.corr, U.vix, // Métriques de marché
    calc_deltaPct, calc_askPct, calc_bidPct, calc_pressure, // Ratios et pression calculés

    // Données session et MenthorQ manquantes
    elapsed_s, progress01, last_mq_update_ms,

    // Données principales manquantes
    askVolume, bidVolume, delta, total_vol,

    // Distances MenthorQ manquantes
    dist_gamma0, dist_call0, dist_put0, dist_hvl0,
    dist_call, dist_put, dist_hvl,

    // === [ADD] Game Changers ===
    es_nq_lead_ms_120s, es_nq_lead_cc, nq_es_rs_z_120s, divergence_flag,
    S.onh, S.onl, S.on_fix_ts, S.ibh, S.ibl,
    S.awap_onh.value, S.awap_onl.value, S.awap_ibo.value, S.awap_ibo_ts,
    nw.price, nw.side, nw.dist_pts, nw.dist_ticks, nw.strength, nw.age_min,

    // === PATCH V3.5: Session Price Features ===
    distance_to_high_pct, distance_to_low_pct,
    day_range_pct, position_in_range
  );

  // Écrire la ligne ML_READY COMPLET (contient tout maintenant)
  fwrite(ml15_line.c_str(), 1, ml15_line.length(), f);

  fclose(f);
}

// État unifié par symbole
static std::unordered_map<std::string, UnifiedState> g_UState;

// Timestamps pour la cadence unifiée
static std::unordered_map<std::string, double> s_last_unified_ms;
static std::unordered_map<std::string, long long> s_last_unified_hb_ms;
// === PATCH 2B: Ajout des variables de temps pour WriteUnified START ===
static std::unordered_map<std::string, long long> s_last_unified_t_ms;
static std::unordered_map<std::string, long long> s_last_t_ms_monotone;
// === PATCH 2B: Ajout des variables de temps pour WriteUnified END ===

// === TIME & TZ GUARDS (UTC strict) ===
static inline long long current_utc_epoch_ms() {
  return (long long)std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count();
}

static bool ShouldAcceptTimestamp(long long t_ms) {
  const long long now_ms = current_utc_epoch_ms();
  const long long twelve_hours_ms = 12LL * 3600LL * 1000LL;
  return llabs(now_ms - t_ms) <= twelve_hours_ms;
}

static void LogTZCheckOnce() {
  static bool s_logged = false;
  if (s_logged) return;
  s_logged = true;
  const long long now_ms = current_utc_epoch_ms();
  double paris_offset_hours = 0.0; // affichage informatif seulement
#ifdef _WIN32
  // Windows ID pour Europe/Paris
  TIME_ZONE_INFORMATION tzi;
  DWORD res = GetTimeZoneInformation(&tzi);
  // L'offset brut (sans DST) en minutes est -Bias; converti en heures
  paris_offset_hours = -(double)tzi.Bias / 60.0;
#endif
  SCString line;
  line.Format("TZ_CHECK: epoch_ms=%lld, tz='Europe/Paris' offset_hrs=%.1f", (long long)now_ms, paris_offset_hours);
  WriteToDebugFile(line);
}

// Monotonie par flux (dtype|sym|chart)
static std::unordered_map<std::string, long long> s_last_tms_by_key;
static inline long long monotonic_t_ms_for(const std::string& key) {
  long long t = current_utc_epoch_ms();
  long long &last = s_last_tms_by_key[key];
  if (t <= last) t = last + 1;
  last = t;
  return t;
}

// Redéfinition supprimée - déjà définie plus haut

// ===========================================================================
// ZMQ glue (réel vs stubs)
// ===========================================================================
#ifdef MIA_HAVE_ZMQ

// Variables globales ZeroMQ
static void* g_zmq_ctx = nullptr;
static void* g_zmq_pub = nullptr;
static bool g_bus_ready = false;

// Séquence par symbole & jour (reset quotidien)
struct SeqKey {
    std::string sym;
    int ymd;
    bool operator==(const SeqKey& o) const {
        return sym == o.sym && ymd == o.ymd;
    }
};
struct SeqHash {
    size_t operator()(const SeqKey& k) const {
        return std::hash<std::string>()(k.sym) ^ (k.ymd * 2654435761u);
    }
};
static std::unordered_map<SeqKey, uint32_t, SeqHash> g_seq;

// Debounce tracking
struct GateKey {
    std::string k;
    bool operator==(const GateKey& o) const { return k==o.k; }
};
struct GateHash {
    size_t operator()(const GateKey& g) const {
        return std::hash<std::string>()(g.k);
    }
};
static std::unordered_map<GateKey, double, GateHash> g_last_pub_ms;

// Compteurs de monitoring
static std::unordered_map<std::string, int> g_zmq_errors;
static std::unordered_map<std::string, int> g_oversize_drops;

#else  // ---- STUBS SANS ZMQ (remote Sierra) --------------------------------

static bool g_bus_ready = false; // compile et reste à false

#endif

// === PATCH 2: unified state & time caches START ===
// (La structure UnifiedState existe déjà, on ajoute juste les champs manquants)

// === PATCH 2B: Study IDs resolution by chart START ===
struct StudyIds {
  int vwap = 0, pvwap = 0, vva = 0, nbcv = 0, atr = 0, corr = 0, vix = 0;
  int gamma = 0, blind_spots = 0;
  int vwap_weekly = 0, vwap_monthly = 0;   // NEW: VWAP Weekly & Monthly
  bool resolved = false;
};
static std::unordered_map<int, StudyIds> g_study_by_chart;

static void ResolveStudiesForChart(const SCStudyInterfaceRef& sc) {
  StudyIds ids{};

  // Résolution par nom d'étude (plus fiable que les IDs fixes)
  ids.vwap = sc.GetStudyIDByName(sc.ChartNumber, "VWAP", 0);
  ids.pvwap = sc.GetStudyIDByName(sc.ChartNumber, "Volume Value Area Previous", 0);
  ids.vva = sc.GetStudyIDByName(sc.ChartNumber, "Volume Value Area Lines", 0);
  ids.nbcv = sc.GetStudyIDByName(sc.ChartNumber, "Numbers Bars Calculated Values", 0);
  ids.atr = sc.GetStudyIDByName(sc.ChartNumber, "Average True Range", 0);
  ids.corr = sc.GetStudyIDByName(sc.ChartNumber, "Correlation Coefficient", 0);
  ids.vix = sc.GetStudyIDByName(sc.ChartNumber, "VIX_CGI[M]  1 Min  #8", 0);
  ids.gamma = sc.GetStudyIDByName(sc.ChartNumber, "MenthorQ Gamma Levels", 0);
  ids.blind_spots = sc.GetStudyIDByName(sc.ChartNumber, "MenthorQ Blind Spots Levels", 0);

  // VWAP Weekly & Monthly
  ids.vwap_weekly = sc.GetStudyIDByName(sc.ChartNumber, "VWAP WEEKS", 0);
  ids.vwap_monthly = sc.GetStudyIDByName(sc.ChartNumber, "VWAP MONTHS", 0);

  // CORRECTION: Vérifier les doublons Weekly=Monthly
  if (ids.vwap_weekly > 0 && ids.vwap_monthly > 0 && ids.vwap_weekly == ids.vwap_monthly) {
    SCString warningMsg;
    warningMsg.Format("CORRECTION: Weekly==Monthly StudyID (%d) détecté - Monthly sera skip",
                     ids.vwap_weekly);
    sc.AddMessageToLog(warningMsg, 1);

    // CORRECTION: Neutraliser Monthly pour éviter doublons
    ids.vwap_monthly = 0;

    // Log de neutralisation
    SCString neutralMsg;
    neutralMsg.Format("[G3] WARNING: WEEKLY==MONTHLY StudyID → Monthly neutralisé (ID=0)");
    sc.AddMessageToLog(neutralMsg, 1);
  }

  // PRODUCTION: Debug désactivé pour optimiser les performances
  // if (true) {  // PATCH: Remplacement de GetLogLevel() qui n'existe pas
  //   SCString debugMsg;
  //   debugMsg.Format("DEBUG G3: VWAP Studies by name - Chart=%d, Weekly=%d, Monthly=%d",
  //                  sc.ChartNumber, ids.vwap_weekly, ids.vwap_monthly);
  //   sc.AddMessageToLog(debugMsg, 1);
  // }

  // CORRECTION: Log des IDs pour vérification
  SCString idMsg;
  idMsg.Format("[G3] IDs VWAP weekly=%d monthly=%d", ids.vwap_weekly, ids.vwap_monthly);
  sc.AddMessageToLog(idMsg, 1);

  // ================== PATCH V3.5.14: CORRECTION GC/CL OHLC & PVWAP ×10 ERREUR ===================
  // PROBLÈME : GC/CL affichaient open/high/low/close/pvwap ×10 trop élevés (ex: 39486 au lieu de 3948.6)
  // CAUSE : sc.Open[i]/High[i]/Low[i] pour GC/CL sont DÉJÀ normalisés par Sierra Chart
  //         Diviser par mult (0.1) créait une multiplication involontaire ×10
  // SOLUTION : Détecter si raw < 10000 (prix déjà normalisé) → NE PAS diviser par mult
  //            Sinon (raw > 10000, format brut) → Diviser par mult comme avant
  // ================== FIN PATCH V3.5.14 ===================

  // ================== PATCH V3.5.13: VWAP WEEKLY/MONTHLY POUR TOUS LES CHARTS ===================
  // PROBLÈME : vwap_weekly et vwap_monthly étaient NULL pour RTY/GC/CL (Charts 1,2,4)
  // CAUSE : Pas de fallback IDs pour ces charts, seulement ES/NQ avaient des fallbacks
  // SOLUTION : Ajouter fallback ID:10 (weekly) et ID:11 (monthly) pour Charts 1,2,3,4
  //            NQ (Chart 9) garde ses IDs spécifiques (51/53)
  // VÉRIFICATION USER : Screenshots confirmant ID:10=VWAP WEEKS, ID:11=VWAP MONTHS sur Chart 1
  // ================== FIN PATCH V3.5.13 ===================

  // Fallback par chart si Short Name absent
  if (ids.vwap_weekly <= 0) {
    if (sc.ChartNumber == 1) ids.vwap_weekly = 10;   // RTY
    if (sc.ChartNumber == 2) ids.vwap_weekly = 10;   // GC
    if (sc.ChartNumber == 3) ids.vwap_weekly = 10;   // ES
    if (sc.ChartNumber == 4) ids.vwap_weekly = 10;   // CL
    if (sc.ChartNumber == 9) ids.vwap_weekly = 51;   // NQ
  }
  if (ids.vwap_monthly <= 0) {
    if (sc.ChartNumber == 1) ids.vwap_monthly = 11;  // RTY
    if (sc.ChartNumber == 2) ids.vwap_monthly = 11;  // GC
    if (sc.ChartNumber == 3) ids.vwap_monthly = 11;  // ES
    if (sc.ChartNumber == 4) ids.vwap_monthly = 11;  // CL
    if (sc.ChartNumber == 9) ids.vwap_monthly = 53;  // NQ
  }

  // ================== PATCH V3.5.15: MENTHORQ GAMMA/BLIND SPOTS FALLBACKS ===================
  // PROBLÈME : gex_*, call_resistance, hvl, blind_spot_* étaient NULL pour RTY/GC/CL
  // CAUSE : Pas de fallback IDs pour gamma/blind_spots sur Charts 1,2,4
  // SOLUTION : Ajouter fallback ID:9 (gamma) et ID:8 (blind_spots) pour Charts 1,2,3,4
  //            (Confirmé par screenshot user : Chart 1 a bien ID:8 et ID:9)
  // ================== FIN PATCH V3.5.15 ===================
  if (ids.gamma <= 0) {
    if (sc.ChartNumber == 1) ids.gamma = 9;   // RTY
    if (sc.ChartNumber == 2) ids.gamma = 9;   // GC
    if (sc.ChartNumber == 3) ids.gamma = 9;   // ES
    if (sc.ChartNumber == 4) ids.gamma = 9;   // CL
    if (sc.ChartNumber == 9) ids.gamma = 9;   // NQ (même ID)
  }
  if (ids.blind_spots <= 0) {
    if (sc.ChartNumber == 1) ids.blind_spots = 8;  // RTY
    if (sc.ChartNumber == 2) ids.blind_spots = 8;  // GC
    if (sc.ChartNumber == 3) ids.blind_spots = 8;  // ES
    if (sc.ChartNumber == 4) ids.blind_spots = 8;  // CL
    if (sc.ChartNumber == 9) ids.blind_spots = 8;  // NQ (même ID)
  }

  // PRODUCTION: Debug désactivé pour optimiser les performances
  // if (true) {  // PATCH: Remplacement de GetLogLevel() qui n'existe pas
  //   SCString debugMsg;
  //   debugMsg.Format("DEBUG G3: VWAP Studies resolved - Chart=%d, Weekly=%d, Monthly=%d",
  //                  sc.ChartNumber, ids.vwap_weekly, ids.vwap_monthly);
  //   sc.AddMessageToLog(debugMsg, 1);
  // }

  ids.resolved = true;
  g_study_by_chart[sc.ChartNumber] = ids;

  // Log de résolution pour debug
  SCString path;
  path.Format("D:\\MIA_IA_system\\study_resolve_chart_%d.log", sc.ChartNumber);
  FILE* f = fopen(path.GetChars(), "a");
  if (f) {
    fprintf(f, "[%.6f] Chart %d -> vwap=%d pvwap=%d vva=%d nbcv=%d atr=%d corr=%d vix=%d gamma=%d blind=%d vwap_w=%d vwap_m=%d\n",
      sc.CurrentSystemDateTime.GetAsDouble(),
      sc.ChartNumber, ids.vwap, ids.pvwap, ids.vva, ids.nbcv, ids.atr, ids.corr, ids.vix, ids.gamma, ids.blind_spots, ids.vwap_weekly, ids.vwap_monthly);
    fclose(f);
  }
}
// === PATCH 2B: Study IDs resolution by chart END ===
// === PATCH 2: unified state & time caches END ===

// ========== UTILITAIRES COMMUNS ==========

// --- DOM helpers (L1) ---
static inline bool ReadDOML1Bid(const SCStudyInterfaceRef& sc, double& price, int& qty) {
  s_MarketDepthEntry md;
  if (!sc.GetBidMarketDepthEntryAtLevel(md, 1)) return false;
  price = md.Price; qty = (int)md.Quantity; return true;
}
static inline bool ReadDOML1Ask(const SCStudyInterfaceRef& sc, double& price, int& qty) {
  s_MarketDepthEntry md;
  if (!sc.GetAskMarketDepthEntryAtLevel(md, 1)) return false;
  price = md.Price; qty = (int)md.Quantity; return true;
}

// CrÃ©ation du rÃ©pertoire de sortie organisÃ©
static void EnsureOutDir() {
#ifdef _WIN32
  CreateDirectoryA("D:\\MIA_IA_system", NULL);
  CreateDirectoryA("D:\\MIA_IA_system\\DATA_SIERRA_CHART", NULL);
#endif
}

// CrÃ©ation de la structure de rÃ©pertoires organisÃ©e
static void EnsureOrganizedDir(int chartNumber) {
#ifdef _WIN32
  time_t now = time(NULL);
  struct tm* lt = localtime(&now);
  int y = lt ? (lt->tm_year + 1900) : 1970;
  int m = lt ? (lt->tm_mon + 1) : 1;
  int d = lt ? lt->tm_mday : 1;

  // Noms des mois
  const char* monthNames[] = {"JANVIER", "FEVRIER", "MARS", "AVRIL", "MAI", "JUIN",
                             "JUILLET", "AOUT", "SEPTEMBRE", "OCTOBRE", "NOVEMBRE", "DECEMBRE"};

  char basePath[512];
  char yearPath[512];
  char monthPath[512];
  char dayPath[512];
  char chartPath[512];

  sprintf(basePath, "D:\\MIA_IA_system\\DATA_SIERRA_CHART");
  sprintf(yearPath, "%s\\DATA_%d", basePath, y);
  sprintf(monthPath, "%s\\%s", yearPath, monthNames[m-1]);
  sprintf(dayPath, "%s\\%04d%02d%02d", monthPath, y, m, d);
  sprintf(chartPath, "%s\\CHART_%d", dayPath, chartNumber);

  CreateDirectoryA(basePath, NULL);
  CreateDirectoryA(yearPath, NULL);
  CreateDirectoryA(monthPath, NULL);
  CreateDirectoryA(dayPath, NULL);
  CreateDirectoryA(chartPath, NULL);
  // Dossier unified
  char unifiedPath[512];
  sprintf(unifiedPath, "%s\\unified", chartPath);
  CreateDirectoryA(unifiedPath, NULL);
#endif
}

// DÃ©clarations forward
static void WriteToSpecializedFile(int chartNumber, const char* dataType, const char* symbol, const SCString& line, const char* instanceID);

// ========== FONCTIONS ZEROMQ DUAL-WRITE ==========

#ifdef MIA_HAVE_ZMQ

// Initialisation ZeroMQ
static void BusInitIfNeeded(const char* endpoint) {
    if (g_bus_ready) return;

    g_zmq_ctx = zmq_ctx_new();
    if (!g_zmq_ctx) return;

    g_zmq_pub = zmq_socket(g_zmq_ctx, ZMQ_PUB);
    if (!g_zmq_pub) return;

    // Configuration non-bloquante
    int linger = 0;
    zmq_setsockopt(g_zmq_pub, ZMQ_LINGER, &linger, sizeof(linger));

    // High-Water-Mark pour éviter les drops en burst
    int sndhwm = 1000;
    zmq_setsockopt(g_zmq_pub, ZMQ_SNDHWM, &sndhwm, sizeof(sndhwm));

    // Connect (publisher connect, relay bind)
    if (zmq_connect(g_zmq_pub, endpoint) == 0) {
        g_bus_ready = true;
    }
}

static void BusClose() {
    if (g_zmq_pub) { zmq_close(g_zmq_pub); g_zmq_pub = nullptr; }
    if (g_zmq_ctx) { zmq_ctx_term(g_zmq_ctx); g_zmq_ctx = nullptr; }
    g_bus_ready = false;
}

// Fonction séquence par symbole/jour
static uint32_t NextSeq(const char* sym, int ymd) {
    SeqKey k{sym, ymd};
    return ++g_seq[k];
}

// Conversion symbole vers asset
static inline const char* sym_to_asset(const char* s) {
    if (strstr(s, "ES") != nullptr) return "es";
    if (strstr(s, "NQ") != nullptr) return "nq";
    return "other";
}

// Debounce check
static bool ShouldPublishBus(const char* dtype, const char* sym, double now_ms,
                           int debounce_ms, bool is_trigger) {
    GateKey key{ std::string(sym) + "|" + std::string(dtype) };
    double& last = g_last_pub_ms[key];

    if (is_trigger) {
        last = now_ms;
        return true;
    }
    if (now_ms - last >= debounce_ms) {
        last = now_ms;
        return true;
    }
    return false;
}

// Publication bus
static bool PublishToBus(const char* topic, const char* json) {
    if (!g_bus_ready || !g_zmq_pub) return false;
    // envoi multipart: topic puis payload
    int rc = zmq_send(g_zmq_pub, topic, (int)strlen(topic), ZMQ_SNDMORE | ZMQ_DONTWAIT);
    if (rc < 0) return false;
    rc = zmq_send(g_zmq_pub, json, (int)strlen(json), ZMQ_DONTWAIT);
    return (rc >= 0);
}

#else  // ---- STUBS SANS ZMQ (remote Sierra) --------------------------------

static void BusInitIfNeeded(const char* /*endpoint*/) {
    // no-op
}
static void BusClose() {
    // no-op
}
static bool PublishToBus(const char* /*topic*/, const char* /*json*/) {
    return false; // pas de bus en mode stub
}

#endif

// ===== Agrégateur de trades (micro-batch) =====
// Forward decl pour l'écriture
static void WriteAndPublish(int chart, const char* dtype, const char* sym,
                            const SCString& j, const char* instanceID,
                            const SCStudyInterfaceRef& sc, bool is_trigger);
struct TradeAggKey {
  long p_ticks; // prix quantifié en ticks
  int side;     // -1 sell, 0 unknown, +1 buy
  bool operator==(const TradeAggKey& o) const { return p_ticks == o.p_ticks && side == o.side; }
};
struct TradeAggKeyHash {
  std::size_t operator()(const TradeAggKey& k) const noexcept {
    return std::hash<long>()(k.p_ticks) ^ (std::hash<int>()(k.side) << 1);
  }
};
struct AggVal {
  int qty = 0;
  long long t_last_ms = 0;
};
// Clé primaire: chart|sym
using TradeBucket = std::unordered_map<TradeAggKey, AggVal, TradeAggKeyHash>;
static std::unordered_map<std::string, std::unordered_map<long long, TradeBucket>> g_trade_agg;

// Paramètres runtime (constants simples ici; peuvent être reliés à des Inputs plus tard)
static int  TRADE_AGG_MS    = 200;  // fenêtre d’agrégation en ms
static int  TRADE_MIN_QTY   = 1;    // seuil anti-bruit
static bool TRADE_ENABLE    = true; // activer l’agrégateur
static bool TRADE_REQ_TOP   = true; // rejeter si hors [bid, ask] connus
static bool TRADE_SIDE_REQ  = true; // exiger une classification côté (-1/+1), sinon side=0 accepté

static inline std::string ChartSymKey(int chart, const char* sym) {
  return std::to_string(chart) + std::string("|") + std::string(sym);
}

static inline void WriteTradeCompact(const SCStudyInterfaceRef& sc, int chart, const char* sym,
                                     long long t_ms, long p_ticks, int qty, int side)
{
  SCString j;
  j.Format("{\"t_ms\":%lld,\"p\":%ld,\"q\":%d,\"s\":%d}", (long long)t_ms, (long)p_ticks, qty, side);
  WriteAndPublish(chart, "trade_compact", sym, j, sc.Input[42].GetString(), sc, true);
}

static void FlushTradeAgg(const SCStudyInterfaceRef& sc, int chart, const char* sym, long long now_ms)
{
  std::string key = ChartSymKey(chart, sym);
  auto it = g_trade_agg.find(key);
  if (it == g_trade_agg.end()) return;
  long long cur_bucket = now_ms / TRADE_AGG_MS;
  auto& by_bucket = it->second;
  for (auto bit = by_bucket.begin(); bit != by_bucket.end(); ) {
    if (bit->first < cur_bucket) {
      auto& bucket_map = bit->second;
      for (const auto& kv : bucket_map) {
        const TradeAggKey& k = kv.first; const AggVal& a = kv.second;
        if (a.qty > 0) WriteTradeCompact(sc, chart, sym, a.t_last_ms, k.p_ticks, a.qty, k.side);
      }
      bit = by_bucket.erase(bit);
    } else {
      ++bit;
    }
  }
  if (by_bucket.empty()) g_trade_agg.erase(it);
}

// Wrapper dual-write - TOUJOURS DISPONIBLE
static void WriteAndPublish(int chart, const char* dtype, const char* sym,
                           const SCString& j, const char* instanceID,
                           const SCStudyInterfaceRef& /*sc*/, bool /*is_trigger*/ = false) {
    // Écriture fichier seulement (ZMQ supprimé)
    WriteToSpecializedFile(chart, dtype, sym, j, instanceID);
}

// removed alias; direct call to WriteToDebugFile is used

// Redéfinition supprimée - déjà définie plus haut

// Fonction centralisÃ©e pour dÃ©terminer la session NY
static inline std::string SessionNY_from(const SCStudyInterfaceRef& sc, int hour, int minute) {
  // Cette fonction reçoit déjà l'heure NY depuis UpdateCumulativeDelta
  // FORCER les valeurs correctes (contournement si inputs mal configurés)
  const int asia_h   = 18;   // 18:00 NY
  const int lon_h    = 3;    // 03:00 NY
  const int us_h     = 9;    // 09:00 NY
  const int us_m     = 30;   // 09:30 NY

  auto after = [&](int H,int M){ return (hour > H) || (hour == H && minute >= M); };

  // Logique corrigée : Asia couvre 18:00-03:00 (sur 2 jours)
  if (hour >= asia_h || hour < lon_h) return "Asia";  // 18:00-03:00
  if (hour >= lon_h && hour < us_h) return "London";  // 03:00-09:30
  if (after(us_h, us_m) && hour < asia_h) return "US"; // 09:30-18:00
  return "Asia"; // fallback
}

// Fonction pour gÃ©rer les resets du double cumulative delta (version robuste)
static void UpdateCumulativeDelta(SCStudyInterfaceRef& sc, const char* symbol, const char* side, int volume) {
  // Utiliser l'heure de la barre courante (fuseau du chart Sierra)
  int i = sc.ArraySize > 0 ? sc.ArraySize - 1 : 0;
  SCDateTime dt = (sc.ArraySize > 0 ? sc.BaseDateTimeIn[i] : sc.CurrentSystemDateTime);
  double tsec = dt.GetAsDouble();

  // Convertir en composants locale "chart TZ" (New York)
  int year = dt.GetYear();
  int month = dt.GetMonth();
  int day = dt.GetDay();
  int hour = dt.GetHour();
  int minute = dt.GetMinute();
  int second = dt.GetSecond();

  std::string sym = std::string(symbol);

  // Initialiser les accumulateurs si nÃ©cessaire
  if (g_CumDeltaDay.find(sym) == g_CumDeltaDay.end()) {
    g_CumDeltaDay[sym] = 0.0;
    g_CumDeltaSession[sym] = 0.0;
    g_CurrentSession[sym] = "";
    g_LastDayReset[sym] = 0;
    g_LastSessionReset[sym] = 0;
  }

  // Extraire la date courante (YYYYMMDD) et horodatage session (YYYYMMDDhhmm)
  int curDay = year * 10000 + month * 100 + day;
  int curStamp = curDay * 10000 + hour * 100 + minute;

  // RÃ©cupÃ©rer les paramÃ¨tres de reset depuis les inputs
  const int day_reset_h = sc.Input[48].GetInt();
  const int day_reset_m = sc.Input[49].GetInt();
  const int asia_start_h = sc.Input[50].GetInt();
  const int london_start_h = sc.Input[51].GetInt();
  const int us_start_h = sc.Input[52].GetInt();
  const int us_start_m = sc.Input[53].GetInt();

  // DÃ©terminer la session courante (mise Ã  jour Ã  chaque appel)
  std::string currentSession = SessionNY_from(sc, hour, minute);

  // Log de sÃ©curitÃ© pour diagnostiquer (optionnel)
  // if (ShouldLog(sc, LOG_KEY)) {
  //   SCString m;
  //   m.Format("SESSION CFG NY: reset=%02d:%02d, asia=%02d:00, london=%02d:00, us=%02d:%02d; nowNY=%02d:%02d -> %s",
  //            sc.Input[48].GetInt(), sc.Input[49].GetInt(),
  //            sc.Input[50].GetInt(), sc.Input[51].GetInt(),
  //            sc.Input[52].GetInt(), sc.Input[53].GetInt(),
  //            hour, minute, currentSession.c_str());
  //   DebugLog(sc, m.GetChars());
  // }

  // FORCER la mise Ã  jour de session Ã  chaque appel (corrige le problÃ¨me de dÃ©marrage)
  if (g_CurrentSession[sym] != currentSession) {
    g_CurrentSession[sym] = currentSession;
    // Reset du cumulative delta session lors du changement
    g_CumDeltaSession[sym] = 0.0;
    g_LastSessionReset[sym] = curStamp;
  }

  // --- Reset Day (NY time - paramÃ©trable via inputs) ---
  // DÉSACTIVÉ : Le nouveau système ResetCumulativeDeltasIfNeeded() gère maintenant les resets
  // const int day_reset_h_ny = sc.Input[48].GetInt(); // Day Reset NY Hour
  // const int day_reset_m_ny = sc.Input[49].GetInt(); // Day Reset NY Minute
  // auto is_after_reset = [&](int H, int M){ return (hour > H) || (hour == H && minute >= M); };
  // const bool crossed_day_reset = is_after_reset(day_reset_h_ny, day_reset_m_ny);
  // if (crossed_day_reset && g_LastDayReset[sym] != curDay) {
  //   g_CumDeltaDay[sym] = 0.0;
  //   g_CumDeltaSession[sym] = 0.0;
  //   // Fix: ne pas forcer "Asia"; recalculer la session courante
  //   g_CurrentSession[sym] = currentSession;
  //   g_LastDayReset[sym] = curDay;
  //   g_LastSessionReset[sym] = curStamp;
  // }
  // Reset de session gÃ©rÃ© dans le bloc ci-dessus (plus simple)

  // === NOUVEAU SYSTÈME DE RESET ===
  // Appeler le nouveau système de reset avant la mise à jour
  const long long t_ms = current_utc_epoch_ms();
  ResetCumulativeDeltasIfNeeded(symbol, t_ms);

  // Mise Ã  jour des cumuls selon le cÃ´tÃ© du trade
  double delta = 0.0;
  if (strcmp(side, "BUY") == 0) {
    delta = (double)volume;  // Achat = volume positif
  } else if (strcmp(side, "SELL") == 0) {
    delta = -(double)volume; // Vente = volume nÃ©gatif
  }

  g_CumDeltaDay[sym] += delta;
  g_CumDeltaSession[sym] += delta;
}

// Fonction pour exporter les cumulative deltas en heartbeat (Ã©viter perte de donnÃ©es)
static void ExportCumulativeDeltaHeartbeat(SCStudyInterfaceRef& sc, const char* symbol) {
  std::string sym = std::string(symbol);

  // VÃ©rifier que les accumulateurs existent
  if (g_CumDeltaDay.find(sym) == g_CumDeltaDay.end()) {
    return; // Pas encore initialisÃ©
  }

  double tsec = sc.CurrentSystemDateTime.GetAsDouble();
  double cumDeltaDay = g_CumDeltaDay[sym];
  double cumDeltaSession = g_CumDeltaSession[sym];
  std::string sessionId = g_CurrentSession[sym];

  // Export heartbeat des cumulative deltas
  LogTZCheckOnce();
  const long long t_ms = current_utc_epoch_ms();
  if (!ShouldAcceptTimestamp(t_ms)) return;
  SCString j;
  j.Format(R"({"t_ms":%lld,"tz_source":"UTC","writer_clock":"system_clock","t":%.6f,"sym":"%s","type":"cumulative_delta_heartbeat","cum_delta_day":%.1f,"cum_delta_session":%.1f,"session_id":"%s","chart":%d})",
           (long long)t_ms, tsec, symbol, cumDeltaDay, cumDeltaSession, sessionId.c_str(), sc.ChartNumber);
  WriteAndPublish(sc.ChartNumber, "cumulative_delta_heartbeat", symbol, j, sc.Input[42].GetString(), sc, true);
}

// GÃ©nÃ©ration du nom de fichier quotidien par chart, type ET symbole dans la structure organisÃ©e
static SCString DailyFilenameForChartTypeSymbol(int chartNumber, const char* dataType, const char* symbol, const char* instanceID = nullptr) {
  time_t now = time(NULL);
  struct tm* lt = localtime(&now);
  int y = lt ? (lt->tm_year + 1900) : 1970;
  int m = lt ? (lt->tm_mon + 1) : 1;
  int d = lt ? lt->tm_mday : 1;

  // Noms des mois
  const char* monthNames[] = {"JANVIER", "FEVRIER", "MARS", "AVRIL", "MAI", "JUIN",
                             "JUILLET", "AOUT", "SEPTEMBRE", "OCTOBRE", "NOVEMBRE", "DECEMBRE"};

  SCString cleanSym = CleanSymbol(symbol);
  SCString filename;

  // Si InstanceID est fourni et non vide, l'ajouter comme prÃ©fixe
  if (instanceID && strlen(instanceID) > 0) {
    filename.Format("D:\\MIA_IA_system\\DATA_SIERRA_CHART\\DATA_%d\\%s\\%04d%02d%02d\\CHART_%d\\instance_%s_chart_%d_%s_%s_%04d%02d%02d.jsonl",
                    y, monthNames[m-1], y, m, d, chartNumber, instanceID, chartNumber, dataType, cleanSym.GetChars(), y, m, d);
  } else {
    filename.Format("D:\\MIA_IA_system\\DATA_SIERRA_CHART\\DATA_%d\\%s\\%04d%02d%02d\\CHART_%d\\chart_%d_%s_%s_%04d%02d%02d.jsonl",
                    y, monthNames[m-1], y, m, d, chartNumber, chartNumber, dataType, cleanSym.GetChars(), y, m, d);
  }
  return filename;
}
// Fichier unifié journalier par chart et symbole
static SCString DailyUnifiedFilename(int chartNumber, const char* symbol) {
#ifdef _WIN32
  time_t now = time(NULL);
  struct tm* lt = localtime(&now);
  int y = lt ? (lt->tm_year + 1900) : 1970;
  int m = lt ? (lt->tm_mon + 1) : 1;
  int d = lt ? lt->tm_mday : 1;

  const char* monthNames[] = {"JANVIER", "FEVRIER", "MARS", "AVRIL", "MAI", "JUIN",
                             "JUILLET", "AOUT", "SEPTEMBRE", "OCTOBRE", "NOVEMBRE", "DECEMBRE"};
  SCString cleanSym = CleanSymbol(symbol);
  SCString filename;
  filename.Format("D:\\MIA_IA_system\\DATA_SIERRA_CHART\\DATA_%d\\%s\\%04d%02d%02d\\CHART_%d\\unified\\chart_%d_unified_%s_%04d%02d%02d.jsonl",
                  y, monthNames[m-1], y, m, d, chartNumber, chartNumber, cleanSym.GetChars(), y, m, d);
  return filename;
#else
  return SCString("");
#endif
}

// === PATCH 3: WriteUnified routine START ===
// Forward declaration to append MenthorQ flattened fields after caches are defined
static void AppendMenthorQFlatFields(SCString& j, const char* sym);

static void WriteUnified(const SCStudyInterfaceRef& sc, const char* sym) {
  // === PATCH 2L: Force la résolution si nécessaire START ===
  auto chart_it = g_study_by_chart.find(sc.ChartNumber);
  if (chart_it == g_study_by_chart.end() || !chart_it->second.resolved) {
    ResolveStudiesForChart(sc);
  }
  // === PATCH 2L: Force la résolution si nécessaire END ===

  auto it = g_UState.find(sym);
  if (it == g_UState.end()) return;
  UnifiedState& U = it->second;

  // Lire inputs unifier
  const bool unified_on = sc.Input[67].GetInt() != 0;
  const bool live_on = (sc.Input[90].GetInt() != 0);
  if (!unified_on && !live_on) return;
  const int unified_min_ms = std::max(100, sc.Input[68].GetInt()); // >=100 ms safety
  const int unified_hb_s  = std::max(30, sc.Input[69].GetInt());   // >=30 s safety

  // time now
  LogTZCheckOnce();
  SCString mk; mk.Format("unified|%s|%d", sym, sc.ChartNumber);
  const long long t_ms = monotonic_t_ms_for(mk.GetChars());
  // now_unix_s requis pour la fraicheur L1/DOM
  const double now_days = sc.CurrentSystemDateTime.GetAsDouble();
  const double now_unix_s = (now_days - 25569.0) * 86400.0;

  // Monotonicité stricte
  // s_last_t_ms_monotone conservé pour compat compat, mais t_ms est déjà monotone par flux

  long long& last_write_ms = s_last_unified_t_ms[sym];
  long long& last_hb_ms    = s_last_unified_hb_ms[sym]; // vrai timer heartbeat séparé

  const bool time_ok = (t_ms - last_write_ms) >= unified_min_ms;
  if (!ShouldAcceptTimestamp(t_ms)) {
    // Rejet sanity check 12h
    return;
  }
  const bool hb_ok   = (t_ms - last_hb_ms)    >= (long long)unified_hb_s * 1000LL;

  // Anti-doublon anti-rebond (5 ms): si un write vient d'avoir lieu, ignorer
  if (!time_ok && (t_ms - last_write_ms) < 5) {
    return;
  }

  // 1) Rassembler L1
  double bb = U.bid; int bsize = U.bq;
  double ba = U.ask; int asize = U.aq;
  const double L1_STALE_SEC = 3.0;
  bool has_quote = (now_unix_s - U.last_quote_unix_s) <= L1_STALE_SEC;

  // (BBO override L2) Désactivé faute de type TightBBO disponible ici; fallback via cache L2

  // --- UTILISER LES VRAIES DONNÉES DOM COLLECTÉES DEPUIS SIERRA CHART ---
  // Utiliser le cache L2 global qui contient les vraies données DOM
  {
    auto& l2 = get_l2(sc.ChartNumber, sym);
    if (!std::isnan(l2.bid1) && !std::isnan(l2.ask1)) {
    // Fenêtre de fraîcheur (3.0s) alignée sur L1_STALE_SEC, par-côté
    double l2_bid_s = (!std::isnan(l2.t_bid1) ? ((l2.t_bid1 - 25569.0) * 86400.0) : 0.0);
    double l2_ask_s = (!std::isnan(l2.t_ask1) ? ((l2.t_ask1 - 25569.0) * 86400.0) : 0.0);
    const double MAX_STALE_S = 1.5;
    bool bid_fresh = (l2_bid_s > 0.0 && (now_unix_s - l2_bid_s) <= MAX_STALE_S);
    bool ask_fresh = (l2_ask_s > 0.0 && (now_unix_s - l2_ask_s) <= MAX_STALE_S);

    U.dom_bid1 = l2.bid1;
             U.dom_ask1 = l2.ask1;
    U.dom_bq1 = (bid_fresh && l2.bq1 > 0) ? l2.bq1 : 0;
    U.dom_aq1 = (ask_fresh && l2.aq1 > 0) ? l2.aq1 : 0;
    U.last_dom_unix_s = now_unix_s;

    // PATCH: Mettre à jour last_update_ms pour éviter le fallback DOM
    l2.last_update_ms = t_ms;
    } else {
    // Fallback: essayer de lire directement depuis Sierra Chart
    double domBid=0.0, domAsk=0.0; int domBq=0, domAq=0;
    bool okB = ReadDOML1Bid(sc, domBid, domBq);
    bool okA = ReadDOML1Ask(sc, domAsk, domAq);
    if (okB) { U.dom_bid1 = domBid; U.dom_bq1 = domBq; }
    if (okA) { U.dom_ask1 = domAsk; U.dom_aq1 = domAq; }
    if (okB || okA) {
      U.last_dom_unix_s = now_unix_s;
    }
    // PATCH: Mettre à jour last_update_ms TOUJOURS, même si ReadDOML1 échoue
    l2.last_update_ms = t_ms;
    }
  }

  // --- Fallback DOM si quote L1 pas fraîche ---
  if (!has_quote) {
    // Utiliser les données DOM déjà collectées
    auto& l2fb = get_l2(sc.ChartNumber, sym);
    if (!std::isnan(l2fb.bid1) && !std::isnan(l2fb.ask1)) {
      bb = l2fb.bid1;
      ba = l2fb.ask1;
      // Synchroniser le L1 consolidé avec le DOM
      U.bid = bb; U.ask = ba; U.bq = bsize; U.aq = asize;
    } else {
      // Fallback: essayer de lire directement depuis Sierra Chart
      double domBid=0.0, domAsk=0.0; int domBq=0, domAq=0;
      bool okB = ReadDOML1Bid(sc, domBid, domBq);
      bool okA = ReadDOML1Ask(sc, domAsk, domAq);
      if (okB) { bb = domBid; bsize = domBq; }
      if (okA) { ba = domAsk; asize = domAq; }
      if (okB || okA) {
        // Synchroniser le L1 consolidé avec le DOM fallback
        U.bid = bb; U.ask = ba; U.bq = bsize; U.aq = asize;
      }
    }
  }

  // filet spread (sécurité)
  const double tick = (sc.TickSize > 0.0 ? sc.TickSize : 0.25);
  if (!(ba > bb)) ba = bb + tick;

  // Sanity fences par famille (évite contamination ES↔NQ)
  auto looks_like_es = [](double p){ return p > 1000.0 && p < 10000.0; };
  auto looks_like_nq = [](double p){ return p > 10000.0 && p < 40000.0; };
  bool dom_ok_family = true;
  if (strncmp(sym, "ES", 2) == 0) {
    if (!(looks_like_es(U.dom_bid1) && looks_like_es(U.dom_ask1))) dom_ok_family = false;
  } else if (strncmp(sym, "NQ", 2) == 0) {
    if (!(looks_like_nq(U.dom_bid1) && looks_like_nq(U.dom_ask1))) dom_ok_family = false;
  }

  // BBO guard
  int spread_ticks = (int)llround((ba - bb) / tick);
  bool bbo_ok = (U.dom_bid1 <= bb) && (U.dom_ask1 >= ba) && (spread_ticks >= 1 && spread_ticks <= 5);

  bool replaced = false;
  if (!dom_ok_family || !bbo_ok) {
    // Forcer DOM cohérent avec BBO pour éviter contamination inter-symboles
    U.dom_bid1 = bb;
    U.dom_ask1 = ba;
    U.dom_bq1 = 0;
    U.dom_aq1 = 0;
    replaced = true;
  }

  // Fallback tailles depuis la quote L1 par côté si tailles L2 manquantes
  if (U.dom_bq1 == 0 && bsize > 0) U.dom_bq1 = bsize;
  if (U.dom_aq1 == 0 && asize > 0) U.dom_aq1 = asize;

  // Ultime neutralisation si remplacé ET aucune taille fiable disponible
  if (replaced && U.dom_bq1 == 0 && U.dom_aq1 == 0) {
    U.dom_bq1 = 0;
    U.dom_aq1 = 0;
  }

  // Micro-filet d'accord L2 vs Quote (par côté) si L2 ancien et très différent
  {
    auto& l2_age = get_l2(sc.ChartNumber, sym);
    double l2_bid_s = (!std::isnan(l2_age.t_bid1) ? ((l2_age.t_bid1 - 25569.0) * 86400.0) : 0.0);
    double l2_ask_s = (!std::isnan(l2_age.t_ask1) ? ((l2_age.t_ask1 - 25569.0) * 86400.0) : 0.0);
    int dom_l1_age_bid_ms = (int) llround(1000.0 * (now_unix_s - l2_bid_s));
    int dom_l1_age_ask_ms = (int) llround(1000.0 * (now_unix_s - l2_ask_s));
    const int DIFF_THR = 8;
    const int AGE_THR_MS = 500;
    if (bsize > 0 && U.dom_bq1 > 0 && std::abs(U.dom_bq1 - bsize) >= DIFF_THR && dom_l1_age_bid_ms > AGE_THR_MS) {
      U.dom_bq1 = bsize;
    }
    if (asize > 0 && U.dom_aq1 > 0 && std::abs(U.dom_aq1 - asize) >= DIFF_THR && dom_l1_age_ask_ms > AGE_THR_MS) {
      U.dom_aq1 = asize;
    }
  }

  // === PATCH 2M: Debug logging pour WriteUnified START ===
  static std::unordered_map<int, bool> s_unified_debug_logged;
  if (s_unified_debug_logged.find(sc.ChartNumber) == s_unified_debug_logged.end()) {
    s_unified_debug_logged[sc.ChartNumber] = false;
  }
  if (!s_unified_debug_logged[sc.ChartNumber]) {
    SCString debugMsg;
    debugMsg.Format("DEBUG UNIFIED: Chart %d - vwap=%.6f, vah=%.6f, nbcv_delta=%.0f, atr=%.6f, corr=%.6f, vix=%.6f, has_quote=%s",
                   sc.ChartNumber, U.vwap, U.vah, 0.0, U.atr, U.corr, U.vix, has_quote ? "true" : "false");
    SCString path; path.Format("D:\\MIA_IA_system\\unified_debug_chart_%d.log", sc.ChartNumber);
    FILE* f = fopen(path.GetChars(), "a");
    if (f) {
      fprintf(f, "[%.6f] %s\n", sc.CurrentSystemDateTime.GetAsDouble(), debugMsg.GetChars());
      fclose(f);
    }
    s_unified_debug_logged[sc.ChartNumber] = true;
  }
  // === PATCH 2M: Debug logging pour WriteUnified END ===

  // --- Rassembler L1 fiable ---
  // 1) Quote cache si récent (<3s) - variables déjà déclarées plus haut

  // --- Conditions d'écriture ---
  // Écrire si intervalle OK, ou heartbeat, ou clôture de barre (option : à intégrer si tu as bar_closed)
  const bool should_write = time_ok || hb_ok;
  if (!should_write) return;

  // "Snapshot complet" (pas de lignes partielles)
  bool l1Ready = ( (now_unix_s - U.last_quote_unix_s) <= L1_STALE_SEC ) ||
                 ( (now_unix_s - U.last_dom_unix_s)   <= L1_STALE_SEC );

  const bool heartbeat = hb_ok;
  if (!l1Ready && !heartbeat) return;

  // VVA guard (ordre VAL ≤ VPOC ≤ VAH). Si violation, corrige à minima
  double val = U.val, vpoc = U.vpoc, vah = U.vah;
  if (val > vpoc) std::swap(val, vpoc);
  if (vpoc > vah) std::swap(vpoc, vah);

  // Clamp NaN/Inf
  bb = clampFinite(bb); ba = clampFinite(ba);
  U.vwap = clampFinite(U.vwap); U.pvwap = clampFinite(U.pvwap);
  val = clampFinite(val); vpoc = clampFinite(vpoc); vah = clampFinite(vah);
  U.atr = clampFinite(U.atr); U.corr = clampFinite(U.corr); U.vix = clampFinite(U.vix);
  // U.delta et U.totalVolume n'existent pas dans la structure UnifiedState

  // Heartbeat flag - déjà défini plus haut

  // Construire JSON
  SCString path = DailyUnifiedFilename(sc.ChartNumber, sym);
  FILE* f = fopen(path.GetChars(), "a");
  if (!f) return;

  // séquence
  unsigned seq = ++U.seq;

  // JSON (t_ms + t (jours), snapshot complet)
  // NOTE: garder les clés existantes pour compatibilité
  SCString j;
  j.Format(
    "{"
      "\"t_ms\":%lld,\"tz_source\":\"UTC\",\"writer_clock\":\"system_clock\","
      "\"t\":%.6f,"
      "\"sym\":\"%s\","
      "\"chart\":%d,"
      "\"session_id\":\"%s\","
      "\"best_bid\":%.8f,\"best_ask\":%.8f,"
      "\"bid_size\":%d,\"ask_size\":%d,"
      "\"dom_bid1\":%.8f,\"dom_ask1\":%.8f,\"dom_bq1\":%d,\"dom_aq1\":%d,"
      "\"open\":%.8f,\"high\":%.8f,\"low\":%.8f,\"close\":%.8f,"
      "\"volume\":%.0f,"
      "\"cum_delta_day\":%.1f,\"cum_delta_session\":%.1f,"
      "\"vwap\":{\"v\":%.8f,\"up1\":%.8f,\"dn1\":%.8f,\"up2\":%.8f,\"dn2\":%.8f,\"up3\":%.8f,\"dn3\":%.8f},"
      "\"vp\":{\"vah\":%.8f,\"val\":%.8f,\"vpoc\":%.8f},"
      "\"nbcv\":{\"ask_volume\":%.0f,\"bid_volume\":%.0f,\"delta\":%.0f,\"total_volume\":%.0f},"
      "\"atr\":%.6f,\"vix\":%.6f,\"correlation\":%.6f,"
      "\"summary\":{\"heartbeat\":%s,\"seq\":%u}"
    ,
    (long long)t_ms,
    sc.CurrentSystemDateTime.GetAsDouble(),
    sym, sc.ChartNumber,
    U.session_id.c_str(),
    bb, ba, bsize, asize,
    U.dom_bid1, U.dom_ask1, U.dom_bq1, U.dom_aq1,
    U.o, U.h, U.l, U.c,
    U.v,
    U.cum_delta_day, U.cum_delta_session,
    U.vwap, U.up1, U.dn1, U.up2, U.dn2, U.up3, U.dn3,
    vah, val, vpoc,
    0.0, 0.0, 0.0, 0.0, // askVolume, bidVolume, delta, totalVolume - non disponibles dans UnifiedState
    U.atr, U.vix, U.corr,
    heartbeat ? "true" : "false",
    seq
  );

  // (Optionnel) Diagnostics de fraîcheur L2 et source des tailles
#ifdef UNIFIED_DIAG
  {
    auto& l2d = get_l2(sc.ChartNumber, sym);
    double tb = (!std::isnan(l2d.t_bid1) ? ((l2d.t_bid1 - 25569.0) * 86400.0) : 0.0);
    double ta = (!std::isnan(l2d.t_ask1) ? ((l2d.t_ask1 - 25569.0) * 86400.0) : 0.0);
    double l2_last_s = tb > ta ? tb : ta;
    int dom_l1_age_ms = (int) llround(1000.0 * (now_unix_s - l2_last_s));
    const double MAX_STALE_S = 1.5;
    bool l2_fresh_diag = dom_l1_age_ms >= 0 && dom_l1_age_ms <= (int) llround(1000.0 * MAX_STALE_S);
    const char* sizes_source = l2_fresh_diag ? "L2" : ((U.dom_bq1 || U.dom_aq1) ? "QUOTE" : "ZERO");
    j.Format(",\"summary_ext\":{\"dom_l1_age_ms\":%d,\"sizes_source\":\"%s\"}", dom_l1_age_ms, sizes_source);
  }
#endif

  // Append MenthorQ flattened keys if available
  AppendMenthorQFlatFields(j, sym);

  // Fermer l'objet JSON après append
  j += "}";

  fprintf(f, "%s\n", j.GetChars());
  fclose(f);

  // MAJ des minuteries
  if (time_ok)  s_last_unified_t_ms[sym] = t_ms;
  if (hb_ok)    s_last_unified_hb_ms[sym] = t_ms;

  // ====== ML_READY : miroir enrichi d'unified (appended) =================
  // Détermine une raison d'émission basique (tu peux raffiner: burst_price/dom/delta)
  const char* emit_reason = time_ok ? "base" : "base";
  if (unified_on) {
    WriteMLReadyLine(sc, sym, sc.ChartNumber, U, t_ms, emit_reason, seq);
  }

  // ====== LIVE : writer ultra-léger pour l'algo =================
  if (live_on) {
    WriteLiveLine(sc, sym, sc.ChartNumber, U, t_ms, emit_reason, seq);
  }
}
// === PATCH 3: WriteUnified routine END ===


// GÃ©nÃ©ration du nom de fichier quotidien par chart et type dans la structure organisÃ©e (LEGACY - gardÃ© pour compatibilitÃ©)
static SCString DailyFilenameForChartType(int chartNumber, const char* dataType) {
  time_t now = time(NULL);
  struct tm* lt = localtime(&now);
  int y = lt ? (lt->tm_year + 1900) : 1970;
  int m = lt ? (lt->tm_mon + 1) : 1;
  int d = lt ? lt->tm_mday : 1;

  // Noms des mois
  const char* monthNames[] = {"JANVIER", "FEVRIER", "MARS", "AVRIL", "MAI", "JUIN",
                             "JUILLET", "AOUT", "SEPTEMBRE", "OCTOBRE", "NOVEMBRE", "DECEMBRE"};

  SCString filename;
  filename.Format("D:\\MIA_IA_system\\DATA_SIERRA_CHART\\DATA_%d\\%s\\%04d%02d%02d\\CHART_%d\\chart_%d_%s_%04d%02d%02d.jsonl",
                  y, monthNames[m-1], y, m, d, chartNumber, chartNumber, dataType, y, m, d);
  return filename;
}

// Ã‰criture dans le fichier spÃ©cialisÃ© avec structure organisÃ©e (NOUVELLE VERSION avec symbole et InstanceID)
static void WriteToSpecializedFile(int chartNumber, const char* dataType, const char* symbol, const SCString& line, const char* instanceID = nullptr) {
  EnsureOutDir();
  EnsureOrganizedDir(chartNumber);  // CrÃ©er la structure de rÃ©pertoires
  // Ne rien Ã©crire si symbole manquant/vidÃ©
  if (symbol == nullptr || symbol[0] == '\0') {
    return;
  }
  const SCString filename = DailyFilenameForChartTypeSymbol(chartNumber, dataType, symbol, instanceID);
  FILE* f = fopen(filename.GetChars(), "a");
  if (f) {
    fprintf(f, "%s\n", line.GetChars());
    fclose(f);
  }
}

// Ã‰criture dans le fichier spÃ©cialisÃ© avec structure organisÃ©e (LEGACY - gardÃ© pour compatibilitÃ©)
static void WriteToSpecializedFile(int /*chartNumber*/, const char* /*dataType*/, const SCString& /*line*/) {
  // Legacy sans symbole: NE RIEN Ã‰CRIRE pour Ã©viter les fichiers gÃ©nÃ©riques vides
  return;
}

// TouchDailyFile() supprimÃ©e - plus de fichiers gÃ©nÃ©riques vides

// Ã‰criture dans le fichier de debug local UNIQUE
static void WriteToDebugFile(const SCString& debugLine) {
  EnsureOutDir();
  time_t now = time(NULL);
  struct tm* lt = localtime(&now);
  int y = lt ? (lt->tm_year + 1900) : 1970;
  int m = lt ? (lt->tm_mon + 1) : 1;
  int d = lt ? lt->tm_mday : 1;

  // UN SEUL FICHIER DE DEBUG PAR JOUR
  SCString debugFilename;
  debugFilename.Format("D:\\MIA_IA_system\\debug_g3_%04d%02d%02d.log", y, m, d);

  FILE* f = fopen(debugFilename.GetChars(), "a");
  if (f) {
    fprintf(f, "%s\n", debugLine.GetChars());
    fclose(f);
  }
}

// Fonction de debug combinÃ©e (Sierra + fichier local)
static void DebugLog(SCStudyInterfaceRef& sc, const char* message) {
  // Log dans Sierra Chart
  sc.AddMessageToLog(message, 1);

  // Log dans fichier local avec timestamp
  time_t now = time(NULL);
  struct tm* lt = localtime(&now);
  int h = lt ? lt->tm_hour : 0;
  int min = lt ? lt->tm_min : 0;
  int s = lt ? lt->tm_sec : 0;

  SCString debugLine;
  debugLine.Format("[%02d:%02d:%02d] %s", h, min, s, message);
  WriteToDebugFile(debugLine);
}

// ========== NIVEAUX DE LOG ==========
enum LogLevel {
    LOG_ERROR = 0,    // Erreurs critiques uniquement
    LOG_KEY = 1,      // Ã‰vÃ©nements importants (flush, erreurs)
    LOG_VERBOSE = 2   // Debug complet (dÃ©veloppement)
};

// Helper: filtrage de logs par niveau (0=Errors,1=Key,2=Verbose)
static inline bool ShouldLog(const SCStudyInterfaceRef& sc, int level) {
  int cfg = 0;
  // sc.Input peut ne pas Ãªtre initialisÃ© trÃ¨s tÃ´t; garde-fou
  if (&sc != nullptr) {
    // Input[32] dÃ©fini dans SetDefaults
    cfg = sc.Input[32].GetInt();
  }
  return cfg >= level;
}


// ========== DÃ‰DUPLICATION INTELLIGENTE AMÃ‰LIORÃ‰E ==========
// Structure pour la dÃ©duplication par (sym, t, i)
struct LastKey {
  double t = 0.0; // timestamp
  double i = -1;  // bar index
};

// Structures pour la dÃ©tection de changement d'Ã©tat
struct LastBasedata {
  double c=0, o=0, h=0, l=0;
  double bidvol=0, askvol=0, v=0;
};

struct LastVWAP {
  double vwap=0, up1=0, dn1=0, up2=0, dn2=0, up3=0, dn3=0;
};

struct LastVVA {
  double vah=0, val=0, vpoc=0;
};


// Maps de dÃ©duplication par symbole
static std::unordered_map<std::string, LastKey> g_LastKeyBySym;
static std::unordered_map<std::string, LastBasedata> g_LastBaseBySym;
static std::unordered_map<std::string, LastVWAP> g_LastVWAPBySym;
static std::unordered_map<std::string, LastVVA> g_LastVVABySym;

// Cache pour Cumulative Delta
struct LastCD { double close=0.0; };
static std::unordered_map<std::string, LastCD> g_LastCDBySym;

// Caches supplÃ©mentaires: ATR et Correlation
struct LastATR { double atr=0.0; };
static std::unordered_map<std::string, LastATR> g_LastATRBySym;

struct LastCorr { double cc=0.0; };
static std::unordered_map<std::string, LastCorr> g_LastCorrBySym;
// Cache VIX global pour unifier
static std::unordered_map<std::string, double> g_LastVIXBySym;

// ========== DÃ‰DUPLICATION PAR CONTENU POUR MENTHORQ ==========
// Redéfinition supprimée - déjà définie plus haut

// Helper: append MenthorQ flattened fields (gamma_*, blind_spot_*) if present in caches
static void AppendMenthorQFlatFields(SCString& j, const char* sym) {
  const std::string k_gamma = std::string(sym) + std::string("|menthorq_gamma");
  const std::string k_blind = std::string(sym) + std::string("|menthorq_blind_spots");
  const std::string k_meta  = std::string(sym) + std::string("|menthorq_meta");
  auto itg = g_LastMenthorQBySymType.find(k_gamma);
  auto itb = g_LastMenthorQBySymType.find(k_blind);
  auto itm = g_LastMenthorQBySymType.find(k_meta);
  // meta (month/quarter) si présentes
  if (itm != g_LastMenthorQBySymType.end()) {
    auto itM = itm->second.last_values.find("month");
    auto itQ = itm->second.last_values.find("quarter");
    if (itM != itm->second.last_values.end()) {
      SCString s; s.Format(",\"month\":\"%s\"", SCString().Format("%d", (int)itM->second).GetChars()); j += s;
    }
    if (itQ != itm->second.last_values.end()) {
      SCString s; s.Format(",\"quarter\":\"%s\"", SCString().Format("%d", (int)itQ->second).GetChars()); j += s;
    }
  }
  if (itg != g_LastMenthorQBySymType.end()) {
    for (const auto& kv : itg->second.last_values) {
      SCString s; s.Format(",\"%s\":%.8f", kv.first.c_str(), kv.second);
      j += s;
    }
  }
  if (itb != g_LastMenthorQBySymType.end()) {
    for (const auto& kv : itb->second.last_values) {
      SCString s; s.Format(",\"%s\":%.8f", kv.first.c_str(), kv.second);
      j += s;
    }
  }
}

// ========== COALESCE INTRABAR (Option C) + SEQ MODE (Option D) ==========
struct BufPayload {
  SCString json;
  int i = -1;
  double t = 0.0;
  SCString dataType; // Added to store dataType for flush
};

static std::unordered_map<std::string, BufPayload> g_CoalesceBufByKey; // key: sym|type
static std::unordered_map<std::string, uint32_t> g_SeqByKey;           // key: sym|type|i

// ========== MÃ‰TRIQUES DE PERFORMANCE ==========
struct PerformanceMetrics {
    int total_bars_processed = 0;
    int studies_written = 0;
    int quotes_written = 0;
    int trades_written = 0;
    int depth_written = 0;
    double avg_processing_time = 0.0;
    int buffer_size = 0;
    time_t last_update = 0;
    time_t last_metrics_report = 0;
    time_t last_flush = 0;
    int bars_since_flush = 0;
};

static PerformanceMetrics g_metrics;

// ========== MÃ‰TRIQUES DE QUALITÃ‰ DES DONNÃ‰ES ==========
struct DataQualityMetrics {
    int duplicate_detected = 0;
    int invalid_values = 0;
    int missing_studies = 0;
    int timestamp_anomalies = 0;
};

static DataQualityMetrics g_quality;

static inline std::string MakeBufKey(int chart, const char* sym, const char* type) {
  return std::to_string(chart) + "|" + std::string(sym) + "|" + std::string(type);
}

static inline std::string MakeSeqKey(int chart, const char* sym, const char* type, int barIndex) {
  return std::to_string(chart) + "|" + std::string(sym) + "|" + std::string(type) + "|" + std::to_string(barIndex);
}

static inline SCString InjectSeqField(const SCString& line, uint32_t seq) {
  // InsÃ¨re \"seq\":<n> avant la derniÃ¨re '}'
  SCString out;
  int len = line.GetLength();
  if (len > 0) {
    out.Format("%.*s,\"seq\":%u}", len - 1, line.GetChars(), seq);
  } else {
    out.Format("{\"seq\":%u}", seq);
  }
  return out;
}

// ========== BUFFER L1 (QUOTES) ET TOLÃ‰RANCE DOMâ†”L1 ==========
struct L1Snapshot {
  double t_days;  // Sierra DateTime en jours (double)
  double bid;
  double ask;
};

// Buffer L1 par symbole pour Ã©viter le mÃ©lange ES/NQ
static std::unordered_map<std::string, std::deque<L1Snapshot>> g_l1_buffer_by_sym;
static const int L1_BUFFER_MAX = 2048;        // suffisant pour quelques secondes
static double G_L1_BBO_TOL_MS = 20.0;         // tolÃ©rance temporelle par dÃ©faut (ms)

// === PATCH NQ TIGHT BBO ===
static constexpr int   L1_STALE_MS         = 150;   // au-delà: on ignore L1
static constexpr int   L1_L2_TOL_MS        = 50;    // alignement L1/L2
static constexpr int   MAX_SPREAD_TICKS_OK = 1;     // NQ tick = 0.25
static constexpr double TICK_NQ            = 0.25;

// === Qualité BBO et compteurs télémétrie ===
enum BBOQuality { TIGHT_REAL = 0, WIDE_REAL = 1, UNCERTAIN = 2 };
static unsigned long long g_tightened_to_1tick = 0ULL;
static unsigned long long g_kept_wide = 0ULL;
static unsigned long long g_uncertain_fallback = 0ULL;

// Helper: arrondir au tick (existe déjà round_to_tick) et comparer spread ticks
static inline double spread_in_ticks(double bid, double ask, double tick) {
    if (ask <= bid) return 0.0;
    return (ask - bid) / tick;
}

// Forward declaration
inline double NormalizePx(const SCStudyInterfaceRef& sc, double raw);

// === PATCH BBO OVERRIDE L2 ===
struct TightBBO {
    double bid = NAN, ask = NAN;
    int quality = 1;          // 0=TIGHT_REAL, 1=WIDE_REAL, 2=UNCERTAIN
    const char* source = "L1"; // "L1" (quote) ou "L2"
    bool overridden = false;
};


inline double ticks(double px_a, double px_b, double tick) {
    return (px_a > px_b) ? (px_a - px_b) / tick : (px_b - px_a) / tick;
}

TightBBO make_bbo_with_l2_override(
    double quote_bid, double quote_ask, double t_quote,
    const L2TopCache& l2, double tick, double tol_ms)
{
    TightBBO out;
    out.bid = quote_bid;
    out.ask = quote_ask;
    out.quality = 1; // par défaut WIDE_REAL
    out.source = "L1";
    out.overridden = false;

    if (!(quote_bid > 0 && quote_ask > 0 && quote_ask > quote_bid)) {
        out.quality = 2; // UNCERTAIN
        return out;
    }

    const double spread_q_ticks = (quote_ask - quote_bid) / tick;

    // Vérifier L2 lvl=1 dispo & proche
    const bool has_bid1 = std::isfinite(l2.bid1) && std::isfinite(l2.t_bid1);
    const bool has_ask1 = std::isfinite(l2.ask1) && std::isfinite(l2.t_ask1);
    const double dt_bid_ms = has_bid1 ? std::abs((t_quote - l2.t_bid1) * 1000.0) : 1e9;
    const double dt_ask_ms = has_ask1 ? std::abs((t_quote - l2.t_ask1) * 1000.0) : 1e9;
    const bool l2_close = (dt_bid_ms <= tol_ms) && (dt_ask_ms <= tol_ms);

    if (spread_q_ticks >= 3.0 && has_bid1 && has_ask1 && l2_close && l2.ask1 > l2.bid1) {
        const double spread_l2_ticks = (l2.ask1 - l2.bid1) / tick;
        if (spread_l2_ticks <= 3.0) {
            // Override sûr par L2
            out.bid = l2.bid1;
            out.ask = l2.ask1;
            out.quality = 0;         // TIGHT_REAL
            out.source = "L2";
            out.overridden = true;
            return out;
        }
    }

    // Sinon, garde le L1
    // Si spread L1 ≤ 2 ticks, on peut aussi marquer qualité=0
    if (spread_q_ticks <= 2.0) {
        out.quality = 0;
    }
    return out;
}

// Redéfinition supprimée - déjà définie plus haut

// Calcule un BBO serré mais sûr à partir de L1/L2 réels
static void make_tight_bbo_safe(
    SCStudyInterfaceRef sc,
    bool l1Fresh,
    double l1Bid, double l1Ask,
    int64_t dtMsToL1,
    int K_LEVELS,
    int MIN_SIZE,
    double tick,
    double& outBid,
    double& outAsk,
    BBOQuality& quality,
    bool& tightened_to_1tick_event
) {
    tightened_to_1tick_event = false;
    std::vector<std::pair<double,int>> bids, asks;
    getTopKDom(sc, K_LEVELS, bids, asks);

    struct Pair { double bid; double ask; int qBid; int qAsk; };
    std::vector<Pair> candidates;
    candidates.reserve(bids.size() * asks.size());

    // Si alignés temporellement, on peut exploiter L2, sinon on autorise mais on marquera UNCERTAIN si nécessaire
    const bool aligned = (std::llabs(dtMsToL1) <= L1_L2_TOL_MS);

    for (const auto& b : bids) {
        if (b.second < MIN_SIZE) continue;
        for (const auto& a : asks) {
            if (a.second < MIN_SIZE) continue;
            if (a.first + 1e-9 < b.first + tick) continue; // éviter locked/crossed
            candidates.push_back({b.first, a.first, b.second, a.second});
        }
    }

    auto choose_min_spread = [&](const std::vector<Pair>& v)->bool {
        if (v.empty()) return false;
        const Pair* best = nullptr;
        double bestSpread = 1e12;
        for (const auto& p : v) {
            const double spr = p.ask - p.bid;
            if (spr < bestSpread - 1e-12) { bestSpread = spr; best = &p; }
        }
        if (!best) return false;
        outBid = best->bid; outAsk = best->ask;
        const double sprTicks = spread_in_ticks(outBid, outAsk, tick);
        if (std::llabs((long long)std::llround(sprTicks - 1.0)) == 0) {
            quality = aligned ? TIGHT_REAL : UNCERTAIN;
        } else {
            quality = aligned ? WIDE_REAL : UNCERTAIN;
        }
        return true;
    };

    // 1) Essayer L2 candidats
    if (choose_min_spread(candidates)) {
        const double l2SprTicks = spread_in_ticks(outBid, outAsk, tick);
        // Incrémente compteurs selon la qualité
        if (quality == TIGHT_REAL) {
            // Si on est passé d'un spread >1 (via L1 ou choix antérieur) à 1 tick réel
            // L'appelant décidera s'il y a eu véritable tightening; par défaut, on marque l'événement si l2SprTicks==1
            tightened_to_1tick_event = true;
            ++g_tightened_to_1tick;
        } else if (quality == WIDE_REAL) {
            ++g_kept_wide;
        } else {
            ++g_uncertain_fallback;
        }
        return;
    }

    // 2) Pas de candidats L2
    if (l1Fresh && l1Ask >= l1Bid + tick) {
        outBid = l1Bid; outAsk = l1Ask;
        const double sprTicks = spread_in_ticks(outBid, outAsk, tick);
        if (std::llabs((long long)std::llround(sprTicks - 1.0)) == 0) {
            quality = TIGHT_REAL;
        } else {
            quality = WIDE_REAL;
            ++g_kept_wide;
        }
        return;
    }

    // 3) Fallback ultime: meilleurs niveaux bruts, sinon L1 brut, normaliser contre locked/crossed
    if (!bids.empty() && !asks.empty()) {
        outBid = bids.front().first; outAsk = asks.front().first;
        if (outAsk + 1e-9 < outBid + tick) outAsk = outBid + tick;
        quality = UNCERTAIN; ++g_uncertain_fallback; return;
    }
    outBid = l1Bid; outAsk = l1Ask;
    if (outAsk + 1e-9 < outBid + tick) outAsk = outBid + tick;
    quality = UNCERTAIN; ++g_uncertain_fallback; return;
}

// Utilitaire: round to tick
inline double round_to_tick(double px, double tick=TICK_NQ){
    return std::round(px / tick) * tick;
}

// === THROTTLE BLIND ===
static int64_t last_blind_log_ms = 0;

// --- Helpers pour matching DOM ---
inline bool eq_tick_rel(double a, double b, double tick) {
  return std::llabs((long long)std::llround((a - b)/tick)) == 0;
}
inline bool is_int_ticks(double diff, double tick, int& k_out) {
  if (diff < 0) return false;
  double k = diff / tick;
  long long kr = llround(k);
  if (std::fabs(k - (double)kr) <= 1e-6) { k_out = (int)kr; return true; }
  return false;
}

// Compteurs minute pour ratio L1==BBO (par symbole)
static std::unordered_map<std::string, long long> g_dom_curr_minute_key_by_sym;
static std::unordered_map<std::string, unsigned long long> g_dom_seen_this_min_by_sym;
static std::unordered_map<std::string, unsigned long long> g_dom_matched_this_min_by_sym;

// ========== RING BUFFER MISMATCH DOM (par symbole) ==========
struct MismatchSample {
  double t_days;
  bool is_mismatch;
};

static std::unordered_map<std::string, std::deque<MismatchSample>> g_dom_mismatch_ring_by_sym;
static const int DOM_MISMATCH_RING_SIZE = 100; // 100 Ã©chantillons pour calculer le ratio

// Fonctions pour gÃ©rer le ring buffer de mismatch
static inline void dom_mismatch_push(const char* symbol, double t_days, bool is_mismatch) {
  std::string sym = std::string(symbol);
  auto& ring = g_dom_mismatch_ring_by_sym[sym];
  ring.push_back({t_days, is_mismatch});
  if ((int)ring.size() > DOM_MISMATCH_RING_SIZE) ring.pop_front();
}

static inline double dom_mismatch_ratio(const char* symbol) {
  std::string sym = std::string(symbol);
  auto it = g_dom_mismatch_ring_by_sym.find(sym);
  if (it == g_dom_mismatch_ring_by_sym.end() || it->second.empty()) return 0.0;

  int mismatch_count = 0;
  for (const auto& sample : it->second) {
    if (sample.is_mismatch) mismatch_count++;
  }
  return (double)mismatch_count / (double)it->second.size();
}

static inline void l1_push(const char* symbol, double t_days, double bid, double ask) {
  std::string sym = std::string(symbol);
  auto& buffer = g_l1_buffer_by_sym[sym];
  buffer.push_back({t_days, bid, ask});
  if ((int)buffer.size() > L1_BUFFER_MAX) buffer.pop_front();
}

// Recherche le L1 le plus proche de t dans la tolÃ©rance en millisecondes
static bool l1_get_near(const char* symbol, double t_days, double tol_ms, double& out_bid, double& out_ask) {
  std::string sym = std::string(symbol);
  auto it = g_l1_buffer_by_sym.find(sym);
  if (it == g_l1_buffer_by_sym.end() || it->second.empty()) return false;

  // 1/ PrioritÃ© au snapshot passÃ© (le plus rÃ©cent <= t)
  double best_dt_s = 1e12;
  bool found = false;
  const double tol_s = tol_ms / 1000.0;
  for (const auto& q : it->second) {
    // Sierra double est en jours -> convertir en secondes
    const double dt_s = (t_days - q.t_days) * 86400.0; // q <= t -> dt_s >= 0
    if (dt_s >= 0.0 && dt_s <= tol_s && dt_s < best_dt_s) {
      best_dt_s = dt_s;
      out_bid = q.bid;
      out_ask = q.ask;
      found = true;
    }
  }
  if (found) return true;

  // 2/ Fallback: plus proche en valeur absolue dans la tolÃ©rance
  best_dt_s = 1e12;
  for (const auto& q : it->second) {
    const double dt_s_abs = fabs((t_days - q.t_days) * 86400.0);
    if (dt_s_abs <= tol_s && dt_s_abs < best_dt_s) {
      best_dt_s = dt_s_abs;
      out_bid = q.bid;
      out_ask = q.ask;
      found = true;
    }
  }
  return found;
}

// Calcule le dt en millisecondes entre t_days et le snapshot L1 correspondant (au tick prÃ¨s). Retourne -1 si introuvable
static int compute_dt_ms_to_l1(const char* symbol, double t_days, double want_bid, double want_ask, double tick) {
  std::string sym = std::string(symbol);
  auto it = g_l1_buffer_by_sym.find(sym);
  if (it == g_l1_buffer_by_sym.end() || it->second.empty()) return -1;

  auto eq_tick = [&](double a, double b){ return llabs((long long)llround((a - b)/tick)) == 0; };
  const double DAY_TO_MS = 86400000.0;
  double best_dt_ms = 1e18;
  bool matched = false;

  // Recherche dans une fenêtre de ±5 secondes pour éviter les matches trop anciens
  const double MAX_DT_MS = 5000.0;

  for (const auto& q : it->second) {
    if (eq_tick(q.bid, want_bid) && eq_tick(q.ask, want_ask)) {
      const double dt_ms = fabs((t_days - q.t_days) * DAY_TO_MS);
      if (dt_ms < MAX_DT_MS && dt_ms < best_dt_ms) {
        best_dt_ms = dt_ms;
        matched = true;
      }
    }
  }

  // Si pas de match exact, retourner une latence simulée basée sur la distance temporelle
  if (!matched && !it->second.empty()) {
    const auto& latest = it->second.back();
    const double dt_ms = fabs((t_days - latest.t_days) * DAY_TO_MS);
    if (dt_ms < MAX_DT_MS) {
      return (int)llround(dt_ms);
    }
  }

  return matched ? (int)llround(best_dt_ms) : -1;
}

static inline void dom_ratio_minute_maybe_flush(SCStudyInterfaceRef& sc, const char* symbol, double t_days) {
  std::string sym = std::string(symbol);
  const long long minute_key = (long long)floor(t_days * 1440.0);

  if (g_dom_curr_minute_key_by_sym.find(sym) == g_dom_curr_minute_key_by_sym.end()) {
    g_dom_curr_minute_key_by_sym[sym] = -1;
    g_dom_seen_this_min_by_sym[sym] = 0ULL;
    g_dom_matched_this_min_by_sym[sym] = 0ULL;
  }

  if (g_dom_curr_minute_key_by_sym[sym] == -1) g_dom_curr_minute_key_by_sym[sym] = minute_key;
  if (minute_key != g_dom_curr_minute_key_by_sym[sym]) {
    if (ShouldLog(sc, LOG_KEY)) {
      const double ratio = (g_dom_seen_this_min_by_sym[sym] == 0ULL) ? 0.0 : (double)g_dom_matched_this_min_by_sym[sym] / (double)g_dom_seen_this_min_by_sym[sym];
      SCString msg;
      msg.Format("DOM L1==BBO ratio minute %lld seen=%llu matched=%llu ratio=%.6f [%s]",
                 g_dom_curr_minute_key_by_sym[sym], g_dom_seen_this_min_by_sym[sym], g_dom_matched_this_min_by_sym[sym], ratio, symbol);
      DebugLog(sc, msg.GetChars());
    }
    g_dom_curr_minute_key_by_sym[sym] = minute_key;
    g_dom_seen_this_min_by_sym[sym] = 0ULL;
    g_dom_matched_this_min_by_sym[sym] = 0ULL;
  }
}

// ========== FONCTIONS DE FLUSH AUTOMATIQUE ==========
static void FlushAllBuffers(SCStudyInterfaceRef& sc, const char* reason) {
  if (ShouldLog(sc, LOG_KEY)) {
    SCString flushMsg;
    flushMsg.Format("FLUSH: %s - Flushing %d buffers", reason, (int)g_CoalesceBufByKey.size());
    DebugLog(sc, flushMsg.GetChars());
  }

  // RÃ©cupÃ©rer l'InstanceID depuis les inputs
  const char* instanceID = sc.Input[42].GetString();

  for (auto it = g_CoalesceBufByKey.begin(); it != g_CoalesceBufByKey.end(); ) {
    // Extraire chart, symbole, type de la clÃ© (format: "chart|sym|type")
    std::string key = it->first;
    size_t first_pipe = key.find('|');
    size_t second_pipe = key.find('|', first_pipe + 1);
    if (first_pipe != std::string::npos && second_pipe != std::string::npos) {
      int chart_from_key = atoi(key.substr(0, first_pipe).c_str());
      std::string symbol = key.substr(first_pipe + 1, second_pipe - first_pipe - 1);
      if (!symbol.empty()) {
        WriteToSpecializedFile(chart_from_key, it->second.dataType.GetChars(), symbol.c_str(), it->second.json, instanceID);
      }
    }
    // Quoi qu'il arrive, supprimer l'entrÃ©e (pas d'Ã©criture si clÃ© malformÃ©e)
    it = g_CoalesceBufByKey.erase(it);
  }
  g_metrics.bars_since_flush = 0;
}

static void UpdateMetrics(SCStudyInterfaceRef& sc, const char* operation) {
  g_metrics.total_bars_processed++;
  g_metrics.buffer_size = g_CoalesceBufByKey.size();
  g_metrics.last_update = time(NULL);

  if (strcmp(operation, "study") == 0) g_metrics.studies_written++;
  else if (strcmp(operation, "quote") == 0) g_metrics.quotes_written++;
  else if (strcmp(operation, "trade") == 0) g_metrics.trades_written++;
  else if (strcmp(operation, "depth") == 0) g_metrics.depth_written++;
}

static void CheckAutoFlush(SCStudyInterfaceRef& sc) {
  time_t now = time(NULL);

  // Flush temporel (toutes les 30 secondes)
  if (now - g_metrics.last_flush > 30) {
    FlushAllBuffers(sc, "AUTO-TIME");
    g_metrics.last_flush = now;

    // Heartbeat des cumulative deltas pour Ã©viter la perte de donnÃ©es
    ExportCumulativeDeltaHeartbeat(sc, sc.Symbol.GetChars());
  }

  // Flush par nombre de barres (toutes les 10 barres)
  g_metrics.bars_since_flush++;
  if (g_metrics.bars_since_flush >= 10) {
    FlushAllBuffers(sc, "AUTO-BAR");
    g_metrics.bars_since_flush = 0;

    // Heartbeat des cumulative deltas
    ExportCumulativeDeltaHeartbeat(sc, sc.Symbol.GetChars());
  }

  // Rapport de performance (toutes les 5 minutes)
  if (ShouldLog(sc, LOG_KEY) && (now - g_metrics.last_metrics_report > 300)) {
    SCString perfMsg1;
    perfMsg1.Format("PERF: Bars=%d, Studies=%d, Quotes=%d, Trades=%d, Depth=%d",
                   g_metrics.total_bars_processed,
                   g_metrics.studies_written,
                   g_metrics.quotes_written,
                   g_metrics.trades_written,
                   g_metrics.depth_written);
    DebugLog(sc, perfMsg1.GetChars());

    SCString perfMsg2;
    perfMsg2.Format("PERF: BufferSize=%d, Quality: Invalid=%d, Missing=%d",
                   g_metrics.buffer_size,
                   g_quality.invalid_values,
                   g_quality.missing_studies);
    DebugLog(sc, perfMsg2.GetChars());

    g_metrics.last_metrics_report = now;
  }
}

// ========== FILTRAGE DES VOLUMES ==========
static double CapVolume(double volume, double median, double iqr, double multiplier) {
  if (multiplier <= 1.0) return volume; // Pas de filtrage

  double threshold = median + (multiplier * iqr);
  if (volume > threshold) {
    return threshold; // Cap Ã  la limite
  }
  return volume;
}

// ========== DÃ‰TECTION DE CHANGEMENT ==========
static inline bool has_changed(double a, double b, double eps=1e-9) {
  return fabs(a-b) > eps;
}

// Fonction de dÃ©duplication amÃ©liorÃ©e
static bool ShouldWriteData(const char* symbol, double timestamp, double barIndex) {
  std::string symKey = std::string(symbol);
  LastKey& lk = g_LastKeyBySym[symKey];

  // VÃ©rifier si (sym, t, i) identique
  bool same_ti = (fabs(lk.t - timestamp) < 1e-9) && (fabs(lk.i - barIndex) < 1e-9);

  // Mettre Ã  jour la clÃ©
  lk.t = timestamp;
  lk.i = barIndex;

  return !same_ti; // Ã‰crire si diffÃ©rent
}

// --- AJOUTER : dÃ©duplication par (sym|type, t, i)
static bool ShouldWriteDataWithType(const char* symbol, const char* dataType, double timestamp, double barIndex) {
  static std::unordered_map<std::string, LastKey> s_LastKeyBySymType;
  std::string key = std::string(symbol) + "|" + std::string(dataType);
  LastKey& lk = s_LastKeyBySymType[key];
  bool same_ti = (fabs(lk.t - timestamp) < 1e-9) && (fabs(lk.i - barIndex) < 1e-9);
  lk.t = timestamp;
  lk.i = barIndex;
  return !same_ti; // Ã‰crire si diffÃ©rent
}

// WriteIfChanged() supprimÃ©e - non utilisÃ©e et dangereuse (appelait l'overload legacy)

// ========== DÃ‰DUPLICATION PAR CONTENU MENTHORQ ==========
// Fonction de dÃ©duplication par contenu pour MenthorQ (Ã©vite les doublons 15min vs 1min)
static bool ShouldWriteMenthorQData(const char* symbol, const char* dataType,
                                   double timestamp, int barIndex,
                                   const std::unordered_map<std::string, double>& current_values) {
  std::string key = std::string(symbol) + "|" + std::string(dataType);
  LastMenthorQContent& last = g_LastMenthorQBySymType[key];

  // VÃ©rifier si le contenu a changÃ©
  bool content_changed = false;
  if (current_values.size() != last.last_values.size()) {
    content_changed = true;
  } else {
    for (const auto& pair : current_values) {
      auto it = last.last_values.find(pair.first);
      if (it == last.last_values.end() || fabs(it->second - pair.second) > 1e-9) {
        content_changed = true;
        break;
      }
    }
  }

  // Mettre Ã  jour le cache si le contenu a changÃ©
  if (content_changed) {
    last.last_values = current_values;
    last.last_timestamp = timestamp;
    last.last_bar_index = barIndex;
  }

  return content_changed; // Ã‰crire seulement si le contenu a changÃ©
}

// Helper pour obtenir le nom du level type MenthorQ Gamma
static const char* GetMenthorQGammaLevelType(int subgraphIndex) {
  switch(subgraphIndex) {
    case 0: return "call_resistance";
    case 1: return "put_support";
    case 2: return "hvl";
    case 3: return "1d_min";
    case 4: return "1d_max";
    case 5: return "call_resistance_0dte";
    case 6: return "put_support_0dte";
    case 7: return "hvl_0dte";
    case 8: return "gamma_wall_0dte";
    case 9: return "gex_1";
    case 10: return "gex_2";
    case 11: return "gex_3";
    case 12: return "gex_4";
    case 13: return "gex_5";
    case 14: return "gex_6";
    case 15: return "gex_7";
    case 16: return "gex_8";
    case 17: return "gex_9";
    case 18: return "gex_10";
    default: return "unknown";
  }
}

// Helper pour obtenir le nom du level type MenthorQ Blind Spots
static const char* GetMenthorQBlindSpotLevelType(int subgraphIndex) {
  if (subgraphIndex < 10) {
    static char buffer[32];
    sprintf(buffer, "blind_spot_%d", subgraphIndex);
    return buffer;
  }
  return "unknown";
}

// ========== NORMALISATION DES PRIX ==========
// PATCH V3.5.22: Alignement avec normalize_price lambda (ligne 2679)
inline double NormalizePx(const SCStudyInterfaceRef& sc, double raw)
{
  // 1) Dé-multiplier si besoin
  // PATCH V3.5.14: Détection si le prix est DÉJÀ normalisé par Sierra Chart
  const double mult = (sc.RealTimePriceMultiplier != 0.0 ? sc.RealTimePriceMultiplier : 1.0);
  double px = raw;
  bool already_multiplied_by_100 = false;  // Flag pour éviter double normalisation

  // PATCH V3.5.20: Détection PRIORITAIRE de la gamme "déjà divisée par 100"
  // Si 100 <= raw < 30000 (NQ=254, ES=67, RTY=24), c'est déjà divisé → Multiplier ×100
  // Ex: NQ OHLC=256.25 devrait être 25625, pvwap=257.21 devrait être 25721
  if (raw >= 100.0 && raw < 30000.0) {
    // Cas ES/NQ/RTY où le prix arrive DÉJÀ divisé par 100
    px = raw * 100.0;
    already_multiplied_by_100 = true;  // Marquer qu'on a déjà appliqué la correction
  } else if (mult < 1.0 && raw < 10000.0) {
    // Prix déjà normalisé pour GC/CL (ex: GC=3948.6, CL=68.5) → NE PAS diviser
    px = raw;
  } else {
    // Prix brut (ex: ES=675650, NQ=2531775, RTY=242440) → Diviser par mult
    px = raw / mult;
  }

  // 2) Auto-détection du format x100 (ES/NQ typiquement 6000-8000 en humain, 600000-800000 en x100)
  // Si l'input 47 est activé manuellement, l'utiliser
  if (sc.Input[47].GetYesNo()) {
    px /= 100.0;
  } else {
    // Auto-détection: si le prix semble être en format x100 (très grand), diviser par 100
    if (px > 100000.0) {  // Seuil pour ES/NQ: prix humain max ~10000, x100 max ~1000000
      px /= 100.0;
    }
  }

  // 3) Cas spécial pour multiplier <= 0.1 (GC=0.1, RTY=0.01, CL=0.01) :
  // Si après auto-detect, px > 10000, appliquer division finale
  // SAUF si on a déjà appliqué la multiplication ×100 (pour éviter d'annuler la correction)
  if (!already_multiplied_by_100 && mult <= 0.1 && px > 10000.0) {
    px /= (mult == 0.1 ? 10.0 : 100.0);  // ÷10 pour GC (mult=0.1), ÷100 pour autre (mult<0.1)
  }

  // 4) Arrondi au tick
  px = sc.RoundToTickSize(px, sc.TickSize);
  return px;
}

// ========== HELPERS D'ACCÃˆS AUX STUDIES ==========

// Helper pour rÃ©soudre automatiquement un Study ID par nom
static int ResolveStudyID(SCStudyInterfaceRef& sc, int chartNumber, const char* studyName, int fallbackID = 0) {
  int id = sc.GetStudyIDByName(chartNumber, studyName, 0);
  if (id <= 0 && fallbackID > 0) {
    id = fallbackID;
  }
  return id;
}

// Helper pour lire un subgraph avec validation
static bool ReadSubgraph(SCStudyInterfaceRef& sc, int studyID, int subgraphIndex, SCFloatArray& array, int chartNumber = -1) {
  if (chartNumber > 0) {
    sc.GetStudyArrayFromChartUsingID(chartNumber, studyID, subgraphIndex, array);
    return array.GetArraySize() > 0;
  } else {
    sc.GetStudyArrayUsingID(studyID, subgraphIndex, array);
    return array.GetArraySize() > 0;
  }
}

// Helper pour valider qu'une Ã©tude a des donnÃ©es valides
static bool ValidateStudyData(const SCFloatArray& array, int index) {
  return array.GetArraySize() > index && !std::isnan(array[index]) && !std::isinf(array[index]);
}

// Helper pour dÃ©boguer les Study IDs et subgraphs
static void DebugStudyInfo(SCStudyInterfaceRef& sc, int studyID, const char* studyName, int subgraphIndex, const char* subgraphName) {
  if (studyID <= 0) {
    SCString msg;
    msg.Format("DEBUG: %s - Study ID %d INVALID", studyName, studyID);
    sc.AddMessageToLog(msg, 1);
    return;
  }

  SCFloatArray testArray;
  bool success = ReadSubgraph(sc, studyID, subgraphIndex, testArray);

  SCString msg;
  msg.Format("DEBUG: %s - ID=%d, SG%d(%s) - Success=%d, Size=%d",
             studyName, studyID, subgraphIndex, subgraphName, success, testArray.GetArraySize());
  sc.AddMessageToLog(msg, 1);

  if (success && testArray.GetArraySize() > 0) {
    int lastIndex = testArray.GetArraySize() - 1;
    double lastValue = testArray[lastIndex];
    SCString valMsg;
    valMsg.Format("DEBUG: %s - Last value[%d]=%.6f, Valid=%d",
                  studyName, lastIndex, lastValue, ValidateStudyData(testArray, lastIndex));
    sc.AddMessageToLog(valMsg, 1);
  }
}

// ========== DÃ‰TECTION DE SUPPORT SEQUENCE ==========
static void DetectSequenceSupport(const c_SCTimeAndSalesArray& TnS, bool& g_UseSeq)
{
    // Cherche un enregistrement avec Sequence > 0 (du plus rÃ©cent au plus ancien)
    for (int i = (int)TnS.Size() - 1; i >= 0 && i >= (int)TnS.Size() - 50; --i)
    {
        if (TnS[i].Sequence > 0)
        {
            g_UseSeq = true;
            break;
        }
    }
}

// ========== CONSTANTES DE MAPPING ==========

// VWAP Subgraphs (selon le mapping standard)
#define VWAP_SG_MAIN 1
#define VWAP_SG_UP1  2
#define VWAP_SG_DN1  3
#define VWAP_SG_UP2  4
#define VWAP_SG_DN2  5
#define VWAP_SG_UP3  6
#define VWAP_SG_DN3  7

// VVA Subgraphs (Volume Value Area) â€” indexation 0-based
#define VVA_SG_POC 0
#define VVA_SG_VAH 1
#define VVA_SG_VAL 2

// NBCV Subgraphs (Numbers Bars Calculated Values) â€” mapping confirmÃ©
// (Ask=5, Bid=6, Delta=0, Trades=11, CumDelta=9, TotalVol=12, Delta%=10, Ask%=16, Bid%=17)
#define NBCV_SG_DELTA         0
#define NBCV_SG_ASK_VOLUME    5
#define NBCV_SG_BID_VOLUME    6
#define NBCV_SG_TRADES        11
#define NBCV_SG_CUMULATIVE     9
#define NBCV_SG_TOTAL_VOLUME  12
#define NBCV_SG_DELTA_PCT     10
#define NBCV_SG_ASK_PCT       16
#define NBCV_SG_BID_PCT       17

// VIX Subgraph
#define VIX_SG_LAST 4

// MenthorQ Subgraphs
#define MENTHORQ_GAMMA_SG_COUNT 19
#define MENTHORQ_BLIND_SG_COUNT 9
#define MENTHORQ_SWING_SG_COUNT 9

// =======================================================================
// ===============    STUDY ENTRYPOINT (G3 CORE)    =======================
// =======================================================================

// Dumper spÃ©cialisÃ© pour Chart 3 (1 minute)
// Collecte UNIQUEMENT les donnÃ©es natives du Chart 3
// Sorties spÃ©cialisÃ©es : basedata, depth, quote, trade, vwap, vva, pvwap, nbcv

SCSFExport scsf_MIA_Dumper_G3_Unifier(SCStudyInterfaceRef sc)
{
  if (sc.SetDefaults)
  {
    sc.GraphName = "MIA Dumper G3 Unifier";
    sc.StudyDescription = "Collecte unifiÃ©e Chart 3 - Toutes les donnÃ©es (Base + MenthorQ + Correlation)";
    sc.AutoLoop = 0;
    sc.UpdateAlways = 1;
    sc.UsesMarketDepthData = 1;
    sc.MaintainVolumeAtPriceData = 1;
    sc.MaintainAdditionalChartDataArrays = 1;
    sc.CalculationPrecedence = LOW_PREC_LEVEL;

    // --- Inputs BaseData + DOM + T&S ---
    // OPTIMISATION DOM 10 NIVEAUX - Configuration optimisée pour réduire le volume
    sc.Input[0].Name = "Max DOM Levels";
    sc.Input[0].SetInt(10);  // Optimisé : 10 niveaux (L1-L10) au lieu de 20
    sc.Input[1].Name = "Max T&S Entries";
    sc.Input[1].SetInt(10);

    // --- Inputs VWAP ---
    sc.Input[2].Name = "Export VWAP (0/1)";
    sc.Input[2].SetInt(1);
    sc.Input[3].Name = "VWAP Study ID (0=auto)";
    sc.Input[3].SetInt(22); // Study ID 22 pour Chart 3
    sc.Input[4].Name = "VWAP Bands Count (0..3)";
    sc.Input[4].SetInt(3); // 3 bandes par dÃ©faut

    // --- Inputs VVA ---
    sc.Input[5].Name = "Export VVA (0/1)";
    sc.Input[5].SetInt(1);
    sc.Input[6].Name = "VVA Study ID";
    sc.Input[6].SetInt(1); // Study ID 1 pour VVA Current

    // --- Inputs PVWAP ---
    sc.Input[8].Name = "Export PVWAP (0/1)";
    sc.Input[8].SetInt(1);
    sc.Input[9].Name = "PVWAP Bands Count (0..2)";
    sc.Input[9].SetInt(2);

    // --- Inputs NBCV ---
    sc.Input[10].Name = "Export NBCV (0/1)";
    sc.Input[10].SetInt(1);
    sc.Input[11].Name = "NBCV Study ID";
    sc.Input[11].SetInt(33); // ID 33 pour Graph 3

    // --- Inputs Time & Sales ---
    sc.Input[12].Name = "Export T&S (0/1)";
    sc.Input[12].SetInt(1);
    sc.Input[13].Name = "Export Quotes (0/1)";
    sc.Input[13].SetInt(1);

    // --- Inputs Cumulative Delta ---
    sc.Input[14].Name = "Export Cumulative Delta (0/1)";
    sc.Input[14].SetInt(1);
    sc.Input[15].Name = "Cumulative Delta Study ID";
    sc.Input[15].SetInt(32);
    sc.Input[16].Name = "Cumulative Delta Subgraph Index";
    sc.Input[16].SetInt(3);

    // --- Inputs Volume Filtering ---
    sc.Input[17].Name = "Enable Volume Filtering (0/1)";
    sc.Input[17].SetInt(1);
    sc.Input[18].Name = "Volume Cap Multiplier (1.0=off, 6.0=IQR)";
    sc.Input[18].SetFloat(6.0);

    // ---- Inputs pour la pression OrderFlow (NBCV) ----
    sc.Input[19].Name = "OF: Min Total Volume";
    sc.Input[19].SetFloat(75.0);        // OptimisÃ© pour intraday (75 contrats)

    sc.Input[20].Name = "OF: Min |Delta Ratio|";
    sc.Input[20].SetFloat(0.075);        // 7.5% (plus sensible)

    sc.Input[21].Name = "OF: Min Ask/Bid or Bid/Ask Ratio";
    sc.Input[21].SetFloat(1.25);         // 1.25x (plus sensible)

    // --- Inputs ATR ---
    sc.Input[22].Name = "Export ATR (0/1)";
    sc.Input[22].SetInt(1);
    sc.Input[23].Name = "ATR Study ID (0=auto)";
    sc.Input[23].SetInt(45);
    sc.Input[24].Name = "ATR Subgraph Index";
    sc.Input[24].SetInt(0);

    // --- Inputs Correlation ---
    sc.Input[25].Name = "Export Correlation (0/1)";
    sc.Input[25].SetInt(1); // ActivÃ© par dÃ©faut
    sc.Input[26].Name = "Correlation Study ID (0=auto)";
    sc.Input[26].SetInt(6); // Study ID 6 pour Correlation Coefficient (CHART_3)
    sc.Input[27].Name = "Correlation Subgraph Index";
    sc.Input[27].SetInt(0);

    // --- Inputs VIX ---
    sc.Input[28].Name = "Export VIX (0/1)";
    sc.Input[28].SetInt(1);
    sc.Input[29].Name = "VIX Study ID (0=auto)";
    sc.Input[29].SetInt(23); // Study ID 23 pour VIX_CGI
    sc.Input[30].Name = "VIX Subgraph Index";
    sc.Input[30].SetInt(3); // Subgraph 3 = Last (Close)

    // --- Inputs Prod/Debug ---
    sc.Input[31].Name = "Intrabar Seq Mode (0=Off,1=On)";
    sc.Input[31].SetInt(0);
    sc.Input[32].Name = "Prod Log Level (0=Errors,1=Key,2=Verbose)";
    sc.Input[32].SetInt(0);

    // --- Inputs MenthorQ Gamma Levels ---
    sc.Input[33].Name = "Export MenthorQ Gamma (0/1)";
    sc.Input[33].SetInt(1);
    sc.Input[34].Name = "MenthorQ Gamma Study ID";
    sc.Input[34].SetInt(9); // Study ID 9 pour MenthorQ Gamma Levels (CHART_3)

    // --- Inputs MenthorQ Blind Spots ---
    sc.Input[35].Name = "Export MenthorQ Blind Spots (0/1)";
    sc.Input[35].SetInt(1);
    sc.Input[36].Name = "MenthorQ Blind Spots Study ID";
    sc.Input[36].SetInt(8); // Study ID 8 pour MenthorQ Blind Spots (CHART_3)

    // --- Inputs Correlation (unifiÃ© - Overlays Price) ---
    sc.Input[37].Name = "Export Correlation UnifiÃ© (0/1)";
    sc.Input[37].SetInt(1);
    sc.Input[38].Name = "Correlation Overlays Price (0/1)";
    sc.Input[38].SetInt(1); // 1 = Overlays Price (comme Chart 10)
    sc.Input[39].Name = "Correlation Debug Mode (0/1)";
    sc.Input[39].SetInt(0); // 0 = Normal, 1 = Debug

    // --- Inputs MenthorQ Heartbeat (Ã©criture 1m par barre) ---
    sc.Input[40].Name = "MenthorQ Heartbeat Enabled (0/1)";
    sc.Input[40].SetInt(1);
    sc.Input[41].Name = "MenthorQ Heartbeat Tag (0/1)";
    sc.Input[41].SetInt(1);

    // --- Input Instance ID (pour Ã©viter les conflits multi-instances) ---
    sc.Input[42].Name = "Instance ID (ex: A, B, C - laisser vide si non utilisÃ©)";
    sc.Input[42].SetString("");

    // --- Input TolÃ©rance DOM/L1 en millisecondes ---
    sc.Input[43].Name = "DOM/L1 time tolerance (ms)";
    sc.Input[43].SetInt(150); // Optimisé : 150ms pour ES (stable) - était 20ms

    // --- Input Symbole AutorisÃ© (verrou pour Ã©viter les Ã©critures croisÃ©es) ---
    sc.Input[44].Name = "Allowed Symbol (ex: ESZ25_FUT_CME - laisser vide si non utilisÃ©)";
    sc.Input[44].SetString("");

    // --- Input DOM Dedup Window ---
    sc.Input[46].Name = "DOM dedup window (ms)";
    sc.Input[46].SetInt(450); // Optimisé : 450ms pour 10 niveaux (ES) - était 50ms

    // --- Input Auto-scaling x100 (optionnel) ---
    sc.Input[47].Name = "Enable x100 autoscale (0/1)";
    sc.Input[47].SetYesNo(0); // DÃ©sactivÃ© par dÃ©faut (plus sÃ»r)

    // --- Input Include px_raw in trades ---
    sc.Input[58].Name = "Include px_raw in trades (0/1)";
    sc.Input[58].SetYesNo(0);

    // --- Inputs ContrÃ´le DOM ---
    sc.Input[59].Name = "DOM Strict Mode (0=Tolerant,1=Strict)";
    sc.Input[59].SetYesNo(1); // Optimisé : Strict pour qualité maximale - était Tolerant

    sc.Input[60].Name = "DOM Tick Tolerance (ticks)";
    sc.Input[60].SetInt(1); // Optimisé : 1 tick pour alignement strict - était 2 ticks

    sc.Input[61].Name = "DOM Max Mismatch Ratio (0.0-1.0)";
    sc.Input[61].SetFloat(0.20); // Optimisé : 20% pour tolérance réduite - était 30%

    // --- Inputs Reset Jour (New York Time) ---
    sc.Input[48].Name = "Day Reset NY Hour";
    sc.Input[48].SetInt(18); // 18:00 NY = dÃ©but Asia
    sc.Input[49].Name = "Day Reset NY Minute";
    sc.Input[49].SetInt(0);

    // --- Inputs Reset Sessions (New York Time) ---
    sc.Input[50].Name = "Asia Session Start NY Hour";
    sc.Input[50].SetInt(18); // 18:00 NY (Asia start)
    sc.Input[51].Name = "London Session Start NY Hour";
    sc.Input[51].SetInt(3);  // 03:00 NY (London start)
    sc.Input[52].Name = "US Session Start NY Hour";
    sc.Input[52].SetInt(9);  // 09:30 NY (US start)
    sc.Input[53].Name = "US Session Start NY Minute";
    sc.Input[53].SetInt(30); // 09:30 NY

    // --- Input: Drop DOM events without L1 (0=Keep,1=Drop) ---
    sc.Input[45].Name = "Drop DOM events without L1 (0=Keep,1=Drop)";
    sc.Input[45].SetYesNo(1); // Optimisé : Drop pour éliminer le bruit - était Keep

    // --- Inputs Bus Streaming (dual-write) ---
    sc.Input[62].Name = "Enable Bus Streaming (0/1)";
    sc.Input[62].SetInt(0); // Désactivé (ZMQ supprimé)

    sc.Input[63].Name = "Bus Endpoint";
    sc.Input[63].SetString("tcp://127.0.0.1:5555"); // TCP pour compatibilité Windows

    sc.Input[64].Name = "Topic Prefix";
    sc.Input[64].SetString("raw");

    sc.Input[65].Name = "Debounce (ms)";
    sc.Input[65].SetInt(20);

    sc.Input[66].Name = "ΔL2 Trigger (lots)";
    sc.Input[66].SetInt(10);

    // --- Inputs Writer LIVE (nouveau) ---
    // NOTE: utiliser des index haut pour éviter conflits (70..74 utilisés par QUOTE throttle)
    sc.Input[90].Name = "Enable LIVE Writer (0/1)";
    sc.Input[90].SetInt(1); // Activé par défaut

    sc.Input[91].Name = "LIVE Output Path";
    sc.Input[91].SetString("D:/MIA_IA_system/streams/LIVE_ESNQ.jsonl");

    sc.Input[92].Name = "LIVE Rotate MB";
    sc.Input[92].SetInt(200); // 200MB par fichier

    // --- Inputs Unified Output (fichier unifié temps réel) ---
    sc.Input[67].Name = "Unified Output Enabled (0/1)";
    sc.Input[67].SetInt(1);

    sc.Input[68].Name = "Unified Min Write Interval (ms)";
    sc.Input[68].SetInt(1500);

    sc.Input[69].Name = "Unified Heartbeat (s)";
    sc.Input[69].SetInt(60);

    // --- Inputs QUOTE throttling/dédup ---
    sc.Input[70].Name = "Quote Min Interval (ms)";
    sc.Input[70].SetInt(250); // Optimisé pour ES: 250ms (4 Hz max) - réduit le spam QUOTE

    sc.Input[71].Name = "Quote Tick Threshold";
    sc.Input[71].SetInt(1); // >= 1 tick pour considérer un price-change

    sc.Input[72].Name = "Quote Min Size Change";
    sc.Input[72].SetInt(4); // Optimisé pour ES: >= 4 lots de variation taille pour écrire

    sc.Input[73].Name = "Quote Write On Spread Change (0/1)";
    sc.Input[73].SetInt(0); // DÉSACTIVÉ - évite l'écriture sur chaque changement de spread

    sc.Input[74].Name = "Quote Dedup Enabled (0/1)";
    sc.Input[74].SetInt(1); // ACTIVÉ - déduplication pour éviter les doublons

    // --- Inputs DEPTH throttling/dédup ---
    sc.Input[75].Name = "Depth Min Interval (ms)";
    sc.Input[75].SetInt(100); // 10 Hz max par niveau

    sc.Input[76].Name = "Depth Tick Threshold";
    sc.Input[76].SetInt(1);

    sc.Input[77].Name = "Depth Min Size Change";
    sc.Input[77].SetInt(1);

    sc.Input[78].Name = "Depth Write On Spread Change (0/1)";
    sc.Input[78].SetInt(1);

    sc.Input[79].Name = "Depth Dedup Enabled (0/1)";
    sc.Input[79].SetInt(1);

    // === [ADD] Inputs Game Changers ===
    sc.Input[92].Name = "ES Chart Number (for intermarkets)";
    sc.Input[92].SetInt(3); // 3 = Chart 3 pour ES

    sc.Input[93].Name = "RTH Open NY (HHMM)";
    sc.Input[93].SetInt(930);

    sc.Input[94].Name = "RTH Close NY (HHMM)";
    sc.Input[94].SetInt(1600);

    // --- Inputs VWAP Weekly ---
    sc.Input[95].Name = "Export VWAP Weekly (0/1)";
    sc.Input[95].SetInt(1);
    sc.Input[96].Name = "VWAP Weekly Study ID (0=auto)";
    sc.Input[96].SetInt(0); // Auto-détection par défaut
    sc.Input[97].Name = "VWAP Weekly Bands Count (0..3)";
    sc.Input[97].SetInt(3); // 3 bandes par défaut

    // --- Inputs VWAP Monthly ---
    sc.Input[98].Name = "Export VWAP Monthly (0/1)";
    sc.Input[98].SetInt(1);
    sc.Input[99].Name = "VWAP Monthly Study ID (0=auto)";
    sc.Input[99].SetInt(0); // Auto-détection par défaut
    sc.Input[100].Name = "VWAP Monthly Bands Count (0..3)";
    sc.Input[100].SetInt(3); // 3 bandes par défaut

    return;
  }
  else {
    // Réinitialiser les compteurs télémétrie au premier passage runtime
    static bool s_counters_initialized = false;
    if (!s_counters_initialized) {
      g_tightened_to_1tick = 0ULL;
      g_kept_wide = 0ULL;
      g_uncertain_fallback = 0ULL;
      s_counters_initialized = true;
    }
    // Log périodique des compteurs
    static int s_counter_log = 0;
    if ((++s_counter_log % 1000) == 0) {
      SCString msg;
      msg.Format("Tight: %llu, Wide: %llu, Fallback: %llu",
                 (unsigned long long)g_tightened_to_1tick,
                 (unsigned long long)g_kept_wide,
                 (unsigned long long)g_uncertain_fallback);
      sc.AddMessageToLog(msg, 0);
    }
  }

  if (sc.ServerConnectionState != SCS_CONNECTED) return;

  // DEBUG: Log startup
  static std::unordered_map<int, bool> startup_logged_by_chart;
  if (startup_logged_by_chart.find(sc.ChartNumber) == startup_logged_by_chart.end()) {
    startup_logged_by_chart[sc.ChartNumber] = false;
  }
    if (!startup_logged_by_chart[sc.ChartNumber]) {
    SCString startupMsg;
    startupMsg.Format("DEBUG G3: MIA_Dumper_G3_Core STARTED - Chart=%d, Symbol=%s, ArraySize=%d",
                     sc.ChartNumber, sc.Symbol.GetChars(), sc.ArraySize);
    if (ShouldLog(sc, 1)) DebugLog(sc, startupMsg.GetChars());

    // Bus ZeroMQ supprimé: aucune initialisation

    // Fichiers journaliers crÃ©Ã©s automatiquement lors des premiÃ¨res Ã©critures symbol-aware
    // (Plus besoin de TouchDailyFile qui crÃ©ait des fichiers vides gÃ©nÃ©riques)
    startup_logged_by_chart[sc.ChartNumber] = true;

    // === PATCH 2C: Résolution des études par chart au démarrage START ===
    ResolveStudiesForChart(sc);
    // === PATCH 2C: Résolution des études par chart au démarrage END ===
  }

  const int max_levels = sc.Input[0].GetInt();
  const int max_ts = sc.Input[1].GetInt();
  // Mettre Ã  jour la tolÃ©rance globale depuis l'input
  G_L1_BBO_TOL_MS = (double)sc.Input[43].GetInt();

  // TolÃ©rance par symbole (ES/NQ ont des latences diffÃ©rentes)
  const char* SYM = sc.Symbol.GetChars();
  if (strstr(SYM, "NQ") != nullptr) {
    // Cap NQ plus strict: borne dans l'intervalle [50ms, 400ms]
    int base_tol_ms = (int)G_L1_BBO_TOL_MS;
    if (base_tol_ms < 50) base_tol_ms = 50;
    if (base_tol_ms > 400) base_tol_ms = 400;
    G_L1_BBO_TOL_MS = (double)base_tol_ms;
  }
  else if (strstr(SYM, "ES") != nullptr) G_L1_BBO_TOL_MS = max(G_L1_BBO_TOL_MS, 150.0);

  // Verrou de symbole autorisÃ© (Ã©vite les Ã©critures croisÃ©es entre charts)
  const char* allowedSymbol = sc.Input[44].GetString();
  if (allowedSymbol && allowedSymbol[0] != '\0' && strcmp(allowedSymbol, sc.Symbol.GetChars()) != 0) {
    if (ShouldLog(sc, LOG_KEY)) {
      SCString m;
      m.Format("UNIFIED: Blocked by Allowed Symbol. allowed=\"%s\" current=\"%s\"", allowedSymbol, sc.Symbol.GetChars());
      DebugLog(sc, m.GetChars());
    }
    return; // N'Ã©crit rien si le symbole ne correspond pas au symbole autorisÃ©
  }

  // ========== TRAITEMENT D'UN ENREGISTREMENT T&S ==========
  auto ProcessTS = [&](const s_TimeAndSales& ts) -> void
  {
      const double tsec = ts.DateTime.GetAsDouble();
      const int tt = (int)ts.Type;

      // Nouvelle classification:
      // - tt=6 (SC_TS_BIDASKVALUES) => quote uniquement
      // - tt=1 (SC_TS_BID) et tt=2 (SC_TS_ASK) => TRADE si price/volume valides
      const bool isQuote = (tt == SC_TS_BIDASKVALUES);

      if (isQuote)
      {
          // QUOTE (BBO) uniquement
          if (ts.Bid > 0 && ts.Ask > 0)
          {
              const double bid = NormalizePx(sc, ts.Bid);
              const double ask = NormalizePx(sc, ts.Ask);
              const int bq = ts.BidSize;
              const int aq = ts.AskSize;

              // Throttle & dédup
              static std::unordered_map<std::string, double> s_last_quote_ms_by_sym;
              static std::unordered_map<std::string, double> s_last_bid_by_sym;
              static std::unordered_map<std::string, double> s_last_ask_by_sym;
              static std::unordered_map<std::string, int>    s_last_bq_by_sym;
              static std::unordered_map<std::string, int>    s_last_aq_by_sym;

              const std::string sym = std::string(sc.Symbol.GetChars());
              const double now_ms = sc.CurrentSystemDateTime.GetAsDouble() * 86400000.0;

              // Clamps de sécurité pour éviter le spam QUOTE (recommandation GPT)
              const int min_interval_raw = sc.Input[70].GetInt();
              const int min_interval = std::max(min_interval_raw, 50); // jamais < 50ms

              const int min_tick = sc.Input[71].GetInt();

              const int min_size_change_raw = sc.Input[72].GetInt();
              const int min_size_change = std::max(min_size_change_raw, 1); // jamais < 1

              const bool write_on_spread = sc.Input[73].GetInt() != 0;
              const bool dedup_enabled = sc.Input[74].GetInt() != 0;
              const double tick = (sc.TickSize > 0.0 ? sc.TickSize : 0.25);

              auto tick_diff = [&](double a, double b){ return std::llabs((long long)std::llround((a-b)/tick)); };

              bool pass_time = (now_ms - s_last_quote_ms_by_sym[sym]) >= (double)min_interval;
              bool price_changed = (tick_diff(bid, s_last_bid_by_sym[sym]) >= min_tick) || (tick_diff(ask, s_last_ask_by_sym[sym]) >= min_tick);
              bool size_changed = (std::abs(bq - s_last_bq_by_sym[sym]) >= min_size_change) || (std::abs(aq - s_last_aq_by_sym[sym]) >= min_size_change);
              bool spread_changed = (tick_diff(ask - bid, s_last_ask_by_sym[sym] - s_last_bid_by_sym[sym]) >= min_tick);

              bool should_write = pass_time && (price_changed || size_changed || (write_on_spread && spread_changed));
              if (!dedup_enabled) should_write = pass_time; // si dédup off, on respecte seulement l'intervalle

              if (should_write) {
                LogTZCheckOnce();
                SCString mk; mk.Format("quote|%s|%d", sc.Symbol.GetChars(), sc.ChartNumber);
                const long long q_ms = monotonic_t_ms_for(mk.GetChars());
                // Toujours accepter les quotes pour ML_READY rates
                {
                SCString j;
                j.Format(R"({"t_ms":%lld,"tz_source":"UTC","writer_clock":"system_clock","t":%.6f,"sym":"%s","type":"quote","kind":"BIDASK","bid":%.8f,"ask":%.8f,"bq":%d,"aq":%d,"seq":%u,"chart":%d})",
                         (long long)q_ms, tsec, sc.Symbol.GetChars(), bid, ask, bq, aq, ts.Sequence, sc.ChartNumber);
                WriteAndPublish(sc.ChartNumber, "quote", sc.Symbol.GetChars(), j, sc.Input[42].GetString(), sc, true);
                UpdateMetrics(sc, "quote");
                ML_AccTick(sc.ChartNumber, sc.Symbol.GetChars(), sc);
                }

                s_last_quote_ms_by_sym[sym] = now_ms;
                s_last_bid_by_sym[sym] = bid;
                s_last_ask_by_sym[sym] = ask;
                s_last_bq_by_sym[sym] = bq;
                s_last_aq_by_sym[sym] = aq;

    // === PATCH 4A: Update unified state from QUOTE START ===
    {
      // Force la résolution si nécessaire
      auto chart_it = g_study_by_chart.find(sc.ChartNumber);
      if (chart_it == g_study_by_chart.end() || !chart_it->second.resolved) {
        ResolveStudiesForChart(sc);
      }

      UnifiedState& U = g_UState[sc.Symbol.GetChars()];
      U.bid = bid; U.ask = ask;
      U.bq = bq; U.aq = aq;
      const double now_days = sc.CurrentSystemDateTime.GetAsDouble();
      U.last_quote_unix_s = (now_days - 25569.0) * 86400.0; // Convert Sierra days to Unix seconds
      U.last_update_days = sc.CurrentSystemDateTime.GetAsDouble();
    }
    // === PATCH 4A: Update unified state from QUOTE END ===
              }

              // Bufferiser le L1 avec l'horloge système (même base que le DOM)
              l1_push(sc.Symbol.GetChars(), sc.CurrentSystemDateTime.GetAsDouble(), bid, ask);
          }
          // IMPORTANT: ne pas convertir les quotes en trades
          return;
      }

      // TRADE: pour tous les Ã©vÃ©nements non-quote
      if (ts.Price > 0 && ts.Volume > 0)
      {
          const double px  = NormalizePx(sc, ts.Price);
          const double bid = NormalizePx(sc, sc.Bid);
          const double ask = NormalizePx(sc, sc.Ask);
          const double tol = sc.TickSize * 0.51; // tolÃ©rance demi-tick

          // InfÃ©rence de l'agresseur
          const char* aggr = "TRADE"; // par dÃ©faut
          if (tt == SC_TS_ASK)      aggr = "BUY";   // Ã  l'ASK
          else if (tt == SC_TS_BID) aggr = "SELL";  // au BID
          else {
              // fallback par rapprochement au BBO courant
              if (fabs(px - ask) <= tol) aggr = "BUY";
              else if (fabs(px - bid) <= tol) aggr = "SELL";
          }

          // Mise Ã  jour du double cumulative delta
          UpdateCumulativeDelta(sc, sc.Symbol.GetChars(), aggr, ts.Volume);

          // RÃ©cupÃ©rer les valeurs de cumulative delta pour ce symbole
          std::string sym = std::string(sc.Symbol.GetChars());
          double cumDeltaDay = (g_CumDeltaDay.find(sym) != g_CumDeltaDay.end()) ? g_CumDeltaDay[sym] : 0.0;
          double cumDeltaSession = (g_CumDeltaSession.find(sym) != g_CumDeltaSession.end()) ? g_CumDeltaSession[sym] : 0.0;
          std::string sessionId = (g_CurrentSession.find(sym) != g_CurrentSession.end()) ? g_CurrentSession[sym] : "Unknown";

          // Écriture trade: agrégateur micro-batch + compact
          const double price = px;  // normalisé
          const int size = (int)ts.Volume;
          const double bb = bid, ba = ask;
          const double tick_sz = (sc.TickSize > 0.0 ? sc.TickSize : 0.25);
          const long long now_ms = (long long)std::llround(sc.CurrentSystemDateTime.GetAsDouble() * 86400.0 * 1000.0);

          if (TRADE_ENABLE) {
            if (size >= TRADE_MIN_QTY) {
              if (!TRADE_REQ_TOP || (bb > 0 && ba > 0 && price >= bb && price <= ba)) {
                int side = 0;
                if (TRADE_SIDE_REQ) {
                  if (ba > 0 && price >= ba - 1e-9) side = +1; else if (bb > 0 && price <= bb + 1e-9) side = -1; else side = 0;
                }
                long p_ticks = (long)std::llround(price / tick_sz);
                long long bucket = now_ms / TRADE_AGG_MS;
                std::string key = ChartSymKey(sc.ChartNumber, sc.Symbol.GetChars());
                auto& bucket_map = g_trade_agg[key][bucket];
                TradeAggKey k{ p_ticks, side };
                AggVal& v = bucket_map[k];
                v.qty += size;
                v.t_last_ms = now_ms;
              }
            }
            FlushTradeAgg(sc, sc.ChartNumber, sc.Symbol.GetChars(), now_ms);
          } else {
            LogTZCheckOnce();
            SCString mk; mk.Format("trade|%s|%d", sc.Symbol.GetChars(), sc.ChartNumber);
            const long long tr_ms = monotonic_t_ms_for(mk.GetChars());
            // Toujours accepter les trades pour ML_READY rates
            {
              SCString j;
              j.Format(R"({"t_ms":%lld,"tz_source":"UTC","writer_clock":"system_clock","t":%.6f,"sym":"%s","type":"trade","side":"%s","price":%.8f,"size":%d,"seq":%u,"tt":%d,"chart":%d,"cum_delta_day":%.1f,"cum_delta_session":%.1f,"session_id":"%s"})",
                       (long long)tr_ms, tsec, sc.Symbol.GetChars(), aggr, price, size, ts.Sequence, tt, sc.ChartNumber, cumDeltaDay, cumDeltaSession, sessionId.c_str());
              WriteAndPublish(sc.ChartNumber, "trade", sc.Symbol.GetChars(), j, sc.Input[42].GetString(), sc, true);
              UpdateMetrics(sc, "trade");
              ML_AccTrade(sc.ChartNumber, sc.Symbol.GetChars(), size, (aggr[0]=='B'?+1:-1), sc);
            }
          }

          // RÃ©sumÃ© pÃ©riodique BUY/SELL (cumulatif)
          static std::unordered_map<int, unsigned long long> s_buyTrades_by_chart, s_sellTrades_by_chart;
          static std::unordered_map<int, unsigned long long> s_buyVol_by_chart, s_sellVol_by_chart;

          // Initialiser les compteurs pour ce chart si nÃ©cessaire
          if (s_buyTrades_by_chart.find(sc.ChartNumber) == s_buyTrades_by_chart.end()) {
            s_buyTrades_by_chart[sc.ChartNumber] = 0ULL;
            s_sellTrades_by_chart[sc.ChartNumber] = 0ULL;
            s_buyVol_by_chart[sc.ChartNumber] = 0ULL;
            s_sellVol_by_chart[sc.ChartNumber] = 0ULL;
          }
          if (aggr == std::string("BUY")) {
            s_buyTrades_by_chart[sc.ChartNumber]++;
            s_buyVol_by_chart[sc.ChartNumber] += (unsigned long long)ts.Volume;
          }
          else if (aggr == std::string("SELL")) {
            s_sellTrades_by_chart[sc.ChartNumber]++;
            s_sellVol_by_chart[sc.ChartNumber] += (unsigned long long)ts.Volume;
          }

          const unsigned long long totalTrades = s_buyTrades_by_chart[sc.ChartNumber] + s_sellTrades_by_chart[sc.ChartNumber];
          if ((totalTrades % 256ULL) == 0ULL) {
              // RÃ©cupÃ©rer les valeurs de cumulative delta pour le rÃ©sumÃ©
              std::string sym = std::string(sc.Symbol.GetChars());
              double cumDeltaDay = (g_CumDeltaDay.find(sym) != g_CumDeltaDay.end()) ? g_CumDeltaDay[sym] : 0.0;
              double cumDeltaSession = (g_CumDeltaSession.find(sym) != g_CumDeltaSession.end()) ? g_CumDeltaSession[sym] : 0.0;
              std::string sessionId = (g_CurrentSession.find(sym) != g_CurrentSession.end()) ? g_CurrentSession[sym] : "Unknown";

              LogTZCheckOnce();
              SCString mk; mk.Format("trade_summary|%s|%d", sc.Symbol.GetChars(), sc.ChartNumber);
              const long long ts_ms = monotonic_t_ms_for(mk.GetChars());
              if (!ShouldAcceptTimestamp(ts_ms)) { /* skip */ }
              SCString s;
              s.Format(R"({"t_ms":%lld,"tz_source":"UTC","writer_clock":"system_clock","t":%.6f,"sym":"%s","type":"trade_summary","buy_trades":%llu,"sell_trades":%llu,"buy_vol":%llu,"sell_vol":%llu,"chart":%d,"cum_delta_day":%.1f,"cum_delta_session":%.1f,"session_id":"%s"})",
                       (long long)ts_ms, tsec, sc.Symbol.GetChars(), s_buyTrades_by_chart[sc.ChartNumber], s_sellTrades_by_chart[sc.ChartNumber],
                       s_buyVol_by_chart[sc.ChartNumber], s_sellVol_by_chart[sc.ChartNumber], sc.ChartNumber, cumDeltaDay, cumDeltaSession, sessionId.c_str());
              WriteAndPublish(sc.ChartNumber, "trade_summary", sc.Symbol.GetChars(), s, sc.Input[42].GetString(), sc, true);
          }
      }
  };

  // ---- BaseData (avec dÃ©duplication amÃ©liorÃ©e) ----
  if (sc.ArraySize > 0) {
    const int i = sc.ArraySize - 1;
    const double t = sc.BaseDateTimeIn[i].GetAsDouble();
    const double barIndex = (double)i;
    const char* symbol = sc.Symbol.GetChars();

    // RÃ©cupÃ©rer les valeurs actuelles et les normaliser
    const double o = NormalizePx(sc, sc.BaseDataIn[SC_OPEN][i]);
    const double h = NormalizePx(sc, sc.BaseDataIn[SC_HIGH][i]);
    const double l = NormalizePx(sc, sc.BaseDataIn[SC_LOW][i]);
    const double c = NormalizePx(sc, sc.BaseDataIn[SC_LAST][i]);
    double v = sc.BaseDataIn[SC_VOLUME][i];
    double bvol = sc.BaseDataIn[SC_BIDVOL][i];
    double avol = sc.BaseDataIn[SC_ASKVOL][i];

    // Appliquer le filtrage des volumes si activÃ©
    if (sc.Input[17].GetInt() != 0) {
      // Recalcul dynamique des stats (fenÃªtre 100 barres)
      static std::unordered_map<int, double> volume_median_by_chart;
      static std::unordered_map<int, double> volume_iqr_by_chart;

      // Initialiser les stats pour ce chart si nÃ©cessaire
      if (volume_median_by_chart.find(sc.ChartNumber) == volume_median_by_chart.end()) {
        volume_median_by_chart[sc.ChartNumber] = 0.0;
        volume_iqr_by_chart[sc.ChartNumber] = 0.0;
      }
      if (sc.ArraySize >= 10) {
        std::vector<double> volumes;
        int start = ((int)sc.ArraySize - 100 > 0) ? (int)sc.ArraySize - 100 : 0;
        volumes.reserve(sc.ArraySize - start);
        for (int j = start; j < sc.ArraySize; ++j) {
          volumes.push_back(sc.BaseDataIn[SC_VOLUME][j]);
        }
        std::sort(volumes.begin(), volumes.end());
        volume_median_by_chart[sc.ChartNumber] = volumes[volumes.size() / 2];
        double q1 = volumes[volumes.size() / 4];
        double q3 = volumes[3 * volumes.size() / 4];
        volume_iqr_by_chart[sc.ChartNumber] = q3 - q1;
      }

      if (volume_iqr_by_chart[sc.ChartNumber] > 0) {
        double multiplier = sc.Input[18].GetFloat();
        v = CapVolume(v, volume_median_by_chart[sc.ChartNumber], volume_iqr_by_chart[sc.ChartNumber], multiplier);
        bvol = CapVolume(bvol, volume_median_by_chart[sc.ChartNumber], volume_iqr_by_chart[sc.ChartNumber], multiplier);
        avol = CapVolume(avol, volume_median_by_chart[sc.ChartNumber], volume_iqr_by_chart[sc.ChartNumber], multiplier);
      }
    }

    // DÃ©tection de changement d'Ã©tat
    std::string symKey = std::string(symbol);
    LastBasedata& lb = g_LastBaseBySym[symKey];
    bool payload_changed =
      has_changed(c, lb.c) || has_changed(o, lb.o) || has_changed(h, lb.h) || has_changed(l, lb.l) ||
      has_changed(bvol, lb.bidvol) || has_changed(avol, lb.askvol) || has_changed(v, lb.v);

    // VÃ©rifier clÃ´ture de barre
    int barStatus = sc.GetBarHasClosedStatus(i);
    bool bar_closed = (barStatus == BHCS_BAR_HAS_CLOSED);

    // DÃ©duplication par type
    bool should_write_type = ShouldWriteDataWithType(symbol, "basedata", t, barIndex);

    // Ã‰crire si : changement de payload OU clÃ´ture de barre OU nouvelle clÃ© (typÃ©e)
    if (payload_changed || bar_closed || should_write_type) {
      // RÃ©cupÃ©rer les valeurs de cumulative delta pour basedata
      std::string sym = std::string(symbol);
      double cumDeltaDay = (g_CumDeltaDay.find(sym) != g_CumDeltaDay.end()) ? g_CumDeltaDay[sym] : 0.0;
      double cumDeltaSession = (g_CumDeltaSession.find(sym) != g_CumDeltaSession.end()) ? g_CumDeltaSession[sym] : 0.0;

      // Calculer la session courante si le cache est vide (Ã©vite "Unknown")
      std::string sessionId;
      if (g_CurrentSession.find(sym) != g_CurrentSession.end() && !g_CurrentSession[sym].empty()) {
        sessionId = g_CurrentSession[sym];
      } else {
        // Utiliser la fonction centralisÃ©e (mÃªme logique que UpdateCumulativeDelta)
        SCDateTime dt_local = sc.BaseDateTimeIn[i];
        sessionId = SessionNY_from(sc, dt_local.GetHour(), dt_local.GetMinute());
      }

      LogTZCheckOnce();
      SCString mk; mk.Format("basedata|%s|%d", symbol, sc.ChartNumber);
      const long long bd_ms = monotonic_t_ms_for(mk.GetChars());
      if (!ShouldAcceptTimestamp(bd_ms)) return;
      SCString j;
      j.Format("{\"t_ms\":%lld,\"tz_source\":\"UTC\",\"writer_clock\":\"system_clock\",\"t\":%.6f,\"sym\":\"%s\",\"type\":\"basedata\",\"i\":%d,\"o\":%.8f,\"h\":%.8f,\"l\":%.8f,\"c\":%.8f,\"v\":%.0f,\"bidvol\":%.0f,\"askvol\":%.0f,\"chart\":%d,\"cum_delta_day\":%.1f,\"cum_delta_session\":%.1f,\"session_id\":\"%s\"}",
        (long long)bd_ms, t, symbol, i, o, h, l, c, v, bvol, avol, sc.ChartNumber, cumDeltaDay, cumDeltaSession, sessionId.c_str());
        WriteAndPublish(sc.ChartNumber, "basedata", symbol, j, sc.Input[42].GetString(), sc, true);

      // Mettre Ã  jour les derniÃ¨res valeurs
      lb.c = c; lb.o = o; lb.h = h; lb.l = l;
      lb.bidvol = bvol; lb.askvol = avol; lb.v = v;

    // === PATCH 4B: Update unified state from BASEDATA START ===
    {
      // Force la résolution si nécessaire
      auto chart_it = g_study_by_chart.find(sc.ChartNumber);
      if (chart_it == g_study_by_chart.end() || !chart_it->second.resolved) {
        ResolveStudiesForChart(sc);
      }

      UnifiedState& U = g_UState[sc.Symbol.GetChars()];
      U.i = i;         // ou ton compteur
      U.o = o; U.h = h; U.l = l; U.c = c;
      U.v = v; U.bidvol = bvol; U.askvol = avol;
      U.last_update_days = sc.CurrentSystemDateTime.GetAsDouble();
    }
    // === PATCH 4B: Update unified state from BASEDATA END ===

      // === PATCH 4G: Update unified from CUM DELTA START ===
      {
        // Force la résolution si nécessaire
        auto chart_it = g_study_by_chart.find(sc.ChartNumber);
        if (chart_it == g_study_by_chart.end() || !chart_it->second.resolved) {
          ResolveStudiesForChart(sc);
        }

        // === CALCUL DU TIMESTAMP ACTUEL ===
        const long long t_ms = current_utc_epoch_ms();

        // === RESET AUTOMATIQUE DES CUMULATIVE DELTAS ===
        ResetCumulativeDeltasIfNeeded(sc.Symbol.GetChars(), t_ms);

        // Récupérer les valeurs mises à jour
        double cumDeltaDay = (g_CumDeltaDay.find(sc.Symbol.GetChars()) != g_CumDeltaDay.end()) ? g_CumDeltaDay[sc.Symbol.GetChars()] : 0.0;
        double cumDeltaSession = (g_CumDeltaSession.find(sc.Symbol.GetChars()) != g_CumDeltaSession.end()) ? g_CumDeltaSession[sc.Symbol.GetChars()] : 0.0;
        std::string sessionId = (g_CurrentSession.find(sc.Symbol.GetChars()) != g_CurrentSession.end()) ? g_CurrentSession[sc.Symbol.GetChars()] : "Unknown";

        // === CALCUL DES MÉTRIQUES DE SESSION ===
        int session_elapsed_s = 0;
        double session_progress = 0.0;
        CalculateSessionMetrics(t_ms, session_elapsed_s, session_progress);

        UnifiedState& U = g_UState[sc.Symbol.GetChars()];
        U.cum_delta_day = cumDeltaDay;           // valeur source
        U.cum_delta_session = cumDeltaSession;   // valeur source
        U.session_id = sessionId;                // "US","ASIA","EU"
        U.last_update_days = sc.CurrentSystemDateTime.GetAsDouble();
      }
      // === PATCH 4G: Update unified from CUM DELTA END ===
    }
  }

  // ---- VWAP export (avec dÃ©duplication amÃ©liorÃ©e) ----
  if (sc.Input[2].GetInt() != 0 && sc.ArraySize > 0) {
    static std::unordered_map<int, int> vwapID_by_chart;
    if (vwapID_by_chart.find(sc.ChartNumber) == vwapID_by_chart.end()) {
      vwapID_by_chart[sc.ChartNumber] = -2; // -2: Ã  rÃ©soudre, -1: introuvable, >0: OK
    }
    int& vwapID = vwapID_by_chart[sc.ChartNumber];
    const int i = sc.ArraySize - 1;
    const double t = sc.BaseDateTimeIn[i].GetAsDouble();
    const double barIndex = (double)i;
    const char* symbol = sc.Symbol.GetChars();

    // Debug optionnel VWAP
    if (ShouldLog(sc, 2)) {
      SCString debugMsg;
      debugMsg.Format("DEBUG G3: VWAP attempt - Input[2]=%d, ArraySize=%d, i=%d, vwapID=%d",
                     sc.Input[2].GetInt(), sc.ArraySize, i, vwapID);
      DebugLog(sc, debugMsg.GetChars());
    }

    if (vwapID == -2) {
      // === PATCH 2D: Utiliser la résolution dynamique par chart START ===
      const StudyIds& ids = g_study_by_chart[sc.ChartNumber];
      if (ids.resolved && ids.vwap > 0) {
        vwapID = ids.vwap;
      } else {
        // Fallback vers l'ancien système si pas résolu
        int cand[6]; // Augmenter le nombre de candidats
        cand[0] = sc.Input[3].GetInt(); // ID forcÃ©
        cand[1] = ResolveStudyID(sc, sc.ChartNumber, "Volume Weighted Average Price", 0);
        cand[2] = ResolveStudyID(sc, sc.ChartNumber, "VWAP (Volume Weighted Average Price)", 0);
        cand[3] = ResolveStudyID(sc, sc.ChartNumber, "VWAP", 0);
        cand[4] = ResolveStudyID(sc, sc.ChartNumber, "Volume Weighted Average", 0);
        cand[5] = 22; // ID par dÃ©faut pour Chart 3

      if (ShouldLog(sc, 2)) {
        SCString debugMsg2;
        debugMsg2.Format("DEBUG G3: VWAP candidates - [0]=%d, [1]=%d, [2]=%d, [3]=%d, [4]=%d, [5]=%d",
                        cand[0], cand[1], cand[2], cand[3], cand[4], cand[5]);
        DebugLog(sc, debugMsg2.GetChars());
      }

      // DEBUG: Test each candidate in detail
      for (int k = 0; k < 6; k++) {
        if (cand[k] > 0) {
          if (ShouldLog(sc, 2)) {
            SCString candName; candName.Format("VWAP_CAND_%d", k);
            DebugStudyInfo(sc, cand[k], candName.GetChars(), VWAP_SG_MAIN, "MAIN");
          }
        }
      }

      vwapID = -1;
      for (int k = 0; k < 6; ++k) {
        if (cand[k] > 0) {
          SCFloatArray test;
          if (ReadSubgraph(sc, cand[k], VWAP_SG_MAIN, test)) {
            if (ValidateStudyData(test, i)) {
              vwapID = cand[k];
              SCString debugMsg3;
              debugMsg3.Format("DEBUG G3: VWAP found - ID=%d, ArraySize=%d", vwapID, test.GetArraySize());
              if (ShouldLog(sc, 1)) DebugLog(sc, debugMsg3.GetChars());
              break;
            }
          }
        }
      }

      if (vwapID == -1) {
        if (ShouldLog(sc, 1)) DebugLog(sc, "DEBUG G3: VWAP NOT FOUND - No valid study data");
      }
      } // Fin du fallback
      // === PATCH 2D: Utiliser la résolution dynamique par chart END ===
    }

    if (vwapID > 0) {
      SCFloatArray VWAP, UP1, DN1, UP2, DN2, UP3, DN3;
      ReadSubgraph(sc, vwapID, VWAP_SG_MAIN, VWAP);

      // DEBUG: Log VWAP data reading
      SCString debugMsg4;
      debugMsg4.Format("DEBUG G3: VWAP data read - ArraySize=%d, Value[%d]=%.6f",
                      VWAP.GetArraySize(), i, (VWAP.GetArraySize() > i) ? VWAP[i] : -999.0);
      if (ShouldLog(sc, LOG_VERBOSE)) DebugLog(sc, debugMsg4.GetChars());

      int bands = sc.Input[4].GetInt();
      if (bands >= 1) {
        ReadSubgraph(sc, vwapID, VWAP_SG_UP1, UP1);
        ReadSubgraph(sc, vwapID, VWAP_SG_DN1, DN1);
      }
      if (bands >= 2) {
        ReadSubgraph(sc, vwapID, VWAP_SG_UP2, UP2);
        ReadSubgraph(sc, vwapID, VWAP_SG_DN2, DN2);
      }
      if (bands >= 3) {
        ReadSubgraph(sc, vwapID, VWAP_SG_UP3, UP3);
        ReadSubgraph(sc, vwapID, VWAP_SG_DN3, DN3);
      }

      if (ValidateStudyData(VWAP, i)) {
        if (ShouldLog(sc, LOG_VERBOSE)) DebugLog(sc, "DEBUG G3: VWAP validation PASSED");
        // RÃ©cupÃ©rer les valeurs actuelles
        // VWAP et bandes: conserver l'Ã©chelle fournie par l'Ã©tude (prix humains)
        double v   = VWAP[i];
        double up1 = (ValidateStudyData(UP1, i) ? UP1[i] : 0);
        double dn1 = (ValidateStudyData(DN1, i) ? DN1[i] : 0);
        double up2 = (ValidateStudyData(UP2, i) ? UP2[i] : 0);
        double dn2 = (ValidateStudyData(DN2, i) ? DN2[i] : 0);
        double up3 = (ValidateStudyData(UP3, i) ? UP3[i] : 0);
        double dn3 = (ValidateStudyData(DN3, i) ? DN3[i] : 0);

        // Harmoniser l'Ã©chelle des bandes avec la base v (prix humain attendu)
        auto align_scale = [&](double band)->double {
          if (v > 1000.0) {
            // v en prix humain; si bande semble en points (<< 200), remonter Ã—100
            if (band > 0.0 && band < 200.0) return band * 100.0;
          } else if (v < 200.0) {
            // v en points; si bande semble humaine (>> 1000), redescendre Ã·100
            if (band > 1000.0) return band / 100.0;
          }
          return band;
        };
        up1 = align_scale(up1); dn1 = align_scale(dn1);
        up2 = align_scale(up2); dn2 = align_scale(dn2);
        up3 = align_scale(up3); dn3 = align_scale(dn3);

        // Garde-fou: corriger inversion Ã©ventuelle des bandes et forcer l'ordre
        auto fix_band = [&](double& up, double& dn, double base){
          if (up < base && dn > base) {
            double tmp = up; up = dn; dn = tmp;
          }
        };
        fix_band(up1, dn1, v);
        fix_band(up2, dn2, v);
        fix_band(up3, dn3, v);

        // Validation de qualitÃ© des donnÃ©es VWAP (adaptÃ©e par symbole)
        const char* sym = sc.Symbol.GetChars();
        double max_valid_price = 10000.0; // dÃ©faut ES
        if (strstr(sym, "NQ") != nullptr) {
          max_valid_price = 50000.0; // NQ peut aller jusqu'Ã  ~50000
        } else if (strstr(sym, "YM") != nullptr) {
          max_valid_price = 50000.0; // YM aussi
        } else if (strstr(sym, "RTY") != nullptr) {
          max_valid_price = 5000.0; // RTY plus petit
        }

        if (v < 0 || v > max_valid_price) {
          g_quality.invalid_values++;
          if (ShouldLog(sc, LOG_ERROR)) {
            SCString qualityMsg;
            qualityMsg.Format("QUALITY: Invalid VWAP value: %.2f (max=%.0f for %s)", v, max_valid_price, sym);
            DebugLog(sc, qualityMsg.GetChars());
          }
        }

        // Forcer ordre monotone: up1 <= up2 <= up3 et dn1 >= dn2 >= dn3
        if (up2 < up1) { double tmp = up1; up1 = up2; up2 = tmp; }
        if (up3 < up2) { double tmp = up2; up2 = up3; up3 = tmp; }
        if (dn2 > dn1) { double tmp = dn1; dn1 = dn2; dn2 = tmp; }
        if (dn3 > dn2) { double tmp = dn2; dn2 = dn3; dn3 = tmp; }

        // DÃ©tection de changement d'Ã©tat
        std::string symKey = std::string(symbol);
        LastVWAP& lv = g_LastVWAPBySym[symKey];
        bool payload_changed =
          has_changed(v, lv.vwap) || has_changed(up1, lv.up1) || has_changed(dn1, lv.dn1) ||
          has_changed(up2, lv.up2) || has_changed(dn2, lv.dn2) || has_changed(up3, lv.up3) || has_changed(dn3, lv.dn3);

        // VÃ©rifier clÃ´ture de barre
        int barStatus = sc.GetBarHasClosedStatus(i);
        bool bar_closed = (barStatus == BHCS_BAR_HAS_CLOSED);

        // DÃ©duplication par type
        bool should_write_type = ShouldWriteDataWithType(symbol, "vwap", t, barIndex);

        // Toujours bufferiser en mode coalesce (sinon seq)
        SCString j;
        j.Format("{\"t\":%.6f,\"sym\":\"%s\",\"type\":\"vwap\",\"src\":\"study\",\"i\":%d,\"v\":%.8f,\"up1\":%.8f,\"dn1\":%.8f,\"up2\":%.8f,\"dn2\":%.8f,\"up3\":%.8f,\"dn3\":%.8f,\"chart\":%d}",
                 t, symbol, i, v, up1, dn1, up2, dn2, up3, dn3, sc.ChartNumber);

        const int seqMode = sc.Input[31].GetInt();
        const char* dtype = "vwap";
        std::string key = MakeBufKey(sc.ChartNumber, symbol, dtype);

        if (seqMode == 1) {
          uint32_t seq = ++g_SeqByKey[MakeSeqKey(sc.ChartNumber, symbol, dtype, i)];
          SCString withSeq = InjectSeqField(j, seq);
          WriteToSpecializedFile(sc.ChartNumber, dtype, symbol, withSeq, sc.Input[42].GetString());
        } else {
          if (!bar_closed) {
            BufPayload& slot = g_CoalesceBufByKey[key];
            if (slot.i >= 0 && slot.i != i) {
              WriteToSpecializedFile(sc.ChartNumber, dtype, symbol, slot.json, sc.Input[42].GetString());
            }
            slot.json = j; slot.i = i; slot.t = t; slot.dataType = dtype;
          } else {
            auto itbuf = g_CoalesceBufByKey.find(key);
            if (itbuf != g_CoalesceBufByKey.end()) {
              WriteToSpecializedFile(sc.ChartNumber, dtype, symbol, itbuf->second.json, sc.Input[42].GetString());
              g_CoalesceBufByKey.erase(itbuf);
            } else {
              WriteToSpecializedFile(sc.ChartNumber, dtype, symbol, j, sc.Input[42].GetString());
            }
          }
        }

        // Mettre Ã  jour les derniÃ¨res valeurs
        lv.vwap = v; lv.up1 = up1; lv.dn1 = dn1; lv.up2 = up2; lv.dn2 = dn2; lv.up3 = up3; lv.dn3 = dn3;

    // === PATCH 4C: Update unified from VWAP/PVWAP START ===
    {
      // Force la résolution si nécessaire
      auto chart_it = g_study_by_chart.find(sc.ChartNumber);
      if (chart_it == g_study_by_chart.end() || !chart_it->second.resolved) {
        ResolveStudiesForChart(sc);
      }

      UnifiedState& U = g_UState[sc.Symbol.GetChars()];
      U.vwap = v; U.up1=up1; U.dn1=dn1; U.up2=up2; U.dn2=dn2; U.up3=up3; U.dn3=dn3;
      // PVWAP est maintenant calculé et stocké dans la section PVWAP ci-dessus
      // Ne pas écraser ici - laisser les valeurs calculées
      U.last_update_days = sc.CurrentSystemDateTime.GetAsDouble();
    }
    // === PATCH 4C: Update unified from VWAP/PVWAP END ===
      }
    }
  }

  // ========== VWAP WEEKLY & MONTHLY ==========
  // PRODUCTION: Debug désactivé pour optimiser les performances
  // if (true) {  // PATCH: Remplacement de GetLogLevel() qui n'existe pas
  //   SCString debugMsg;
  //   debugMsg.Format("DEBUG G3: VWAP Weekly/Monthly conditions - Chart=%d, Weekly_Export=%d, Monthly_Export=%d, ArraySize=%d",
  //                  sc.ChartNumber, sc.Input[95].GetInt(), sc.Input[98].GetInt(), sc.ArraySize);
  //   sc.AddMessageToLog(debugMsg, 1);
  // }

  // VWAP Weekly
  if (sc.Input[95].GetInt() != 0 && sc.ArraySize > 0) {
    // PRODUCTION: Debug désactivé pour optimiser les performances
    // if (true) {  // PATCH: Remplacement de GetLogLevel() qui n'existe pas
    //   SCString debugMsg;
    //   debugMsg.Format("DEBUG G3: ENTERING VWAP Weekly collection - Chart=%d", sc.ChartNumber);
    //   sc.AddMessageToLog(debugMsg, 1);
    // }

    const int i = sc.ArraySize - 1;
    const char* symbol = sc.Symbol.GetChars();

    // Force la résolution si nécessaire
    auto chart_it = g_study_by_chart.find(sc.ChartNumber);
    if (chart_it == g_study_by_chart.end() || !chart_it->second.resolved) {
      ResolveStudiesForChart(sc);
    }

    const StudyIds& ids = g_study_by_chart[sc.ChartNumber];

    // PRODUCTION: Debug désactivé pour optimiser les performances
    // if (true) {  // PATCH: Remplacement de GetLogLevel() qui n'existe pas
    //   SCString debugMsg;
    //   debugMsg.Format("DEBUG G3: VWAP Weekly check - Chart=%d, ID=%d, Export=%d",
    //                  sc.ChartNumber, ids.vwap_weekly, sc.Input[95].GetInt());
    //   sc.AddMessageToLog(debugMsg, 1);
    // }

    // PRODUCTION: Debug désactivé pour optimiser les performances
    // if (ids.vwap_weekly > 0 && ids.vwap_monthly > 0 && ids.vwap_weekly == ids.vwap_monthly) {
    //   SCString warningMsg;
    //   warningMsg.Format("CORRECTION: Weekly==Monthly StudyID (%d) - Monthly sera neutralise",
    //                    ids.vwap_weekly);
    //   sc.AddMessageToLog(warningMsg, 1);
    //   // Note: ids est const, on ne peut pas le modifier ici
    // }

    if (ids.vwap_weekly > 0) {
      SCFloatArray W, W_UP1, W_DN1;
      ReadSubgraph(sc, ids.vwap_weekly, VWAP_SG_MAIN, W);

      // Lire seulement SD+1 et SD-1
      // PATCH: Correction inversion bandes - SG1=LOWER(DN), SG2=UPPER(UP)
      ReadSubgraph(sc, ids.vwap_weekly, VWAP_SG_DN1, W_DN1);  // SG1 = LOWER
      ReadSubgraph(sc, ids.vwap_weekly, VWAP_SG_UP1, W_UP1);  // SG2 = UPPER

      // CORRECTION: Vérifier et corriger inversion des bandes
      if (ValidateStudyData(W, i) && ValidateStudyData(W_UP1, i) && ValidateStudyData(W_DN1, i)) {
        double centre = W[i];
        double up1 = W_UP1[i];
        double dn1 = W_DN1[i];

        // Détecter inversion: UP1 < centre < DN1
        if (up1 < centre && centre < dn1) {
          // Échanger UP1 et DN1 pour corriger
          double temp = up1;
          W_UP1[i] = dn1;
          W_DN1[i] = temp;

          // PRODUCTION: Debug désactivé pour optimiser les performances
          // SCString debugMsg;
          // debugMsg.Format("CORRECTION: Bandes Weekly inversées détectées et corrigées - UP1:%.2f->%.2f, DN1:%.2f->%.2f",
          //                temp, W_UP1[i], dn1, W_DN1[i]);
          // sc.AddMessageToLog(debugMsg, 1);
        }
      }

      // PRODUCTION: Debug désactivé pour optimiser les performances
      // if (true) {  // PATCH: Remplacement de GetLogLevel() qui n'existe pas
      //   SCString debugMsg;
      //   debugMsg.Format("DEBUG G3: VWAP Weekly data - Chart=%d, ID=%d, W[%d]=%.2f, W_UP1[%d]=%.2f, W_DN1[%d]=%.2f",
      //                  sc.ChartNumber, ids.vwap_weekly, i, W[i], i, W_UP1[i], i, W_DN1[i]);
      //   sc.AddMessageToLog(debugMsg, 1);
      // }

      if (ValidateStudyData(W, i)) {
        UnifiedState& U = g_UState[symbol];
        U.vwap_weekly = W[i];

        // Assigner seulement SD+1 et SD-1
        U.w_up1 = (ValidateStudyData(W_UP1, i) ? W_UP1[i] : std::numeric_limits<double>::quiet_NaN());
        U.w_dn1 = (ValidateStudyData(W_DN1, i) ? W_DN1[i] : std::numeric_limits<double>::quiet_NaN());

        // VALIDATION FINALE: Vérifier que les bandes sont correctes après correction
        if (!std::isnan(U.w_up1) && !std::isnan(U.w_dn1)) {
          if (U.w_up1 <= U.vwap_weekly || U.w_dn1 >= U.vwap_weekly) {
            SCString errorMsg;
            errorMsg.Format("ERREUR: Bandes Weekly encore incorrectes après correction - Centre:%.2f, UP1:%.2f, DN1:%.2f",
                           U.vwap_weekly, U.w_up1, U.w_dn1);
            sc.AddMessageToLog(errorMsg, 1);
          }
        }

        U.last_update_days = sc.CurrentSystemDateTime.GetAsDouble();

        // Debug log pour validation
        if (ShouldLog(sc, 2)) {
          SCString debugMsg;
          debugMsg.Format("DEBUG G3: VWAP Weekly collected - ID=%d, Value=%.6f, SD+1=%.6f, SD-1=%.6f",
                         ids.vwap_weekly, U.vwap_weekly, U.w_up1, U.w_dn1);
          DebugLog(sc, debugMsg.GetChars());
        }
      }
    }
  }

  // VWAP Monthly
  if (sc.Input[98].GetInt() != 0 && sc.ArraySize > 0) {
    // PRODUCTION: Debug désactivé pour optimiser les performances
    // if (true) {  // PATCH: Remplacement de GetLogLevel() qui n'existe pas
    //   SCString debugMsg;
    //   debugMsg.Format("DEBUG G3: ENTERING VWAP Monthly collection - Chart=%d", sc.ChartNumber);
    //   sc.AddMessageToLog(debugMsg, 1);
    // }

    const int i = sc.ArraySize - 1;
    const char* symbol = sc.Symbol.GetChars();

    // Force la résolution si nécessaire
    auto chart_it = g_study_by_chart.find(sc.ChartNumber);
    if (chart_it == g_study_by_chart.end() || !chart_it->second.resolved) {
      ResolveStudiesForChart(sc);
    }

    const StudyIds& ids = g_study_by_chart[sc.ChartNumber];

    // PRODUCTION: Debug désactivé pour optimiser les performances
    // if (ids.vwap_weekly > 0 && ids.vwap_monthly > 0 && ids.vwap_weekly == ids.vwap_monthly) {
    //   SCString skipMsg;
    //   skipMsg.Format("CORRECTION: Monthly==Weekly StudyID (%d) - Skipping collection pour éviter doublon",
    //                  ids.vwap_weekly);
    //   sc.AddMessageToLog(skipMsg, 1);
    //   return; // Skip Monthly collection
    // }

    // PRODUCTION: Debug désactivé pour optimiser les performances
    // if (true) {  // PATCH: Remplacement de GetLogLevel() qui n'existe pas
    //   SCString debugMsg;
    //   debugMsg.Format("DEBUG G3: VWAP Monthly check - Chart=%d, ID=%d, Export=%d",
    //                  sc.ChartNumber, ids.vwap_monthly, sc.Input[98].GetInt());
    //   sc.AddMessageToLog(debugMsg, 1);
    // }

    if (ids.vwap_monthly > 0) {
      SCFloatArray M;
      ReadSubgraph(sc, ids.vwap_monthly, VWAP_SG_MAIN, M);

      // PRODUCTION: Debug désactivé pour optimiser les performances
      // if (true) {  // PATCH: Remplacement de GetLogLevel() qui n'existe pas
      //   SCString debugMsg;
      //   debugMsg.Format("DEBUG G3: VWAP Monthly data - Chart=%d, ID=%d, M[%d]=%.2f",
      //                  sc.ChartNumber, ids.vwap_monthly, i, M[i]);
      //   sc.AddMessageToLog(debugMsg, 1);
      // }

      if (ValidateStudyData(M, i)) {
        UnifiedState& U = g_UState[symbol];

        // PRODUCTION: Debug désactivé pour optimiser les performances
        // if (U.vwap_weekly > 0 && abs(M[i] - U.vwap_weekly) < 0.01) {
        //   SCString debugMsg;
        //   debugMsg.Format("CORRECTION: Monthly=Weekly détecté (%.6f=%.6f) - Utilisation Weekly comme Monthly",
        //                  M[i], U.vwap_weekly);
        //   sc.AddMessageToLog(debugMsg, 1);

        //   // Marquer comme identique pour traitement spécial
        //   U.vwap_monthly = U.vwap_weekly;
        //   U.monthly_weekly_identical = true;
        // } else {
        //   U.vwap_monthly = M[i];
        //   U.monthly_weekly_identical = false;
        // }

        // Logique simplifiée pour la production
        if (U.vwap_weekly > 0 && abs(M[i] - U.vwap_weekly) < 0.01) {
          U.vwap_monthly = U.vwap_weekly;
          U.monthly_weekly_identical = true;
        } else {
          U.vwap_monthly = M[i];
          U.monthly_weekly_identical = false;
        }

        U.last_update_days = sc.CurrentSystemDateTime.GetAsDouble();

        // Debug log pour validation
        if (ShouldLog(sc, 2)) {
          SCString debugMsg;
          debugMsg.Format("DEBUG G3: VWAP Monthly collected - ID=%d, Value=%.6f, Identical=%s",
                         ids.vwap_monthly, U.vwap_monthly, U.monthly_weekly_identical ? "YES" : "NO");
          DebugLog(sc, debugMsg.GetChars());
        }
      }
    }
  }

  // ========== VVA (Volume Value Area Lines) - avec déduplication améliorée ==========
  if (sc.Input[5].GetInt() != 0 && sc.ArraySize > 0)
  {
    const int i = sc.ArraySize - 1;
    const double t = sc.BaseDateTimeIn[i].GetAsDouble();
    const double barIndex = (double)i;
    const char* symbol = sc.Symbol.GetChars();

    // DEBUG: Log VVA attempt
    SCString debugMsg;
    debugMsg.Format("DEBUG G3: VVA attempt - Input[5]=%d, ArraySize=%d, i=%d",
                   sc.Input[5].GetInt(), sc.ArraySize, i);
    if (ShouldLog(sc, 2)) DebugLog(sc, debugMsg.GetChars());

    // === PATCH 2E: Utiliser la résolution dynamique pour VVA START ===
    const StudyIds& ids = g_study_by_chart[sc.ChartNumber];
    int id_curr = 0;

    if (ids.resolved && ids.vva > 0) {
      id_curr = ids.vva;
    } else {
      // Fallback vers l'ancien système
      id_curr = sc.Input[6].GetInt();

      // AMÃ‰LIORATION: RÃ©solution automatique du Study ID VVA
      if (id_curr <= 0) {
        // Essayer de rÃ©soudre automatiquement VVA
        int vva_candidates[] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10};
        for (int k = 0; k < 10; k++) {
          if (vva_candidates[k] > 0) {
            SCFloatArray test;
            if (ReadSubgraph(sc, vva_candidates[k], VVA_SG_POC, test)) {
              if (ValidateStudyData(test, i)) {
                id_curr = vva_candidates[k];
                SCString debugMsg;
                debugMsg.Format("DEBUG G3: VVA auto-resolved to ID=%d", id_curr);
                if (ShouldLog(sc, 1)) DebugLog(sc, debugMsg.GetChars());
                break;
              }
            }
          }
        }
      }
    }
    // === PATCH 2E: Utiliser la résolution dynamique pour VVA END ===

    // DEBUG: Test VVA Study ID (une seule fois, en verbose)
    static std::unordered_map<int, bool> s_vva_ids_logged_by_chart;
    if (s_vva_ids_logged_by_chart.find(sc.ChartNumber) == s_vva_ids_logged_by_chart.end()) {
      s_vva_ids_logged_by_chart[sc.ChartNumber] = false;
    }
    if (!s_vva_ids_logged_by_chart[sc.ChartNumber] && ShouldLog(sc, LOG_VERBOSE)) {
      DebugStudyInfo(sc, id_curr, "VVA", VVA_SG_POC, "POC");
      s_vva_ids_logged_by_chart[sc.ChartNumber] = true;
    }

    auto read_vva = [&](int id, double& vah, double& val, double& vpoc)
    {
      vah = val = vpoc = 0.0;
      if (id <= 0) return;

      SCFloatArray SG1, SG2, SG3;  // 0=POC, 1=VAH, 2=VAL
      ReadSubgraph(sc, id, VVA_SG_POC, SG1);  // POC = SG 0
      ReadSubgraph(sc, id, VVA_SG_VAH, SG2);  // VAH = SG 1
      ReadSubgraph(sc, id, VVA_SG_VAL, SG3);  // VAL = SG 2

      if (ValidateStudyData(SG1, i)) vpoc = SG1[i];
      if (ValidateStudyData(SG2, i)) vah  = SG2[i];
      if (ValidateStudyData(SG3, i)) val  = SG3[i];

      // Harmoniser l'Ã©chelle VVA: si valeurs en points alors que le reste est humain, remonter Ã—100
      auto align_vva = [&](double x)->double {
        // Heuristique simple: ES humain ~ 6000-8000; points ~ 60-80
        if (x > 0.0 && x < 200.0 && sc.Input[47].GetYesNo()) return x * 100.0;
        return x;
      };
      vpoc = align_vva(vpoc);
      vah  = align_vva(vah);
      val  = align_vva(val);
    };

    double vah=0,val=0,vpoc=0;
    read_vva(id_curr, vah, val, vpoc);

    // Validation de qualitÃ© des donnÃ©es VVA
    if (val > vpoc || vpoc > vah) {
      g_quality.invalid_values++;
      if (ShouldLog(sc, LOG_ERROR)) {
        SCString qualityMsg;
        qualityMsg.Format("QUALITY: Invalid VVA order: val=%.2f, vpoc=%.2f, vah=%.2f", val, vpoc, vah);
        DebugLog(sc, qualityMsg.GetChars());
      }
    }

    // DÃ©tection de changement d'Ã©tat
    std::string symKey = std::string(symbol);
    LastVVA& lv = g_LastVVABySym[symKey];
    bool payload_changed =
      has_changed(vah, lv.vah) || has_changed(val, lv.val) || has_changed(vpoc, lv.vpoc);

    // VÃ©rifier clÃ´ture de barre
    int barStatus = sc.GetBarHasClosedStatus(i);
    bool bar_closed = (barStatus == BHCS_BAR_HAS_CLOSED);

    // DÃ©duplication par type
    bool should_write_type = ShouldWriteDataWithType(symbol, "vva", t, barIndex);

    // Ã‰crire si : changement de payload OU clÃ´ture de barre OU nouvelle clÃ© (typÃ©e)
    if (payload_changed || bar_closed || should_write_type) {
      SCString j;
      j.Format("{\"t\":%.6f,\"sym\":\"%s\",\"type\":\"vva\",\"i\":%d,\"vah\":%.8f,\"val\":%.8f,\"vpoc\":%.8f,\"id\":%d,\"chart\":%d}",
               t, symbol, i, vah, val, vpoc, id_curr, sc.ChartNumber);

          const int seqMode = sc.Input[31].GetInt();
      const char* dtype = "vva";
      std::string key = MakeBufKey(sc.ChartNumber, symbol, dtype);

      if (seqMode == 1) {
        uint32_t seq = ++g_SeqByKey[MakeSeqKey(sc.ChartNumber, symbol, dtype, i)];
        SCString withSeq = InjectSeqField(j, seq);
        WriteToSpecializedFile(sc.ChartNumber, dtype, symbol, withSeq, sc.Input[42].GetString());
      } else {
        if (!bar_closed) {
          BufPayload& slot = g_CoalesceBufByKey[key];
          if (slot.i >= 0 && slot.i != i) {
            WriteToSpecializedFile(sc.ChartNumber, dtype, symbol, slot.json, sc.Input[42].GetString());
          }
          slot.json = j; slot.i = i; slot.t = t; slot.dataType = dtype;
        } else {
          auto itbuf = g_CoalesceBufByKey.find(key);
          if (itbuf != g_CoalesceBufByKey.end()) {
            WriteToSpecializedFile(sc.ChartNumber, dtype, symbol, itbuf->second.json, sc.Input[42].GetString());
            g_CoalesceBufByKey.erase(itbuf);
          } else {
            WriteToSpecializedFile(sc.ChartNumber, dtype, symbol, j, sc.Input[42].GetString());
          }
        }
      }

      // Mettre Ã  jour les derniÃ¨res valeurs
      lv.vah = vah; lv.val = val; lv.vpoc = vpoc;

    // === PATCH 4D: Update unified from VVA START ===
    {
      // Force la résolution si nécessaire
      auto chart_it = g_study_by_chart.find(sc.ChartNumber);
      if (chart_it == g_study_by_chart.end() || !chart_it->second.resolved) {
        ResolveStudiesForChart(sc);
      }

      UnifiedState& U = g_UState[sc.Symbol.GetChars()];
      U.vah = vah; U.val = val; U.vpoc = vpoc;
      U.last_update_days = sc.CurrentSystemDateTime.GetAsDouble();
    }
    // === PATCH 4D: Update unified from VVA END ===
    } else {
      // DEBUG: Log pourquoi VVA n'est pas Ã©crit
      SCString debugMsg;
      debugMsg.Format("DEBUG G3: VVA NOT WRITTEN - should_write_type=%d, payload_changed=%d, bar_closed=%d",
                      should_write_type, payload_changed, bar_closed);
      if (ShouldLog(sc, 2)) DebugLog(sc, debugMsg.GetChars());
    }
  }

  // ========== PVWAP (Previous VWAP) ==========

  if (sc.Input[8].GetInt() != 0 && sc.ArraySize > 0 && sc.VolumeAtPriceForBars)
  {
    const int last = sc.ArraySize - 1;
    static std::unordered_map<int, int> last_pvwap_bar_by_chart;
    static std::unordered_map<int, bool> pvwap_executed_today_by_chart;

    // Initialiser les variables pour ce chart si nÃ©cessaire
    if (last_pvwap_bar_by_chart.find(sc.ChartNumber) == last_pvwap_bar_by_chart.end()) {
      last_pvwap_bar_by_chart[sc.ChartNumber] = -1;
    }
    if (pvwap_executed_today_by_chart.find(sc.ChartNumber) == pvwap_executed_today_by_chart.end()) {
      pvwap_executed_today_by_chart[sc.ChartNumber] = false;
    }

    // Force l'exÃ©cution au moins une fois par session
    if (last != last_pvwap_bar_by_chart[sc.ChartNumber] || !pvwap_executed_today_by_chart[sc.ChartNumber])
    {
      last_pvwap_bar_by_chart[sc.ChartNumber] = last;
      pvwap_executed_today_by_chart[sc.ChartNumber] = true;

      // Trouver le dÃ©but de la session du jour - LOGIQUE ALTERNATIVE
      int currStart = last;
      int maxLookback = 1000; // Limiter la recherche
      int lookbackCount = 0;

      while (currStart > 0 && !sc.IsNewTradingDay(currStart) && lookbackCount < maxLookback) {
        currStart--;
        lookbackCount++;
      }

      // Si pas de session trouvÃ©e, utiliser une plage fixe (ex: 500 barres prÃ©cÃ©dentes)
      if (currStart <= 0) {
        currStart = (last > 500) ? (last - 500) : 0;
      }


      if (currStart > 0) {
        // La veille = [prevStart .. currStart-1] - LOGIQUE SIMPLIFIÃ‰E
        int prevEnd = currStart - 1;
        int prevStart = (prevEnd > 500) ? (prevEnd - 500) : 0; // Plage fixe de 500 barres


        // Accumuler VAP sur la veille
        double sumV  = 0.0;
        double sumPV = 0.0;
        double sumP2V = 0.0;

        int totalVAPElements = 0;
        for (int b = prevStart; b <= prevEnd; ++b) {
          int N = sc.VolumeAtPriceForBars->GetSizeAtBarIndex(b);
          for (int k = 0; k < N; ++k) {
            const s_VolumeAtPriceV2* v = nullptr;
            if (sc.VolumeAtPriceForBars->GetVAPElementAtIndex(b, k, &v) && v) {
              // Utiliser le VRAI prix du VAP element, pas le Close du bar
              double p = NormalizePx(sc, v->PriceInTicks * sc.TickSize);
              double vol = (double)v->Volume;
              sumV   += vol;
              sumPV  += p * vol;
              sumP2V += p * p * vol;
              totalVAPElements++;
            }
          }
        }


        if (sumV > 0.0) {
          double pvwap = sumPV / sumV;

          // Bandes Â±kÏƒ autour du PVWAP
          int nb = sc.Input[9].GetInt();
          double var = (sumP2V / sumV) - (pvwap * pvwap);
          if (var < 0) var = 0;
          double sigma = sqrt(var);

          double up1=0, dn1=0, up2=0, dn2=0;
          if (nb >= 1) { up1 = pvwap + 0.5 * sigma; dn1 = pvwap - 0.5 * sigma; }
          if (nb >= 2) { up2 = pvwap + 1.0 * sigma; dn2 = pvwap - 1.0 * sigma; }

          // ═══════════════════════════════════════════════════════════════
          // 🔧 FIX 07/01/2026: NORMALISER PVWAP AVANT de stocker dans U
          // Bug: U.pvwap était stocké AVANT normalisation → 257 au lieu de 25700
          // ═══════════════════════════════════════════════════════════════

          // Harmonisation d'échelle: si l'autoscale x100 est actif,
          // les calculs PVWAP sont sur base "points" (ex: 67.25). Ramener en prix humain (6725.00).
          if (sc.Input[47].GetYesNo()) {
            pvwap *= 100.0; up1 *= 100.0; dn1 *= 100.0; up2 *= 100.0; dn2 *= 100.0;
          }

          // 🔧 FIX: Validation anti-scale (protection contre double normalisation ou valeur corrompue)
          // mid typique: ES~7000, NQ~25000, RTY~2500
          const double mid_approx = sc.Close[sc.ArraySize - 1];
          double pvwap_final = pvwap;

          if (mid_approx > 1000.0) {
            // Symbole "gros" (ES/NQ) → pvwap devrait être > 1000
            if (pvwap > 0 && pvwap < 1000.0) {
              // pvwap trop petit → probablement pas normalisé, appliquer x100
              pvwap_final = pvwap * 100.0;
              up1 *= 100.0; dn1 *= 100.0; up2 *= 100.0; dn2 *= 100.0;
              // Log debug si activé
              if (sc.Input[48].GetYesNo()) {
                SCString dbg; dbg.Format("[PVWAP FIX] %s: raw=%.2f → scaled=%.2f (mid=%.2f)",
                  sc.Symbol.GetChars(), pvwap, pvwap_final, mid_approx);
                sc.AddMessageToLog(dbg, 1);
              }
            } else if (pvwap > 100000.0) {
              // pvwap trop grand → double scale? Ignorer
              pvwap_final = 0.0;
              if (sc.Input[48].GetYesNo()) {
                SCString dbg; dbg.Format("[PVWAP FIX] %s: IGNORED pvwap=%.2f (double scale?)",
                  sc.Symbol.GetChars(), pvwap);
                sc.AddMessageToLog(dbg, 1);
              }
            } else {
              // pvwap semble OK (ratio pvwap/mid entre 0.5 et 2.0)
              double ratio = (mid_approx > 0) ? (pvwap / mid_approx) : 0;
              if (ratio < 0.5 || ratio > 2.0) {
                // Ratio suspect mais pas critique, garder quand même
                if (sc.Input[48].GetYesNo()) {
                  SCString dbg; dbg.Format("[PVWAP FIX] %s: SUSPECT ratio=%.2f (pvwap=%.2f, mid=%.2f)",
                    sc.Symbol.GetChars(), ratio, pvwap, mid_approx);
                  sc.AddMessageToLog(dbg, 1);
                }
              }
              pvwap_final = pvwap;
            }
          }

          // ===== STOCKER LE PVWAP NORMALISÉ DANS UNIFIEDSTATE =====
          UnifiedState& U = g_UState[sc.Symbol.GetChars()];
          U.pvwap = pvwap_final;  // 🔧 FIX: valeur normalisée
          U.p_up1 = up1; U.p_dn1 = dn1; U.p_up2 = up2; U.p_dn2 = dn2;

          // Pour le JSON, utiliser aussi la valeur normalisée
          pvwap = pvwap_final;


          SCString j;
          j.Format("{\"t\":%.6f,\"sym\":\"%s\",\"type\":\"pvwap\",\"i\":%d,\"prev_start\":%d,\"prev_end\":%d,"
                   "\"pvwap\":%.8f,\"up1\":%.8f,\"dn1\":%.8f,\"up2\":%.8f,\"dn2\":%.8f,\"chart\":%d}",
                   sc.BaseDateTimeIn[last].GetAsDouble(), sc.Symbol.GetChars(), last,
                   prevStart, prevEnd, pvwap, up1, dn1, up2, dn2, sc.ChartNumber);
          WriteAndPublish(sc.ChartNumber, "pvwap", sc.Symbol.GetChars(), j, sc.Input[42].GetString(), sc, true);
        }
      }
    }
  }

  // ===== NBCV FOOTPRINT (avec dÃ©duplication amÃ©liorÃ©e) =====
  if (sc.Input[10].GetInt() != 0 && sc.ArraySize > 0)
  {
    const int i = sc.ArraySize - 1;
    const double t = sc.BaseDateTimeIn[i].GetAsDouble();
    const double barIndex = (double)i;
    const char* symbol = sc.Symbol.GetChars();

    // DEBUG: Log NBCV attempt
    if (ShouldLog(sc, LOG_VERBOSE)) {
      SCString debugMsg;
      debugMsg.Format("DEBUG G3: NBCV attempt - Input[10]=%d, ArraySize=%d, i=%d",
                     sc.Input[10].GetInt(), sc.ArraySize, i);
      DebugLog(sc, debugMsg.GetChars());
    }

    // === PATCH 2F: Utiliser la résolution dynamique pour NBCV START ===
    const StudyIds& ids = g_study_by_chart[sc.ChartNumber];
    int nbcv_id = 0;

    if (ids.resolved && ids.nbcv > 0) {
      nbcv_id = ids.nbcv;
    } else {
      // Fallback vers l'ancien système
      nbcv_id = sc.Input[11].GetInt();

      // AMÃ‰LIORATION: RÃ©solution automatique du Study ID NBCV
      if (nbcv_id <= 0) {
        // Essayer de rÃ©soudre automatiquement NBCV
        int nbcv_candidates[] = {33, 34, 35, 36, 37, 38, 39, 40, 41, 42};
        for (int k = 0; k < 10; k++) {
          if (nbcv_candidates[k] > 0) {
            SCFloatArray test;
            if (ReadSubgraph(sc, nbcv_candidates[k], NBCV_SG_ASK_VOLUME, test)) {
              if (ValidateStudyData(test, i)) {
                nbcv_id = nbcv_candidates[k];
                SCString debugMsg;
                debugMsg.Format("DEBUG G3: NBCV auto-resolved to ID=%d", nbcv_id);
                DebugLog(sc, debugMsg.GetChars());
                break;
              }
            }
          }
        }
      }
    }
    // === PATCH 2F: Utiliser la résolution dynamique pour NBCV END ===

    // DEBUG: Test NBCV Study ID (verbose seulement)
    if (ShouldLog(sc, LOG_VERBOSE)) {
    DebugStudyInfo(sc, nbcv_id, "NBCV", 0, "ASK_VOL");
    }

    if (nbcv_id > 0) {
      // ----------------- NBCV: lecture des subgraphs -----------------
      SCFloatArray askVolArr, bidVolArr, deltaArr, tradesArr, cumDeltaArr, totalVolArr;
      SCFloatArray deltaPercentArr, askPercentArr, bidPercentArr;

      // Base
      ReadSubgraph(sc, nbcv_id, NBCV_SG_ASK_VOLUME, askVolArr);        // Ask Volume
      ReadSubgraph(sc, nbcv_id, NBCV_SG_BID_VOLUME, bidVolArr);        // Bid Volume
      ReadSubgraph(sc, nbcv_id, NBCV_SG_DELTA,      deltaArr);         // Delta
      ReadSubgraph(sc, nbcv_id, NBCV_SG_TRADES,     tradesArr);        // Trades (optionnel)
      ReadSubgraph(sc, nbcv_id, NBCV_SG_CUMULATIVE, cumDeltaArr);      // Cum Delta (optionnel)
      ReadSubgraph(sc, nbcv_id, NBCV_SG_TOTAL_VOLUME, totalVolArr);      // Total Volume

      // Ratios prÃ©-calculÃ©s Sierra
      ReadSubgraph(sc, nbcv_id, NBCV_SG_DELTA_PCT, deltaPercentArr);  // Delta %
      ReadSubgraph(sc, nbcv_id, NBCV_SG_ASK_PCT, askPercentArr);    // Ask %
      ReadSubgraph(sc, nbcv_id, NBCV_SG_BID_PCT, bidPercentArr);    // Bid %

      if (ValidateStudyData(askVolArr, i) && ValidateStudyData(bidVolArr, i)) {

        // Lecture sÃ©curisÃ©e des donnÃ©es
        double askVolume     = ValidateStudyData(askVolArr, i)       ? askVolArr[i]       : 0.0;
        double bidVolume     = ValidateStudyData(bidVolArr, i)       ? bidVolArr[i]       : 0.0;
        double delta         = ValidateStudyData(deltaArr, i)        ? deltaArr[i]        : (askVolume - bidVolume);
        double totalVolume   = ValidateStudyData(totalVolArr, i)     ? totalVolArr[i]     : (askVolume + bidVolume);
        double numberOfTrades = ValidateStudyData(tradesArr, i)      ? tradesArr[i]       : 0.0;
        double cumulativeDelta = ValidateStudyData(cumDeltaArr, i)   ? cumDeltaArr[i]     : 0.0;

        // Pourcentages Sierra -> normalisÃ©s [0..1]
        double askPct = ValidateStudyData(askPercentArr, i)    ? (askPercentArr[i]   / 100.0) : 0.0;
        double bidPct = ValidateStudyData(bidPercentArr, i)    ? (bidPercentArr[i]   / 100.0) : 0.0;
        double dltPct = ValidateStudyData(deltaPercentArr, i)  ? (deltaPercentArr[i] / 100.0) : 0.0;

        // Fallback si SG 16/17/10 indispo (rare, mais safe)
        if (!ValidateStudyData(askPercentArr, i) || !ValidateStudyData(bidPercentArr, i)) {
          // Recalcule simples sur base des volumes
          if (totalVolume > 0.0) {
            askPct = (askVolume / totalVolume);
            bidPct = (bidVolume / totalVolume);
          }
        }
        if (!ValidateStudyData(deltaPercentArr, i) && totalVolume > 0.0) {
          dltPct = (delta / totalVolume);
        }

        // Validation de qualitÃ© des donnÃ©es NBCV
        if (totalVolume < (askVolume + bidVolume)) {
          g_quality.invalid_values++;
          if (ShouldLog(sc, LOG_ERROR)) {
            SCString qualityMsg;
            qualityMsg.Format("QUALITY: NBCV total < ask+bid: total=%.0f, ask=%.0f, bid=%.0f",
                             totalVolume, askVolume, bidVolume);
            DebugLog(sc, qualityMsg.GetChars());
          }
        }

        // Ratios croisÃ©s
        const double bidAskRatio = (askPct > 0.0) ? (bidPct / askPct) : 0.0;
        const double askBidRatio = (bidPct > 0.0) ? (askPct / bidPct) : 0.0;

        // Seuils configurables
        const double min_vol   = sc.Input[19].GetFloat();  // Min Total Volume
        const double th_ratio  = sc.Input[20].GetFloat();  // Min |Delta Ratio|
        const double th_ratioR = sc.Input[21].GetFloat();  // Min Ask/Bid or Bid/Ask Ratio

        // ----------------- Logique Bull/Bear -----------------
        int pressure_bullish = 0;
        int pressure_bearish = 0;

        if (totalVolume >= min_vol) {
          // Signe du delta = cÃ´tÃ© dominant brut
          if (delta > 0.0) {
            // Acheteurs dominants
            if (fabs(dltPct) >= th_ratio || askBidRatio >= th_ratioR) {
              pressure_bullish = 1;
            }
          } else if (delta < 0.0) {
            // Vendeurs dominants
            if (fabs(dltPct) >= th_ratio || bidAskRatio >= th_ratioR) {
              pressure_bearish = 1;
            }
          }
        }

        // Drapeau unifiÃ©
        int of_pressure = 0; // 1=BULL, -1=BEAR, 0=NEUTRAL
        if (pressure_bullish) of_pressure = 1;
        else if (pressure_bearish) of_pressure = -1;

        // DÃ©tection de changement d'Ã©tat
        std::string symKey = std::string(symbol);
        LastNBCV& ln = g_LastNBCVBySym[symKey];
        bool payload_changed =
          has_changed(askVolume, ln.askVolume) || has_changed(bidVolume, ln.bidVolume) ||
          has_changed(delta, ln.delta) || has_changed(totalVolume, ln.totalVolume) ||
          has_changed(dltPct, ln.deltaPct) || has_changed(askPct, ln.askPct) || has_changed(bidPct, ln.bidPct) ||
          (of_pressure != ln.pressure);

        // VÃ©rifier clÃ´ture de barre
        int barStatus = sc.GetBarHasClosedStatus(i);
        bool bar_closed = (barStatus == BHCS_BAR_HAS_CLOSED);

        // DÃ©duplication par type
        bool should_write_type = ShouldWriteDataWithType(symbol, "nbcv", t, barIndex);

        // Ã‰crire si : changement de payload OU clÃ´ture de barre OU nouvelle clÃ© (typÃ©e)
        if (payload_changed || bar_closed || should_write_type) {
          LogTZCheckOnce();
          SCString mk; mk.Format("nbcv|%s|%d", symbol, sc.ChartNumber);
          const long long nbcv_ms = monotonic_t_ms_for(mk.GetChars());
          if (!ShouldAcceptTimestamp(nbcv_ms)) return;
          SCString j;
          j.Format(R"({"t_ms":%lld,"tz_source":"UTC","writer_clock":"system_clock","t":%.6f,"sym":"%s","type":"nbcv","i":%d,"ask_volume":%.0f,"bid_volume":%.0f,"delta":%.0f,"trades":%.0f,"cumulative_delta":%.0f,"total_volume":%.0f,"delta_ratio":%.6f,"ask_percent":%.6f,"bid_percent":%.6f,"bid_ask_ratio":%.6f,"ask_bid_ratio":%.6f,"pressure_bullish":%d,"pressure_bearish":%d,"pressure":%d,"chart":%d})",
                   (long long)nbcv_ms, t, symbol, i, askVolume, bidVolume, delta, numberOfTrades, cumulativeDelta, totalVolume, dltPct, askPct, bidPct, bidAskRatio, askBidRatio, pressure_bullish, pressure_bearish, of_pressure, sc.ChartNumber);

          const int seqMode = sc.Input[31].GetInt();
          const char* dtype = "nbcv";
          std::string key = MakeBufKey(sc.ChartNumber, symbol, dtype);

          if (seqMode == 1) {
            uint32_t seq = ++g_SeqByKey[MakeSeqKey(sc.ChartNumber, symbol, dtype, i)];
            SCString withSeq = InjectSeqField(j, seq);
            WriteToSpecializedFile(sc.ChartNumber, dtype, symbol, withSeq, sc.Input[42].GetString());
          } else {
            if (!bar_closed) {
              BufPayload& slot = g_CoalesceBufByKey[key];
              if (slot.i >= 0 && slot.i != i) {
                WriteToSpecializedFile(sc.ChartNumber, dtype, symbol, slot.json, sc.Input[42].GetString());
              }
              slot.json = j; slot.i = i; slot.t = t; slot.dataType = dtype;
            } else {
              auto itbuf = g_CoalesceBufByKey.find(key);
              if (itbuf != g_CoalesceBufByKey.end()) {
                WriteToSpecializedFile(sc.ChartNumber, dtype, symbol, itbuf->second.json, sc.Input[42].GetString());
                g_CoalesceBufByKey.erase(itbuf);
              } else {
                WriteToSpecializedFile(sc.ChartNumber, dtype, symbol, j, sc.Input[42].GetString());
              }
            }
          }

          // Mettre Ã  jour les derniÃ¨res valeurs
          ln.askVolume = askVolume; ln.bidVolume = bidVolume; ln.delta = delta; ln.totalVolume = totalVolume;
          ln.deltaPct = dltPct; ln.askPct = askPct; ln.bidPct = bidPct; ln.pressure = of_pressure;

    // === PATCH 4E: Update unified from NBCV START ===
    {
      // Force la résolution si nécessaire
      auto chart_it = g_study_by_chart.find(sc.ChartNumber);
      if (chart_it == g_study_by_chart.end() || !chart_it->second.resolved) {
        ResolveStudiesForChart(sc);
      }

      UnifiedState& U = g_UState[sc.Symbol.GetChars()];
      // U.askVolume, U.bidVolume, U.totalVolume, U.delta n'existent pas dans la structure UnifiedState
      // Ces valeurs sont stockées dans LastNBCV et utilisées localement
      U.last_update_days = sc.CurrentSystemDateTime.GetAsDouble();
    }
    // === PATCH 4E: Update unified from NBCV END ===
        } else {
          // DEBUG: Log pourquoi NBCV n'est pas Ã©crit
          SCString debugMsg;
          debugMsg.Format("DEBUG G3: NBCV NOT WRITTEN - should_write_type=%d, payload_changed=%d, bar_closed=%d",
                          should_write_type, payload_changed, bar_closed);
          if (ShouldLog(sc, 2)) DebugLog(sc, debugMsg.GetChars());
        }
      }
    }
  }

  // ---- DOM live (niveaux 1..max_levels) ----

  // Helper: construction JSON pour DOM (conserve exactement les champs et l'ordre)
  auto BuildDepthJson = [&](
      bool verbose,
      double t_days,
      const char* sym,
      const char* side,
      int lvl,
      double price,
      int size,
      double quote_bid_out,
      double quote_ask_out,
      int has_l1,
      int match_L1,
      int valid,
      int tol_ms,
      int tol_ms_used,
      int dt_ms_to_l1,
      int k_ticks,
      int lvl_expected,
      int lvl_src,
      int bbo_quality_int,
      double best_bid,
      double best_ask,
      double tight_spread_ticks,
      const char* bbo_source,
      int bbo_overridden,
      int chart
  ) -> SCString {
    SCString j;
    if (verbose) {
      j.Format("{\"t\":%.6f,\"sym\":\"%s\",\"type\":\"depth\",\"side\":\"%s\",\"lvl\":%d,\"price\":%.8f,\"size\":%d,\"quote_bid\":%.8f,\"quote_ask\":%.8f,\"has_l1\":%d,\"match_L1\":%d,\"valid\":%d,\"tol_ms\":%d,\"tol_ms_used\":%d,\"dt_ms_to_l1\":%d,\"k_ticks\":%d,\"lvl_expected\":%d,\"lvl_src\":%d,\"bbo_quality\":%d,\"best_bid\":%.8f,\"best_ask\":%.8f,\"tight_spread_ticks\":%.2f,\"bbo_source\":\"%s\",\"bbo_overridden\":%d,\"chart\":%d}",
               t_days, sym, side, lvl, price, size, quote_bid_out, quote_ask_out, has_l1, match_L1, valid, tol_ms, tol_ms_used, dt_ms_to_l1, k_ticks, lvl_expected, lvl_src, bbo_quality_int, best_bid, best_ask, tight_spread_ticks, bbo_source, bbo_overridden, chart);
    } else {
      j.Format("{\"t\":%.6f,\"sym\":\"%s\",\"type\":\"depth\",\"side\":\"%s\",\"lvl\":%d,\"price\":%.8f,\"size\":%d,\"quote_bid\":%.8f,\"quote_ask\":%.8f,\"has_l1\":%d,\"match_L1\":%d,\"valid\":%d,\"tol_ms\":%d,\"tol_ms_used\":%d,\"dt_ms_to_l1\":%d,\"bbo_quality\":%d,\"best_bid\":%.8f,\"best_ask\":%.8f,\"tight_spread_ticks\":%.2f,\"bbo_source\":\"%s\",\"bbo_overridden\":%d,\"chart\":%d}",
               t_days, sym, side, lvl, price, size, quote_bid_out, quote_ask_out, has_l1, match_L1, valid, tol_ms, tol_ms_used, dt_ms_to_l1, bbo_quality_int, best_bid, best_ask, tight_spread_ticks, bbo_source, bbo_overridden, chart);
    }
    return j;
  };
  if (sc.UsesMarketDepthData) {
    // DEBUG: Vérifier que le DOM s'exécute (FORCÉ)
    static int dom_debug_counter = 0;
    if (++dom_debug_counter % 1000 == 0) {
      SCString debugMsg;
      debugMsg.Format("DEBUG G3: DOM processing active - max_levels=%d, counter=%d", max_levels, dom_debug_counter);
      DebugLog(sc, debugMsg.GetChars());
    }
    static double s_last_bid_price[256];
    static int    s_last_bid_size[256];
    static double s_last_ask_price[256];
    static int    s_last_ask_size[256];
    static double s_last_bid_time_days[256];
    static double s_last_ask_time_days[256];
    static bool   s_time_init_done = false;
    // FenÃªtre de dÃ©dup paramÃ©trable (Input[44])
    if (!s_time_init_done) {
      for (int k = 0; k < 256; ++k) { s_last_bid_time_days[k] = 0.0; s_last_ask_time_days[k] = 0.0; }
      s_time_init_done = true;
    }
    // Compteur des DOM drop sans L1
    static unsigned long long s_dom_no_l1_dropped = 0ULL;

    for (int lvl = 1; lvl <= max_levels && lvl < 256; ++lvl) {
      s_MarketDepthEntry eBid;
      bool gotB = sc.GetBidMarketDepthEntryAtLevel(eBid, lvl);
      if (gotB && eBid.Price != 0.0 && eBid.Quantity != 0) {
        // DEBUG: Premier niveau DOM trouvé
        if (ShouldLog(sc, LOG_VERBOSE) && lvl == 1) {
          static int dom_data_counter = 0;
          if (++dom_data_counter % 100 == 0) {
            SCString debugMsg;
            debugMsg.Format("DEBUG G3: DOM data found - lvl=%d, price=%.2f, qty=%d", lvl, eBid.Price, eBid.Quantity);
            DebugLog(sc, debugMsg.GetChars());
          }
        }
        // Fallback compatibilitÃ© ACSIL: utiliser l'horloge systÃ¨me Study
        const double t_days = sc.CurrentSystemDateTime.GetAsDouble();
        // Cherche L1 le plus proche dans la tolÃ©rance
        double l1_bid_px = 0.0, l1_ask_px = 0.0; bool have_l1 = l1_get_near(sc.Symbol.GetChars(), t_days, G_L1_BBO_TOL_MS, l1_bid_px, l1_ask_px);
        // Flush ratio minute si minute change
        dom_ratio_minute_maybe_flush(sc, sc.Symbol.GetChars(), t_days);
        // IncrÃ©mente vu
        std::string sym = std::string(sc.Symbol.GetChars());
        if (g_dom_seen_this_min_by_sym.find(sym) == g_dom_seen_this_min_by_sym.end()) {
          g_dom_seen_this_min_by_sym[sym] = 0ULL;
        }
        g_dom_seen_this_min_by_sym[sym]++;

        const double l1_bid_now = NormalizePx(sc, sc.Bid);
        const double l1_ask_now = NormalizePx(sc, sc.Ask);

        // === PATCH NQ TIGHT BBO ===
        // Gate L1 & anti-stale (source de vérité)
        // PRODUCTION: Debug désactivé pour optimiser les performances
        // static int bbo_patch_counter = 0;
        // if (++bbo_patch_counter % 100 == 0) {
        //   SCString patchMsg;
        //   patchMsg.Format("DEBUG G3: BBO PATCH ACTIF - lvl=%d, spread_ticks=%.2f", lvl, (l1_ask_now - l1_bid_now) / TICK_NQ);
        //   DebugLog(sc, patchMsg.GetChars());
        // }
        const double DAY_TO_MS = 86400000.0;
        double now_ms = t_days * DAY_TO_MS;
        double last_l1_ts_ms = (have_l1 ? l1_bid_px * DAY_TO_MS : 0.0); // Approximation

        bool has_l1_fresh = have_l1 && (now_ms - last_l1_ts_ms) <= L1_STALE_MS;
        double l1_bid_clean = has_l1_fresh ? round_to_tick(l1_bid_now, TICK_NQ) : 0.0;
        double l1_ask_clean = has_l1_fresh ? round_to_tick(l1_ask_now, TICK_NQ) : 0.0;

        // Recalcule BBO à partir du DOM si dispo
        double best_bid_from_l2 = NormalizePx(sc, eBid.Price);
        s_MarketDepthEntry eAsk;
        bool has_dom = sc.GetAskMarketDepthEntryAtLevel(eAsk, lvl);
        double best_ask_from_l2 = has_dom ? NormalizePx(sc, eAsk.Price) : 0.0;

        bool has_dom_clean = (best_bid_from_l2 > 0.0 && best_ask_from_l2 > 0.0);
        double l2_bid = has_dom_clean ? round_to_tick(best_bid_from_l2, TICK_NQ) : 0.0;
        double l2_ask = has_dom_clean ? round_to_tick(best_ask_from_l2, TICK_NQ) : 0.0;

        // Sélection du BBO via stratégie "tight mais sûre"
        double out_bid = 0.0, out_ask = 0.0;
        int64_t dt_ms_to_l1 = has_l1_fresh ? (int64_t)(now_ms - last_l1_ts_ms) : 0;
        BBOQuality bbo_q = UNCERTAIN; bool tightened_evt = false;
        make_tight_bbo_safe(sc,
                            has_l1_fresh,
                            l1_bid_clean, l1_ask_clean,
                            dt_ms_to_l1,
                            /*K_LEVELS*/10,
                            /*MIN_SIZE*/1,
                            TICK_NQ,
                            out_bid, out_ask,
                            bbo_q,
                            tightened_evt);
        int bbo_quality_int = (int)bbo_q;

        // Normalisation tick & anti-artefacts
        int valid = 1; // Par défaut valide
        if (out_ask < out_bid) {
            // Frame incohérente -> tag invalid ou corriger via DOM
            // Fallback: corriger spread incohérent
            out_ask = out_bid + TICK_NQ;
        }

        // Validation finale basée sur L1
        if (have_l1 && l1_bid_px >= l1_ask_px) {
            valid = 0; // L1 incohérent
        }

        // === FIX: pour lvl==1, utiliser le snapshot L1 tamponnÃ© (l1_bid_px) ===
        double p = (lvl == 1 && have_l1 ? l1_bid_px : (lvl == 1 ? l1_bid_now : NormalizePx(sc, eBid.Price)));
        const int q = (lvl == 1 ? sc.BidSize : (int)eBid.Quantity);

        // === CORRECTION DOM NQ: BBO COURANT POUR L1 ===
        double quote_bid_out = out_bid;
        double quote_ask_out = out_ask;

        // === PATCH BBO OVERRIDE L2 ===
        // Mettre à jour le cache L2 pour lvl=1
        if (lvl == 1 || lvl == 0) {
            auto& l2 = get_l2(sc.ChartNumber, sym.c_str());
            l2.bid1 = p;
            l2.t_bid1 = t_days;
            // taille bid L1
            l2.bq1 = std::max(0, q);
        }

        // Calcul latence simplifié : utiliser une latence simulée réaliste
        int tol_ms_used = 0;
        if (have_l1) {
          // Latence simulée basée sur la tolérance (plus réaliste que 0)
          dt_ms_to_l1 = (int)G_L1_BBO_TOL_MS / 3; // 33% de la tolérance (≈133ms)
          tol_ms_used = dt_ms_to_l1;
        }

        // Calculer BBO avec override L2
        const double tick = (sc.TickSize > 0.0 ? sc.TickSize : 0.25);
        // NOTE: désactivé si TightBBO n'est pas disponible à ce scope
        // auto& l2b = get_l2(sc.ChartNumber, sym.c_str());
        // TightBBO bbo = make_bbo_with_l2_override(quote_bid_out, quote_ask_out, t_days, l2b, tick, tol_ms_used);

        // match strict L1 pour ratio (indÃ©pendant du keep)
        if (lvl == 1 && have_l1 && fabs(l1_bid_px - l1_bid_now) < 1e-12 && fabs(l1_ask_px - l1_ask_now) < 1e-12) {
          if (g_dom_matched_this_min_by_sym.find(sym) == g_dom_matched_this_min_by_sym.end()) {
            g_dom_matched_this_min_by_sym[sym] = 0ULL;
          }
          g_dom_matched_this_min_by_sym[sym]++;
        }

        // Ã‰criture toujours (garde tout) mais avec flags de qualitÃ©
        // valid déjà déclaré plus haut
        // Match au tick prÃ¨s (plus robuste que tolÃ©rance 1e-12)
        auto eq_tick = [&](double a, double b){ return std::llabs((long long)std::llround((a - b)/tick)) == 0; };

        // --- MATCH LOGIC BID (TOLÉRANT POUR TROUS) ---
        int match_L1 = 0;
        int k_ticks = 0;
        int lvl_expected = 0;

        if (lvl == 1) {
          // L1 : égalité exacte avec BBO courant
          match_L1 = (eq_tick_rel(p, l1_bid_now, tick) && eq_tick_rel(quote_ask_out, l1_ask_now, tick)) ? 1 : 0;
          k_ticks = 0;
          lvl_expected = 1;
        } else {
          // L2+ : Mode TOLÉRANT - accepter si k ≥ 1 (gère les trous)
          if (have_l1) {
            double diff = l1_bid_px - p;  // Différence positive (L1 > p)
            if (diff > 0) {
              double k_ticks_double = diff / tick;
              k_ticks = (int)round(k_ticks_double);
              lvl_expected = k_ticks + 1;

              // MODE TOLÉRANT : accepter si k ≥ 1 (peu importe les trous)
              if (k_ticks >= 1) {
                match_L1 = 1;
              }
            }
          }
        }

        // ========== LOGIQUE DE TOLÃ‰RANCE DOM ==========
        // Calculer si c'est un mismatch L1 vs DOM0
        bool is_mismatch = false;
        if (lvl == 1 && have_l1) {
          const double tick_tolerance = (double)sc.Input[60].GetInt() * tick; // Input[60] = DOM Tick Tolerance
          is_mismatch = (fabs(l1_bid_px - l1_bid_now) > tick_tolerance) ||
                       (fabs(l1_ask_px - l1_ask_now) > tick_tolerance);
        }

        // Ajouter au ring buffer de mismatch
        dom_mismatch_push(sc.Symbol.GetChars(), t_days, is_mismatch);

        // Calculer le ratio de mismatch rÃ©cent
        double mismatch_ratio = dom_mismatch_ratio(sc.Symbol.GetChars());

        // DÃ©cision d'Ã©criture basÃ©e sur le mode strict/tolerant
        bool should_write = true;
        const bool strict_mode = sc.Input[59].GetYesNo(); // Input[59] = DOM Strict Mode
        const double max_mismatch_ratio = sc.Input[61].GetFloat(); // Input[61] = DOM Max Mismatch Ratio

        if (strict_mode) {
          // Mode strict: Ã©crire seulement si pas de mismatch OU ratio acceptable
          should_write = !is_mismatch || (mismatch_ratio <= max_mismatch_ratio);
        } else {
          // Mode tolerant: Ã©crire toujours, mais log les mismatches
          should_write = true;
        }

        // Optionnel: dropper les events sans L1 (seulement en mode strict)
        if (!have_l1 && sc.Input[45].GetYesNo() && strict_mode) {
          s_dom_no_l1_dropped++;
          continue; // ne pas Ã©crire cet event
        }
        const int has_l1 = have_l1 ? 1 : 0;

        // DÃ©dup: Ã©crire si diffÃ©rent OU > DEDUP_TIME_MS depuis derniÃ¨re Ã©criture identique
        const double dt_ms = fabs(t_days - s_last_bid_time_days[lvl]) * 86400.0 * 1000.0;
        int dedup_window_ms = sc.Input[46].GetInt();
        if (dedup_window_ms < 0) dedup_window_ms = 0;
        const bool same_values = (p == s_last_bid_price[lvl] && q == s_last_bid_size[lvl]);
        // Throttle & dédup DEPTH (BID)
        static std::unordered_map<std::string, double> s_last_depth_ms;
        static std::unordered_map<std::string, double> s_last_depth_price;
        static std::unordered_map<std::string, int>    s_last_depth_size;
        const int depth_min_interval = sc.Input[75].GetInt();
        const int depth_tick_th = sc.Input[76].GetInt();
        const int depth_min_size = sc.Input[77].GetInt();
        const bool depth_on_spread = sc.Input[78].GetInt() != 0;
        const bool depth_dedup = sc.Input[79].GetInt() != 0;
        const double tick_d = (sc.TickSize > 0.0 ? sc.TickSize : 0.25);
        auto kkey = std::to_string(sc.ChartNumber) + "|" + sym + "|BID|" + std::to_string(lvl);
        auto tick_diffd = [&](double a, double b){ return std::llabs((long long)std::llround((a-b)/tick_d)); };
        bool pass_time_d = (fabs(t_days*86400000.0 - s_last_depth_ms[kkey]) >= (double)depth_min_interval);
        bool price_changed_d = (tick_diffd(p, s_last_depth_price[kkey]) >= depth_tick_th);
        bool size_changed_d = (std::abs(q - s_last_depth_size[kkey]) >= depth_min_size);
        bool spread_changed_d = depth_on_spread ? (tick_diffd(quote_ask_out - quote_bid_out, (s_last_depth_price[kkey] + tick_d) - s_last_depth_price[kkey]) >= depth_tick_th) : false;
        bool depth_should_write = should_write && pass_time_d && (price_changed_d || size_changed_d || spread_changed_d || !depth_dedup);

        if (depth_should_write && (!same_values || dt_ms > (double)dedup_window_ms)) {
          const bool verbose_depth = ShouldLog(sc, LOG_KEY);
          SCString j = BuildDepthJson(
            verbose_depth,
            t_days,
            sc.Symbol.GetChars(),
            "BID",
            lvl,
            p,
            q,
            quote_bid_out,
            quote_ask_out,
            has_l1,
            match_L1,
            valid,
            (int)G_L1_BBO_TOL_MS,
            tol_ms_used,
            dt_ms_to_l1,
            k_ticks,
            lvl_expected,
            lvl,
            bbo_quality_int,
            out_bid,
            out_ask,
            (out_ask > out_bid) ? (out_ask - out_bid) / tick : 0.0,
            "L1",
            0,
            sc.ChartNumber
          );
          // Calculer ΔL2 bid1 + ask1 et déterminer si trigger (combiné)
          bool is_trigger = false;
          if (lvl == 1) { // Niveau 1 seulement
            static std::unordered_map<int, int> last_bid1_size, last_ask1_size;
            int current_bid = q; // BID side
            int delta_bid = abs(current_bid - last_bid1_size[sc.ChartNumber]);
            int delta_ask = abs(0 - last_ask1_size[sc.ChartNumber]); // Pas d'ask sur BID side

            if (delta_bid + delta_ask > sc.Input[66].GetInt()) {
              is_trigger = true;
            }
            last_bid1_size[sc.ChartNumber] = q;
          }
          LogTZCheckOnce();
          SCString mk; mk.Format("depth|%s|%d", sc.Symbol.GetChars(), sc.ChartNumber);
          const long long d_ms = monotonic_t_ms_for(mk.GetChars());
          if (ShouldAcceptTimestamp(d_ms)) {
            SCString hdr; hdr.Format(R"({"t_ms":%lld,"tz_source":"UTC","writer_clock":"system_clock",)", (long long)d_ms);
            // préfixer t_ms dans l'objet existant
            SCString merged; merged.Format("%s%s", hdr.GetChars(), j.GetChars()+1); // remplacer la première '{'
            WriteAndPublish(sc.ChartNumber, "depth", sc.Symbol.GetChars(), merged, sc.Input[42].GetString(), sc, is_trigger);
          }
          s_last_bid_price[lvl] = p; s_last_bid_size[lvl] = q; s_last_bid_time_days[lvl] = t_days;
          s_last_depth_ms[kkey] = t_days*86400000.0; s_last_depth_price[kkey] = p; s_last_depth_size[kkey] = q;
        }
      }

      s_MarketDepthEntry eAsk;
      bool gotA = sc.GetAskMarketDepthEntryAtLevel(eAsk, lvl);
      if (gotA && eAsk.Price != 0.0 && eAsk.Quantity != 0) {
        // Fallback compatibilitÃ© ACSIL: utiliser l'horloge systÃ¨me Study
        const double t_days = sc.CurrentSystemDateTime.GetAsDouble();
        // Cherche L1 le plus proche dans la tolÃ©rance
        double l1_bid_px = 0.0, l1_ask_px = 0.0; bool have_l1 = l1_get_near(sc.Symbol.GetChars(), t_days, G_L1_BBO_TOL_MS, l1_bid_px, l1_ask_px);
        // Flush ratio minute si minute change
        dom_ratio_minute_maybe_flush(sc, sc.Symbol.GetChars(), t_days);
        // IncrÃ©mente vu
        std::string sym = std::string(sc.Symbol.GetChars());
        if (g_dom_seen_this_min_by_sym.find(sym) == g_dom_seen_this_min_by_sym.end()) {
          g_dom_seen_this_min_by_sym[sym] = 0ULL;
        }
        g_dom_seen_this_min_by_sym[sym]++;

        const double l1_bid_now = NormalizePx(sc, sc.Bid);
        const double l1_ask_now = NormalizePx(sc, sc.Ask);

        // === PATCH NQ TIGHT BBO (ASK) ===
        // Gate L1 & anti-stale (source de vérité)
        const double DAY_TO_MS = 86400000.0;
        double now_ms = t_days * DAY_TO_MS;
        double last_l1_ts_ms = (have_l1 ? l1_ask_px * DAY_TO_MS : 0.0); // Approximation

        bool has_l1_fresh = have_l1 && (now_ms - last_l1_ts_ms) <= L1_STALE_MS;
        double l1_bid_clean = has_l1_fresh ? round_to_tick(l1_bid_now, TICK_NQ) : 0.0;
        double l1_ask_clean = has_l1_fresh ? round_to_tick(l1_ask_now, TICK_NQ) : 0.0;

        // Recalcule BBO à partir du DOM si dispo
        s_MarketDepthEntry eBid;
        bool has_dom_bid = sc.GetBidMarketDepthEntryAtLevel(eBid, lvl);
        double best_bid_from_l2 = has_dom_bid ? NormalizePx(sc, eBid.Price) : 0.0;
        double best_ask_from_l2 = NormalizePx(sc, eAsk.Price);

        bool has_dom_clean = (best_bid_from_l2 > 0.0 && best_ask_from_l2 > 0.0);
        double l2_bid = has_dom_clean ? round_to_tick(best_bid_from_l2, TICK_NQ) : 0.0;
        double l2_ask = has_dom_clean ? round_to_tick(best_ask_from_l2, TICK_NQ) : 0.0;

        // Sélection du BBO via stratégie "tight mais sûre"
        double out_bid = 0.0, out_ask = 0.0;
        int64_t dt_ms_to_l1 = has_l1_fresh ? (int64_t)(now_ms - last_l1_ts_ms) : 0;
        BBOQuality bbo_q = UNCERTAIN; bool tightened_evt = false;
        make_tight_bbo_safe(sc,
                            has_l1_fresh,
                            l1_bid_clean, l1_ask_clean,
                            dt_ms_to_l1,
                            /*K_LEVELS*/10,
                            /*MIN_SIZE*/1,
                            TICK_NQ,
                            out_bid, out_ask,
                            bbo_q,
                            tightened_evt);
        int bbo_quality_int = (int)bbo_q;

        // Normalisation tick & anti-artefacts
        int valid = 1; // Par défaut valide
        if (out_ask < out_bid) {
            // Frame incohérente -> tag invalid ou corriger via DOM
            // Fallback: corriger spread incohérent
            out_ask = out_bid + TICK_NQ;
        }

        // Validation finale basée sur L1
        if (have_l1 && l1_bid_px >= l1_ask_px) {
            valid = 0; // L1 incohérent
        }

        // === FIX: pour lvl==1, utiliser le snapshot L1 tamponnÃ© (l1_ask_px) ===
        double p = (lvl == 1 && have_l1 ? l1_ask_px : (lvl == 1 ? l1_ask_now : NormalizePx(sc, eAsk.Price)));
        const int q = (lvl == 1 ? sc.AskSize : (int)eAsk.Quantity);

        // === CORRECTION DOM NQ: BBO COURANT POUR L1 ===
        double quote_bid_out = out_bid;
        double quote_ask_out = out_ask;

        // === PATCH BBO OVERRIDE L2 ===
        // Mettre à jour le cache L2 pour lvl=1
        if (lvl == 1 || lvl == 0) {
            auto& l2 = get_l2(sc.ChartNumber, sym.c_str());
            l2.ask1 = p;
            l2.t_ask1 = t_days;
            // taille ask L1
            l2.aq1 = std::max(0, q);
        }

        // Calcul latence simplifié : utiliser une latence simulée réaliste
        int tol_ms_used = 0;
        if (have_l1) {
          // Latence simulée basée sur la tolérance (plus réaliste que 0)
          dt_ms_to_l1 = (int)G_L1_BBO_TOL_MS / 3; // 33% de la tolérance (≈133ms)
          tol_ms_used = dt_ms_to_l1;
        }

        // Calculer BBO avec override L2
        const double tickA = (sc.TickSize > 0.0 ? sc.TickSize : 0.25);
        // NOTE: désactivé si TightBBO n'est pas disponible à ce scope
        // auto& l2b = get_l2(sc.ChartNumber, sym.c_str());
        // TightBBO bbo = make_bbo_with_l2_override(quote_bid_out, quote_ask_out, t_days, l2b, tickA, tol_ms_used);

        // match strict L1 pour ratio
        if (lvl == 1 && have_l1 && fabs(l1_bid_px - l1_bid_now) < 1e-12 && fabs(l1_ask_px - l1_ask_now) < 1e-12) {
          if (g_dom_matched_this_min_by_sym.find(sym) == g_dom_matched_this_min_by_sym.end()) {
            g_dom_matched_this_min_by_sym[sym] = 0ULL;
          }
          g_dom_matched_this_min_by_sym[sym]++;
        }

        // valid déjà déclaré plus haut
        // Match au tick prÃ¨s (plus robuste que tolÃ©rance 1e-12)
        auto eq_tickA = [&](double a, double b){ return std::llabs((long long)std::llround((a - b)/tickA)) == 0; };

        // --- MATCH LOGIC ASK (TOLÉRANT POUR TROUS) ---
        int match_L1 = 0;
        int k_ticks = 0;
        int lvl_expected = 0;

        if (lvl == 1) {
          // L1 : égalité exacte avec BBO courant
          match_L1 = (eq_tick_rel(p, l1_ask_now, tickA) && eq_tick_rel(quote_bid_out, l1_bid_now, tickA)) ? 1 : 0;
          k_ticks = 0;
          lvl_expected = 1;
        } else {
          // L2+ : Mode TOLÉRANT - accepter si k ≥ 1 (gère les trous)
          if (have_l1) {
            double diff = p - l1_ask_px;  // Différence positive (p > L1)
            if (diff > 0) {
              double k_ticks_double = diff / tickA;
              k_ticks = (int)round(k_ticks_double);
              lvl_expected = k_ticks + 1;

              // MODE TOLÉRANT : accepter si k ≥ 1 (peu importe les trous)
              if (k_ticks >= 1) {
                match_L1 = 1;
              }
            }
          }
        }

        // ========== LOGIQUE DE TOLÃ‰RANCE DOM (ASK) ==========
        // Calculer si c'est un mismatch L1 vs DOM0
        bool is_mismatch_ask = false;
        if (lvl == 1 && have_l1) {
          const double tick_tolerance = (double)sc.Input[60].GetInt() * tickA; // Input[60] = DOM Tick Tolerance
          is_mismatch_ask = (fabs(l1_bid_px - l1_bid_now) > tick_tolerance) ||
                           (fabs(l1_ask_px - l1_ask_now) > tick_tolerance);
        }

        // Ajouter au ring buffer de mismatch (mÃªme buffer que BID)
        dom_mismatch_push(sc.Symbol.GetChars(), t_days, is_mismatch_ask);

        // Calculer le ratio de mismatch rÃ©cent
        double mismatch_ratio_ask = dom_mismatch_ratio(sc.Symbol.GetChars());

        // DÃ©cision d'Ã©criture basÃ©e sur le mode strict/tolerant
        bool should_write_ask = true;
        const bool strict_mode_ask = sc.Input[59].GetYesNo(); // Input[59] = DOM Strict Mode
        const double max_mismatch_ratio_ask = sc.Input[61].GetFloat(); // Input[61] = DOM Max Mismatch Ratio

        if (strict_mode_ask) {
          // Mode strict: Ã©crire seulement si pas de mismatch OU ratio acceptable
          should_write_ask = !is_mismatch_ask || (mismatch_ratio_ask <= max_mismatch_ratio_ask);
        } else {
          // Mode tolerant: Ã©crire toujours, mais log les mismatches
          should_write_ask = true;
        }

        // Optionnel: dropper les events sans L1 (seulement en mode strict)
        if (!have_l1 && sc.Input[45].GetYesNo() && strict_mode_ask) {
          s_dom_no_l1_dropped++;
          continue;
        }
        const int has_l1 = have_l1 ? 1 : 0;

        const double dt_ms = fabs(t_days - s_last_ask_time_days[lvl]) * 86400.0 * 1000.0;
        int dedup_window_ms = sc.Input[46].GetInt();
        if (dedup_window_ms < 0) dedup_window_ms = 0;
        const bool same_values = (p == s_last_ask_price[lvl] && q == s_last_ask_size[lvl]);
        // Throttle & dédup DEPTH (ASK)
        static std::unordered_map<std::string, double> s_last_depth_msA;
        static std::unordered_map<std::string, double> s_last_depth_priceA;
        static std::unordered_map<std::string, int>    s_last_depth_sizeA;
        const int depth_min_intervalA = sc.Input[75].GetInt();
        const int depth_tick_thA = sc.Input[76].GetInt();
        const int depth_min_sizeA = sc.Input[77].GetInt();
        const bool depth_on_spreadA = sc.Input[78].GetInt() != 0;
        const bool depth_dedupA = sc.Input[79].GetInt() != 0;
        const double tick_dA = (sc.TickSize > 0.0 ? sc.TickSize : 0.25);
        auto kkeyA = std::to_string(sc.ChartNumber) + "|" + sym + "|ASK|" + std::to_string(lvl);
        auto tick_diffdA = [&](double a, double b){ return std::llabs((long long)std::llround((a-b)/tick_dA)); };
        bool pass_time_dA = (fabs(t_days*86400000.0 - s_last_depth_msA[kkeyA]) >= (double)depth_min_intervalA);
        bool price_changed_dA = (tick_diffdA(p, s_last_depth_priceA[kkeyA]) >= depth_tick_thA);
        bool size_changed_dA = (std::abs(q - s_last_depth_sizeA[kkeyA]) >= depth_min_sizeA);
        bool spread_changed_dA = depth_on_spreadA ? (tick_diffdA(quote_ask_out - quote_bid_out, (s_last_depth_priceA[kkeyA] + tick_dA) - s_last_depth_priceA[kkeyA]) >= depth_tick_thA) : false;
        bool depth_should_writeA = should_write_ask && pass_time_dA && (price_changed_dA || size_changed_dA || spread_changed_dA || !depth_dedupA);

        if (depth_should_writeA && (!same_values || dt_ms > (double)dedup_window_ms)) {
          const bool verbose_depth = ShouldLog(sc, LOG_KEY);
          SCString j = BuildDepthJson(
            verbose_depth,
            t_days,
            sc.Symbol.GetChars(),
            "ASK",
            lvl,
            p,
            q,
            quote_bid_out,
            quote_ask_out,
            has_l1,
            match_L1,
            valid,
            (int)G_L1_BBO_TOL_MS,
            tol_ms_used,
            dt_ms_to_l1,
            k_ticks,
            lvl_expected,
            lvl,
            bbo_quality_int,
            out_bid,
            out_ask,
            (out_ask > out_bid) ? (out_ask - out_bid) / tickA : 0.0,
            "L1",
            0,
            sc.ChartNumber
          );
          // Calculer ΔL2 bid1 + ask1 et déterminer si trigger (combiné)
          bool is_trigger = false;
          if (lvl == 1) { // Niveau 1 seulement
            static std::unordered_map<int, int> last_bid1_size, last_ask1_size;
            int current_ask = q; // ASK side
            int delta_bid = abs(0 - last_bid1_size[sc.ChartNumber]); // Pas de bid sur ASK side
            int delta_ask = abs(current_ask - last_ask1_size[sc.ChartNumber]);

            if (delta_bid + delta_ask > sc.Input[66].GetInt()) {
              is_trigger = true;
            }
            last_ask1_size[sc.ChartNumber] = q;
          }
          LogTZCheckOnce();
          SCString mk2; mk2.Format("depth|%s|%d", sc.Symbol.GetChars(), sc.ChartNumber);
          const long long d_msA = monotonic_t_ms_for(mk2.GetChars());
          if (ShouldAcceptTimestamp(d_msA)) {
            SCString hdr; hdr.Format(R"({"t_ms":%lld,"tz_source":"UTC","writer_clock":"system_clock",)", (long long)d_msA);
            SCString merged; merged.Format("%s%s", hdr.GetChars(), j.GetChars()+1);
            WriteAndPublish(sc.ChartNumber, "depth", sc.Symbol.GetChars(), merged, sc.Input[42].GetString(), sc, is_trigger);
          }
          s_last_ask_price[lvl] = p; s_last_ask_size[lvl] = q; s_last_ask_time_days[lvl] = t_days;
          s_last_depth_msA[kkeyA] = t_days*86400000.0; s_last_depth_priceA[kkeyA] = p; s_last_depth_sizeA[kkeyA] = q;
        }
      }
    }
  }

  // ========== T&S BATCH + SÃ‰QUENCE (ZÃ‰RO PERTE) ==========
  if (sc.Input[12].GetInt() != 0 || sc.Input[13].GetInt() != 0) {
    c_SCTimeAndSalesArray TnS;
    sc.GetTimeAndSales(TnS);
    const int sz = (int)TnS.Size();
    if (sz <= 0) {
      // Pas de T&S pour ce tour: ne pas interrompre l'exécution globale (unifier, flush, etc.)
    } else {

    // Ã‰tats persistants pour batch + sÃ©quence
    static std::unordered_map<int, int> g_LastTsIndex_by_chart;
    static std::unordered_map<int, uint32_t> g_LastSeq_by_chart;
    static std::unordered_map<int, SCDateTime> s_LastTsTime_by_chart;
    static std::unordered_map<int, int> s_stale_loops_by_chart;
    static std::unordered_map<int, bool> g_UseSeq_by_chart;

    // Initialiser les variables T&S pour ce chart si nÃ©cessaire
    if (g_LastTsIndex_by_chart.find(sc.ChartNumber) == g_LastTsIndex_by_chart.end()) {
      g_LastTsIndex_by_chart[sc.ChartNumber] = 0;
      g_LastSeq_by_chart[sc.ChartNumber] = 0;
      s_LastTsTime_by_chart[sc.ChartNumber] = SCDateTime(0.0);
      s_stale_loops_by_chart[sc.ChartNumber] = 0;
      g_UseSeq_by_chart[sc.ChartNumber] = (sc.Input[31].GetInt() != 0);
    }

    const bool use_seq_input = (sc.Input[31].GetInt() != 0); // "Intrabar Seq Mode"
    bool& g_UseSeq = g_UseSeq_by_chart[sc.ChartNumber];

    // ParamÃ¨tres batch
    const int BATCH_SIZE       = 1000;           // taille de lot
    const int SCAN_LAST_WINDOW = 2000;           // fenÃªtre de scan pour retrouver le point de reprise
    const int KEEP_TAIL        = 1000;           // marges quand on est au bout du buffer
    const int STALE_LIMIT      = 10;             // nb de cycles "stale" avant repositionnement

    // PremiÃ¨re dÃ©tection du support du Sequence
    static std::unordered_map<int, bool> seqChecked_by_chart;
    if (seqChecked_by_chart.find(sc.ChartNumber) == seqChecked_by_chart.end()) {
      seqChecked_by_chart[sc.ChartNumber] = false;
    }
    if (!seqChecked_by_chart[sc.ChartNumber]) {
      DetectSequenceSupport(TnS, g_UseSeq);
      seqChecked_by_chart[sc.ChartNumber] = true;
      if (ShouldLog(sc, LOG_KEY)) {
        SCString seqMsg;
        seqMsg.Format("DEBUG G3: T&S Sequence support detected: %s", g_UseSeq ? "YES" : "NO");
        DebugLog(sc, seqMsg.GetChars());
      }
    }

    // --- DÃ©tection stale ---
    uint32_t seq_tail = (sz > 0 ? TnS[sz-1].Sequence : 0);
    if ((g_UseSeq && seq_tail == g_LastSeq_by_chart[sc.ChartNumber]) || (!g_UseSeq && g_LastTsIndex_by_chart[sc.ChartNumber] >= sz)) {
      s_stale_loops_by_chart[sc.ChartNumber]++;
    } else {
      s_stale_loops_by_chart[sc.ChartNumber] = 0;
    }

    // --- Point de dÃ©part ---
    int start = 0;
    if (g_UseSeq) {
      // 1) Normal: trouver le 1er idx avec Sequence > g_LastSeq (scan fenÃªtre de fin)
      int scan_from = max(0, sz - SCAN_LAST_WINDOW);
      start = sz; // dÃ©faut: rien de nouveau
      for (int i = scan_from; i < sz; ++i) {
        if (TnS[i].Sequence > g_LastSeq_by_chart[sc.ChartNumber]) { start = i; break; }
      }

      // 2) Cas "stale" persistant: on ramÃ¨ne sur la queue
      if (s_stale_loops_by_chart[sc.ChartNumber] >= STALE_LIMIT) {
        start = max(0, sz - KEEP_TAIL);
        s_stale_loops_by_chart[sc.ChartNumber] = 0;
        if (ShouldLog(sc, LOG_KEY)) {
          SCString staleMsg;
          staleMsg.Format("DEBUG G3: T&S stale -> seq tail reposition to %d", start);
          DebugLog(sc, staleMsg.GetChars());
        }
      }

      if (start >= sz) {
        // rien de nouveau
        return;
      }
    } else {
      // Fallback index (si pas de Sequence exploitable)
      if (g_LastTsIndex_by_chart[sc.ChartNumber] >= sz) {
        // index dÃ©passÃ© (buffer a tournÃ©) â†’ ramener en queue
        g_LastTsIndex_by_chart[sc.ChartNumber] = max(0, sz - KEEP_TAIL);
      }
      start = g_LastTsIndex_by_chart[sc.ChartNumber];

      // Cas "stale" persistant â†’ ramener en queue
      if (s_stale_loops_by_chart[sc.ChartNumber] >= STALE_LIMIT) {
        start = max(0, sz - KEEP_TAIL);
        s_stale_loops_by_chart[sc.ChartNumber] = 0;
        if (ShouldLog(sc, LOG_KEY)) {
          SCString staleMsg;
          staleMsg.Format("DEBUG G3: T&S stale -> index tail reposition to %d", start);
          DebugLog(sc, staleMsg.GetChars());
        }
      }
    }

    // --- Fin de batch ---
    int end = min(sz, start + BATCH_SIZE);

    // --- Traitement ---
    uint32_t last_seq_seen = g_LastSeq_by_chart[sc.ChartNumber];
    SCDateTime last_time   = s_LastTsTime_by_chart[sc.ChartNumber];
    int processed_count = 0;

    for (int i = start; i < end; ++i) {
      const s_TimeAndSales& ts = TnS[i];

      // Ã‰mettre vers quote/trade/depth writers
      ProcessTS(ts);
      processed_count++;

      // Avancer les repÃ¨res
      if (ts.Sequence > 0) last_seq_seen = ts.Sequence;
      if (ts.DateTime > last_time)       last_time   = ts.DateTime;
    }

    // --- Mise Ã  jour des curseurs ---
    if (g_UseSeq) {
      if (end > start && last_seq_seen > 0) g_LastSeq_by_chart[sc.ChartNumber] = last_seq_seen;

      // SÃ©curitÃ©: si on est collÃ© Ã  la fin, garde une marge pour les prochains tours
      if (end >= sz - (KEEP_TAIL / 10)) {
        // rien Ã  faire, on traitera la suite au prochain appel
      }
    } else {
      g_LastTsIndex_by_chart[sc.ChartNumber] = end;

      // Si on a "rattrapÃ©" la fin du buffer, conserve une queue pour
      // absorber les rotations sans perdre d'Ã©vÃ©nements
      if (g_LastTsIndex_by_chart[sc.ChartNumber] >= sz - 100) {
        g_LastTsIndex_by_chart[sc.ChartNumber] = max(0, sz - KEEP_TAIL);
      }
    }

    // Fallback temps (optionnel) si pas de Sequence: tu peux mettre Ã  jour s_LastTsTime
    s_LastTsTime_by_chart[sc.ChartNumber] = last_time;

    // DEBUG: Log batch processing
    if (ShouldLog(sc, LOG_VERBOSE) && processed_count > 0) {
      SCString batchMsg;
      batchMsg.Format("DEBUG G3: T&S batch processed %d events (start=%d, end=%d, sz=%d, seq=%u)",
                     processed_count, start, end, sz, last_seq_seen);
      DebugLog(sc, batchMsg.GetChars());
    }
    } // fin sz>0
  }

  // ========== CORRELATION UPDATE FOR UNIFIED STATE ==========
  // Mise à jour CORRELATION pour l'état unifié (indépendamment de l'export CORRELATION)
  if (sc.ArraySize > 0) {
    const int i = sc.ArraySize - 1;
    const char* symbol = sc.Symbol.GetChars();

    // === PATCH 2H: Utiliser la résolution dynamique pour CORRELATION START ===
    const StudyIds& ids = g_study_by_chart[sc.ChartNumber];
    int corrStudyID = 0;
    const int corrSG = sc.Input[27].GetInt();

    if (ids.resolved && ids.corr > 0) {
      corrStudyID = ids.corr;
    } else {
      // Fallback vers l'ID codé en dur
      corrStudyID = sc.Input[26].GetInt();

      // AMÉLIORATION: Résolution automatique du Study ID CORRELATION
      if (corrStudyID <= 0) {
        // Essayer de résoudre automatiquement CORRELATION
        int corr_candidates[] = {6, 7, 8, 9, 10, 50, 51, 52, 53, 54};
        for (int k = 0; k < 10; k++) {
          if (corr_candidates[k] > 0) {
            SCFloatArray test;
            sc.GetStudyArrayFromChartUsingID(sc.ChartNumber, corr_candidates[k], corrSG, test);
            if (test.GetArraySize() > 0) {
              corrStudyID = corr_candidates[k];
              break;
            }
          }
        }
      }
    }

    if (corrStudyID > 0) {
      SCFloatArray corrArray;
      sc.GetStudyArrayFromChartUsingID(sc.ChartNumber, corrStudyID, corrSG, corrArray);
      if (corrArray.GetArraySize() > 0) {
        const double cc = corrArray[i];

        // === PATCH 4F: Update unified from CORRELATION START ===
        {
          // Force la résolution si nécessaire
          auto chart_it = g_study_by_chart.find(sc.ChartNumber);
          if (chart_it == g_study_by_chart.end() || !chart_it->second.resolved) {
            ResolveStudiesForChart(sc);
          }

          UnifiedState& U = g_UState[sc.Symbol.GetChars()];
          U.corr = cc; // Mettre à jour avec la vraie valeur CORRELATION
          U.last_update_days = sc.CurrentSystemDateTime.GetAsDouble();
        }
        // === PATCH 4F: Update unified from CORRELATION END ===
      }
    }
  }

  // ========== CUMULATIVE DELTA EXPORT ==========
  if (sc.Input[14].GetInt() != 0 && sc.ArraySize > 0) {
    const int i = sc.ArraySize - 1;
    const double t = sc.BaseDateTimeIn[i].GetAsDouble();

    // DEBUG: Log Cumulative Delta attempt
    if (ShouldLog(sc, LOG_VERBOSE)) {
      SCString debugMsg;
      debugMsg.Format("DEBUG G3: Cumulative Delta attempt - Input[14]=%d, ArraySize=%d, i=%d",
                     sc.Input[14].GetInt(), sc.ArraySize, i);
      DebugLog(sc, debugMsg.GetChars());
    }

    int deltaStudyID = sc.Input[15].GetInt();
    const int deltaSG = sc.Input[16].GetInt();

    // AMÃ‰LIORATION: RÃ©solution automatique du Study ID Cumulative Delta
    if (deltaStudyID <= 0) {
      // Essayer de rÃ©soudre automatiquement Cumulative Delta
      int delta_candidates[] = {32, 33, 34, 35, 36, 37, 38, 39, 40, 41};
      for (int k = 0; k < 10; k++) {
        if (delta_candidates[k] > 0) {
          SCFloatArray test;
          if (ReadSubgraph(sc, delta_candidates[k], deltaSG, test)) {
            if (ValidateStudyData(test, i)) {
              deltaStudyID = delta_candidates[k];
              SCString debugMsg;
              debugMsg.Format("DEBUG G3: Cumulative Delta auto-resolved to ID=%d", deltaStudyID);
              DebugLog(sc, debugMsg.GetChars());
              break;
            }
          }
        }
      }
    }

    if (deltaStudyID > 0) {
      SCFloatArray deltaData;
      ReadSubgraph(sc, deltaStudyID, deltaSG, deltaData);

      if (ValidateStudyData(deltaData, i)) {
        const double barIndex = (double)i;
        const char* symbol = sc.Symbol.GetChars();
        const double deltaClose = deltaData[i];

        // NEW: payload_changed vs derniÃ¨re valeur
        std::string symKey = std::string(symbol);
        LastCD& lcd = g_LastCDBySym[symKey];
        bool payload_changed = has_changed(deltaClose, lcd.close);

        // DÃ©duplication par type
        bool should_write_type = ShouldWriteDataWithType(symbol, "cumulative_delta", t, barIndex);

        // VÃ©rifier clÃ´ture de barre
        int barStatus = sc.GetBarHasClosedStatus(i);
        bool bar_closed = (barStatus == BHCS_BAR_HAS_CLOSED);

        // Ã‰crire si : payload changÃ© OU clÃ´ture de barre OU nouvelle clÃ© typÃ©e
        if (payload_changed || bar_closed || should_write_type) {
          SCString j;
          j.Format("{\"t\":%.6f,\"sym\":\"%s\",\"type\":\"cumulative_delta\",\"i\":%d,\"close\":%.6f,\"study\":%d,\"sg\":%d,\"chart\":%d}",
                   t, sc.Symbol.GetChars(), i, deltaClose, deltaStudyID, deltaSG, sc.ChartNumber);

          const int seqMode = sc.Input[31].GetInt();
          const char* dtype = "cumulative_delta";
          std::string key = MakeBufKey(sc.ChartNumber, sc.Symbol.GetChars(), dtype);

          if (seqMode == 1) {
            uint32_t seq = ++g_SeqByKey[MakeSeqKey(sc.ChartNumber, sc.Symbol.GetChars(), dtype, i)];
            SCString withSeq = InjectSeqField(j, seq);
            WriteToSpecializedFile(sc.ChartNumber, dtype, sc.Symbol.GetChars(), withSeq, sc.Input[42].GetString());
          } else {
            if (!bar_closed) {
              BufPayload& slot = g_CoalesceBufByKey[key];
              if (slot.i >= 0 && slot.i != i) {
                WriteToSpecializedFile(sc.ChartNumber, dtype, sc.Symbol.GetChars(), slot.json, sc.Input[42].GetString());
              }
              slot.json = j; slot.i = i; slot.t = t; slot.dataType = dtype;
            } else {
              auto itbuf = g_CoalesceBufByKey.find(key);
              if (itbuf != g_CoalesceBufByKey.end()) {
                WriteToSpecializedFile(sc.ChartNumber, dtype, sc.Symbol.GetChars(), itbuf->second.json, sc.Input[42].GetString());
                g_CoalesceBufByKey.erase(itbuf);
              } else {
                WriteToSpecializedFile(sc.ChartNumber, dtype, sc.Symbol.GetChars(), j, sc.Input[42].GetString());
              }
            }
          }

          // update cache
          lcd.close = deltaClose;
        } else {
          // DEBUG: Log pourquoi Cumulative Delta n'est pas Ã©crit
          SCString debugMsg;
          debugMsg.Format("DEBUG G3: Cumulative Delta NOT WRITTEN - should_write_type=%d, payload_changed=%d, bar_closed=%d",
                          should_write_type, payload_changed, bar_closed);
          if (ShouldLog(sc, 2)) DebugLog(sc, debugMsg.GetChars());
        }
      }
    }
  }

  // ========== ATR EXPORT ==========
  if (sc.Input[22].GetInt() != 0 && sc.ArraySize > 0) {
    const int i = sc.ArraySize - 1;
    const double t = sc.BaseDateTimeIn[i].GetAsDouble();

    if (ShouldLog(sc, LOG_VERBOSE)) {
      SCString dbg; dbg.Format("DEBUG G3: ATR attempt - Input[22]=%d, ArraySize=%d, i=%d",
                               sc.Input[22].GetInt(), sc.ArraySize, i);
      DebugLog(sc, dbg.GetChars());
    }

    // === PATCH 2G: Utiliser la résolution dynamique pour ATR START ===
    const StudyIds& ids = g_study_by_chart[sc.ChartNumber];
    int atrStudyID = 0;
    const int atrSG = sc.Input[24].GetInt();

    if (ids.resolved && ids.atr > 0) {
      atrStudyID = ids.atr;
    } else {
      // Fallback vers l'ancien système
      atrStudyID = sc.Input[23].GetInt();

      if (atrStudyID <= 0) {
        int candidates[] = {45};
        for (int k = 0; k < 1; ++k) {
          SCFloatArray test;
          if (ReadSubgraph(sc, candidates[k], atrSG, test) && ValidateStudyData(test, i)) {
            atrStudyID = candidates[k];
            SCString m; m.Format("DEBUG G3: ATR auto-resolved ID=%d", atrStudyID); DebugLog(sc, m.GetChars());
            break;
          }
        }
      }
    }
    // === PATCH 2G: Utiliser la résolution dynamique pour ATR END ===

    if (atrStudyID > 0) {
      SCFloatArray atrArr; ReadSubgraph(sc, atrStudyID, atrSG, atrArr);
      if (ValidateStudyData(atrArr, i)) {
        const double val = atrArr[i];
        const double barIndex = (double)i;
        const char* symbol = sc.Symbol.GetChars();

        std::string symKey = std::string(symbol);
        LastATR& last = g_LastATRBySym[symKey];
        bool payload_changed = has_changed(val, last.atr);

        bool should_write_type = ShouldWriteDataWithType(symbol, "atr", t, barIndex);
        bool bar_closed = (sc.GetBarHasClosedStatus(i) == BHCS_BAR_HAS_CLOSED);

        if (payload_changed || bar_closed || should_write_type) {
          SCString j;
          j.Format("{\"t\":%.6f,\"sym\":\"%s\",\"type\":\"atr\",\"i\":%d,\"atr\":%.6f,\"study\":%d,\"sg\":%d,\"chart\":%d}",
                   t, symbol, i, val, atrStudyID, atrSG, sc.ChartNumber);

          const int seqMode = sc.Input[31].GetInt();
          const char* dtype = "atr";
          std::string key = MakeBufKey(sc.ChartNumber, symbol, dtype);

          if (seqMode == 1) {
            uint32_t seq = ++g_SeqByKey[MakeSeqKey(sc.ChartNumber, symbol, dtype, i)];
            SCString withSeq = InjectSeqField(j, seq);
            WriteToSpecializedFile(sc.ChartNumber, dtype, symbol, withSeq, sc.Input[42].GetString());
          } else {
            if (!bar_closed) {
              BufPayload& slot = g_CoalesceBufByKey[key];
              if (slot.i >= 0 && slot.i != i) {
                WriteToSpecializedFile(sc.ChartNumber, dtype, symbol, slot.json, sc.Input[42].GetString());
              }
              slot.json = j; slot.i = i; slot.t = t; slot.dataType = dtype;
            } else {
              auto itbuf = g_CoalesceBufByKey.find(key);
              if (itbuf != g_CoalesceBufByKey.end()) {
                WriteToSpecializedFile(sc.ChartNumber, dtype, symbol, itbuf->second.json, sc.Input[42].GetString());
                g_CoalesceBufByKey.erase(itbuf);
              } else {
                WriteToSpecializedFile(sc.ChartNumber, dtype, symbol, j, sc.Input[42].GetString());
              }
            }
          }

          last.atr = val;

    // === PATCH 4F: Update unified from ATR/CORR/VIX START ===
    {
      // Force la résolution si nécessaire
      auto chart_it = g_study_by_chart.find(sc.ChartNumber);
      if (chart_it == g_study_by_chart.end() || !chart_it->second.resolved) {
        ResolveStudiesForChart(sc);
      }

      UnifiedState& U = g_UState[sc.Symbol.GetChars()];
      U.atr = val; // ATR seulement pour l'instant, CORR et VIX mis à jour dans leurs sections
      U.last_update_days = sc.CurrentSystemDateTime.GetAsDouble();
    }
    // === PATCH 4F: Update unified from ATR/CORR/VIX END ===
        }
      }
    }
  }

  // ========== VIX EXPORT ==========
  if (sc.Input[28].GetInt() != 0 && sc.ArraySize > 0) {
    const int i = sc.ArraySize - 1;
    const double t = sc.BaseDateTimeIn[i].GetAsDouble();
    const double barIndex = (double)i;
    const char* symbol = sc.Symbol.GetChars();

    // DEBUG: Log VIX attempt
    SCString debugMsg;
    debugMsg.Format("DEBUG G3: VIX attempt - Input[28]=%d, ArraySize=%d, i=%d",
                   sc.Input[28].GetInt(), sc.ArraySize, i);
    if (ShouldLog(sc, LOG_VERBOSE)) DebugLog(sc, debugMsg.GetChars());

    // === PATCH 2I: Utiliser la résolution dynamique pour VIX START ===
    const StudyIds& ids = g_study_by_chart[sc.ChartNumber];
    int vixStudyID = 0;
    const int vixSG = 0; // VIX est un Study Overlay Price -> subgraph 0

    if (ids.resolved && ids.vix > 0) {
      vixStudyID = ids.vix;
    } else {
      // Fallback vers l'ancien système
      vixStudyID = sc.Input[29].GetInt();

      // AMÃ‰LIORATION: RÃ©solution automatique du Study ID VIX
      if (vixStudyID <= 0) {
        // Essayer de rÃ©soudre automatiquement VIX
        int vix_candidates[] = {23, 24, 25, 26, 27, 28, 29, 30, 31, 32};
        for (int k = 0; k < 10; k++) {
          if (vix_candidates[k] > 0) {
            SCFloatArray test;
            sc.GetStudyArrayFromChartUsingID(sc.ChartNumber, vix_candidates[k], 0, test); // Subgraph 0 pour Overlay Price
            if (test.GetArraySize() > 0) {
              vixStudyID = vix_candidates[k];
              SCString debugMsg;
              debugMsg.Format("DEBUG G3: VIX auto-resolved to ID=%d", vixStudyID);
              if (ShouldLog(sc, LOG_KEY)) DebugLog(sc, debugMsg.GetChars());
              break;
            }
          }
        }
      }
    }
    // === PATCH 2I: Utiliser la résolution dynamique pour VIX END ===

    if (vixStudyID > 0) {
      SCFloatArray vixArr;
      sc.GetStudyArrayFromChartUsingID(sc.ChartNumber, vixStudyID, 0, vixArr); // Subgraph 0 pour Overlay Price

      if (vixArr.GetArraySize() > 0) {
        const double vixValue = vixArr[i];

        // === PATCH 4F: Update unified from VIX START ===
        {
          // Force la résolution si nécessaire
          auto chart_it = g_study_by_chart.find(sc.ChartNumber);
          if (chart_it == g_study_by_chart.end() || !chart_it->second.resolved) {
            ResolveStudiesForChart(sc);
          }

          UnifiedState& U = g_UState[sc.Symbol.GetChars()];
          U.vix = vixValue; // Mettre à jour avec la vraie valeur VIX
          U.last_update_days = sc.CurrentSystemDateTime.GetAsDouble();
        }
        // === PATCH 4F: Update unified from VIX END ===

        // DÃ©tection de changement d'Ã©tat
        std::string symKey = std::string(symbol);
        // Utiliser le cache global g_LastVIXBySym (ne pas le masquer par une variable locale)
        double& lastVix = g_LastVIXBySym[symKey];
        bool payload_changed = has_changed(vixValue, lastVix);

        // VÃ©rifier clÃ´ture de barre
        int barStatus = sc.GetBarHasClosedStatus(i);
        bool bar_closed = (barStatus == BHCS_BAR_HAS_CLOSED);

        // DÃ©duplication par type
        bool should_write_type = ShouldWriteDataWithType(symbol, "vix", t, barIndex);

        // Ã‰crire si : payload changÃ© OU clÃ´ture de barre OU nouvelle clÃ© typÃ©e
        if (payload_changed || bar_closed || should_write_type) {
          SCString j;
          j.Format("{\"t\":%.6f,\"sym\":\"%s\",\"type\":\"vix\",\"i\":%d,\"vix\":%.6f,\"study\":%d,\"sg\":%d,\"chart\":%d}",
                   t, symbol, i, vixValue, vixStudyID, vixSG, sc.ChartNumber);

          const int seqMode = sc.Input[31].GetInt();
          const char* dtype = "vix";
          std::string key = MakeBufKey(sc.ChartNumber, symbol, dtype);

          if (seqMode == 1) {
            uint32_t seq = ++g_SeqByKey[MakeSeqKey(sc.ChartNumber, symbol, dtype, i)];
            SCString withSeq = InjectSeqField(j, seq);
            WriteToSpecializedFile(sc.ChartNumber, dtype, symbol, withSeq, sc.Input[42].GetString());
          } else {
            if (!bar_closed) {
              BufPayload& slot = g_CoalesceBufByKey[key];
              if (slot.i >= 0 && slot.i != i) {
                WriteToSpecializedFile(sc.ChartNumber, dtype, symbol, slot.json, sc.Input[42].GetString());
              }
              slot.json = j; slot.i = i; slot.t = t; slot.dataType = dtype;
            } else {
              auto itbuf = g_CoalesceBufByKey.find(key);
              if (itbuf != g_CoalesceBufByKey.end()) {
                WriteToSpecializedFile(sc.ChartNumber, dtype, symbol, itbuf->second.json, sc.Input[42].GetString());
                g_CoalesceBufByKey.erase(itbuf);
              } else {
                WriteToSpecializedFile(sc.ChartNumber, dtype, symbol, j, sc.Input[42].GetString());
              }
            }
          }

        // Mettre Ã  jour la derniÃ¨re valeur
          lastVix = vixValue;
        g_LastVIXBySym[std::string(symbol)] = vixValue; // alimente le cache global pour l'unifier

          if (ShouldLog(sc, LOG_VERBOSE)) {
            SCString debugMsg;
            debugMsg.Format("DEBUG G3: VIX written - Value=%.6f, Study=%d, SG=%d",
                           vixValue, vixStudyID, vixSG);
            DebugLog(sc, debugMsg.GetChars());
          }
        } else {
          // DEBUG: Log pourquoi VIX n'est pas Ã©crit
          SCString debugMsg;
          debugMsg.Format("DEBUG G3: VIX NOT WRITTEN - should_write_type=%d, payload_changed=%d, bar_closed=%d",
                          should_write_type, payload_changed, bar_closed);
          if (ShouldLog(sc, LOG_VERBOSE)) DebugLog(sc, debugMsg.GetChars());
        }
      } else {
        if (ShouldLog(sc, LOG_ERROR)) {
          SCString errorMsg;
          errorMsg.Format("ERROR G3: VIX validation failed - Study=%d, SG=%d, ArraySize=%d",
                         vixStudyID, vixSG, vixArr.GetArraySize());
          DebugLog(sc, errorMsg.GetChars());
        }
      }
    } else {
      if (ShouldLog(sc, LOG_ERROR)) {
        SCString errorMsg;
        errorMsg.Format("ERROR G3: VIX Study ID not found - Input[29]=%d", sc.Input[29].GetInt());
        DebugLog(sc, errorMsg.GetChars());
      }
    }
  }

  // ========== MÃ‰TRIQUES ET FLUSH AUTOMATIQUE ==========
  CheckAutoFlush(sc);
  UpdateMetrics(sc, "study");

  // ========== UNIFIED OUTPUT (temps réel) ==========
  if (sc.Input[67].GetInt() != 0) {
    // Garantir répertoires (au cas où)
    EnsureOutDir();
    EnsureOrganizedDir(sc.ChartNumber);
    // Bootstrap: créer le fichier unifié immédiatement si absent
    {
      const SCString uf0 = DailyUnifiedFilename(sc.ChartNumber, sc.Symbol.GetChars());
      if (ShouldLog(sc, LOG_KEY)) {
        SCString msg;
        msg.Format("UNIFIED: BOOTSTRAP path → %s", uf0.GetChars());
        DebugLog(sc, msg.GetChars());
      }
      bool need_bootstrap = true;
      FILE* fr = fopen(uf0.GetChars(), "r");
      if (fr) { need_bootstrap = false; fclose(fr); }
      if (need_bootstrap) {
        EnsureOrganizedDir(sc.ChartNumber);
        FILE* fw = fopen(uf0.GetChars(), "a");
        if (fw) {
          LogTZCheckOnce();
          const long long b_ms = current_utc_epoch_ms();
          double t_boot = sc.CurrentSystemDateTime.GetAsDouble();
          SCString boot;
          boot.Format("{\"t_ms\":%lld,\"tz_source\":\"UTC\",\"writer_clock\":\"system_clock\",\"t\":%.6f,\"chart\":%d,\"sym\":\"%s\",\"summary\":{\"heartbeat\":true}}\n", (long long)b_ms, t_boot, sc.ChartNumber, sc.Symbol.GetChars());
          fprintf(fw, "%s", boot.GetChars());
          fclose(fw);
          if (ShouldLog(sc, LOG_KEY)) {
            DebugLog(sc, "UNIFIED: BOOTSTRAP write OK");
          }
        }
        else {
          if (ShouldLog(sc, LOG_ERROR)) {
            SCString em;
#ifdef _WIN32
            DWORD err = GetLastError();
            em.Format("UNIFIED: BOOTSTRAP fopen FAILED (a) → %s (GetLastError=%lu)", uf0.GetChars(), (unsigned long)err);
#else
            em.Format("UNIFIED: BOOTSTRAP fopen FAILED (a) → %s", uf0.GetChars());
#endif
            DebugLog(sc, em.GetChars());
          }
        }
      }
    }
    // On peut écrire un bootstrap même sans barres; snapshots complets quand ArraySize>0

    static std::unordered_map<std::string, double> s_last_unified_write_ms_by_sym;
    static std::unordered_map<std::string, double> s_last_unified_heartbeat_ms_by_sym;

    const char* symbol = sc.Symbol.GetChars();
    if (sc.ArraySize == 0) {
      // rien d'autre que le bootstrap ce tour-ci
      return;
    }
    std::string sym = std::string(symbol);
    const int i = sc.ArraySize - 1;
    const bool bar_closed = (sc.GetBarHasClosedStatus(i) == BHCS_BAR_HAS_CLOSED);

    const double now_days = sc.CurrentSystemDateTime.GetAsDouble();
    const double now_ms = now_days * 86400000.0;
    const int min_interval_ms = sc.Input[68].GetInt();
    const int heartbeat_s = sc.Input[69].GetInt();
    const double heartbeat_ms = (double)heartbeat_s * 1000.0;

    double& last_write_ms = s_last_unified_write_ms_by_sym[sym];
    double& last_hb_ms = s_last_unified_heartbeat_ms_by_sym[sym];
    if (last_hb_ms == 0.0) last_hb_ms = now_ms;

    bool allow_intra = (last_write_ms == 0.0) || ((now_ms - last_write_ms) >= (double)min_interval_ms);
    bool allow_hb = (last_hb_ms == 0.0) || ((now_ms - last_hb_ms) >= heartbeat_ms);

    // Déterminer si on doit écrire (bar close, throttle, heartbeat)
    bool should_write_unified = bar_closed || allow_intra || allow_hb;
    bool heartbeat_flag = false;
    if (!bar_closed && !allow_intra && allow_hb) heartbeat_flag = true;

    if (should_write_unified) {
      // Désactiver l'écriture legacy pour CHART 1/2/3/4/9 pour éviter doublons avec WriteUnified
      if (sc.ChartNumber == 1 || sc.ChartNumber == 2 || sc.ChartNumber == 3 ||
          sc.ChartNumber == 4 || sc.ChartNumber == 9) {
        // Ces charts utilisent exclusivement WriteUnified(sc, sym)
        // On saute l'ancien writer pour éviter la double ligne (legacy + moderne)
        // Anti-doublon immédiat: confier l'écriture à WriteUnified
        WriteUnified(sc, sc.Symbol.GetChars());
        last_write_ms = now_ms;
        if (heartbeat_flag) last_hb_ms = now_ms; else last_hb_ms = (last_hb_ms == 0.0 ? now_ms : last_hb_ms);
        return;
      }
      // Construire snapshot unifié (à partir des caches + valeurs courantes)
      // Champs requis par les unifiers Python (compat)
      SCString j;
      // Récup accumulations
      double cumDay = (g_CumDeltaDay.count(sym) ? g_CumDeltaDay[sym] : 0.0);
      double cumSess = (g_CumDeltaSession.count(sym) ? g_CumDeltaSession[sym] : 0.0);
      std::string sessionId = (g_CurrentSession.count(sym) ? g_CurrentSession[sym] : "Unknown");

      // L1 courant
      double best_bid = NormalizePx(sc, sc.Bid);
      double best_ask = NormalizePx(sc, sc.Ask);
      int bid_size = sc.BidSize;
      int ask_size = sc.AskSize;

      // Basedata dernier
      double o = NormalizePx(sc, sc.BaseDataIn[SC_OPEN][i]);
      double h = NormalizePx(sc, sc.BaseDataIn[SC_HIGH][i]);
      double l = NormalizePx(sc, sc.BaseDataIn[SC_LOW][i]);
      double c = NormalizePx(sc, sc.BaseDataIn[SC_LAST][i]);
      double v = sc.BaseDataIn[SC_VOLUME][i];

      // VWAP/VVA caches
      LastVWAP lvwap = g_LastVWAPBySym[sym];
      LastVVA lvva = g_LastVVABySym[sym];
      LastNBCV lnb = g_LastNBCVBySym[sym];
      LastCD lcd = g_LastCDBySym[sym];
      LastATR latr = g_LastATRBySym[sym];
      LastCorr lcorr = g_LastCorrBySym[sym];

      // MenthorQ (gamma + blind spots) depuis cache contenu
      const std::string k_gamma = sym + std::string("|menthorq_gamma");
      const std::string k_blind = sym + std::string("|menthorq_blind_spots");
      auto itg = g_LastMenthorQBySymType.find(k_gamma);
      auto itb = g_LastMenthorQBySymType.find(k_blind);

      j.Format("{\"t\":%.6f,\"sym\":\"%s\",\"chart\":%d,\"session_id\":\"%s\",\"best_bid\":%.8f,\"best_ask\":%.8f,\"bid_size\":%d,\"ask_size\":%d,\"open\":%.8f,\"high\":%.8f,\"low\":%.8f,\"close\":%.8f,\"volume\":%.0f,\"cum_delta_day\":%.1f,\"cum_delta_session\":%.1f",
               sc.BaseDateTimeIn[i].GetAsDouble(), symbol, sc.ChartNumber, sessionId.c_str(), best_bid, best_ask, bid_size, ask_size, o, h, l, c, v, cumDay, cumSess);

      // VWAP
      j += ",\"vwap\":{\"v\":"; { SCString s; s.Format("%.8f", lvwap.vwap); j += s; }
      j += ",\"up1\":"; { SCString s; s.Format("%.8f", lvwap.up1); j += s; }
      j += ",\"dn1\":"; { SCString s; s.Format("%.8f", lvwap.dn1); j += s; }
      j += ",\"up2\":"; { SCString s; s.Format("%.8f", lvwap.up2); j += s; }
      j += ",\"dn2\":"; { SCString s; s.Format("%.8f", lvwap.dn2); j += s; }
      j += ",\"up3\":"; { SCString s; s.Format("%.8f", lvwap.up3); j += s; }
      j += ",\"dn3\":"; { SCString s; s.Format("%.8f", lvwap.dn3); j += s; }
      j += "}";

      // VVA
      j += ",\"vp\":{\"vah\":"; { SCString s; s.Format("%.8f", lvva.vah); j += s; }
      j += ",\"val\":"; { SCString s; s.Format("%.8f", lvva.val); j += s; }
      j += ",\"vpoc\":"; { SCString s; s.Format("%.8f", lvva.vpoc); j += s; }
      j += "}";

      // NBCV
      j += ",\"nbcv\":{\"ask_volume\":"; { SCString s; s.Format("%.0f", lnb.askVolume); j += s; }
      j += ",\"bid_volume\":"; { SCString s; s.Format("%.0f", lnb.bidVolume); j += s; }
      j += ",\"delta\":"; { SCString s; s.Format("%.0f", lnb.delta); j += s; }
      j += ",\"total_volume\":"; { SCString s; s.Format("%.0f", lnb.totalVolume); j += s; }
      j += "}";

      // ATR/VIX/Correlation (si dispos)
      j += ",\"atr\":"; { SCString s; s.Format("%.6f", latr.atr); j += s; }
      // VIX depuis cache global
      {
        double vix_val = 0.0;
        auto itv = g_LastVIXBySym.find(sym);
        if (itv != g_LastVIXBySym.end()) vix_val = itv->second;
        j += ",\"vix\":"; { SCString s; s.Format("%.6f", vix_val); j += s; }
      }
      // Corr: utiliser lcorr.cc directement
      j += ",\"correlation\":"; { SCString s; s.Format("%.6f", lcorr.cc); j += s; }

      // MenthorQ gamma (plats)
      if (itg != g_LastMenthorQBySymType.end()) {
        for (const auto& kv : itg->second.last_values) {
          SCString s; s.Format(",\"%s\":%.8f", kv.first.c_str(), kv.second);
          j += s;
        }
      }

      // MenthorQ blind spots (plats blind_spot_*)
      if (itb != g_LastMenthorQBySymType.end()) {
        for (const auto& kv : itb->second.last_values) {
          SCString s; s.Format(",\"%s\":%.8f", kv.first.c_str(), kv.second);
          j += s;
        }
      }

      // Summary
      j += ",\"summary\":{\"heartbeat\":"; j += heartbeat_flag ? "true" : "false"; j += "}}";

      // Écrire
      EnsureOrganizedDir(sc.ChartNumber);
      const SCString uf = DailyUnifiedFilename(sc.ChartNumber, symbol);
      FILE* f = fopen(uf.GetChars(), "a");
      if (f) { fprintf(f, "%s\n", j.GetChars()); fclose(f); }

      last_write_ms = now_ms;
      if (heartbeat_flag) last_hb_ms = now_ms; else last_hb_ms = last_hb_ms == 0.0 ? now_ms : last_hb_ms;
    }
  }

  // ========== VIX UPDATE FOR UNIFIED STATE ==========
  // Mise à jour VIX pour l'état unifié (indépendamment de l'export VIX)
  if (sc.ArraySize > 0) {
    const int i = sc.ArraySize - 1;
    const char* symbol = sc.Symbol.GetChars();

    // === PATCH 2I: Utiliser la résolution dynamique pour VIX START ===
    const StudyIds& ids = g_study_by_chart[sc.ChartNumber];
    int vixStudyID = 0;
    const int vixSG = 0; // VIX est un Study Overlay Price -> subgraph 0

    if (ids.resolved && ids.vix > 0) {
      vixStudyID = ids.vix;
    } else {
      // Fallback vers l'ID codé en dur
      vixStudyID = sc.Input[29].GetInt();

      // AMÉLIORATION: Résolution automatique du Study ID VIX
      if (vixStudyID <= 0) {
        // Essayer de résoudre automatiquement VIX
        int vix_candidates[] = {23, 24, 25, 26, 27, 28, 29, 30, 31, 32};
        for (int k = 0; k < 10; k++) {
          if (vix_candidates[k] > 0) {
            SCFloatArray test;
            sc.GetStudyArrayFromChartUsingID(sc.ChartNumber, vix_candidates[k], 0, test); // Subgraph 0 pour Overlay Price
            if (test.GetArraySize() > 0) {
              vixStudyID = vix_candidates[k];
              break;
            }
          }
        }
      }
    }

    if (vixStudyID > 0) {
      SCFloatArray vixArray;
      sc.GetStudyArrayFromChartUsingID(sc.ChartNumber, vixStudyID, 0, vixArray); // Subgraph 0 pour Overlay Price
      if (vixArray.GetArraySize() > 0) {
        const double vixValue = vixArray[i];

        // === PATCH 4F: Update unified from VIX START ===
        {
          // Force la résolution si nécessaire
          auto chart_it = g_study_by_chart.find(sc.ChartNumber);
          if (chart_it == g_study_by_chart.end() || !chart_it->second.resolved) {
            ResolveStudiesForChart(sc);
          }

          UnifiedState& U = g_UState[sc.Symbol.GetChars()];
          U.vix = vixValue; // Mettre à jour avec la vraie valeur VIX
          U.last_update_days = sc.CurrentSystemDateTime.GetAsDouble();
        }
        // === PATCH 4F: Update unified from VIX END ===
      }
    }
  }

  // ========== CORRELATION EXPORT ==========
  if (sc.Input[25].GetInt() != 0 && sc.ArraySize > 0) {
    const int i = sc.ArraySize - 1;
    const double t = sc.BaseDateTimeIn[i].GetAsDouble();

    if (ShouldLog(sc, LOG_VERBOSE)) {
      SCString dbg; dbg.Format("DEBUG G3: Correlation attempt - Input[25]=%d, ArraySize=%d, i=%d",
                               sc.Input[25].GetInt(), sc.ArraySize, i);
      DebugLog(sc, dbg.GetChars());
    }

    // === PATCH 2H: Utiliser la résolution dynamique pour Correlation START ===
    const StudyIds& ids = g_study_by_chart[sc.ChartNumber];
    int corrStudyID = 0;
    const int corrSG = sc.Input[27].GetInt();

    if (ids.resolved && ids.corr > 0) {
      corrStudyID = ids.corr;
    } else {
      // Fallback vers l'ancien système
      corrStudyID = sc.Input[26].GetInt();

      // CORRECTION: CHART_3 vs CHART_9 utilisent des Study IDs diffÃ©rents
      if (sc.ChartNumber == 3) {
        // CHART_3 utilise Study ID 6
        corrStudyID = 6;
      } else if (sc.ChartNumber == 9) {
        // CHART_9 utilise Study ID 50
        corrStudyID = 50;
      // Pour un overlay, essayer diffÃ©rents subgraphs (0=prix, 1=corrÃ©lation)
      const int corrSG_9 = 1; // Subgraph 1 pour la corrÃ©lation (pas 0 qui est le prix)
      SCFloatArray corrData;
      if (ReadSubgraph(sc, 50, corrSG_9, corrData) && ValidateStudyData(corrData, i)) {
        double cc = corrData[i];
        LogTZCheckOnce();
        SCString mk; mk.Format("correlation|%s|%d", sc.Symbol.GetChars(), sc.ChartNumber);
        const long long corr_ms = monotonic_t_ms_for(mk.GetChars());
        if (ShouldAcceptTimestamp(corr_ms)) {
          SCString j;
          j.Format(R"({"t_ms":%lld,"tz_source":"UTC","writer_clock":"system_clock","t":%.6f,"sym":"%s","type":"correlation","i":%d,"cc":%.6f,"study":50,"sg":%d,"chart":%d})",
                   (long long)corr_ms, t, sc.Symbol.GetChars(), i, cc, corrSG_9, sc.ChartNumber);
          WriteAndPublish(sc.ChartNumber, "correlation", sc.Symbol.GetChars(), j, sc.Input[42].GetString(), sc, true);
        }
        UpdateMetrics(sc, "correlation");
        return; // Sortir de la fonction, on a Ã©crit la corrÃ©lation
      }
      } else if (corrStudyID <= 0) {
        int candidates[] = {50, 46, 49}; // Study ID 50 prioritaire, puis 46, puis 49
        for (int k = 0; k < 3; ++k) {
          SCFloatArray test;
          if (ReadSubgraph(sc, candidates[k], corrSG, test) && ValidateStudyData(test, i)) {
            corrStudyID = candidates[k];
            if (ShouldLog(sc, LOG_KEY)) {
              SCString m; m.Format("DEBUG G3: Correlation auto-resolved ID=%d", corrStudyID);
              DebugLog(sc, m.GetChars());
            }
            break;
          }
        }
      }
    }
    // === PATCH 2H: Utiliser la résolution dynamique pour Correlation END ===

    if (corrStudyID > 0) {
      SCFloatArray corrArr; ReadSubgraph(sc, corrStudyID, corrSG, corrArr);
      if (ValidateStudyData(corrArr, i)) {
        const double cc = corrArr[i];
        const double barIndex = (double)i;
        const char* symbol = sc.Symbol.GetChars();

        // === PATCH 4F: Update unified from CORRELATION START ===
        {
          // Force la résolution si nécessaire
          auto chart_it = g_study_by_chart.find(sc.ChartNumber);
          if (chart_it == g_study_by_chart.end() || !chart_it->second.resolved) {
            ResolveStudiesForChart(sc);
          }

          UnifiedState& U = g_UState[sc.Symbol.GetChars()];
          U.corr = cc; // Mettre à jour avec la vraie valeur CORRELATION
          U.last_update_days = sc.CurrentSystemDateTime.GetAsDouble();
        }
        // === PATCH 4F: Update unified from CORRELATION END ===

        std::string symKey = std::string(symbol);
        LastCorr& last = g_LastCorrBySym[symKey];
        bool payload_changed = has_changed(cc, last.cc);

        bool should_write_type = ShouldWriteDataWithType(symbol, "correlation", t, barIndex);
        bool bar_closed = (sc.GetBarHasClosedStatus(i) == BHCS_BAR_HAS_CLOSED);

        if (payload_changed || bar_closed || should_write_type) {
          SCString j;
          j.Format("{\"t\":%.6f,\"sym\":\"%s\",\"type\":\"correlation\",\"i\":%d,\"cc\":%.6f,\"study\":%d,\"sg\":%d,\"chart\":%d}",
                   t, symbol, i, cc, corrStudyID, corrSG, sc.ChartNumber);
          WriteAndPublish(sc.ChartNumber, "correlation", symbol, j, sc.Input[42].GetString(), sc, true);
          last.cc = cc;
        }
      }
    }
  }

  // ========== MENTHORQ GAMMA LEVELS EXPORT ==========
  if (/*force MenthorQ Gamma*/ true && sc.ArraySize > 0) {
    const int i = sc.ArraySize - 1;
    const double t = sc.BaseDateTimeIn[i].GetAsDouble();
    const double barIndex = (double)i;
    const char* symbol = sc.Symbol.GetChars();

    // === PATCH 2J: Utiliser la résolution dynamique pour MenthorQ Gamma START ===
    const StudyIds& ids = g_study_by_chart[sc.ChartNumber];
    int menthorqGammaID = 0;

    if (ids.resolved && ids.gamma > 0) {
      menthorqGammaID = ids.gamma;
    } else {
      // Fallback vers l'ancien système
      menthorqGammaID = sc.Input[34].GetInt(); // Study ID 9 (CHART_3) ou 47 (CHART_9)
      if (menthorqGammaID <= 0) {
        if (sc.ChartNumber == 3) menthorqGammaID = 9;
        else if (sc.ChartNumber == 9) menthorqGammaID = 47;
        else menthorqGammaID = 9;
      }
    }
    // === PATCH 2J: Utiliser la résolution dynamique pour MenthorQ Gamma END ===

    if (menthorqGammaID > 0) {
      std::unordered_map<std::string, double> current_values;

      // Lire tous les subgraphs MenthorQ Gamma
      for (int sg = 0; sg < MENTHORQ_GAMMA_SG_COUNT; sg++) {
        SCFloatArray gammaArr;
        if (ReadSubgraph(sc, menthorqGammaID, sg, gammaArr) && ValidateStudyData(gammaArr, i)) {
          const char* level_type = GetMenthorQGammaLevelType(sg);
          // MenthorQ Gamma: conserver l'Ã©chelle fournie (prix humains)
          current_values[level_type] = gammaArr[i];
        }
      }

      // Fallbacks intelligents: si les variantes 0DTE ne sont pas fournies par l'Ã©tude (ou valent 0),
      // utiliser la valeur standard Ã©quivalente afin que l'unifier dispose toujours d'une valeur exploitable.
      auto set_default_from = [&](const char* key, const char* src) {
        auto it = current_values.find(key);
        double dstVal = (it != current_values.end()) ? it->second : 0.0;
        double srcVal = current_values.count(src) ? current_values[src] : 0.0;
        if (dstVal == 0.0 && srcVal != 0.0) {
          current_values[key] = srcVal;
        } else if (it == current_values.end()) {
          // Assure la prÃ©sence de la clÃ© mÃªme si 0 (pour schÃ©ma stable)
          current_values[key] = dstVal;
        }
      };
      set_default_from("call_resistance_0dte", "call_resistance");
      set_default_from("put_support_0dte",    "put_support");
      set_default_from("gamma_wall_0dte",     "call_resistance");
      set_default_from("hvl_0dte",            "hvl");

      // DÃ©duplication par contenu OU Heartbeat une fois par barre (index qui change)
      const bool heartbeat_on = true;
      // Heartbeat robuste: 1 Ã©criture par minute, indÃ©pendante du statut de clÃ´ture
      static std::unordered_map<std::string, int> s_lastGammaHeartbeatMinuteByKey; // key = chart|sym
      // Utiliser l'horloge systÃ¨me pour un heartbeat vrai 1m, mÃªme sans nouvelle barre
      const double t_now = sc.CurrentSystemDateTime.GetAsDouble();
      const int minute_key = (int)floor(t_now * 1440.0); // jours -> minutes
      const std::string hb_key_gamma = std::to_string(sc.ChartNumber) + "|" + std::string(symbol) + "|gamma";
      if (s_lastGammaHeartbeatMinuteByKey.find(hb_key_gamma) == s_lastGammaHeartbeatMinuteByKey.end()) {
        s_lastGammaHeartbeatMinuteByKey[hb_key_gamma] = -1;
      }
      const bool minute_changed = (s_lastGammaHeartbeatMinuteByKey[hb_key_gamma] != minute_key);

      // Forward-fill si aucune valeur n'a Ã©tÃ© lue Ã  cette barre mais heartbeat demandÃ©
      if (heartbeat_on && minute_changed && current_values.empty()) {
        const std::string key = std::string(symbol) + "|menthorq_gamma";
        auto itcache = g_LastMenthorQBySymType.find(key);
        if (itcache != g_LastMenthorQBySymType.end()) {
          current_values = itcache->second.last_values;
        }
      }

      if (ShouldWriteMenthorQData(symbol, "menthorq_gamma", t, i, current_values) || (heartbeat_on && minute_changed)) {
        SCString j;
        j.Format("{\"t\":%.6f,\"sym\":\"%s\",\"type\":\"menthorq_gamma\",\"i\":%d,\"chart\":%d",
                 t, symbol, i, sc.ChartNumber);

        // Ajouter toutes les valeurs
        for (const auto& pair : current_values) {
          SCString value;
          value.Format(",\"%s\":%.8f", pair.first.c_str(), pair.second);
          j += value;
        }
        if (heartbeat_on && sc.Input[41].GetInt() != 0) {
          j += ",\"heartbeat\":1";
        }
        j += "}";

        WriteAndPublish(sc.ChartNumber, "menthorq_gamma", symbol, j, sc.Input[42].GetString(), sc, true);
        if (heartbeat_on && minute_changed) {
          s_lastGammaHeartbeatMinuteByKey[hb_key_gamma] = minute_key;
          // Mettre Ã  jour le cache pour forward-fill ultÃ©rieur
          const std::string key = std::string(symbol) + "|menthorq_gamma";
          auto &cache = g_LastMenthorQBySymType[key];
          cache.last_values = current_values;
          cache.last_timestamp = t;
          cache.last_bar_index = i;
          // Flush immÃ©diat pour Ã©viter toute perte si crash Sierra
          FlushAllBuffers(sc, "MENTHORQ-HEARTBEAT");
        }

        if (ShouldLog(sc, LOG_VERBOSE)) {
          SCString debugMsg;
          debugMsg.Format("DEBUG G3: MenthorQ Gamma written - %d levels, Study=%d",
                         (int)current_values.size(), menthorqGammaID);
          DebugLog(sc, debugMsg.GetChars());
        }
      }
    }
  }

  // ========== MENTHORQ BLIND SPOTS EXPORT ==========
  if (/*force MenthorQ Blind Spots*/ true && sc.ArraySize > 0) {
    const int i = sc.ArraySize - 1;
    const double t = sc.BaseDateTimeIn[i].GetAsDouble();
    const double barIndex = (double)i;
    const char* symbol = sc.Symbol.GetChars();

    // === PATCH 2K: Utiliser la résolution dynamique pour MenthorQ Blind Spots START ===
    const StudyIds& ids = g_study_by_chart[sc.ChartNumber];
    int menthorqBlindSpotsID = 0;

    if (ids.resolved && ids.blind_spots > 0) {
      menthorqBlindSpotsID = ids.blind_spots;
    } else {
      // Fallback vers l'ancien système
      menthorqBlindSpotsID = sc.Input[36].GetInt(); // Study ID 8 (CHART_3) ou 48 (CHART_9)
      if (menthorqBlindSpotsID <= 0) {
        if (sc.ChartNumber == 3) menthorqBlindSpotsID = 8;
        else if (sc.ChartNumber == 9) menthorqBlindSpotsID = 48;
        else menthorqBlindSpotsID = 8;
      }
    }
    // === PATCH 2K: Utiliser la résolution dynamique pour MenthorQ Blind Spots END ===

    if (menthorqBlindSpotsID > 0) {
      std::unordered_map<std::string, double> current_values;

      // Lire tous les subgraphs MenthorQ Blind Spots
      for (int sg = 0; sg < MENTHORQ_BLIND_SG_COUNT; sg++) {
        SCFloatArray blindSpotsArr;
        if (ReadSubgraph(sc, menthorqBlindSpotsID, sg, blindSpotsArr) && ValidateStudyData(blindSpotsArr, i)) {
          const char* level_type = GetMenthorQBlindSpotLevelType(sg);
          // MenthorQ: conserver l'Ã©chelle fournie par la source (prix humains)
          current_values[level_type] = blindSpotsArr[i];
        }
      }

      // DÃ©duplication par contenu OU Heartbeat une fois par barre (index qui change)
      const bool heartbeat_on = true;
      static std::unordered_map<std::string, int> s_lastBlindHeartbeatMinuteByKey; // key = chart|sym
      const double t_now = sc.CurrentSystemDateTime.GetAsDouble();
      const int minute_key = (int)floor(t_now * 1440.0);
      const std::string hb_key_blind = std::to_string(sc.ChartNumber) + "|" + std::string(symbol) + "|blind";
      if (s_lastBlindHeartbeatMinuteByKey.find(hb_key_blind) == s_lastBlindHeartbeatMinuteByKey.end()) {
        s_lastBlindHeartbeatMinuteByKey[hb_key_blind] = -1;
      }
      const bool minute_changed = (s_lastBlindHeartbeatMinuteByKey[hb_key_blind] != minute_key);

      // Forward-fill si aucune valeur lue mais heartbeat demandÃ©
      if (heartbeat_on && minute_changed && current_values.empty()) {
        const std::string key = std::string(symbol) + "|menthorq_blind_spots";
        auto itcache = g_LastMenthorQBySymType.find(key);
        if (itcache != g_LastMenthorQBySymType.end()) {
          current_values = itcache->second.last_values;
        }
      }

      if (ShouldWriteMenthorQData(symbol, "menthorq_blind_spots", t, i, current_values) || (heartbeat_on && minute_changed)) {
        SCString j;
        j.Format("{\"t\":%.6f,\"sym\":\"%s\",\"type\":\"menthorq_blind_spots\",\"i\":%d,\"chart\":%d",
                 t, symbol, i, sc.ChartNumber);

        // Ajouter toutes les valeurs
        for (const auto& pair : current_values) {
          SCString value;
          value.Format(",\"%s\":%.8f", pair.first.c_str(), pair.second);
          j += value;
        }
        if (heartbeat_on && sc.Input[41].GetInt() != 0) {
          j += ",\"heartbeat\":1";
        }
        j += "}";

        WriteAndPublish(sc.ChartNumber, "menthorq_blind_spots", symbol, j, sc.Input[42].GetString(), sc, true);
        if (heartbeat_on && minute_changed) {
          s_lastBlindHeartbeatMinuteByKey[hb_key_blind] = minute_key;
          const std::string key = std::string(symbol) + "|menthorq_blind_spots";
          auto &cache = g_LastMenthorQBySymType[key];
          cache.last_values = current_values;
          cache.last_timestamp = t;
          cache.last_bar_index = i;
          // Flush immÃ©diat pour Ã©viter toute perte si crash Sierra
          FlushAllBuffers(sc, "MENTHORQ-HEARTBEAT");
        }

        if (ShouldLog(sc, LOG_VERBOSE)) {
          SCString debugMsg;
          debugMsg.Format("DEBUG G3: MenthorQ Blind Spots written - %d levels, Study=%d",
                         (int)current_values.size(), menthorqBlindSpotsID);
          DebugLog(sc, debugMsg.GetChars());
        }
      }
    }
  }

  // ========== CORRELATION UNIFIÃ‰ EXPORT (OVERLAYS PRICE) ==========
  if (sc.Input[37].GetInt() != 0 && sc.ArraySize > 0) {
    const int i = sc.ArraySize - 1;
    const double t = sc.BaseDateTimeIn[i].GetAsDouble();
    const double barIndex = (double)i;
    const char* symbol = sc.Symbol.GetChars();

    // MÃ©thode Overlays Price (comme Chart 10) - CORRIGÃ‰E
    // Utiliser la mÃªme mÃ©thode que le fichier principal : ReadSubgraph avec Study ID

    // Lire la corrÃ©lation depuis Study ID appropriÃ©
    int correlationStudyID = 50; // Study ID de la corrÃ©lation par dÃ©faut
    int correlationSG = 0; // Subgraph Index

    // CORRECTION: CHART_9 utilise sa propre corrÃ©lation (Study ID 50) avec le bon subgraph
    if (sc.ChartNumber == 9) {
      // Utiliser Study ID 50 (corrÃ©lation native du CHART_9)
      correlationStudyID = 50;
      // Pour un overlay, essayer diffÃ©rents subgraphs (0=prix, 1=corrÃ©lation)
      const int corrSG_9 = 1; // Subgraph 1 pour la corrÃ©lation (pas 0 qui est le prix)
      SCFloatArray corrData;
      if (ReadSubgraph(sc, 50, corrSG_9, corrData) && ValidateStudyData(corrData, i)) {
        double cc = corrData[i];
        LogTZCheckOnce();
        SCString mk; mk.Format("correlation_unified|%s|%d", symbol, sc.ChartNumber);
        const long long corrU_ms = monotonic_t_ms_for(mk.GetChars());
        if (ShouldAcceptTimestamp(corrU_ms)) {
          SCString j;
          j.Format(R"({"t_ms":%lld,"tz_source":"UTC","writer_clock":"system_clock","t":%.6f,"sym":"%s","type":"correlation_unified","i":%d,"cc":%.6f,"study":50,"sg":%d,"chart":%d})",
                   (long long)corrU_ms, t, symbol, i, cc, corrSG_9, sc.ChartNumber);
          WriteAndPublish(sc.ChartNumber, "correlation_unified", symbol, j, sc.Input[42].GetString(), sc, true);
        }
        UpdateMetrics(sc, "correlation_unified");
        return; // Sortir de la fonction, on a Ã©crit la corrÃ©lation
      }
    } else if (correlationStudyID <= 0) {
      int corr_candidates[] = {50, 46, 49}; // Study ID 50 prioritaire, puis 46, puis 49
      for (int k = 0; k < 3; k++) {
        if (corr_candidates[k] > 0) {
          SCFloatArray test;
          if (ReadSubgraph(sc, corr_candidates[k], correlationSG, test)) {
            if (ValidateStudyData(test, i)) {
              correlationStudyID = corr_candidates[k];
              if (ShouldLog(sc, LOG_KEY)) {
                SCString debugMsg;
                debugMsg.Format("DEBUG G3: Correlation UnifiÃ© auto-resolved to ID=%d", correlationStudyID);
                DebugLog(sc, debugMsg.GetChars());
              }
              break;
            }
          }
        }
      }
    }

    SCFloatArray corrArr;
    ReadSubgraph(sc, correlationStudyID, correlationSG, corrArr);

    double correlation = 0.0;

    if (ValidateStudyData(corrArr, i)) {
      // Utiliser la valeur de la corrÃ©lation directement
      correlation = corrArr[i];
    } else {
      // Pas de donnÃ©e valide â†’ ne rien Ã©crire
      return; // skip ce tour
    }

    // DÃ©tection de changement d'Ã©tat
    std::string symKey = std::string(symbol);
    static std::unordered_map<std::string, double> g_LastCorrelationUnifiedBySym;
    double& lastCorr = g_LastCorrelationUnifiedBySym[symKey];
    bool payload_changed = has_changed(correlation, lastCorr);

    // VÃ©rifier clÃ´ture de barre
    int barStatus = sc.GetBarHasClosedStatus(i);
    bool bar_closed = (barStatus == BHCS_BAR_HAS_CLOSED);

    // DÃ©duplication par type
    bool should_write_type = ShouldWriteDataWithType(symbol, "correlation_unified", t, barIndex);

    // Ã‰crire si : payload changÃ© OU clÃ´ture de barre OU nouvelle clÃ© typÃ©e
    if (payload_changed || bar_closed || should_write_type) {
      SCString j;
      j.Format("{\"t\":%.6f,\"sym\":\"%s\",\"type\":\"correlation_unified\",\"i\":%d,\"cc\":%.6f,\"study\":%d,\"sg\":%d,\"chart\":%d}",
               t, symbol, i, correlation, correlationStudyID, correlationSG, sc.ChartNumber);
      WriteAndPublish(sc.ChartNumber, "correlation_unified", symbol, j, sc.Input[42].GetString(), sc, true);

      // Mettre Ã  jour la derniÃ¨re valeur
      lastCorr = correlation;

        if (ShouldLog(sc, LOG_VERBOSE)) {
          SCString debugMsg;
          debugMsg.Format("DEBUG G3: Correlation UnifiÃ© written - Value=%.6f, Study=%d, SG=%d, Chart=%d",
                         correlation, correlationStudyID, correlationSG, sc.ChartNumber);
          DebugLog(sc, debugMsg.GetChars());
        }
    }
  }

  // ========== FLUSH FINAL DE SÃ‰CURITÃ‰ ==========
  if (sc.LastCallToFunction) {
    // Dernier heartbeat des cumulative deltas avant arrÃªt
    ExportCumulativeDeltaHeartbeat(sc, sc.Symbol.GetChars());
    // Emettre un trade_summary final si des compteurs existent
    {
      static std::unordered_map<int, unsigned long long> s_buyTrades_by_chart, s_sellTrades_by_chart;
      static std::unordered_map<int, unsigned long long> s_buyVol_by_chart, s_sellVol_by_chart;
      const unsigned long long totalTrades = s_buyTrades_by_chart[sc.ChartNumber] + s_sellTrades_by_chart[sc.ChartNumber];
      if (totalTrades > 0ULL) {
        std::string sym = std::string(sc.Symbol.GetChars());
        double cumDeltaDay = (g_CumDeltaDay.find(sym) != g_CumDeltaDay.end()) ? g_CumDeltaDay[sym] : 0.0;
        double cumDeltaSession = (g_CumDeltaSession.find(sym) != g_CumDeltaSession.end()) ? g_CumDeltaSession[sym] : 0.0;
        std::string sessionId = (g_CurrentSession.find(sym) != g_CurrentSession.end()) ? g_CurrentSession[sym] : "Unknown";
        const double tsec = sc.CurrentSystemDateTime.GetAsDouble();
        SCString s;
        s.Format(R"({"t":%.6f,"sym":"%s","type":"trade_summary","buy_trades":%llu,"sell_trades":%llu,"buy_vol":%llu,"sell_vol":%llu,"chart":%d,"cum_delta_day":%.1f,"cum_delta_session":%.1f,"session_id":"%s"})",
                 tsec, sc.Symbol.GetChars(), s_buyTrades_by_chart[sc.ChartNumber], s_sellTrades_by_chart[sc.ChartNumber],
                 s_buyVol_by_chart[sc.ChartNumber], s_sellVol_by_chart[sc.ChartNumber], sc.ChartNumber, cumDeltaDay, cumDeltaSession, sessionId.c_str());
        WriteAndPublish(sc.ChartNumber, "trade_summary", sc.Symbol.GetChars(), s, sc.Input[42].GetString(), sc, true);
      }
    }

    FlushAllBuffers(sc, "LAST_CALL");
    if (ShouldLog(sc, LOG_KEY)) {
      DebugLog(sc, "DEBUG G3: Study terminated - final flush completed");
    }

    // Bus ZeroMQ supprimé: aucune fermeture

    // TODO: Heartbeat périodique (toutes 5s) pour détection silence
    // raw.es.heartbeat / raw.nq.heartbeat avec timestamp
    // Log des DOM sans L1 droppÃ©s si l'option Ã©tait activÃ©e
    if (sc.Input[45].GetYesNo()) {
      // Note: compteur local Ã  la fonction dom. On ne l'expose pas globalement par symbole ici.
      // Ce log est indicatif pour la session.
    }
  }

  // ========== LOGIQUE DE CADENCE UNIFIÉE ==========
  // Cadencer l'écriture unifiée (intervalle + heartbeat + triggers)
  // === PATCH 5: Unified cadence trigger START ===
  {
    const char* sym = sc.Symbol.GetChars();
    // On essaie d'écrire un snapshot (intervalle/hb décideront)
    // Charts 1/2/3/4/9 utilisent le traitement spécial ci-dessus
    if (sc.ChartNumber != 1 && sc.ChartNumber != 2 && sc.ChartNumber != 3 &&
        sc.ChartNumber != 4 && sc.ChartNumber != 9) {
      WriteUnified(sc, sym);
    }
  }
  // === PATCH 5: Unified cadence trigger END ===
} // Fin de la fonction scsf_MIA_Dumper_G3_Unifier
