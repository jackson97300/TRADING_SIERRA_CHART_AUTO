#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// MIA_StudyConfig.h - Chargement dynamique des Study IDs depuis JSON
// ═══════════════════════════════════════════════════════════════════════════════
// Date: 31/01/2026
// Parse study_mapping.json pour externaliser les hardcoded Study IDs
// Permet de modifier les IDs sans recompiler le bot
// ═══════════════════════════════════════════════════════════════════════════════

#include "MIA_Config.h"
#include <fstream>
#include <map>
#include <string>
#include <sstream>

// ═══════════════════════════════════════════════════════════════════════════════
// STRUCTURES
// ═══════════════════════════════════════════════════════════════════════════════

struct ChartStudyMapping {
    int chart_number;
    std::string description;
    std::map<std::string, int> studies;
};

// ═══════════════════════════════════════════════════════════════════════════════
// STUDY CONFIG SINGLETON
// ═══════════════════════════════════════════════════════════════════════════════

class StudyConfig {
private:
    std::map<std::string, ChartStudyMapping> m_mappings;
    bool m_loaded = false;
    std::string m_last_error;
    
    // Private constructor (Singleton)
    StudyConfig() {}
    
    // Interdire copie
    StudyConfig(const StudyConfig&) = delete;
    StudyConfig& operator=(const StudyConfig&) = delete;
    
    // Parser JSON simple (sans librairie externe)
    // Format attendu: "key": value  ou  "key": "value"
    std::string trim(const std::string& str) {
        size_t first = str.find_first_not_of(" \t\n\r\"");
        if (first == std::string::npos) return "";
        size_t last = str.find_last_not_of(" \t\n\r\",");
        return str.substr(first, (last - first + 1));
    }
    
    int parseIntValue(const std::string& line) {
        size_t colon = line.find(':');
        if (colon == std::string::npos) return -1;
        
        std::string value_str = line.substr(colon + 1);
        value_str = trim(value_str);
        
        return atoi(value_str.c_str());
    }
    
    std::string parseStringValue(const std::string& line) {
        size_t colon = line.find(':');
        if (colon == std::string::npos) return "";
        
        std::string value_str = line.substr(colon + 1);
        return trim(value_str);
    }
    
public:
    static StudyConfig& Instance() {
        static StudyConfig instance;
        return instance;
    }
    
    // ═══════════════════════════════════════════════════════════════════════════
    // CHARGEMENT DU FICHIER JSON
    // ═══════════════════════════════════════════════════════════════════════════
    
    bool LoadFromFile(const char* filepath) {
        std::ifstream file(filepath);
        if (!file.is_open()) {
            m_last_error = "Cannot open file: ";
            m_last_error += filepath;
            return false;
        }
        
        m_mappings.clear();
        
        std::string line;
        std::string current_chart_key;
        ChartStudyMapping current_mapping;
        bool in_studies_block = false;
        bool in_chart_block = false;
        
        while (std::getline(file, line)) {
            // Skip empty lines and comments
            if (line.empty() || line.find("//") == 0 || line.find("#") == 0) continue;
            if (line.find("_comment") != std::string::npos) continue;
            if (line.find("_version") != std::string::npos) continue;
            if (line.find("_updated") != std::string::npos) continue;
            if (line.find("_description") != std::string::npos) continue;
            
            // Detect chart key (e.g., "ES_FOOTPRINT": {)
            if (line.find("\"") != std::string::npos && line.find(": {") != std::string::npos) {
                // Save previous chart if any
                if (!current_chart_key.empty()) {
                    m_mappings[current_chart_key] = current_mapping;
                }
                
                // Extract chart key
                size_t first_quote = line.find("\"");
                size_t second_quote = line.find("\"", first_quote + 1);
                current_chart_key = line.substr(first_quote + 1, second_quote - first_quote - 1);
                
                current_mapping = ChartStudyMapping();
                current_mapping.chart_number = -1;
                in_chart_block = true;
                in_studies_block = false;
                continue;
            }
            
            // Detect chart_number
            if (in_chart_block && line.find("\"chart_number\"") != std::string::npos) {
                current_mapping.chart_number = parseIntValue(line);
                continue;
            }
            
            // Detect description
            if (in_chart_block && line.find("\"description\"") != std::string::npos) {
                current_mapping.description = parseStringValue(line);
                continue;
            }
            
            // Detect studies block
            if (in_chart_block && line.find("\"studies\"") != std::string::npos) {
                in_studies_block = true;
                continue;
            }
            
            // Parse study entry (e.g., "EDGE_BUY": 32)
            if (in_studies_block && line.find("\"") != std::string::npos && line.find(":") != std::string::npos) {
                // Extract study name
                size_t first_quote = line.find("\"");
                size_t second_quote = line.find("\"", first_quote + 1);
                if (first_quote != std::string::npos && second_quote != std::string::npos) {
                    std::string study_name = line.substr(first_quote + 1, second_quote - first_quote - 1);
                    int study_id = parseIntValue(line);
                    
                    if (study_id >= 0) {
                        current_mapping.studies[study_name] = study_id;
                    }
                }
                continue;
            }
            
            // End of studies block
            if (in_studies_block && line.find("}") != std::string::npos) {
                in_studies_block = false;
                continue;
            }
            
            // End of chart block
            if (in_chart_block && !in_studies_block && line.find("}") != std::string::npos) {
                // Save current chart
                if (!current_chart_key.empty()) {
                    m_mappings[current_chart_key] = current_mapping;
                    current_chart_key.clear();
                }
                in_chart_block = false;
                continue;
            }
        }
        
        // Save last chart if any
        if (!current_chart_key.empty()) {
            m_mappings[current_chart_key] = current_mapping;
        }
        
        file.close();
        m_loaded = true;
        return true;
    }
    
    // ═══════════════════════════════════════════════════════════════════════════
    // ACCÈS AUX DONNÉES
    // ═══════════════════════════════════════════════════════════════════════════
    
    int GetStudyID(const char* chart_key, const char* study_name) {
        // Auto-load on first access
        if (!m_loaded) {
            LoadFromFile("D:\\TRADING_SIERRA_CHART_AUTO\\CPP\\MIA_REFACTORED\\study_mapping.json");
        }
        
        auto it = m_mappings.find(chart_key);
        if (it == m_mappings.end()) {
            return -1;  // Chart key not found
        }
        
        auto& studies = it->second.studies;
        auto sit = studies.find(study_name);
        if (sit == studies.end()) {
            return -1;  // Study not found
        }
        
        return sit->second;
    }
    
    int GetChartNumber(const char* chart_key) {
        if (!m_loaded) {
            LoadFromFile("D:\\TRADING_SIERRA_CHART_AUTO\\CPP\\MIA_REFACTORED\\study_mapping.json");
        }
        
        auto it = m_mappings.find(chart_key);
        if (it == m_mappings.end()) {
            return -1;
        }
        
        return it->second.chart_number;
    }
    
    bool IsLoaded() const {
        return m_loaded;
    }
    
    const char* GetLastError() const {
        return m_last_error.c_str();
    }
    
    // Debug: Liste tous les mappings
    void PrintMappings() {
        if (!m_loaded) return;
        
        for (auto& chart_pair : m_mappings) {
            printf("[StudyConfig] %s (Chart %d):\n", 
                   chart_pair.first.c_str(), 
                   chart_pair.second.chart_number);
            
            for (auto& study_pair : chart_pair.second.studies) {
                printf("  - %s = %d\n", 
                       study_pair.first.c_str(), 
                       study_pair.second);
            }
        }
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// MACROS DE COMPATIBILITÉ
// ═══════════════════════════════════════════════════════════════════════════════

#define STUDY_ID(chart, name) StudyConfig::Instance().GetStudyID(chart, name)
#define CHART_NUM(chart) StudyConfig::Instance().GetChartNumber(chart)

// ═══════════════════════════════════════════════════════════════════════════════
// EXEMPLES D'UTILISATION
// ═══════════════════════════════════════════════════════════════════════════════
/*

// AVANT (hardcodé):
const int ES_FP_EDGE_BUY = 32;
sc.GetStudyArrayFromChartUsingID(chart_footprint, ES_FP_EDGE_BUY, 0, arr);

// APRÈS (depuis JSON):
int edge_buy_id = STUDY_ID("ES_FOOTPRINT", "EDGE_BUY");
if (edge_buy_id > 0) {
    sc.GetStudyArrayFromChartUsingID(chart_footprint, edge_buy_id, 0, arr);
} else {
    sc.AddMessageToLog("ERROR: EDGE_BUY study not found in config!", 1);
}

// Obtenir chart number depuis config:
int es_fp_chart = CHART_NUM("ES_FOOTPRINT");

// Debug: Afficher tous les mappings
StudyConfig::Instance().PrintMappings();

*/