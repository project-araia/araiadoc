RESILIENCE_SEARCHES = [
    "Extreme Heat",
    "Extreme Cold",
    "Heat Waves",
    "Drought",
    "Flooding",
    "Tropical Cyclone",
    "Hurricane",
    "Wildfires",
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
    "Coastal Flooding",  # terms from here onward from jlnav
    "Extreme Rainfall",
    "Blizzard",
    "Climate",
]

YEAR_RANGES = [
    ["2000", "2005"],
    ["2005", "2010"],
    ["2010", "2015"],
    ["2015", "2020"],
    ["2020", "2025"],
]

# for term in search_terms:             # KNOWN
#     for range in year_ranges:         # KNOWN
#         for page in result_pages:     # UNKNOWN
#             for document in page:     # UNKNOWN

# could probably just cache result_page

# index = [term, range, page, document]
# e.g. index = ["Extreme Heat", "2000-2005", 4, 8]
