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

# q2 is split into URL-safe chunks (each ~5-8k encoded chars) to avoid HTTP 414.
# titanv.py iterates over all chunks and deduplicates results by corpus_id.
Q2_AND_BLOCK = """(
  "electricity" OR
  "electric power" OR
  "power system" OR
  "power grid" OR
  "energy system" OR
  "electric system" OR
  "electricity grid" OR
  "electric grid" OR
  "electric utility" OR
  "energy infrastructure" OR
  "generation infrastructure" OR
  "generation asset" OR
  "transmission infrastructure" OR
  "transmission system" OR
  "transmission asset" OR
  "distribution infrastructure" OR
  "distribution system" OR
  "distribution asset" OR
  "substation" OR
  "electric service" OR
  "megawatt" OR
  "kilowatt" OR
  "voltage" OR
  "service territory" OR
  "kilowatt-hour" OR
  "kWh" OR
  "megawatt-hour" OR
  "MWh" OR
  "gigawatt" OR
  "GW" OR
  "transformer" OR
  "feeder" OR
  "powerline" OR
  "power line" OR
  "electrification" OR
  "grid-connected" OR
  "grid connected" OR
  "off-grid" OR
  "bulk electric" OR
  "interconnection" OR
  "ISO" OR
  "independent system operator" OR
  "RTO" OR
  "regional transmission organization" OR
  "utility-scale" OR
  "behind-the-meter" OR
  "ratepayer" OR
  "load-serving"
)"""

Q2_NOT_BLOCK = """(
  "protein structure" OR
  "gene expression" OR
  "amino acid" OR
  "cell signaling" OR
  "neural circuit" OR
  "genome" OR
  "genomic" OR
  "transcriptome" OR
  "metabolome" OR
  "clinical trial" OR
  "patient outcome" OR
  "drug delivery" OR
  "pharmaceutical" OR
  "oncology" OR
  "tumor" OR
  "pathogen" OR

  "chemical reactor" OR
  "distillation column" OR
  "catalytic cracking" OR
  "reaction kinetics" OR
  "molar concentration" OR

  "mass spectrometry" OR
  "NMR spectroscopy" OR
  "X-ray diffraction" OR
  "emulsion polymerization" OR
  "radical polymerization"

  "stellar" OR
  "galactic" OR
  "exoplanet" OR
  "black hole" OR
  "neutron star" OR
  "dark matter" OR
  "dark energy" OR
  "redshift" OR

  "hadron" OR
  "quark" OR
  "lepton" OR
  "boson" OR
  "particle accelerator" OR
  "collider" OR
  "photoinjection" OR
  "tokamak" OR
  "magnetic confinement fusion" OR
  "inertial confinement fusion" OR
  "plasma confinement" OR

  "thin film deposition" OR
  "sputter" OR
  "epitaxial growth" OR
  "nanoparticle synthesis" OR
  "quantum dot" OR
  "CMOS" OR

  "microbial fuel cell" OR
  "microbial fuel cells" OR
  "sediment microbial" OR

  "perovskite" OR
  "hole transport layer" OR
  "hole transport layers" OR

  "half cell" OR
  "half-cell" OR
  "galvanostatic cycling" OR
  "galvanostatic cycle" OR
  "galvanostatic cell" OR
  "galvanostatic cells" OR
  "coulombic efficiency" OR
  "intercalation mechanism" OR
  "intercalation mechanisms" OR
  "electrolyte decomposition" OR
  "solid electrolyte interphase"
)"""


def _q2_chunk(or_block: str) -> str:
    return f"(\n{or_block}\n)"


# Chunk 01: Utility types (G1)
_Q2_CHUNK_01_OR = """(
    "electric utility" OR
    "electric cooperative" OR
    "electric co-op" OR
    "rural electric" OR
    "rural utility" OR
    "municipal utility" OR
    "municipal electric" OR
    "public utility" OR
    "public power" OR
    "investor-owned utility" OR
    "investor owned utility" OR
    "power utility" OR
    "energy utility" OR
    "utility company" OR
    "utility sector" OR
    "utility industry" OR
    "utility operations" OR
    "utility infrastructure" OR
    "utility planning" OR
    "load-serving entity" OR
    "load serving entity" OR
    "distribution utility" OR
    "vertically integrated utility" OR
    "small utility" OR
    "cooperative utility"
  )"""

# Chunk 02: Grid lines & conductors (G2a)
_Q2_CHUNK_02_OR = """(
    "power grid" OR
    "electric grid" OR
    "electrical grid" OR
    "electricity grid" OR
    "transmission line" OR
    "transmission system" OR
    "transmission network" OR
    "transmission infrastructure" OR
    "distribution line" OR
    "distribution system" OR
    "distribution network" OR
    "distribution feeder" OR
    "overhead line" OR
    "overhead conductor" OR
    "underground cable" OR
    "power line" OR
    "electric line" OR
    "high voltage transmission" OR
    "transmission tower" OR
    "transmission corridor" OR
    "distribution pole" OR
    "utility pole" OR
    "wood pole" OR
    "power pole" OR
    "lattice tower" OR
    "conductor sag" OR
    "conductor rating" OR
    "ampacity" OR
    "thermal rating" OR
    "dynamic line rating" OR
    "reconductoring"
  )"""

# Chunk 03: Grid equipment & modernization (G2b)
_Q2_CHUNK_03_OR = """(
    "grid hardening" OR
    "undergrounding" OR
    "substation" OR
    "distribution substation" OR
    "transmission substation" OR
    "power transformer" OR
    "distribution transformer" OR
    "transformer loading" OR
    "transformer aging" OR
    "transformer failure" OR
    "transformer overload" OR
    "switchgear" OR
    "circuit breaker" OR
    "recloser" OR
    "voltage regulator" OR
    "capacitor bank" OR
    "grid modernization" OR
    "grid resilience" OR
    "grid reliability" OR
    "grid vulnerability" OR
    "smart grid" OR
    "microgrid" OR
    "grid architecture" OR
    "distribution automation" OR
    "advanced metering" OR
    "AMI" OR
    "metering infrastructure" OR
    "SCADA" OR
    "supervisory control and data acquisition"
  )"""

# Chunk 04: Conventional generation (G3a)
_Q2_CHUNK_04_OR = """(
    "power plant" OR
    "power station" OR
    "power generation" OR
    "generating station" OR
    "electricity generation" OR
    "electric generation" OR
    "thermal power" OR
    "thermal plant" OR
    "thermal generation" OR
    "coal plant" OR
    "coal power" OR
    "coal generator" OR
    "natural gas plant" OR
    "gas turbine" OR
    "petroleum coke plant" OR
    "petroleum coke generator" OR
    "petroleum coke power" OR
    "fuel oil plant" OR
    "fuel oil generator" OR
    "fuel oil power" OR
    "combined cycle" OR
    "combustion turbine" OR
    "nuclear power" OR
    "nuclear plant" OR
    "nuclear generation" OR
    "hydroelectric" OR
    "hydropower" OR
    "hydroelectric power" OR
    "pumped storage"
  )"""

# Chunk 05: Renewable generation (G3b)
_Q2_CHUNK_05_OR = """(
    "solar power" OR
    "solar generation" OR
    "photovoltaic" OR
    "solar farm" OR
    "solar panel" OR
    "utility-scale solar" OR
    "distributed solar" OR
    "rooftop solar" OR
    "wind power" OR
    "wind generation" OR
    "wind farm" OR
    "wind turbine" OR
    "offshore wind" OR
    "onshore wind" OR
    "wind energy" OR
    "geothermal plant" OR
    "geothermal power" OR
    "geothermal generation" OR
    "battery storage" OR
    "energy storage" OR
    "grid-scale storage" OR
    "battery energy storage" OR
    "distributed energy resource" OR
    "distributed generation"
  )"""

# Chunk 06: Generation economics & water nexus (G3c)
_Q2_CHUNK_06_OR = """(
    "cogeneration" OR
    "combined heat and power" OR
    "peaking plant" OR
    "baseload generation" OR
    "capacity factor" OR
    "renewable energy" OR
    "renewable generation" OR
    "clean energy" OR
    "methane generator" OR
    "decarbonization" OR
    "resource adequacy" OR
    "flywheel energy storage" OR
    "cooling water" OR
    "once-through cooling" OR
    "cooling tower" OR
    "water-energy nexus" OR
    "water energy nexus" OR
    "water withdrawal" OR
    "water consumption" OR
    "thermal discharge" OR
    "intake temperature" OR
    "condenser cooling"
  )"""

# Chunk 07: Outages & interruptions (G4a)
_Q2_CHUNK_07_OR = """(
    "power outage" OR
    "electric outage" OR
    "electricity outage" OR
    "power interruption" OR
    "service interruption" OR
    "service restoration" OR
    "outage management" OR
    "outage duration" OR
    "outage frequency" OR
    "customer outage" OR
    "widespread outage" OR
    "major event day" OR
    "SAIDI" OR
    "SAIFI" OR
    "CAIDI" OR
    "MAIFI" OR
    "reliability index" OR
    "reliability metric" OR
    "system reliability" OR
    "electric reliability" OR
    "power system reliability" OR
    "bulk power system" OR
    "power system operation"
  )"""

# Chunk 08: Grid operations & restoration (G4b)
_Q2_CHUNK_08_OR = """(
    "grid operation" OR
    "system operator" OR
    "economic dispatch" OR
    "unit commitment" OR
    "load balancing" OR
    "frequency regulation" OR
    "voltage stability" OR
    "power quality" OR
    "power system stability" OR
    "islanding" OR
    "black start" OR
    "load shedding" OR
    "blackout" OR
    "system collapse" OR
    "brownout" OR
    "cascading failure" OR
    "system restoration" OR
    "crew deployment" OR
    "storm response" OR
    "emergency response" OR
    "NERC" OR
    "North American Electric Reliability Corporation" OR
    "situational awareness"
  )"""

# Chunk 09: Resource & capacity planning (G5a)
_Q2_CHUNK_09_OR = """(
    "integrated resource plan" OR
    "integrated resource planning" OR
    "capacity expansion" OR
    "generation planning" OR
    "resource planning" OR
    "transmission planning" OR
    "distribution planning" OR
    "system planning" OR
    "electric infrastructure planning" OR
    "power infrastructure planning" OR
    "capital planning" OR
    "load forecast" OR
    "load forecasting" OR
    "demand forecast" OR
    "demand forecasting" OR
    "peak demand" OR
    "peak load" OR
    "peak shaving" OR
    "load growth" OR
    "load profile" OR
    "load duration curve" OR
    "electricity demand" OR
    "electric demand" OR
    "power demand" OR
    "energy demand"
  )"""

# Chunk 10: Markets & grid integration (G5b)
_Q2_CHUNK_10_OR = """(
    "capacity planning" OR
    "reserve margin" OR
    "planning reserve" OR
    "loss of load" OR
    "loss-of-load" OR
    "expected unserved energy" OR
    "capacity market" OR
    "energy market" OR
    "electricity market" OR
    "wholesale market" OR
    "ancillary services" OR
    "electricity price" OR
    "wholesale electricity" OR
    "locational marginal price" OR
    "congestion management" OR
    "interconnection queue" OR
    "interconnection process" OR
    "interconnection agreement" OR
    "hosting capacity" OR
    "DER integration" OR
    "distributed energy integration" OR
    "grid integration" OR
    "renewable integration" OR
    "inverter-based resource" OR
    "inverter based resource" OR
    "grid-forming inverter" OR
    "grid forming inverter"
  )"""

# Chunk 11: Asset condition & maintenance (G6a)
_Q2_CHUNK_11_OR = """(
    "asset management" OR
    "infrastructure aging" OR
    "aging infrastructure" OR
    "equipment failure" OR
    "equipment reliability" OR
    "preventive maintenance" OR
    "predictive maintenance" OR
    "condition-based maintenance" OR
    "asset life" OR
    "asset replacement" OR
    "failure rate" OR
    "failure analysis" OR
    "line sagging" OR
    "inspection program" OR
    "vegetation management" OR
    "tree trimming" OR
    "right-of-way" OR
    "right of way" OR
    "tree-caused outage" OR
    "vegetation contact" OR
    "tree encroachment" OR
    "wildfire mitigation plan" OR
    "public safety power shutoff" OR
    "PSPS" OR
    "de-energization" OR
    "fire risk" OR
    "ignition risk"
  )"""

# Chunk 12: Physical damage & degradation (G6b)
_Q2_CHUNK_12_OR = """(
    "utility-caused wildfire" OR
    "utility wildfire" OR
    "wire down" OR
    "downed wire" OR
    "downed conductor" OR
    "pole failure" OR
    "structure failure" OR
    "crossarm failure" OR
    "insulator failure" OR
    "lightning arrester" OR
    "surge arrester" OR
    "conductor corrosion" OR
    "pole corrosion" OR
    "equipment corrosion" OR
    "weather degradation" OR
    "weather-related degradation" OR
    "environmental degradation" OR
    "UV degradation" OR
    "material weathering" OR
    "pole weathering" OR
    "conductor weathering" OR
    "equipment weathering" OR
    "flood damage" OR
    "wind damage" OR
    "ice loading" OR
    "galloping" OR
    "aeolian vibration"
  )"""

# Chunk 13: Demand-side management & DERs (G7)
_Q2_CHUNK_13_OR = """(
    "demand response" OR
    "demand-side management" OR
    "demand side management" OR
    "load management" OR
    "load control" OR
    "interruptible load" OR
    "curtailable load" OR
    "energy efficiency" OR
    "energy conservation" OR
    "weatherization" OR
    "building energy" OR
    "building electrification" OR
    "transportation electrification" OR
    "vehicle electrification" OR
    "electric vehicle" OR
    "EV charging" OR
    "heat pump" OR
    "behind-the-meter" OR
    "behind the meter" OR
    "net metering" OR
    "net energy metering" OR
    "time-of-use" OR
    "time of use" OR
    "critical peak pricing" OR
    "load flexibility" OR
    "flexible load" OR
    "virtual power plant"
  )"""

# Chunk 14: Utility regulation & policy (G8)
_Q2_CHUNK_14_OR = """(
    "public utility commission" OR
    "public service commission" OR
    "utility regulation" OR
    "utility regulator" OR
    "rate case" OR
    "rate design" OR
    "rate structure" OR
    "cost of service" OR
    "performance-based regulation" OR
    "performance based regulation" OR
    "resilience standard" OR
    "reliability standard" OR
    "NERC standard" OR
    "NERC reliability" OR
    "interconnection standard" OR
    "grid code" OR
    "utility compliance" OR
    "renewable portfolio standard" OR
    "clean energy standard" OR
    "energy policy" OR
    "electricity policy" OR
    "utility investment"
  )"""

# Chunk 15: System resilience & climate risk (G9a)
_Q2_CHUNK_15_OR = """(
    "power system resilience" OR
    "grid resilience" OR
    "infrastructure resilience" OR
    "energy resilience" OR
    "electric system resilience" OR
    "utility resilience" OR
    "climate adaptation" OR
    "climate risk" OR
    "climate vulnerability" OR
    "climate impact" OR
    "weather impact" OR
    "extreme weather" OR
    "weather-related" OR
    "weather related" OR
    "climate resilience" OR
    "disaster preparedness" OR
    "disaster recovery" OR
    "business continuity" OR
    "continuity of operations" OR
    "infrastructure vulnerability" OR
    "infrastructure risk" OR
    "risk assessment" OR
    "vulnerability assessment" OR
    "consequence analysis" OR
    "threat assessment"
  )"""

# Chunk 16: Hardening, standards & financial resilience (G9b)
_Q2_CHUNK_16_OR = """(
    "asset hardening" OR
    "system hardening" OR
    "flood protection" OR
    "wind loading" OR
    "design standard" OR
    "engineering standard" OR
    "NESC" OR
    "national electrical safety code" OR
    "ASCE 7" OR
    "design wind speed" OR
    "return period" OR
    "climate scenario" OR
    "future climate" OR
    "climate projection" OR
    "utility insurance" OR
    "self-insurance" OR
    "catastrophe risk" OR
    "financial resilience" OR
    "cost recovery" OR
    "storm cost" OR
    "disaster cost" OR
    "restoration cost" OR
    "resilience investment" OR
    "resilience benefit" OR
    "avoided cost"
  )"""

# Chunk 17: Energy equity & community impact (G10)
_Q2_CHUNK_17_OR = """(
    "energy burden" OR
    "energy poverty" OR
    "energy insecurity" OR
    "energy equity" OR
    "energy justice" OR
    "environmental justice" OR
    "vulnerable population" OR
    "disadvantaged community" OR
    "underserved community" OR
    "frontline community" OR
    "customer impact" OR
    "service territory" OR
    "ratepayer" OR
    "community resilience" OR
    "critical facility" OR
    "critical load"
  )"""

# Chunk 18: Workforce & organizations (G11 + G12)
_Q2_CHUNK_18_OR = """(
    "utility workforce" OR
    "lineworker" OR
    "line worker" OR
    "lineman" OR
    "journeyman lineman" OR
    "apprentice lineman" OR
    "workforce development" OR
    "workforce planning" OR
    "skilled trades" OR
    "workforce shortage" OR
    "heat illness" OR
    "occupational health" OR
    "worker safety" OR
    "field crew" OR
    "organizational resilience" OR
    "institutional capacity"
  )
  OR
  (
    "independent system operator" OR
    "regional transmission organization" OR
    "balancing authority" OR
    "reliability coordinator" OR
    "planning authority" OR
    "FERC" OR
    "Federal Energy Regulatory Commission" OR
    "DOE" OR
    "Department of Energy" OR
    "EPRI" OR
    "Electric Power Research Institute" OR
    "APPA" OR
    "American Public Power Association" OR
    "NRECA" OR
    "National Rural Electric Cooperative Association" OR
    "EEI" OR
    "Edison Electric Institute" OR
    "IEEE" OR
    "Institute of Electrical and Electronics Engineers"
  )"""

# Chunk 19: Cybersecurity (G13)
_Q2_CHUNK_19_OR = """(
    "grid cybersecurity" OR
    "cyber-physical security" OR
    "grid security" OR
    "physical security" OR
    "cyber attack" OR
    "cyberattack"
  )"""

# Chunk 20: Federal programs & disaster funding (G14)
_Q2_CHUNK_20_OR = """(
    "FEMA" OR
    "Federal Emergency Management Agency" OR
    "hazard mitigation grant" OR
    "hazard mitigation plan" OR
    "BRIC" OR
    "Building Resilient Infrastructure and Communities" OR
    "community development block grant" OR
    "disaster declaration" OR
    "public assistance program" OR
    "infrastructure investment" OR
    "Bipartisan Infrastructure Law" OR
    "IIJA" OR
    "Infrastructure Investment and Jobs Act"
  )"""


q2_chunks = [
    _q2_chunk(_Q2_CHUNK_01_OR),
    _q2_chunk(_Q2_CHUNK_02_OR),
    _q2_chunk(_Q2_CHUNK_03_OR),
    _q2_chunk(_Q2_CHUNK_04_OR),
    _q2_chunk(_Q2_CHUNK_05_OR),
    _q2_chunk(_Q2_CHUNK_06_OR),
    _q2_chunk(_Q2_CHUNK_07_OR),
    _q2_chunk(_Q2_CHUNK_08_OR),
    _q2_chunk(_Q2_CHUNK_09_OR),
    _q2_chunk(_Q2_CHUNK_10_OR),
    _q2_chunk(_Q2_CHUNK_11_OR),
    _q2_chunk(_Q2_CHUNK_12_OR),
    _q2_chunk(_Q2_CHUNK_13_OR),
    _q2_chunk(_Q2_CHUNK_14_OR),
    _q2_chunk(_Q2_CHUNK_15_OR),
    _q2_chunk(_Q2_CHUNK_16_OR),
    _q2_chunk(_Q2_CHUNK_17_OR),
    _q2_chunk(_Q2_CHUNK_18_OR),
    _q2_chunk(_Q2_CHUNK_19_OR),
    _q2_chunk(_Q2_CHUNK_20_OR),
]
