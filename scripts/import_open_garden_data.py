"""Extract crop details from open-garden-data into scripts/data/open_garden_data.json.

open-garden-data (https://github.com/thedude459/open-garden-data) is dedicated
to the public domain under CC0 1.0. This script reads a local checkout of it
(YAML only, nothing in it is run) and keeps the fields Reap uses: spacing,
sowing depth, days to germinate, soil temperature and pH, named varieties,
companion pairs, and notes for crops Reap didn't have. build_catalog.py merges
the result into crops.json. Sowing windows and days to maturity are not
imported: Reap keeps its own regional timings.

Run: python scripts/import_open_garden_data.py /path/to/open-garden-data
"""
import json
import subprocess
import sys
from pathlib import Path

import yaml

OUT = Path(__file__).resolve().parent / "data/open_garden_data.json"

# open-garden-data id -> Reap crop key. Several of theirs can map to one of ours.
MAP = {
    "bush-bean": "bean_bush_pole", "pole-bean": "bean_bush_pole",
    "sweet-pepper": "pepper", "hot-pepper": "pepper",
    "sweet-corn": "corn",
    "winter-squash": "squash", "summer-squash": "squash", "pumpkin": "squash",
}
# Crops of theirs Reap adds as new crops (their notes are kept for these).
NEW = {"watermelon", "sweet_potato", "calendula", "marigold", "nasturtium", "sweet_alyssum"}
# Perennial fruit and the like: not imported.
SKIP = {"apple", "blackberry", "blueberry", "peach", "pear", "raspberry", "sweet-cherry", "comfrey", "tansy"}


def key_for(crop_id):
    return MAP.get(crop_id, crop_id.replace("-", "_"))


def main(src):
    src = Path(src)
    crops = {}
    # Where several of theirs map to one of ours, spacing and depth come from
    # the first: the most typical one.
    first = {"winter-squash": 0, "sweet-pepper": 0, "bush-bean": 0}
    for path in sorted((src / "crops").glob("*.yaml"), key=lambda p: (first.get(p.stem, 1), p.stem)):
        d = yaml.safe_load(path.read_text(encoding="utf-8"))
        if d["id"] in SKIP:
            continue
        key = key_for(d["id"])
        out = crops.setdefault(key, {"from": []})
        out["from"].append(d["id"])
        if "spacingCm" in d and "spacing_cm" not in out:
            out["spacing_cm"] = {k: v for k, v in (("in_row", d["spacingCm"].get("inRow")),
                                                    ("between_rows", d["spacingCm"].get("betweenRows"))) if v}
        if "sowingDepthCm" in d and "sowing_depth_cm" not in out:
            out["sowing_depth_cm"] = d["sowingDepthCm"]
        if "germinationDays" in d:
            g = d["germinationDays"]
            old = out.get("germination_days", [g["min"], g["max"]])
            out["germination_days"] = [min(old[0], g["min"]), max(old[1], g["max"])]
        if "minSoilTemperatureC" in d:
            out["min_soil_temp_c"] = min(out.get("min_soil_temp_c", 99), d["minSoilTemperatureC"])
        if "soilPh" in d and "soil_ph" not in out:
            out["soil_ph"] = [d["soilPh"]["min"], d["soilPh"]["max"]]
        for v in d.get("varieties") or []:
            out.setdefault("varieties", [])
            if v["name"] not in out["varieties"]:
                out["varieties"].append(v["name"])
        if key in NEW and d.get("notes"):
            out["notes"] = d["notes"].strip()
    for pair in yaml.safe_load((src / "companions.yaml").read_text(encoding="utf-8")):
        a, b = pair["crops"]
        if a in SKIP or b in SKIP:
            continue
        ka, kb = key_for(a), key_for(b)
        if ka == kb:
            continue
        for mine, other in ((ka, kb), (kb, ka)):
            if mine not in crops:
                continue
            entry = {"crop": other, "kind": pair["kind"], "reason": pair["reason"].strip()}
            listed = crops[mine].setdefault("companions", [])
            if not any(e["crop"] == other and e["kind"] == entry["kind"] for e in listed):
                listed.append(entry)
    commit = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    data = {
        "source": "open-garden-data",
        "url": "https://github.com/thedude459/open-garden-data",
        "license": "CC0-1.0",
        "commit": commit,
        "crops": crops,
    }
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(crops)} crops written to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
