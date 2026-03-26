RESILIENCE_SEARCHES = [
    "Extreme Heat Climate",
    "Extreme Cold Climate",
    "Heat Wave Climate",
    "Drought",
    "Flooding",
    "Tropical Cyclone",
    "Hurricane",
    "Wildfire",
    "Convective Storm",
    "Sea Level Rise",
    "Permafrost Thaw",
    "Ocean Acidification",
    "Carbon Dioxide Fertilizer",
    "Rising Ocean Temperature",
    "Snowmelt Timing",
    "Arctic Sea Ice",
    "Ice Storm",
    "Derecho",
    "Tornado",
    "Extreme Wind",
    "Urban Heat Island",
    "Coastal Flooding",
    "Extreme Rainfall",
    "Blizzard",
]

YEAR_RANGES = [
    ["2000", "2005"],
    ["2005", "2010"],
    ["2010", "2015"],
    ["2015", "2020"],
    ["2020", "2025"],
]

cat = """
Heat
Cold
Flooding
Drought
Wildfire
Tropical Cyclone/Hurricane
Convective Storm
Sea Level / oceans / cryosphere
"""

q = """
(
  (
    "extreme heat" OR
    "heat mortality" OR
    "wet-bulb temperature" OR
    "extreme temperature" OR
    "heat wave" OR
    heatwave OR
    "heat stress" OR
    "hot temperature" OR
    "high temperature" OR
    "temperature extreme" OR
    "heat index" OR
    "urban heat island" OR
    "urban warming"
  )
  OR
  (
    "extreme cold" OR
    "cold wave" OR
    "cold spell" OR
    "freeze event" OR
    "winter storm" OR
    frost OR
    snowstorm OR
    "hard freeze" OR
    "ice storm" OR
    blizzard
  )
  OR
  (
    flood OR
    "flash flood" OR
    "river flood" OR
    "urban flooding" OR
    "coastal flooding" OR
    "compound flooding" OR
    inundation OR
    "storm surge" OR
    "heavy precipitation" OR
    "pluvial flooding" OR
    "riverine flooding" OR
    "extreme rainfall"
  )
  OR
  (
    drought OR
    "water scarcity" OR
    "hydrologic drought" OR
    "agricultural drought" OR
    "meteorological drought" OR
    "snow drought"
  )
  OR
  (
    wildfire OR
    "forest fire" OR
    bushfire OR
    "fire weather" OR
    "wildland fire" OR
    "wildfire smoke" OR
    "smoke exposure"
  )
  OR
  (
    "tropical cyclone" OR
    hurricane OR
    typhoon OR
    "cyclonic storm"
  )
  OR
  (
    "convective storm" OR
    "severe convective storm" OR
    thunderstorm OR
    "severe thunderstorm" OR
    hail OR
    "straight-line wind" OR
    downburst OR
    microburst OR
    tornado OR
    "extreme wind"
  )
  OR
  (
    "sea level rise" OR
    "coastal erosion" OR
    salinization OR
    "saltwater intrusion" OR
    "ocean warming" OR
    "rising ocean temperature" OR
    "marine heatwave" OR
    "ocean acidification"
  )
  OR
  (
    "sea ice loss" OR
    "glacial melt" OR
    "permafrost thaw" OR
    "snowmelt timing" OR
    "arctic sea ice"
  )
  OR
  (
    "carbon dioxide fertilization" OR
    "CO2 fertilization"
  )
  OR
  (
    "crop failure" OR
    "crop yield" OR
    "ecosystem services"
  )
)
AND
(
  climate OR
  weather OR
  hazard OR
  resilience OR
  adaptation OR
  vulnerability OR
  mitigation OR
  preparedness OR
  forecast OR
  recovery OR
  response OR
  exposure OR
  risk OR
  infrastructure OR
  community OR
  ecosystem OR
  "public health" OR
  planning OR
  disaster OR
  policy OR
  governance OR
  sustainability
)
"""

counts_init = {
    "Extreme Heat Climate": 14,
    "Extreme Cold Climate": 61,
    "Heat Wave Climate": 4,
    "Drought": 173524,
    "Flooding Climate": 70,
    "Tropical Cyclone": 5188,
    "Hurricane": 22584,
    "Wildfire": 15363,
    "Convective Storm": 651,
    "Sea Level Rise": 20201,
    "Permafrost Thaw": 1762,
    "Ocean Acidification": 8286,
    "Carbon Dioxide Fertilizer": 3,
    "Rising Ocean Temperature": 42,
    "Snowmelt Timing": 296,
    "Arctic Sea Ice": 4113,
    "Ice Storm": 526,
    "Derecho": 47105,
    "Tornado": 20113,
    "Extreme Wind": 2112,
    "Urban Heat Island": 8618,
    "Coastal Flooding": 3159,
    "Extreme Rainfall": 7803,
    "Blizzard": 2326,
}
