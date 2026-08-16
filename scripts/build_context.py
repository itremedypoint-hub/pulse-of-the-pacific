#!/usr/bin/env python3
"""Build curated context datasets: major events, teleconnection impacts, RONI comparison."""
import json

# Major historical El Nino events with peak ONI and documented consequences (from the research reports).
events = [
  {"period":"1877-78","peak":None,"strength":"Very strong (historical)","flavor":"EP",
   "note":"Among the strongest in the ERSSTv5 historical record; linked to global drought and famines estimated to have killed tens of millions. 19th-century data is sparse, so magnitude is uncertain."},
  {"period":"1972-73","peak":2.1,"strength":"Strong","flavor":"EP",
   "note":"Collapse of the Peruvian anchoveta fishery; a benchmark event for early ENSO science."},
  {"period":"1982-83","peak":2.2,"strength":"Very strong","flavor":"EP",
   "note":"~$4.1T in global income losses over the following ~5 years (Callahan & Mankin 2023). Severe global disruption; arrived largely unforecast."},
  {"period":"1997-98","peak":2.4,"strength":"Very strong","flavor":"EP",
   "note":"First El Nino tracked end-to-end in real time. ~$5.7T in global income losses over ~5 years. Major floods, droughts, and coral bleaching worldwide."},
  {"period":"2009-10","peak":1.6,"strength":"Moderate-strong","flavor":"CP",
   "note":"A prominent Central Pacific ('Modoki') event with teleconnections distinct from canonical events."},
  {"period":"2015-16","peak":2.6,"strength":"Very strong","flavor":"EP",
   "note":"Tied among the strongest on record. Drove record global heat, the 2014-17 global coral bleaching event, Indonesian peat fires, and the Amazon drought."},
  {"period":"2023-24","peak":2.0,"strength":"Strong","flavor":"EP",
   "note":"Among the five strongest on record. Contributed to record 2024 global temperatures and the fourth global coral bleaching event. Under the new RONI index it reads ~+1.5C, though real-world impacts were unchanged."},
  {"period":"2026-27","peak":None,"strength":"Developing","flavor":"TBD",
   "note":"El Nino Advisory in effect as of June 2026; conditions present and expected to strengthen into NH winter 2026-27. Impacts remain probabilistic."},
]

# Regional teleconnection impacts (DJF / boreal-winter canonical tendencies).
# coords are [lon, lat] approximate centroids for map markers.
impacts = [
  {"region":"Coastal Peru & Ecuador","coord":[-78,-6],"effect":"flood","sev":3,
   "txt":"Much higher odds of heavy rain and flooding as warm water and convection shift east. Strongest in Eastern-Pacific events."},
  {"region":"Indonesia & Malaysia","coord":[114,0],"effect":"drought","sev":3,
   "txt":"Suppressed convection brings drought, heat, and elevated fire/haze risk."},
  {"region":"Eastern Australia","coord":[147,-25],"effect":"drought","sev":3,
   "txt":"Reduced winter-spring rainfall, delayed monsoon, heightened bushfire risk."},
  {"region":"Southern Africa","coord":[26,-24],"effect":"drought","sev":3,
   "txt":"Negative rainfall and positive temperature anomalies; severe risk to rain-fed agriculture."},
  {"region":"Equatorial East Africa","coord":[38,0],"effect":"flood","sev":2,
   "txt":"Wetter 'short rains', especially when reinforced by a positive Indian Ocean Dipole."},
  {"region":"Southern United States","coord":[-95,31],"effect":"flood","sev":2,
   "txt":"On average wetter, cooler, stormier winter as the Pacific jet strengthens and shifts south."},
  {"region":"Pacific Northwest","coord":[-121,46],"effect":"drought","sev":1,
   "txt":"Tends toward milder, drier conditions than normal."},
  {"region":"Amazon Basin","coord":[-60,-4],"effect":"drought","sev":2,
   "txt":"Drought and elevated fire risk; can flip the tropical biosphere to a net carbon source."},
  {"region":"India","coord":[79,22],"effect":"drought","sev":2,
   "txt":"Tendency toward a weaker/delayed summer monsoon, though the relationship is non-stationary."},
  {"region":"Northeast Brazil","coord":[-40,-8],"effect":"drought","sev":2,
   "txt":"Reduced rainfall and drought risk."},
  {"region":"Southeastern South America","coord":[-58,-31],"effect":"flood","sev":2,
   "txt":"Increased odds of higher mean and extreme rainfall."},
  {"region":"Atlantic Hurricane Basin","coord":[-50,20],"effect":"calm","sev":2,
   "txt":"Hurricane activity is generally suppressed by increased vertical wind shear (exceptions occur)."},
  {"region":"Central/East Pacific","coord":[-130,15],"effect":"storm","sev":2,
   "txt":"Tropical cyclone activity tends to increase relative to the Atlantic."},
]

# RONI comparison: selected seasons showing ONI vs RONI divergence (illustrative, from research).
roni_compare = [
  {"period":"1997-98 peak (NDJ)","oni":2.4,"roni":2.2},
  {"period":"2015-16 peak (NDJ)","oni":2.6,"roni":2.2},
  {"period":"2023-24 peak (DJF)","oni":2.0,"roni":1.5},
]

for name,obj in [("events",events),("impacts",impacts),("roni_compare",roni_compare)]:
    with open(f"public/data/{name}.json","w") as f:
        json.dump(obj,f,separators=(",",":"))
    print(f"Wrote {name}.json ({len(obj)} items)")
