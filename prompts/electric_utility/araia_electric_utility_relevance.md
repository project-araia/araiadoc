Judge whether this document is relevant to the electric power and utility sector — the
generation, transmission, distribution, operation, planning, reliability, resilience,
regulation, workforce, or community service of electricity, including how the power system
copes with weather, climate, and other hazards.

Definitions (as used in this context):
- Electric utility: an organization that generates, transmits, or distributes electricity to customers (e.g., investor-owned, municipal, cooperative, or public power utility).
- Power grid: the interconnected system of generation, transmission lines, substations, transformers, and distribution lines that delivers electricity.
- Generation: producing electricity, including coal, natural gas, nuclear, hydropower, solar, wind, geothermal, and storage.
- Reliability: the ability of the power system to deliver electricity without interruption (e.g., outages, SAIDI/SAIFI, reserve margins).
- Resilience: the ability of the power system or utility to withstand, recover from, or adapt to a disruptive event such as a storm, flood, wildfire, or extreme-temperature event.
- Planning: utility resource, capacity, transmission, or distribution planning, including load and demand forecasting.
- Regulation: institutional or policy arrangements governing utilities (e.g., public utility commissions, rate cases, reliability standards). Corporate, data, or AI governance do not qualify.
- Risk: the likelihood and/or magnitude of harm to the power system, its customers, or the electricity service it provides. Pure financial risk, medical risk, or unrelated engineering reliability not tied to electricity service does not qualify.

THE CORE TEST — apply this first, before anything else. A document is RELEVANT only if it is true that:

- POWER SECTOR: the document substantively involves the electric power or utility sector
  (see topics below), AND it does so as a real focus of the work — not merely as an example,
  application, or passing mention.

If the power-sector connection is missing, weak, or only mentioned in passing, the document is NOT relevant (mark `maybe` or `irrelevant`).
**Do not judge relevance from isolated keywords.**

Electric power and utility topics include:

- utilities and ownership: electric utilities, electric cooperatives, municipal utilities, public power, investor-owned utilities, rural electric, load-serving entities
- the grid: power grids, transmission lines and towers, distribution lines and feeders, substations, transformers, switchgear, conductors, undergrounding, grid hardening, smart grids, microgrids, SCADA, advanced metering
- generation: power plants and stations, coal/gas/nuclear/hydropower, solar PV, wind, geothermal, battery and energy storage, distributed energy resources, cooling water and the water-energy nexus
- reliability and operations: power outages, service interruption and restoration, reliability indices (SAIDI, SAIFI, CAIDI), blackouts, load shedding, cascading failures, grid operations, dispatch, frequency and voltage stability, storm response
- planning and markets: integrated resource planning, capacity expansion, transmission/distribution planning, load and demand forecasting, peak demand, capacity and energy markets, interconnection, grid integration of renewables
- assets and maintenance: asset management, aging infrastructure, equipment failure, preventive/predictive maintenance, vegetation management, right-of-way, wildfire mitigation plans, public safety power shutoffs (PSPS), physical damage (downed wires, pole failure, ice loading, flood/wind damage)
- demand-side: demand response, demand-side management, energy efficiency, weatherization, electrification, electric vehicles and charging, heat pumps, net metering, time-of-use pricing
- regulation and policy: public utility commissions, rate cases and design, reliability and resilience standards (NERC, NESC), renewable portfolio standards, utility investment and cost recovery
- resilience and climate risk: power-system and grid resilience, climate adaptation and risk for utilities, extreme-weather impacts on the grid, hardening and design standards, disaster preparedness and recovery for utilities
- equity, workforce, and institutions: energy burden/poverty/justice as it affects electricity customers, community resilience and critical loads, the utility workforce (lineworkers, occupational/heat safety), and sector institutions (FERC, DOE, EPRI, NERC, FEMA programs for grid/infrastructure)
- cybersecurity and physical security of the grid

Decision and score — these **MUST agree**. Choose the score first, then set `decision` from it:

- score 3 -> decision "relevant": Strongly relevant. The electric power or utility sector is the central focus of the document.
- score 2 -> decision "relevant": Relevant. The power-sector connection is clear and substantive but secondary to a broader topic (e.g., a multi-sector infrastructure study that covers the grid well, or a methods paper whose case study is a real power-system problem).
- score 1 -> decision "maybe": Partial or indirect. The power sector appears but is underdeveloped, OR the document is about energy in general with only a weak link to electricity utilities/grids. Potentially useful but unclear.
- score 0 -> decision "irrelevant": No meaningful electric power or utility content.

**Never pair a high score with "irrelevant" or a 0 score with "relevant".**

Common false positives to mark IRRELEVANT unless they explicitly center on the electric power or utility sector:

- Materials, chemistry, or device papers that hit a keyword but are about the material itself, not the power system — e.g., "perovskite" or "solar cell" chemistry, battery electrochemistry ("half-cell", "galvanostatic", "coulombic efficiency", "solid electrolyte interphase"), microbial fuel cells, quantum dots, thin-film deposition.
- Papers that mention electricity, power, or the grid only as background motivation but focus on unrelated methods, materials, biology, chemistry, physics, or computing.
- Biomedical, genomics, clinical, or pharmaceutical papers (protein structure, gene expression, clinical trials, tumors, pathogens).
- Astrophysics, particle physics, or fusion/plasma papers (stellar, black hole, dark matter, hadron, quark, tokamak, magnetic/inertial confinement fusion).
- Chemical-engineering or spectroscopy papers (chemical reactors, distillation, reaction kinetics, mass spectrometry, NMR, X-ray diffraction, polymerization).
- Documents where words like "power," "grid," "load," "transmission," "distribution," or "outage" are used only metaphorically or in an unrelated technical sense (e.g., "transmission" of disease, "distribution" in statistics, "grid" in image processing).
- General energy, sustainability, or climate papers with no clear connection to electricity utilities, the grid, or power generation/delivery.

Important judging guidance:

- **When uncertain between two scores, pick the LOWER one. Prefer precision over recall.**
- Positive descriptive test: ask "does this document describe something about how electricity is generated, delivered, planned for, operated, regulated, or kept reliable and resilient?"
  If yes, the power sector is real here. If the power sector is only cited as motivation and the rest of the document could proceed without it, it is not substantive -> not relevant.
- Judge only from the provided evidence. Sectionized text may omit references and some details; **do not assume content that is not shown.**
- A document can be relevant even if it is about policy, regulation, economics, workforce, equity, or planning rather than engineering, as long as the electric power or utility connection is clear.
- A document about a hazard (storm, flood, wildfire, heat, cold) is relevant only when it connects to the power system or a utility (e.g., grid damage, outages, restoration, hardening). A hazard study with no power-sector tie is NOT relevant here.
- If the title/abstract are vague but multiple sections substantively discuss power-sector content, mark relevant.
- If only one weak sentence mentions the power sector and the rest is unrelated, mark irrelevant.

Examples (decision / score / why):

- "Grid Hardening and Restoration Strategies for Distribution Systems After Hurricanes"
  -> relevant / 3. The power system (distribution grid) and its resilience to a hazard are the central focus.
- "Integrated Resource Planning Under Uncertain Peak Demand for a Municipal Utility"
  -> relevant / 3. Utility planning and load forecasting are the central focus; no hazard needed.
- "Reliability Indices and Outage Causes Across U.S. Electric Cooperatives"
  -> relevant / 3. Outages, reliability metrics, and utilities are the core subject.
- "Multi-Sector Critical Infrastructure Interdependencies During Extreme Weather"
  -> relevant / 2. The grid is covered substantively as one of several systems; power-sector tie is clear but shared with other sectors.
- "Techno-economic Analysis of Perovskite Solar Cells for Improved Efficiency"
  -> irrelevant / 0. Materials/device chemistry. "Solar" appears, but it is about the cell material, not power generation or the grid.
- "Galvanostatic Cycling Behavior of a New Lithium-Ion Cathode"
  -> irrelevant / 0. Battery electrochemistry; "energy storage" keyword does not make it about the power sector.
- "Transmission Dynamics of a Foodborne Pathogen in Poultry"
  -> irrelevant / 0. "Transmission" is unrelated technical usage; biomedical topic.
- "Drought Impacts on Reservoir Ecosystems in the Southwest"
  -> maybe / 1. A real hazard, but no electric power or utility connection (no hydropower, cooling water, or grid tie shown). Out of scope unless a power-sector link appears.
- "National Energy Outlook: Primary Fuel Mix and Emissions Projections"
  -> maybe / 1. Energy in general with only a weak, indirect link to electricity utilities or the grid.
