"""Build custom_components/garden_planner/data/crops.json.

The windows below are calendar dates read off the South Coastal BC Vegetable
Planting Guide chart (to roughly half-month accuracy). The chart is drawn for
an April 1 last frost and a November 16 first frost, so each date is stored as
days from the last frost (L) for dates before July, or from the first frost (F)
after that. That lets the planner work anywhere from its frost dates.

Run: python scripts/build_catalog.py
"""
import json
import sys
from datetime import date
from pathlib import Path

CHART_LAST_FROST = date(2001, 4, 1)
CHART_FIRST_FROST = date(2001, 11, 16)
OUT = Path(__file__).resolve().parent.parent / "custom_components/garden_planner/data/crops.json"


def to_offset(mmdd):
    month, day = (int(p) for p in mmdd.split("-"))
    d = date(2001, month, day)
    if d.month < 7:
        return f"L{(d - CHART_LAST_FROST).days:+d}"
    return f"F{(d - CHART_FIRST_FROST).days:+d}"

# name, key, windows, weeks_indoor, days_to_harvest (from sowing/planting), harvest_weeks, flags
# window: (season, {"indoor":(s,e), "direct":(s,e), "transplant":(s,e), "cover":(s,e)})
C = []
def crop(key, name, windows, weeks_indoor=None, dth=60, harvest_weeks=4, tender=False, pot_up=False, perennial=False, source="pdf", notes=None):
    d = {"key": key, "name": name, "source": source, "windows": [], "weeks_indoor": weeks_indoor,
         "days_to_harvest": dth, "harvest_weeks": harvest_weeks, "frost_tender": tender,
         "pot_up": pot_up, "perennial": perennial}
    if notes: d["notes"] = notes
    for season, w in windows:
        ww = {"season": season}
        for k, v in w.items():
            ww[k] = [to_offset(v[0]), to_offset(v[1])]
        d["windows"].append(ww)
    C.append(d)

S = "spring"; F = "fall"; SU = "summer"
crop("amaranth","Amaranth",[(S,{"direct":("05-01","06-15")})],dth=60,harvest_weeks=8,tender=True)
crop("artichoke","Artichoke",[(S,{"indoor":("02-01","02-28"),"transplant":("05-01","05-20")})],weeks_indoor=12,dth=180,harvest_weeks=6,pot_up=True,perennial=True)
crop("arugula","Arugula",[(S,{"direct":("03-01","09-30")})],dth=35,harvest_weeks=3)
crop("asparagus","Asparagus",[(S,{"indoor":("02-15","05-01"),"transplant":("05-15","06-01")})],weeks_indoor=12,dth=730,harvest_weeks=6,perennial=True,notes="First real harvest in the third spring.")
crop("bean_asparagus","Bean, asparagus",[(S,{"indoor":("04-01","05-15"),"transplant":("05-15","06-15")})],weeks_indoor=4,dth=80,harvest_weeks=6,tender=True)
crop("bean_broad","Bean, broad",[(S,{"direct":("02-01","04-15")}),(F,{"direct":("09-15","11-15")})],dth=90,harvest_weeks=4)
crop("bean_bush_pole","Bean, bush & pole",[(S,{"direct":("05-01","07-15")})],dth=60,harvest_weeks=6,tender=True)
crop("bean_soya","Bean, soya",[(S,{"direct":("05-01","06-01")})],dth=90,harvest_weeks=3,tender=True)
crop("beet","Beet",[(S,{"direct":("04-15","08-15")})],dth=60,harvest_weeks=4)
crop("broccoli","Broccoli",[(S,{"indoor":("03-01","04-15"),"direct":("04-15","04-30"),"transplant":("05-01","06-01")})],weeks_indoor=5,dth=95,harvest_weeks=3)
crop("broccoli_sprouting","Broccoli, sprouting",[(S,{"indoor":("03-01","04-01"),"transplant":("04-10","05-01"),"direct":("05-01","06-30")}),(SU,{"indoor":("07-01","07-20"),"transplant":("08-01","08-20")})],weeks_indoor=5,dth=120,harvest_weeks=6)
crop("brussels_sprouts","Brussels sprouts",[(S,{"indoor":("05-15","06-15"),"transplant":("06-20","07-15")})],weeks_indoor=5,dth=130,harvest_weeks=8)
crop("cabbage","Cabbage",[(S,{"indoor":("03-01","04-01"),"transplant":("04-01","05-15"),"direct":("05-15","06-30")})],weeks_indoor=5,dth=100,harvest_weeks=4)
crop("cabbage_overwinter","Cabbage, overwinter",[(SU,{"indoor":("07-01","07-15"),"direct":("07-15","08-01"),"transplant":("08-01","08-20")})],weeks_indoor=5,dth=210,harvest_weeks=6)
crop("carrot","Carrot",[(S,{"direct":("04-01","07-15")})],dth=75,harvest_weeks=6)
crop("cauliflower","Cauliflower",[(S,{"indoor":("03-01","04-20"),"transplant":("04-20","05-01")}),(SU,{"indoor":("05-01","06-15"),"transplant":("06-20","07-31")})],weeks_indoor=5,dth=100,harvest_weeks=3)
crop("celery","Celery/Celeriac",[(S,{"indoor":("03-01","04-15"),"transplant":("05-15","06-01")})],weeks_indoor=10,dth=140,harvest_weeks=6)
crop("corn","Corn",[(S,{"direct":("05-15","06-30")})],dth=85,harvest_weeks=3,tender=True)
crop("corn_salad","Corn salad",[(S,{"direct":("02-01","04-15")}),(F,{"direct":("09-01","10-15"),"cover":("10-01","10-31")})],dth=50,harvest_weeks=8)
crop("cress","Cress",[(S,{"direct":("03-01","09-30")})],dth=20,harvest_weeks=2)
crop("cucumber","Cucumber",[(S,{"indoor":("04-25","05-10"),"direct":("05-10","06-30"),"transplant":("05-25","06-15")})],weeks_indoor=3,dth=60,harvest_weeks=8,tender=True)
crop("eggplant","Eggplant",[(S,{"indoor":("04-01","04-20"),"transplant":("06-01","06-30")})],weeks_indoor=9,dth=130,harvest_weeks=8,tender=True,pot_up=True)
crop("endive","Endive/Escarole",[(S,{"direct":("04-01","04-30")}),(F,{"direct":("08-15","09-30"),"cover":("09-15","10-31")})],dth=85,harvest_weeks=4)
crop("fennel","Fennel",[(S,{"direct":("04-01","06-30")})],dth=80,harvest_weeks=4)
crop("garlic","Garlic",[(S,{"direct":("03-01","03-15")}),(F,{"direct":("09-20","11-15")})],dth=270,harvest_weeks=3,notes="Plant cloves. Fall planting is harvested the next July.")
crop("kale","Kale & Collard",[(S,{"direct":("03-01","07-31")})],dth=60,harvest_weeks=16)
crop("kohlrabi","Kohlrabi",[(S,{"direct":("04-01","05-15")}),(SU,{"direct":("07-15","07-31")})],dth=55,harvest_weeks=3)
crop("leek","Leek",[(S,{"indoor":("02-01","04-01"),"transplant":("04-01","04-15"),"direct":("04-15","05-15")}),(SU,{"indoor":("06-01","06-15"),"transplant":("08-01","08-15")})],weeks_indoor=10,dth=150,harvest_weeks=12)
crop("lettuce","Lettuce",[(S,{"indoor":("03-01","04-01"),"transplant":("04-01","04-30"),"direct":("05-01","09-15"),"cover":("09-01","09-30")})],weeks_indoor=4,dth=50,harvest_weeks=4)
crop("melon","Melon",[(S,{"indoor":("04-15","05-01"),"transplant":("06-01","06-30")})],weeks_indoor=4,dth=90,harvest_weeks=4,tender=True)
crop("mustard","Mustard",[(S,{"direct":("03-01","06-30")}),(F,{"direct":("08-01","09-30"),"cover":("09-15","10-15")})],dth=40,harvest_weeks=4)
crop("okra","Okra",[(S,{"indoor":("04-15","05-01"),"transplant":("05-20","06-01")})],weeks_indoor=5,dth=90,harvest_weeks=6,tender=True)
crop("onion","Onion",[(S,{"indoor":("01-01","03-31"),"direct":("04-01","04-30"),"transplant":("04-30","05-31")})],weeks_indoor=10,dth=150,harvest_weeks=3)
crop("onion_overwinter","Onion, overwinter",[(SU,{"indoor":("06-01","07-15"),"transplant":("08-15","08-31")})],weeks_indoor=8,dth=330,harvest_weeks=3)
crop("scallion","Onion, scallion",[(S,{"indoor":("03-15","04-01"),"direct":("04-01","08-31")})],weeks_indoor=4,dth=60,harvest_weeks=6)
crop("pac_choi","Pac choi & choi sum",[(S,{"direct":("03-01","09-30"),"cover":("03-01","03-31")})],dth=45,harvest_weeks=3)
crop("parsnip","Parsnip",[(S,{"direct":("04-01","06-15")})],dth=120,harvest_weeks=12)
crop("pea","Pea",[(S,{"direct":("02-15","05-31")}),(SU,{"direct":("07-01","08-15")})],dth=65,harvest_weeks=4)
crop("pepper","Pepper",[(S,{"indoor":("03-01","04-15"),"transplant":("06-01","06-30")})],weeks_indoor=10,dth=140,harvest_weeks=10,tender=True,pot_up=True)
crop("radicchio","Radicchio",[(S,{"indoor":("03-15","04-01"),"transplant":("04-01","04-30")}),(SU,{"indoor":("06-15","07-31"),"transplant":("08-01","08-20")})],weeks_indoor=4,dth=90,harvest_weeks=4)
crop("radish","Radish",[(S,{"direct":("03-01","04-30")}),(F,{"direct":("08-01","10-31"),"cover":("10-01","10-31")})],dth=28,harvest_weeks=2)
crop("rhubarb","Rhubarb",[(S,{"indoor":("03-15","04-15"),"transplant":("05-01","06-01")})],weeks_indoor=8,dth=730,harvest_weeks=8,perennial=True,notes="First harvest in the second or third spring.")
crop("rutabaga","Rutabaga",[(S,{"direct":("06-15","07-15")})],dth=100,harvest_weeks=8)
crop("spinach","Spinach",[(S,{"direct":("03-01","06-15")}),(F,{"direct":("08-01","10-01"),"cover":("09-15","10-15")})],dth=45,harvest_weeks=4)
crop("squash","Squash/pumpkin",[(S,{"indoor":("04-15","05-15"),"transplant":("05-15","06-01"),"direct":("06-01","06-10")})],weeks_indoor=3,dth=100,harvest_weeks=8,tender=True)
crop("strawberry","Strawberry",[(S,{"indoor":("01-01","02-28"),"transplant":("05-01","05-20")})],weeks_indoor=12,dth=365,harvest_weeks=4,perennial=True)
crop("swiss_chard","Swiss chard",[(S,{"direct":("04-15","07-15")})],dth=55,harvest_weeks=16)
crop("tomato","Tomato",[(S,{"indoor":("03-01","04-15"),"transplant":("05-01","06-15")})],weeks_indoor=7,dth=120,harvest_weeks=10,tender=True,pot_up=True)
crop("turnip","Turnip",[(S,{"direct":("03-01","08-31")})],dth=50,harvest_weeks=4)
# Added crops (not in the PDF)
A = "added"
crop("potato","Potato",[(S,{"direct":("03-15","06-15")})],dth=100,harvest_weeks=6,source=A,notes="Plant seed potatoes. Early varieties about 70 days, main crop about 110.")
crop("tomatillo","Tomatillo",[(S,{"indoor":("03-15","04-15"),"transplant":("05-15","06-15")})],weeks_indoor=7,dth=120,harvest_weeks=8,tender=True,pot_up=True,source=A)
# Herbs, from the South Coastal BC Flower & Herb Planting Guide.
H = "pdf_herbs"
crop("basil","Basil",[(S,{"indoor":("04-15","05-20"),"transplant":("06-01","06-30")})],weeks_indoor=6,dth=85,harvest_weeks=10,tender=True,source=H)
crop("bergamot","Bergamot",[(S,{"indoor":("02-15","03-20"),"direct":("03-20","04-15"),"transplant":("05-01","05-15")}),(F,{"direct":("10-01","10-31")})],weeks_indoor=10,dth=120,harvest_weeks=8,perennial=True,source=H)
crop("borage","Borage",[(S,{"direct":("04-01","08-15")})],dth=55,harvest_weeks=8,source=H)
crop("chamomile","Chamomile",[(S,{"direct":("04-01","06-30")}),(F,{"direct":("09-15","10-31")})],dth=65,harvest_weeks=8,source=H)
crop("chervil","Chervil",[(S,{"indoor":("03-10","04-01"),"direct":("04-01","08-15")})],weeks_indoor=4,dth=50,harvest_weeks=6,source=H)
crop("chives","Chives",[(S,{"indoor":("02-01","04-01"),"transplant":("04-01","04-20"),"direct":("04-20","06-30")}),(SU,{"direct":("08-01","09-30")})],weeks_indoor=8,dth=90,harvest_weeks=20,perennial=True,source=H)
crop("cilantro","Cilantro",[(S,{"direct":("03-01","09-30")})],dth=45,harvest_weeks=3,source=H,notes="Bolts in summer heat, so sow small batches every 2 to 3 weeks.")
crop("dill","Dill",[(S,{"direct":("05-01","08-31")})],dth=50,harvest_weeks=4,source=H)
crop("lavender","Lavender",[(S,{"indoor":("01-15","03-01"),"transplant":("05-15","06-15")})],weeks_indoor=14,dth=365,harvest_weeks=6,perennial=True,source=H)
crop("lemon_balm","Lemon balm",[(S,{"indoor":("02-01","03-01"),"transplant":("03-20","04-01"),"direct":("04-01","07-31")})],weeks_indoor=7,dth=80,harvest_weeks=16,perennial=True,source=H)
crop("lemongrass","Lemongrass",[(S,{"indoor":("02-15","03-31"),"transplant":("05-15","06-15")})],weeks_indoor=12,dth=120,harvest_weeks=10,tender=True,source=H)
crop("lovage","Lovage",[(S,{"indoor":("03-01","04-01"),"direct":("04-01","04-20"),"transplant":("04-20","05-01")}),(F,{"direct":("10-01","10-31")})],weeks_indoor=7,dth=365,harvest_weeks=12,perennial=True,source=H)
crop("mint","Mint",[(S,{"indoor":("02-01","03-31"),"transplant":("05-01","06-15")})],weeks_indoor=10,dth=120,harvest_weeks=16,perennial=True,source=H)
crop("oregano","Oregano",[(S,{"indoor":("02-15","04-20"),"transplant":("04-20","05-15")})],weeks_indoor=8,dth=110,harvest_weeks=16,perennial=True,source=H)
crop("parsley","Parsley",[(S,{"direct":("04-15","08-15")})],dth=75,harvest_weeks=20,source=H,notes="Flat-leaf (Italian) and curly are timed the same.")
crop("rosemary","Rosemary",[(S,{"indoor":("02-01","04-20"),"transplant":("04-20","05-15")})],weeks_indoor=10,dth=180,harvest_weeks=20,perennial=True,source=H)
crop("sage","Sage",[(S,{"indoor":("02-01","04-20"),"transplant":("04-20","05-15")})],weeks_indoor=10,dth=150,harvest_weeks=20,perennial=True,source=H)
crop("savory","Savory",[(S,{"indoor":("03-01","04-25"),"transplant":("04-25","05-10")})],weeks_indoor=7,dth=90,harvest_weeks=12,source=H)
crop("shiso","Shiso",[(S,{"indoor":("03-15","04-01"),"transplant":("04-01","04-20"),"direct":("04-20","06-30")})],weeks_indoor=5,dth=80,harvest_weeks=12,source=H)
crop("stevia","Stevia",[(S,{"indoor":("04-01","05-31"),"transplant":("06-01","06-30")})],weeks_indoor=8,dth=120,harvest_weeks=8,tender=True,source=H)
crop("marjoram","Sweet marjoram",[(S,{"indoor":("02-15","04-20"),"transplant":("04-20","05-15")})],weeks_indoor=8,dth=100,harvest_weeks=12,source=H)
crop("thyme","Thyme",[(S,{"indoor":("02-01","04-15"),"transplant":("04-20","05-20")})],weeks_indoor=10,dth=120,harvest_weeks=16,perennial=True,source=H)

out = {
    "source": "South Coastal BC Vegetable and Flower & Herb Planting Guides (West Coast Seeds), plus added crops",
    "format": "Ranges are days from the last spring frost (L) or first fall frost (F).",
    "crops": C,
}
OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
print(f"{len(C)} crops written to {OUT}")

# Keep the crop dropdown in services.yaml in step with the catalog.
SERVICES = OUT.parent.parent / "services.yaml"
options = "\n".join(
    f'              - label: "{c["name"]}"\n                value: "{c["key"]}"'
    for c in sorted(C, key=lambda c: c["name"])
)
text = SERVICES.read_text(encoding="utf-8")
parts = text.split("    crop:\n      required: true\n      selector:\n        select:\n          custom_value: true\n          options:\n")
rebuilt = [parts[0]]
for part in parts[1:]:
    rest = part[part.index("    method:"):]
    rebuilt.append(options + "\n" + rest)
SERVICES.write_text(
    ("    crop:\n      required: true\n      selector:\n        select:\n          custom_value: true\n          options:\n").join(rebuilt),
    encoding="utf-8",
)
print(f"Crop options updated in {SERVICES}")
