"""Audit detaille des reponses MenthorQ par section/slug."""
import json
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "DATA/MENTHORQ/20251215_menthorq_complete.json"

with open(path) as f:
    d = json.load(f)

sections = ["ES", "NQ", "ES_swing", "NQ_swing",
            "ES_intraday", "NQ_intraday", "CTA", "VOL"]

totals = {"json_data": 0, "image_only": 0, "failed": 0, "total": 0}

for section in sections:
    raw = d.get(section, {}).get("raw_ajax", {})
    if not raw:
        continue
    print(f"\n=== {section} ===")
    sec_stats = {"json_data": 0, "image_only": 0, "failed": 0}
    for slug, resp in raw.items():
        totals["total"] += 1
        if not isinstance(resp, dict):
            continue
        success = resp.get("success")
        if success is False:
            err = resp.get("data", {}).get("error", "?")
            print(f"  [FAIL]  {slug:30s} {err}")
            sec_stats["failed"] += 1
            totals["failed"] += 1
            continue
        if success is True:
            resource = resp.get("data", {}).get("resource", {})
            data_field = resource.get("data", [])
            text_data = resource.get("text_data", "")
            table_data = resource.get("table_data", [])
            image_url = resource.get("image_url", "")
            if data_field or text_data or table_data:
                print(f"  [JSON]  {slug:30s} data={bool(data_field)} text={bool(text_data)} table={bool(table_data)}")
                sec_stats["json_data"] += 1
                totals["json_data"] += 1
            elif image_url:
                print(f"  [IMG]   {slug:30s} image_url only")
                sec_stats["image_only"] += 1
                totals["image_only"] += 1
            else:
                print(f"  [EMPTY] {slug:30s}")
                sec_stats["failed"] += 1
                totals["failed"] += 1
    print(f"  -> JSON: {sec_stats['json_data']}, IMG: {sec_stats['image_only']}, FAIL: {sec_stats['failed']}")

print(f"\n{'='*60}")
print(f"TOTAL: {totals['total']} slugs")
print(f"  JSON_DATA  (utilisable directement) : {totals['json_data']}")
print(f"  IMAGE_ONLY (besoin OCR/Vision API)  : {totals['image_only']}")
print(f"  FAILED     (MenthorQ refuse)        : {totals['failed']}")
print(f"{'='*60}")
