// =============================================================================
// TEST_Scan_All.cpp - Scanner COMPLET de tous les subgraphs
// AJOUTER SUR LE CHART À SCANNER - auto-détection!
// =============================================================================

#include "sierrachart.h"
#include <fstream>
#include <string>
#include <ctime>

SCDLLName("TEST_Scan_All")

SCSFExport scsf_TEST_Scan_All(SCStudyInterfaceRef sc) {
    SCInputRef Input_Path = sc.Input[0];
    SCInputRef Input_ForceRescan = sc.Input[1];

    if (sc.SetDefaults) {
        sc.GraphName = "TEST Scan All Subgraphs";
        sc.StudyDescription = "AJOUTER SUR LE CHART A SCANNER! Studies 1-60, Subgraphs 0-70";
        sc.AutoLoop = 0;
        sc.UpdateAlways = 1;

        Input_Path.Name = "Output Path";
        Input_Path.SetPathAndFileName("D:\\MIA_IA_system\\DATA_SIERRA_CHART\\TEST_FOOTPRINT\\");

        Input_ForceRescan.Name = "Force Rescan (0->1 to rescan)";
        Input_ForceRescan.SetInt(0);

        return;
    }

    // Reset si demande de rescan
    int& done = sc.GetPersistentInt(1);
    int& lastRescanValue = sc.GetPersistentInt(2);

    if (Input_ForceRescan.GetInt() != lastRescanValue) {
        lastRescanValue = Input_ForceRescan.GetInt();
        done = 0;  // Reset pour permettre un nouveau scan
    }

    if (done == 1) return;
    done = 1;

    // AUTO-DETECTION du chart
    int chartNum = sc.ChartNumber;

    // Paramètres fixes
    int studyStart = 1;
    int studyEnd = 60;

    // Timestamp
    time_t now = time(nullptr);
    struct tm* t = localtime(&now);
    char dateStr[20];
    strftime(dateStr, sizeof(dateStr), "%Y%m%d_%H%M%S", t);

    // Fichier de sortie
    std::string path = Input_Path.GetPathAndFileName();
    std::string filename = path + "scan_chart" + std::to_string(chartNum) + "_" + dateStr + ".txt";

    std::ofstream file(filename);
    if (!file.is_open()) {
        sc.AddMessageToLog("Cannot open output file!", 1);
        return;
    }

    file << "=== FULL SCAN CHART " << chartNum << " ===\n";
    file << "Scanning studies " << studyStart << " to " << studyEnd << "\n";
    file << "Scanning subgraphs 0 to 70\n\n";

    int totalFound = 0;

    // Scanner chaque étude
    for (int study = studyStart; study <= studyEnd; study++) {
        bool hasData = false;
        std::string studyData = "";

        // Scanner chaque subgraph
        for (int sg = 0; sg <= 70; sg++) {
            SCFloatArray arr;
            sc.GetStudyArrayFromChartUsingID(chartNum, study, sg, arr);

            if (arr.GetArraySize() > 0) {
                int lastIdx = arr.GetArraySize() - 1;
                float val = arr[lastIdx];

                // Valeur valide et non-nulle?
                if (val != 0 && val == val && val < 1e10 && val > -1e10) {
                    if (!hasData) {
                        studyData += "STUDY " + std::to_string(study) + ":\n";
                        hasData = true;
                    }

                    char valStr[50];
                    sprintf(valStr, "%.4f", val);
                    studyData += "  sg" + std::to_string(sg) + " = " + valStr + "\n";
                    totalFound++;
                }
            }
        }

        if (hasData) {
            file << studyData << "\n";
        }
    }

    file << "=== END SCAN ===\n";
    file << "Total non-zero values found: " << totalFound << "\n";
    file.close();

    SCString msg;
    msg.Format("SCAN DONE Chart %d: %d values found -> %s", chartNum, totalFound, filename.c_str());
    sc.AddMessageToLog(msg, 0);
}
