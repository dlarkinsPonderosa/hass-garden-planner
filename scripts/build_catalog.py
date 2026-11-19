"""Build custom_components/reap/data/crops.json.

The windows below are calendar dates read off West Coast Seeds' regional
planting charts (to roughly half-month accuracy). The crop list and the
"cool_spring" profile come from the South Coastal BC charts; "continental"
averages South Central BC and the South Central Prairies; "atlantic" is the
Maritimes chart. A crop missing from a regional chart is estimated from its
coastal timing, shifted by the typical difference for crops that are on both. The chart is drawn for
an April 1 last frost and a November 16 first frost, so each date is stored as
days from the last frost (L) for dates before July, or from the first frost (F)
after that. That lets the planner work anywhere from its frost dates.

Run: python scripts/build_catalog.py
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

CHART_LAST_FROST = date(2001, 4, 1)
CHART_FIRST_FROST = date(2001, 11, 16)
OUT = Path(__file__).resolve().parent.parent / "custom_components/reap/data/crops.json"


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


# ---------------------------------------------------------------------------
# Other regional charts, read the same way. Each is measured from that chart's
# own typical frost dates (the middle of the towns listed on it).
# ---------------------------------------------------------------------------
I, D, T, V = "indoor", "direct", "transplant", "cover"

SOUTH_CENTRAL_BC = {  # Kamloops, Vernon, Kelowna, Nelson: about May 1 - Oct 6
    "frost": ("05-01", "10-06"),
    "amaranth": [(S, {D: ("06-01", "06-30")})],
    "artichoke": [(S, {I: ("03-01", "03-25"), T: ("05-25", "06-10")})],
    "arugula": [(S, {D: ("04-10", "09-01")})],
    "asparagus": [(S, {I: ("02-25", "05-01"), T: ("06-01", "06-25")})],
    "bean_asparagus": [(S, {I: ("04-01", "05-20"), T: ("05-20", "06-25")})],
    "bean_broad": [(S, {D: ("03-25", "05-20")}), (F, {D: ("09-10", "10-31")})],
    "bean_soya": [(S, {D: ("06-01", "06-30")})],
    "bean_bush_pole": [(S, {D: ("05-25", "07-01")})],
    "beet": [(S, {D: ("05-10", "07-20")})],
    "broccoli": [(S, {I: ("03-10", "04-01"), T: ("05-01", "05-30")})],
    "broccoli_sprouting": [(SU, {I: ("06-01", "06-15"), T: ("07-20", "08-05")})],
    "brussels_sprouts": [(S, {I: ("05-20", "06-10"), T: ("07-20", "08-05")})],
    "cabbage": [(S, {I: ("04-01", "04-25"), T: ("05-10", "06-01"), D: ("06-01", "06-15")})],
    "cabbage_overwinter": [(SU, {I: ("06-15", "07-01"), D: ("07-01", "07-20"), T: ("07-25", "08-10")})],
    "carrot": [(S, {D: ("05-10", "07-15")})],
    "cauliflower": [(S, {I: ("04-01", "04-25"), T: ("05-20", "06-05")})],
    "celery": [(S, {I: ("03-01", "04-20"), T: ("05-20", "06-01")})],
    "corn": [(S, {D: ("05-25", "06-25")})],
    "corn_salad": [(S, {D: ("04-05", "05-10")}), (F, {D: ("09-10", "10-01")})],
    "cress": [(S, {D: ("04-10", "08-25")})],
    "cucumber": [(S, {I: ("05-01", "05-15"), D: ("05-15", "05-25"), T: ("05-25", "06-10")})],
    "eggplant": [(S, {I: ("03-25", "04-10"), T: ("06-01", "06-15")})],
    "endive": [(S, {D: ("05-05", "05-30")}), (F, {D: ("07-05", "07-31")})],
    "radicchio": [(S, {D: ("05-05", "05-30")}), (SU, {D: ("07-05", "07-31")})],
    "fennel": [(S, {D: ("05-01", "06-30")})],
    "garlic": [(F, {D: ("10-01", "11-15")})],
    "kale": [(S, {D: ("04-10", "07-20")})],
    "kohlrabi": [(S, {I: ("04-10", "04-20"), T: ("05-10", "06-05")})],
    "leek": [(S, {I: ("03-01", "04-15"), T: ("05-01", "05-25")})],
    "lettuce": [(S, {I: ("04-10", "04-30"), T: ("05-10", "06-01"), D: ("06-01", "07-31")})],
    "melon": [(S, {I: ("04-15", "04-25"), T: ("05-20", "06-01")})],
    "mustard": [(S, {D: ("04-05", "06-30")}), (F, {D: ("08-01", "09-25")})],
    "okra": [(S, {I: ("04-25", "05-05"), T: ("05-20", "06-05")})],
    "onion": [(S, {I: ("03-01", "04-15"), T: ("05-20", "06-01")})],
    "onion_overwinter": [(SU, {I: ("06-15", "07-15"), T: ("08-10", "08-15")})],
    "scallion": [(S, {D: ("05-01", "09-20")})],
    "pac_choi": [(S, {D: ("04-10", "08-25"), V: ("04-10", "05-05")})],
    "parsnip": [(S, {D: ("04-25", "06-25")})],
    "pea": [(S, {D: ("04-10", "06-05")}), (SU, {D: ("07-01", "07-20")})],
    "pepper": [(S, {I: ("03-01", "03-25"), T: ("06-01", "06-15")})],
    "radish": [(S, {D: ("04-10", "05-31"), V: ("04-10", "05-05")}), (F, {D: ("08-10", "09-25")})],
    "rhubarb": [(S, {I: ("03-15", "04-10"), T: ("05-15", "06-01")})],
    "rutabaga": [(S, {D: ("06-01", "07-01")})],
    "spinach": [(S, {D: ("04-10", "05-05"), V: ("04-10", "05-05")}), (F, {D: ("08-10", "08-20")})],
    "squash": [(S, {I: ("05-01", "05-15"), T: ("05-15", "06-05")})],
    "strawberry": [(S, {I: ("01-01", "02-28"), T: ("05-10", "06-01")})],
    "swiss_chard": [(S, {D: ("05-10", "08-05")})],
    "tomato": [(S, {I: ("03-20", "04-10"), T: ("05-20", "06-05")})],
    "turnip": [(S, {D: ("05-10", "08-25")})],
}

PRAIRIES = {  # Edmonton, Saskatoon and area: about May 21 - Sep 11
    "frost": ("05-21", "09-11"),
    "amaranth": [(S, {D: ("06-01", "06-30")})],
    "artichoke": [(S, {I: ("02-25", "03-31"), T: ("05-20", "06-05")})],
    "arugula": [(S, {D: ("04-15", "06-30")})],
    "asparagus": [(S, {I: ("02-25", "03-31"), T: ("05-15", "06-15")})],
    "bean_broad": [(S, {D: ("04-10", "05-31")})],
    "bean_soya": [(S, {D: ("06-01", "06-20")})],
    "bean_bush_pole": [(S, {D: ("05-25", "06-30")})],
    "beet": [(S, {D: ("05-25", "07-10")})],
    "broccoli": [(S, {I: ("04-15", "04-30"), T: ("05-25", "06-05")})],
    "brussels_sprouts": [(S, {I: ("04-15", "04-30"), T: ("05-25", "06-05")})],
    "cabbage": [(S, {I: ("04-20", "05-05"), T: ("05-15", "05-31"), D: ("06-01", "06-10")})],
    "carrot": [(S, {D: ("05-25", "07-15")})],
    "cauliflower": [(S, {I: ("03-25", "04-30"), T: ("05-25", "06-15")})],
    "celery": [(S, {I: ("03-25", "04-30"), T: ("06-01", "06-15")})],
    "corn": [(S, {D: ("06-01", "06-30")})],
    "corn_salad": [(S, {D: ("04-10", "05-31"), V: ("04-10", "04-25")}), (F, {D: ("08-01", "09-30"), V: ("09-01", "09-30")})],
    "cucumber": [(S, {I: ("05-01", "05-20"), D: ("05-20", "06-01"), T: ("06-01", "06-20")})],
    "eggplant": [(S, {I: ("03-25", "04-15"), T: ("06-01", "06-20")})],
    "endive": [(S, {D: ("05-15", "06-30")})],
    "radicchio": [(S, {D: ("05-15", "06-30")})],
    "fennel": [(S, {D: ("05-15", "06-30")})],
    "garlic": [(F, {D: ("10-01", "11-01")})],
    "kale": [(S, {D: ("04-15", "07-31")})],
    "kohlrabi": [(S, {I: ("03-25", "04-30"), T: ("05-01", "05-31")})],
    "leek": [(S, {I: ("03-01", "04-15"), T: ("05-10", "05-31")})],
    "lettuce": [(S, {I: ("04-20", "05-20"), T: ("05-20", "06-05"), D: ("06-05", "07-31")})],
    "melon": [(S, {I: ("05-01", "05-15"), T: ("06-01", "06-20")})],
    "mustard": [(S, {D: ("04-20", "06-30")})],
    "okra": [(S, {I: ("04-20", "05-01"), T: ("06-01", "06-10")})],
    "onion": [(S, {I: ("02-01", "03-31"), T: ("05-15", "05-31")})],
    "onion_overwinter": [(SU, {I: ("06-20", "07-15"), T: ("08-01", "08-20")})],
    "scallion": [(S, {I: ("04-01", "04-15"), D: ("04-15", "08-15")})],
    "pac_choi": [(S, {D: ("04-10", "06-10"), V: ("04-10", "05-01")}), (SU, {D: ("07-10", "08-15")})],
    "parsnip": [(S, {D: ("05-25", "06-10")})],
    "pea": [(S, {D: ("05-01", "06-30")})],
    "pepper": [(S, {I: ("03-01", "03-25"), T: ("06-01", "06-20")})],
    "radish": [(S, {D: ("04-20", "05-25")}), (F, {D: ("07-20", "08-15")})],
    "rhubarb": [(S, {I: ("03-15", "04-10"), T: ("05-15", "06-15")})],
    "rutabaga": [(S, {I: ("04-01", "04-15"), T: ("06-01", "06-20")})],
    "spinach": [(S, {D: ("04-10", "06-30"), V: ("04-10", "05-01")}), (F, {D: ("08-01", "09-10"), V: ("08-25", "09-10")})],
    "squash": [(S, {I: ("05-01", "05-15"), D: ("05-15", "05-25"), T: ("06-01", "06-10")})],
    "strawberry": [(S, {I: ("01-01", "02-25"), T: ("05-15", "06-01")})],
    "swiss_chard": [(S, {D: ("05-15", "07-31")})],
    "tomato": [(S, {I: ("03-25", "04-10"), T: ("05-25", "06-15")})],
    "turnip": [(S, {D: ("04-20", "08-01")})],
}

MARITIMES = {  # Halifax, Fredericton, Charlottetown and area: about May 16 - Oct 17
    "frost": ("05-16", "10-17"),
    "amaranth": [(S, {D: ("06-01", "06-30")})],
    "artichoke": [(S, {I: ("03-20", "03-31"), T: ("06-01", "06-15")})],
    "arugula": [(S, {D: ("02-15", "07-10")}), (F, {D: ("09-05", "10-05")})],
    "asparagus": [(S, {I: ("02-25", "05-10"), T: ("06-01", "06-20")})],
    "bean_asparagus": [(S, {I: ("03-31", "05-20"), T: ("05-20", "06-20")})],
    "bean_broad": [(S, {D: ("04-10", "06-01")}), (F, {D: ("09-05", "10-05")})],
    "bean_bush_pole": [(S, {D: ("06-01", "07-25")})],
    "bean_soya": [(S, {D: ("06-01", "06-30")})],
    "beet": [(S, {D: ("06-01", "07-25")})],
    "broccoli": [(S, {I: ("04-10", "04-30"), T: ("05-20", "06-05"), D: ("06-05", "06-30")})],
    "broccoli_sprouting": [(SU, {I: ("06-10", "06-20"), T: ("08-01", "08-15")})],
    "brussels_sprouts": [(S, {I: ("04-10", "04-20"), T: ("05-20", "05-31")})],
    "cabbage": [(S, {I: ("04-10", "04-30"), T: ("05-25", "06-05"), D: ("06-05", "06-30")})],
    "cabbage_overwinter": [(SU, {I: ("06-15", "07-15"), T: ("08-01", "08-15")})],
    "carrot": [(S, {D: ("05-10", "08-15")})],
    "cauliflower": [(S, {I: ("04-10", "04-30"), T: ("05-15", "06-01")})],
    "celery": [(S, {I: ("04-10", "04-30"), T: ("05-20", "06-05")})],
    "corn": [(S, {D: ("06-01", "06-30")})],
    "corn_salad": [(S, {D: ("04-10", "06-30")}), (F, {D: ("08-01", "09-10")})],
    "cress": [(S, {D: ("04-10", "06-15")}), (F, {D: ("08-01", "08-25")})],
    "cucumber": [(S, {I: ("05-01", "05-15"), T: ("06-01", "06-15")})],
    "eggplant": [(S, {I: ("05-01", "05-10"), T: ("06-01", "06-15")})],
    "endive": [(S, {I: ("04-01", "04-15"), T: ("05-20", "06-01")})],
    "radicchio": [(S, {I: ("04-01", "04-15"), T: ("05-20", "06-01")})],
    "fennel": [(S, {D: ("04-25", "07-15")})],
    "garlic": [(F, {D: ("09-01", "11-15")})],
    "kale": [(S, {D: ("05-10", "07-15")})],
    "kohlrabi": [(S, {I: ("04-10", "04-30"), T: ("05-20", "06-01")}), (SU, {D: ("07-15", "07-31")})],
    "leek": [(S, {I: ("03-15", "05-15"), T: ("05-15", "05-25"), D: ("05-25", "06-30")})],
    "lettuce": [(S, {I: ("04-10", "04-30"), T: ("05-01", "05-31"), D: ("06-01", "08-31")})],
    "melon": [(S, {I: ("05-15", "05-20"), T: ("06-10", "06-30")})],
    "mustard": [(S, {D: ("04-10", "06-30")}), (F, {D: ("08-01", "09-30")})],
    "okra": [(S, {I: ("04-20", "05-01"), T: ("05-20", "06-05")})],
    "onion": [(S, {I: ("02-20", "04-10"), T: ("05-15", "06-01")})],
    "onion_overwinter": [(SU, {I: ("07-01", "07-15"), T: ("08-01", "08-15")})],
    "scallion": [(S, {D: ("05-01", "08-15")})],
    "pac_choi": [(S, {D: ("04-10", "06-30"), V: ("04-10", "05-01")}), (SU, {D: ("08-01", "08-25")})],
    "parsnip": [(S, {D: ("04-25", "06-30")})],
    "pea": [(S, {D: ("04-05", "05-31")}), (SU, {D: ("06-15", "07-15")})],
    "pepper": [(S, {I: ("03-01", "03-25"), T: ("06-01", "06-25")})],
    "radish": [(S, {D: ("04-10", "05-31"), V: ("04-10", "05-01")}), (F, {D: ("09-01", "10-15")})],
    "rhubarb": [(S, {I: ("04-10", "05-10"), T: ("05-10", "08-01")})],
    "rutabaga": [(S, {D: ("06-01", "07-15")})],
    "spinach": [(S, {D: ("04-25", "06-15"), V: ("04-25", "05-15")}), (F, {D: ("08-01", "09-30"), V: ("09-01", "09-30")})],
    "squash": [(S, {I: ("05-01", "05-15"), D: ("05-15", "05-20"), T: ("05-25", "06-10")})],
    "strawberry": [(S, {I: ("01-01", "02-28"), T: ("05-01", "05-31")})],
    "swiss_chard": [(S, {D: ("05-15", "08-10")})],
    "tomato": [(S, {I: ("03-20", "04-10"), T: ("05-15", "06-05")})],
    "turnip": [(S, {D: ("05-15", "08-15")})],
}


def offset_from(mmdd, frost):
    """A calendar date as days from a chart's own frost dates."""
    last, first = (date(2001, *map(int, f.split("-"))) for f in frost)
    month, day = (int(p) for p in mmdd.split("-"))
    d = date(2001, month, day)
    if d.month < 7:
        return ("L", (d - last).days)
    return ("F", (d - first).days)


def chart_windows(chart, key):
    """A crop's windows in one chart as {season: {kind: [(anchor, days), ...]}}."""
    out = {}
    for season, w in chart.get(key, []):
        out[season] = {k: [offset_from(v[0], chart["frost"]), offset_from(v[1], chart["frost"])]
                       for k, v in w.items()}
    return out


def average(*sets):
    """Average windows from several charts, season by season and kind by kind."""
    merged = {}
    for windows in sets:
        for season, kinds in windows.items():
            for kind, ends in kinds.items():
                merged.setdefault(season, {}).setdefault(kind, []).append(ends)
    out = {}
    for season, kinds in merged.items():
        out[season] = {}
        for kind, all_ends in kinds.items():
            pair = []
            for i in (0, 1):
                anchors = [e[i][0] for e in all_ends]
                anchor = max(set(anchors), key=anchors.count)
                days = [e[i][1] for e in all_ends if e[i][0] == anchor]
                pair.append((anchor, round(sum(days) / len(days))))
            if pair[0] == pair[1] or (pair[0][0] == pair[1][0] and pair[1][1] < pair[0][1]):
                pair[1] = (pair[0][0], pair[0][1] + 7)
            out[season][kind] = pair
    return out


def coastal_windows(crop_dict):
    out = {}
    for w in crop_dict["windows"]:
        out[w["season"]] = {k: [(v[0][0], int(v[0][1:])), (v[1][0], int(v[1][1:]))]
                            for k, v in w.items() if k != "season"}
    return out


def fit_shift(profile_sets, tender):
    """Median change from the coastal timing for crops that appear in both,
    used to estimate crops (herbs, potato, tomatillo) a regional chart lacks."""
    deltas = {"L": [], "F": []}
    for c in C:
        if c["frost_tender"] != tender or c["key"] not in profile_sets:
            continue
        coast = coastal_windows(c)
        for season, kinds in profile_sets[c["key"]].items():
            for kind, ends in kinds.items():
                # Only sowing and planting-out dates drive the schedule.
                if kind not in ("direct", "transplant"):
                    continue
                if season in coast and kind in coast[season]:
                    for i in (0, 1):
                        a, b = coast[season][kind][i], ends[i]
                        if a[0] == b[0]:
                            deltas[a[0]].append(b[1] - a[1])
    med = {}
    for anchor, values in deltas.items():
        values.sort()
        med[anchor] = values[len(values) // 2] if values else 0
    return med


def shifted(windows, shift):
    out = {}
    for season, kinds in windows.items():
        out[season] = {k: [(a, d + shift[a]) for a, d in ends] for k, ends in kinds.items()}
    return out


def to_json(windows):
    return [{"season": season, **{k: [f"{a}{d:+d}" for a, d in ends] for k, ends in kinds.items()}}
            for season, kinds in windows.items()]


PROFILES = {
    "continental": [SOUTH_CENTRAL_BC, PRAIRIES],
    "atlantic": [MARITIMES],
}
for profile, charts in PROFILES.items():
    sets = {}
    for c in C:
        found = [chart_windows(ch, c["key"]) for ch in charts if c["key"] in ch]
        if found:
            sets[c["key"]] = average(*found)
    shifts = {t: fit_shift(sets, t) for t in (False, True)}
    for c in C:
        c.setdefault("profiles", {})
        if c["key"] in sets:
            windows = sets[c["key"]]
            # Keep coastal-only seasons out: a region's chart is the authority.
            c["profiles"][profile] = to_json(windows)
        else:
            c["profiles"][profile] = to_json(shifted(coastal_windows(c), shifts[c["frost_tender"]]))
            c.setdefault("estimated_profiles", []).append(profile)
    print(profile, "estimated shift from coastal:", shifts)

# ---------------------------------------------------------------------------
# Icons (Material Design Icons).
# ---------------------------------------------------------------------------
ICONS = {
    "carrot": "mdi:carrot", "parsnip": "mdi:carrot",
    "beet": "mdi:sprout", "radish": "mdi:sprout", "turnip": "mdi:sprout",
    "rutabaga": "mdi:sprout", "potato": "mdi:sprout",
    "corn": "mdi:corn", "pepper": "mdi:chili-mild", "tomato": "mdi:fruit-cherries",
    "tomatillo": "mdi:fruit-cherries", "eggplant": "mdi:food-variant",
    "cucumber": "mdi:food-variant", "melon": "mdi:fruit-watermelon",
    "squash": "mdi:pumpkin", "strawberry": "mdi:fruit-cherries",
    "rhubarb": "mdi:leaf", "asparagus": "mdi:sprout", "artichoke": "mdi:flower",
    "pea": "mdi:seed", "bean_broad": "mdi:seed", "bean_bush_pole": "mdi:seed",
    "bean_soya": "mdi:seed", "bean_asparagus": "mdi:seed",
    "onion": "mdi:sprout", "onion_overwinter": "mdi:sprout", "scallion": "mdi:sprout",
    "leek": "mdi:sprout", "garlic": "mdi:sprout",
    "broccoli": "mdi:tree", "broccoli_sprouting": "mdi:tree", "cauliflower": "mdi:tree",
    "cabbage": "mdi:leaf-circle", "cabbage_overwinter": "mdi:leaf-circle",
    "brussels_sprouts": "mdi:leaf-circle", "kohlrabi": "mdi:leaf-circle",
    "amaranth": "mdi:grain", "corn_salad": "mdi:leaf",
}
HERB = "mdi:spa"
LEAFY = "mdi:leaf"
for c in C:
    if c["key"] in ICONS:
        icon = ICONS[c["key"]]
    elif c["source"] == "pdf_herbs":
        icon = HERB
    else:
        icon = LEAFY
    c["icon"] = icon


# ---------------------------------------------------------------------------
# Planting defaults: what a new planting of the crop starts with. People can
# override these per crop in Home Assistant, and per planting.
# ---------------------------------------------------------------------------
SUCCESSION = {
    # key: (repeat every N days, number of sowings or None for the whole window)
    "arugula": (14, None), "cress": (14, None), "radish": (14, None), "spinach": (14, None),
    "mustard": (14, None), "lettuce": (14, None), "pac_choi": (21, None),
    "carrot": (21, None), "beet": (21, None), "turnip": (21, None), "kohlrabi": (21, None),
    "scallion": (21, None), "cilantro": (21, None), "dill": (21, None), "chervil": (21, None),
    "pea": (21, 3), "bean_bush_pole": (21, 4), "corn": (14, 3),
}
DIRECT_FIRST = {"lettuce", "scallion", "pac_choi", "cabbage", "kale", "chives", "shiso", "lemon_balm"}
for c in C:
    defaults = {}
    has_indoor = any("transplant" in w for w in c["windows"])
    has_direct = any("direct" in w for w in c["windows"])
    if has_direct and (not has_indoor or c["key"] in DIRECT_FIRST or c["key"] in SUCCESSION):
        defaults["method"] = "direct_bed"
    elif has_indoor:
        defaults["method"] = "indoor_bed"
    if c["key"] in SUCCESSION:
        days, count = SUCCESSION[c["key"]]
        defaults["succession_days"] = days
        if count:
            defaults["succession_count"] = count
    c["defaults"] = defaults

out = {
    "source": "South Coastal BC Vegetable and Flower & Herb Planting Guides (West Coast Seeds), plus added crops",
    "format": "Ranges are days from the last spring frost (L) or first fall frost (F).",
    "profiles": {
        "cool_spring": "South Coastal BC chart (long, cool spring)",
        "continental": "South Central BC and South Central Prairies charts, averaged (spring warms fast)",
        "atlantic": "Maritimes chart",
    },
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
# Replace the option list under every crop dropdown.
pattern = re.compile(
    r"(    crop:\n(?:      required: true\n)?      selector:\n        select:\n"
    r"          custom_value: true\n          options:\n)(?:              .*\n)+"
)
text, count = pattern.subn(lambda m: m.group(1) + options + "\n", text)
SERVICES.write_text(text, encoding="utf-8")
print(f"Crop options updated in {count} places in {SERVICES}")
