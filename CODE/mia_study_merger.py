"""
MIA Study Merger — Fusion de tous les chart_XX.json en un recueil unique
========================================================================
07/02/2026

USAGE:
    python mia_study_merger.py

ENTRÉE:  D:\TRADING_SIERRA_CHART_AUTO\STUDIES\chart_*.json
SORTIE:  D:\TRADING_SIERRA_CHART_AUTO\STUDIES\RECUEIL_COMPLET.json
         D:\TRADING_SIERRA_CHART_AUTO\STUDIES\RECUEIL_COMPLET.txt  (lisible)

Le recueil fusionne TOUTES les études de TOUS les charts :
  - Sans doublons (une étude apparaît une seule fois)
  - Avec la liste de TOUS les charts où elle est présente
  - Avec TOUS les subgraphs trouvés (union de tous les charts)
  - Trié par nom d'étude pour navigation facile
"""

import json
import os
import glob
from collections import defaultdict
from datetime import datetime
from pathlib import Path


STUDIES_DIR = r"D:\TRADING_SIERRA_CHART_AUTO\STUDIES"


def load_all_charts(studies_dir: str) -> list:
    """Charger tous les fichiers chart_XX.json."""
    pattern = os.path.join(studies_dir, "chart_*.json")
    files = sorted(glob.glob(pattern))
    
    charts = []
    for filepath in files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            charts.append(data)
            chart_num = data.get("chart_number", "?")
            n_studies = len(data.get("studies", []))
            print(f"  ✅ chart_{chart_num}.json : {n_studies} études")
        except Exception as e:
            print(f"  ❌ Erreur {filepath}: {e}")
    
    return charts


def merge_studies(charts: list) -> dict:
    """
    Fusionner toutes les études de tous les charts.
    
    Clé de dédoublication : nom de l'étude (study name).
    On fusionne les subgraphs de tous les charts.
    """
    
    # Structure : study_name → { info, charts, subgraphs }
    merged = {}
    
    # Index des charts
    chart_index = {}
    
    for chart_data in charts:
        chart_num = chart_data.get("chart_number", 0)
        chart_symbol = chart_data.get("chart_symbol", "")
        chart_index[chart_num] = chart_symbol
        
        for study in chart_data.get("studies", []):
            study_name = study.get("name", "").strip()
            short_name = study.get("short_name", "").strip()
            study_id = study.get("study_id", 0)
            study_idx = study.get("study_index", 0)
            
            # Clé = nom de l'étude (dédoublication)
            key = study_name if study_name else f"UNNAMED_ID{study_id}"
            
            if key not in merged:
                merged[key] = {
                    "name": study_name,
                    "short_name": short_name,
                    "study_ids": {},         # chart_num → study_id
                    "study_indexes": {},     # chart_num → study_index
                    "charts_present": [],    # liste des charts
                    "subgraphs": {},         # sg_index → { name, values_per_chart }
                }
            
            entry = merged[key]
            
            # Enregistrer l'ID et l'index pour ce chart
            entry["study_ids"][chart_num] = study_id
            entry["study_indexes"][chart_num] = study_idx
            
            if chart_num not in entry["charts_present"]:
                entry["charts_present"].append(chart_num)
            
            # Fusionner les subgraphs
            for sg in study.get("subgraphs", []):
                sg_idx = sg.get("sg_index", 0)
                sg_name = sg.get("sg_name", "")
                sg_value = sg.get("value", 0)
                sg_arr_size = sg.get("array_size", 0)
                
                sg_key = sg_idx
                
                if sg_key not in entry["subgraphs"]:
                    entry["subgraphs"][sg_key] = {
                        "sg_index": sg_idx,
                        "sg_name": sg_name,
                        "values_per_chart": {},
                        "array_sizes": {},
                    }
                
                sg_entry = entry["subgraphs"][sg_key]
                sg_entry["values_per_chart"][chart_num] = sg_value
                sg_entry["array_sizes"][chart_num] = sg_arr_size
                
                # Si un nom est trouvé sur un chart mais pas un autre, le garder
                if sg_name and not sg_entry["sg_name"]:
                    sg_entry["sg_name"] = sg_name
    
    return merged, chart_index


def build_recueil(merged: dict, chart_index: dict) -> dict:
    """
    Construire le recueil final structuré et trié.
    """
    
    studies_list = []
    
    for key in sorted(merged.keys()):
        entry = merged[key]
        
        # Trier les subgraphs par index
        sg_list = []
        for sg_idx in sorted(entry["subgraphs"].keys()):
            sg = entry["subgraphs"][sg_idx]
            sg_list.append({
                "sg_index": sg["sg_index"],
                "sg_name": sg["sg_name"],
                "example_value": next(iter(sg["values_per_chart"].values()), 0),
                "found_on_charts": sorted(sg["values_per_chart"].keys()),
                "values_per_chart": {str(k): v for k, v in sorted(sg["values_per_chart"].items())},
            })
        
        studies_list.append({
            "name": entry["name"],
            "short_name": entry["short_name"],
            "n_charts": len(entry["charts_present"]),
            "charts_present": sorted(entry["charts_present"]),
            "study_ids_per_chart": {str(k): v for k, v in sorted(entry["study_ids"].items())},
            "study_indexes_per_chart": {str(k): v for k, v in sorted(entry["study_indexes"].items())},
            "n_subgraphs": len(sg_list),
            "subgraphs": sg_list,
        })
    
    recueil = {
        "title": "MIA - Recueil Complet des Études Sierra Chart",
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "charts_scanned": {str(k): v for k, v in sorted(chart_index.items())},
        "n_charts": len(chart_index),
        "n_unique_studies": len(studies_list),
        "n_total_subgraphs": sum(s["n_subgraphs"] for s in studies_list),
        "studies": studies_list,
    }
    
    return recueil


def write_readable_txt(recueil: dict, filepath: str):
    """Écrire une version lisible (TXT) du recueil."""
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("  MIA - RECUEIL COMPLET DES ÉTUDES SIERRA CHART\n")
        f.write(f"  Généré le : {recueil['generated']}\n")
        f.write("=" * 80 + "\n\n")
        
        # Résumé
        f.write(f"📊 Charts scannés : {recueil['n_charts']}\n")
        for chart_num, symbol in sorted(recueil['charts_scanned'].items()):
            f.write(f"   Chart {chart_num:>3s} : {symbol}\n")
        f.write(f"\n📋 Études uniques : {recueil['n_unique_studies']}\n")
        f.write(f"📐 Subgraphs totaux : {recueil['n_total_subgraphs']}\n")
        f.write("\n")
        
        # Index rapide
        f.write("=" * 80 + "\n")
        f.write("  INDEX RAPIDE (par nom)\n")
        f.write("=" * 80 + "\n\n")
        
        for i, study in enumerate(recueil['studies'], 1):
            charts_str = ", ".join(str(c) for c in study['charts_present'])
            f.write(f"  {i:3d}. {study['name'][:55]:<55s}  Charts: [{charts_str}]  SG: {study['n_subgraphs']}\n")
        
        f.write("\n\n")
        
        # Détail de chaque étude
        f.write("=" * 80 + "\n")
        f.write("  DÉTAIL DES ÉTUDES\n")
        f.write("=" * 80 + "\n\n")
        
        for i, study in enumerate(recueil['studies'], 1):
            f.write("─" * 80 + "\n")
            f.write(f"  [{i}] {study['name']}\n")
            if study['short_name']:
                f.write(f"      Short: {study['short_name']}\n")
            
            f.write(f"      Présent sur {study['n_charts']} chart(s): {study['charts_present']}\n")
            
            # Study IDs par chart
            f.write("      Study IDs: ")
            ids = [f"Chart{k}→ID{v}" for k, v in study['study_ids_per_chart'].items()]
            f.write(", ".join(ids) + "\n")
            
            # Indexes par chart
            f.write("      Indexes:   ")
            idxs = [f"Chart{k}→Idx{v}" for k, v in study['study_indexes_per_chart'].items()]
            f.write(", ".join(idxs) + "\n")
            
            f.write(f"      Subgraphs ({study['n_subgraphs']}):\n")
            
            for sg in study['subgraphs']:
                name_part = f" [{sg['sg_name']}]" if sg['sg_name'] else ""
                charts_part = ", ".join(str(c) for c in sg['found_on_charts'])
                f.write(f"        SG {sg['sg_index']:>3d}{name_part:<40s}  "
                        f"val={sg['example_value']:>12.4f}  charts=[{charts_part}]\n")
            
            f.write("\n")
        
        # Table de mapping rapide pour le code C++
        f.write("\n" + "=" * 80 + "\n")
        f.write("  TABLE DE MAPPING POUR CODE C++\n")
        f.write("  (copier-coller dans study_mapping.json ou MIA_StudyConfig.h)\n")
        f.write("=" * 80 + "\n\n")
        
        for study in recueil['studies']:
            for chart_num, study_id in study['study_ids_per_chart'].items():
                for sg in study['subgraphs']:
                    sg_name_clean = sg['sg_name'].replace(' ', '_').replace('/', '_')
                    if sg_name_clean:
                        f.write(f"  // Chart {chart_num}, Study ID {study_id}, "
                                f"SG {sg['sg_index']} → {study['name']} / {sg['sg_name']}\n")
        
        f.write("\n" + "=" * 80 + "\n")
        f.write("  FIN DU RECUEIL\n")
        f.write("=" * 80 + "\n")


def write_study_mapping_json(recueil: dict, filepath: str):
    """
    Générer un study_mapping.json utilisable directement par MIA_StudyConfig.h.
    Format: { "chart_XX": { "study_name": { "id": N, "index": N, "subgraphs": {...} } } }
    """
    
    mapping = {}
    
    for study in recueil['studies']:
        for chart_str, study_id in study['study_ids_per_chart'].items():
            chart_key = f"chart_{chart_str}"
            
            if chart_key not in mapping:
                mapping[chart_key] = {}
            
            study_entry = {
                "study_id": study_id,
                "study_index": study['study_indexes_per_chart'].get(chart_str, 0),
                "name": study['name'],
                "short_name": study['short_name'],
                "subgraphs": {}
            }
            
            for sg in study['subgraphs']:
                if int(chart_str) in sg['found_on_charts']:
                    sg_key = sg['sg_name'] if sg['sg_name'] else f"sg_{sg['sg_index']}"
                    study_entry["subgraphs"][sg_key] = {
                        "index": sg['sg_index'],
                        "example_value": sg['values_per_chart'].get(chart_str, 0),
                    }
            
            # Utiliser le nom court comme clé, ou le nom complet
            entry_key = study['short_name'] if study['short_name'] else study['name']
            mapping[chart_key][entry_key] = study_entry
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)
    
    print(f"  ✅ Mapping JSON: {filepath}")


def main():
    print("=" * 60)
    print("  MIA STUDY MERGER — Fusion des inventaires")
    print("=" * 60)
    print()
    
    # 1. Charger tous les fichiers chart_XX.json
    print(f"📂 Scan: {STUDIES_DIR}")
    if not os.path.exists(STUDIES_DIR):
        print(f"❌ Répertoire non trouvé: {STUDIES_DIR}")
        print(f"   Lancer d'abord MIA_Study_Mapper sur chaque chart!")
        return
    
    charts = load_all_charts(STUDIES_DIR)
    
    if not charts:
        print("❌ Aucun fichier chart_*.json trouvé!")
        print(f"   Vérifier: {STUDIES_DIR}\\chart_*.json")
        return
    
    print(f"\n📊 {len(charts)} chart(s) chargé(s)")
    
    # 2. Fusionner
    print("\n🔄 Fusion en cours...")
    merged, chart_index = merge_studies(charts)
    print(f"   {len(merged)} études uniques trouvées")
    
    # 3. Construire le recueil
    recueil = build_recueil(merged, chart_index)
    
    # 4. Écrire les sorties
    
    # JSON complet
    json_path = os.path.join(STUDIES_DIR, "RECUEIL_COMPLET.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(recueil, f, indent=2, ensure_ascii=False)
    print(f"  ✅ JSON: {json_path}")
    
    # TXT lisible
    txt_path = os.path.join(STUDIES_DIR, "RECUEIL_COMPLET.txt")
    write_readable_txt(recueil, txt_path)
    print(f"  ✅ TXT:  {txt_path}")
    
    # Mapping pour le code C++
    mapping_path = os.path.join(STUDIES_DIR, "study_mapping_generated.json")
    write_study_mapping_json(recueil, mapping_path)
    
    # 5. Résumé
    print("\n" + "=" * 60)
    print("  RÉSUMÉ")
    print("=" * 60)
    print(f"  📊 Charts scannés  : {recueil['n_charts']}")
    for k, v in sorted(recueil['charts_scanned'].items()):
        print(f"       Chart {k:>3s} : {v}")
    print(f"  📋 Études uniques  : {recueil['n_unique_studies']}")
    print(f"  📐 Subgraphs total : {recueil['n_total_subgraphs']}")
    print()
    
    # Top études (les plus présentes)
    top = sorted(recueil['studies'], key=lambda s: s['n_charts'], reverse=True)[:10]
    print("  🏆 Top études (présentes sur le plus de charts):")
    for s in top:
        print(f"       [{s['n_charts']} charts] {s['name'][:50]}  ({s['n_subgraphs']} SG)")
    
    print("\n  ✅ DONE!")
    print(f"  → Recueil: {json_path}")
    print(f"  → Mapping: {mapping_path}")


if __name__ == "__main__":
    main()
