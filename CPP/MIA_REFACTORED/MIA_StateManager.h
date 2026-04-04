#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// MIA_StateManager.h - Gestion thread-safe des états globaux
// ═══════════════════════════════════════════════════════════════════════════════
// Date: 31/01/2026
// Protection des variables globales avec mutex pour éviter les race conditions
// ═══════════════════════════════════════════════════════════════════════════════

#include "MIA_Config.h"

// ═══════════════════════════════════════════════════════════════════════════════
// DÉTECTION DE L'ENVIRONNEMENT DE COMPILATION
// ═══════════════════════════════════════════════════════════════════════════════
// Sierra Chart Remote Build ne supporte pas <mutex>
// On utilise une version compatible quand nécessaire

#if defined(_MSC_VER) && !defined(SIERRA_REMOTE_BUILD)
    // Visual Studio Local Build - Full C++11 support
    #define MIA_USE_STD_MUTEX 1
    #include <mutex>
    #include <functional>
#else
    // Sierra Chart Remote Build - No mutex support
    #define MIA_USE_STD_MUTEX 0
#endif

// ═══════════════════════════════════════════════════════════════════════════════
// STATE MANAGER SINGLETON
// ═══════════════════════════════════════════════════════════════════════════════

class StateManager {
private:
    // États par symbole (private, accès uniquement via méthodes)
    BotState m_es_state;
    BotState m_nq_state;
    DashboardData m_dashboard;
    
#if MIA_USE_STD_MUTEX
    // Mutex pour protection thread-safe (Local Build uniquement)
    std::mutex m_es_mutex;
    std::mutex m_nq_mutex;
    std::mutex m_dashboard_mutex;
#endif
    
    // Constructor privé (Singleton)
    StateManager() {
        // Initialisation par défaut
        memset(&m_es_state, 0, sizeof(BotState));
        memset(&m_nq_state, 0, sizeof(BotState));
        memset(&m_dashboard, 0, sizeof(DashboardData));
        
        m_es_state.enabled = true;
        m_nq_state.enabled = true;
        strcpy(m_es_state.waiting_for, "Signal");
        strcpy(m_nq_state.waiting_for, "Signal");
    }
    
    // Interdire copie et assignation
    StateManager(const StateManager&) = delete;
    StateManager& operator=(const StateManager&) = delete;
    
public:
    // Accès au singleton
    static StateManager& Instance() {
        static StateManager instance;
        return instance;
    }
    
    // ═══════════════════════════════════════════════════════════════════════════
    // ES STATE ACCESS
    // ═══════════════════════════════════════════════════════════════════════════
    
    // Lecture complète (retourne une copie)
    BotState GetESState() {
#if MIA_USE_STD_MUTEX
        std::lock_guard<std::mutex> lock(m_es_mutex);
#endif
        return m_es_state;
    }
    
    // Modification via callback (permet modifications atomiques multiples)
#if MIA_USE_STD_MUTEX
    void UpdateESState(const std::function<void(BotState&)>& updater) {
        std::lock_guard<std::mutex> lock(m_es_mutex);
        updater(m_es_state);
    }
#else
    template<typename F>
    void UpdateESState(F updater) {
        updater(m_es_state);
    }
#endif
    
    // Lecture d'un champ spécifique (plus rapide que copier tout)
    bool GetESInPosition() {
#if MIA_USE_STD_MUTEX
        std::lock_guard<std::mutex> lock(m_es_mutex);
#endif
        return m_es_state.in_position;
    }
    
    float GetESEntryPrice() {
#if MIA_USE_STD_MUTEX
        std::lock_guard<std::mutex> lock(m_es_mutex);
#endif
        return m_es_state.entry_price;
    }
    
    int GetESTradesToday() {
#if MIA_USE_STD_MUTEX
        std::lock_guard<std::mutex> lock(m_es_mutex);
#endif
        return m_es_state.trades_today;
    }
    
    float GetESPnLToday() {
#if MIA_USE_STD_MUTEX
        std::lock_guard<std::mutex> lock(m_es_mutex);
#endif
        return m_es_state.pnl_today;
    }
    
    // ═══════════════════════════════════════════════════════════════════════════
    // NQ STATE ACCESS
    // ═══════════════════════════════════════════════════════════════════════════
    
    BotState GetNQState() {
#if MIA_USE_STD_MUTEX
        std::lock_guard<std::mutex> lock(m_nq_mutex);
#endif
        return m_nq_state;
    }
    
#if MIA_USE_STD_MUTEX
    void UpdateNQState(const std::function<void(BotState&)>& updater) {
        std::lock_guard<std::mutex> lock(m_nq_mutex);
        updater(m_nq_state);
    }
#else
    template<typename F>
    void UpdateNQState(F updater) {
        updater(m_nq_state);
    }
#endif
    
    bool GetNQInPosition() {
#if MIA_USE_STD_MUTEX
        std::lock_guard<std::mutex> lock(m_nq_mutex);
#endif
        return m_nq_state.in_position;
    }
    
    float GetNQEntryPrice() {
#if MIA_USE_STD_MUTEX
        std::lock_guard<std::mutex> lock(m_nq_mutex);
#endif
        return m_nq_state.entry_price;
    }
    
    int GetNQTradesToday() {
#if MIA_USE_STD_MUTEX
        std::lock_guard<std::mutex> lock(m_nq_mutex);
#endif
        return m_nq_state.trades_today;
    }
    
    float GetNQPnLToday() {
#if MIA_USE_STD_MUTEX
        std::lock_guard<std::mutex> lock(m_nq_mutex);
#endif
        return m_nq_state.pnl_today;
    }
    
    // ═══════════════════════════════════════════════════════════════════════════
    // DASHBOARD ACCESS
    // ═══════════════════════════════════════════════════════════════════════════
    
    DashboardData GetDashboard() {
#if MIA_USE_STD_MUTEX
        std::lock_guard<std::mutex> lock(m_dashboard_mutex);
#endif
        return m_dashboard;
    }
    
#if MIA_USE_STD_MUTEX
    void UpdateDashboard(const std::function<void(DashboardData&)>& updater) {
        std::lock_guard<std::mutex> lock(m_dashboard_mutex);
        updater(m_dashboard);
    }
#else
    template<typename F>
    void UpdateDashboard(F updater) {
        updater(m_dashboard);
    }
#endif
    
    // ═══════════════════════════════════════════════════════════════════════════
    // RÉINITIALISATION (pour nouveau jour)
    // ═══════════════════════════════════════════════════════════════════════════
    
    void ResetDailyStats() {
#if MIA_USE_STD_MUTEX
        std::lock_guard<std::mutex> lock_es(m_es_mutex);
        std::lock_guard<std::mutex> lock_nq(m_nq_mutex);
        std::lock_guard<std::mutex> lock_dash(m_dashboard_mutex);
#endif
        
        // Reset ES
        m_es_state.trades_today = 0;
        m_es_state.wins_today = 0;
        m_es_state.losses_today = 0;
        m_es_state.pnl_today = 0.0f;
        m_es_state.best_trade = 0.0f;
        m_es_state.worst_trade = 0.0f;
        m_es_state.consecutive_losses = 0;
        
        // Reset NQ
        m_nq_state.trades_today = 0;
        m_nq_state.wins_today = 0;
        m_nq_state.losses_today = 0;
        m_nq_state.pnl_today = 0.0f;
        m_nq_state.best_trade = 0.0f;
        m_nq_state.worst_trade = 0.0f;
        m_nq_state.consecutive_losses = 0;
        
        // Reset Dashboard
        m_dashboard.signals_rejected_es = 0;
        m_dashboard.signals_rejected_nq = 0;
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// MACROS DE COMPATIBILITÉ - MIGRATION PROGRESSIVE
// ═══════════════════════════════════════════════════════════════════════════════
// Ces macros permettent de migrer progressivement le code existant
// sans tout casser d'un coup.

// Lecture d'état complet
#define GET_ES_STATE() StateManager::Instance().GetESState()
#define GET_NQ_STATE() StateManager::Instance().GetNQState()
#define GET_DASHBOARD() StateManager::Instance().GetDashboard()

// Modification d'état via callback
#define UPDATE_ES_STATE(updater) StateManager::Instance().UpdateESState(updater)
#define UPDATE_NQ_STATE(updater) StateManager::Instance().UpdateNQState(updater)
#define UPDATE_DASHBOARD(updater) StateManager::Instance().UpdateDashboard(updater)

// Réinitialisation quotidienne
#define RESET_DAILY_STATS() StateManager::Instance().ResetDailyStats()

// ═══════════════════════════════════════════════════════════════════════════════
// EXEMPLES D'UTILISATION
// ═══════════════════════════════════════════════════════════════════════════════
/*

// AVANT (accès direct - NON thread-safe):
g_es_state.in_position = true;
g_es_state.entry_price = 6100.0f;
g_es_state.trades_today++;

// APRÈS (thread-safe avec callback):
UPDATE_ES_STATE([&](BotState& state) {
    state.in_position = true;
    state.entry_price = 6100.0f;
    state.trades_today++;
});

// LECTURE SIMPLE:
BotState es = GET_ES_STATE();
if (es.in_position) {
    // ...
}

// LECTURE D'UN SEUL CHAMP (plus efficace):
if (StateManager::Instance().GetESInPosition()) {
    float entry = StateManager::Instance().GetESEntryPrice();
    // ...
}

// RESET QUOTIDIEN:
RESET_DAILY_STATS();

*/
