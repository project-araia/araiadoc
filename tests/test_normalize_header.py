"""
Tests for _normalize_header and apply_synonyms against rows extracted from
resilience_normalization_pipeline.xlsx.

Run with:
    pixi run -e dev python tests/test_normalize_header.py
"""

from araiadoc.text_quality.content_assessment import _normalize_header, apply_synonyms


def _n(raw: str) -> str:
    """Normalize then apply synonyms."""
    return apply_synonyms(_normalize_header(raw))


# ---------------------------------------------------------------------------
# (raw_key, expected_after_normalize_only, description)
# Expected is what _normalize_header alone should produce (pre-synonym).
# ---------------------------------------------------------------------------
NORMALIZE_CASES = [
    # Introduction variants
    ("Introduction", "introduction", "Base form"),
    ("INTRODUCTION", "introduction", "All-caps"),
    ("I. INTRODUCTION", "i. introduction", "Roman prefix I (numeral retained)"),
    ("| INTRODUC TI ON", "introduction", "Pipe + OCR space"),
    ("| INTRODUCTION", "introduction", "Pipe prefix"),
    ("\u00e2 INTRODUCTION", "introduction", "Unicode garbage prefix"),
    (". Introduction", "introduction", "Stray dot"),
    ("Introduction \u00ef", "introduction", "Trailing unicode garbage"),
    ("1.Introduction", "1. introduction", "Digit prefix no space (numeral retained)"),
    ("IntroductIon", "introduction", "Mixed case"),
    ("I N T RO D U C T I O N", "introduction", "Extreme OCR spacing"),
    ("introduction", "introduction", "Already lowercase"),
    # Results variants
    ("Results", "results", "Results base form"),
    ("RESULTS", "results", "Results all-caps"),
    ("| RE SULTS", "results", "Results pipe + OCR space"),
    ("III. RESULTS", "iii. results", "Results roman prefix III (numeral retained)"),
    ("IV. RESULTS", "iv. results", "Results roman prefix IV (numeral retained)"),
    ("V. RESULTS", "v. results", "Results roman prefix V (numeral retained)"),
    ("II. RESULTS", "ii. results", "Results roman prefix II (numeral retained)"),
    ("Result", "result", "Results singular"),
    ("RESULT", "result", "Results all-caps singular"),
    ("results", "results", "Results already lowercase"),
    # Discussion variants
    ("Discussion", "discussion", "Discussion base form"),
    ("DISCUSSION", "discussion", "Discussion all-caps"),
    ("| DISCUSSION", "discussion", "Discussion pipe prefix"),
    ("| D ISCUSS I ON", "discussion", "Discussion pipe + extreme OCR"),
    ("| DISCUSS ION", "discussion", "Discussion pipe + OCR space"),
    ("Discussions", "discussions", "Discussion plural (pre-synonym)"),
    ("DISCUSSIONS", "discussions", "Discussion all-caps plural (pre-synonym)"),
    ("dIscussIon", "discussion", "Discussion mixed case"),
    ("discussion", "discussion", "Discussion already lowercase"),
    # Conclusion variants
    ("Conclusions", "conclusions", "Conclusions plural (pre-synonym)"),
    ("Conclusion", "conclusion", "Conclusion singular"),
    ("CONCLUSION", "conclusion", "Conclusion all-caps"),
    ("CONCLUSIONS", "conclusions", "Conclusions all-caps plural (pre-synonym)"),
    ("V. CONCLUSION", "v. conclusion", "Conclusion roman prefix V (numeral retained)"),
    ("IV. CONCLUSION", "iv. conclusion", "Conclusion roman prefix IV (numeral retained)"),
    ("VI. CONCLUSION", "vi. conclusion", "Conclusion roman prefix VI (numeral retained)"),
    ("| CONCLUSIONS", "conclusions", "Conclusions pipe prefix (pre-synonym)"),
    ("| CONCLUSION", "conclusion", "Conclusion pipe prefix"),
    ("| CON CLUS IONS", "conclusions", "Conclusions pipe + OCR space (pre-synonym)"),
    ("\u00e2 CONCLUSIONS", "conclusions", "Conclusions unicode prefix (pre-synonym)"),
    ("Concluding remarks", "concluding remarks", "Concluding remarks (pre-synonym)"),
    ("Concluding Remarks", "concluding remarks", "Concluding Remarks (pre-synonym)"),
    (
        "CONCLUDING REMARKS",
        "concluding remarks",
        "Concluding Remarks all-caps (pre-synonym)",
    ),
    ("Final remarks", "final remarks", "Final remarks (pre-synonym)"),
    ("Final Remarks", "final remarks", "Final Remarks (pre-synonym)"),
    (
        "Final considerations",
        "final considerations",
        "Final considerations (pre-synonym)",
    ),
    ("conclusion", "conclusion", "Conclusion already lowercase"),
    ("conclusions", "conclusions", "Conclusions already lowercase (pre-synonym)"),
    # Materials and Methods variants — surface normalization only
    ("Materials and Methods", "materials and methods", "M&M canonical"),
    ("Materials and methods", "materials and methods", "M&M case variant"),
    ("MATERIALS AND METHODS", "materials and methods", "M&M all-caps"),
    (
        "Material and methods",
        "material and methods",
        "M&M singular Material (pre-synonym)",
    ),
    (
        "Material and Methods",
        "material and methods",
        "M&M singular Material mixed (pre-synonym)",
    ),
    ("Materials And Methods", "materials and methods", "M&M title case"),
    (
        "MATERIAL AND METHODS",
        "material and methods",
        "M&M all-caps singular (pre-synonym)",
    ),
    ("Methods and Materials", "methods and materials", "M&M reversed (pre-synonym)"),
    (
        "Methods and materials",
        "methods and materials",
        "M&M reversed lowercase (pre-synonym)",
    ),
    (
        "METHODS AND MATERIALS",
        "methods and materials",
        "M&M all-caps reversed (pre-synonym)",
    ),
    ("Materials & Methods", "materials & methods", "M&M ampersand (pre-synonym)"),
    ("Materials & methods", "materials & methods", "M&M ampersand case (pre-synonym)"),
    (
        "MATERIALS & METHODS",
        "materials & methods",
        "M&M all-caps ampersand (pre-synonym)",
    ),
    ("Material and Method", "material and method", "M&M both singular (pre-synonym)"),
    ("Materials and Method", "materials and method", "M&M one singular (pre-synonym)"),
    (
        "Materials and method",
        "materials and method",
        "M&M lowercase method (pre-synonym)",
    ),
    ("| MATERIAL S AND ME THODS", "materials and methods", "M&M pipe + OCR space"),
    ("| MATERIALS AND METHODS", "materials and methods", "M&M pipe prefix"),
    ("\u00e2 MATERIALS AND METHODS", "materials and methods", "M&M unicode prefix"),
    (
        "MATERIAL AND METHOD",
        "material and method",
        "M&M all-caps both singular (pre-synonym)",
    ),
    (
        "Materials and Reagents",
        "materials and reagents",
        "M&M chemistry synonym (pre-synonym)",
    ),
    (
        "Materials and Chemicals",
        "materials and chemicals",
        "M&M chemistry synonym 2 (pre-synonym)",
    ),
    # Methods variants — surface normalization only
    ("Methods", "methods", "Methods base form"),
    ("METHODS", "methods", "Methods all-caps"),
    ("Method", "method", "Methods singular (pre-synonym)"),
    ("METHOD", "method", "Methods all-caps singular (pre-synonym)"),
    ("| ME THODS", "methods", "Methods pipe + OCR space"),
    ("| METHODS", "methods", "Methods pipe prefix"),
    # Results and Discussion variants — surface normalization only
    ("Results and Discussion", "results and discussion", "R&D canonical"),
    ("Results and discussion", "results and discussion", "R&D case variant"),
    ("RESULTS AND DISCUSSION", "results and discussion", "R&D all-caps"),
    (
        "Results and Discussions",
        "results and discussions",
        "R&D plural Discussion (pre-synonym)",
    ),
    (
        "Results and discussions",
        "results and discussions",
        "R&D lowercase plural (pre-synonym)",
    ),
    (
        "Result and Discussion",
        "result and discussion",
        "R&D singular Result (pre-synonym)",
    ),
    (
        "Result and discussion",
        "result and discussion",
        "R&D singular lowercase (pre-synonym)",
    ),
    (
        "RESULTS AND DISCUSSIONS",
        "results and discussions",
        "R&D all-caps plural (pre-synonym)",
    ),
    ("Results & Discussion", "results & discussion", "R&D ampersand (pre-synonym)"),
    (
        "Results & discussion",
        "results & discussion",
        "R&D ampersand case (pre-synonym)",
    ),
    ("Results And Discussion", "results and discussion", "R&D title case"),
    (
        "RESULTS & DISCUSSION",
        "results & discussion",
        "R&D all-caps ampersand (pre-synonym)",
    ),
    ("| RESULTS AND DISCUSSION", "results and discussion", "R&D pipe prefix"),
    ("| RE SULTS AND D ISCUSS I ON", "results and discussion", "R&D pipe + OCR"),
    ("\u00e2 RESULTS AND DISCUSSION", "results and discussion", "R&D unicode prefix"),
    ("III. RESULTS AND DISCUSSION", "iii. results and discussion", "R&D roman prefix III (numeral retained)"),
    ("IV. RESULTS AND DISCUSSION", "iv. results and discussion", "R&D roman prefix IV (numeral retained)"),
    (
        "Results and Analysis",
        "results and analysis",
        "R&D analysis synonym (pre-synonym)",
    ),
    (
        "Result and Analysis",
        "result and analysis",
        "R&D analysis singular (pre-synonym)",
    ),
    # Discussion and Conclusions — surface normalization only
    ("Discussion and Conclusions", "discussion and conclusions", "D&C canonical"),
    ("Discussion and conclusions", "discussion and conclusions", "D&C case variant"),
    ("DISCUSSION AND CONCLUSIONS", "discussion and conclusions", "D&C all-caps"),
    (
        "Discussion and Conclusion",
        "discussion and conclusion",
        "D&C singular (pre-synonym)",
    ),
    (
        "DISCUSSION AND CONCLUSION",
        "discussion and conclusion",
        "D&C all-caps singular (pre-synonym)",
    ),
    (
        "Conclusions and Discussion",
        "conclusions and discussion",
        "D&C reversed (pre-synonym)",
    ),
    (
        "Conclusion and Discussion",
        "conclusion and discussion",
        "D&C singular reversed (pre-synonym)",
    ),
    (
        "Conclusions and discussion",
        "conclusions and discussion",
        "D&C reversed case (pre-synonym)",
    ),
    (
        "Conclusion and discussion",
        "conclusion and discussion",
        "D&C singular reversed lc (pre-synonym)",
    ),
    (
        "Discussions and Conclusions",
        "discussions and conclusions",
        "D&C both plural (pre-synonym)",
    ),
    (
        "Discussions and conclusions",
        "discussions and conclusions",
        "D&C both plural lc (pre-synonym)",
    ),
    # Methodology variants — surface normalization only
    ("Methodology", "methodology", "Methodology base form"),
    ("METHODOLOGY", "methodology", "Methodology all-caps"),
    (
        "Research Methodology",
        "research methodology",
        "Methodology research (pre-synonym)",
    ),
    (
        "Research methodology",
        "research methodology",
        "Methodology research lc (pre-synonym)",
    ),
    (
        "RESEARCH METHODOLOGY",
        "research methodology",
        "Methodology research all-caps (pre-synonym)",
    ),
    ("Research Method", "research method", "Methodology research method (pre-synonym)"),
    (
        "Research Methods",
        "research methods",
        "Methodology research methods (pre-synonym)",
    ),
    (
        "RESEARCH METHODS",
        "research methods",
        "Methodology research methods all-caps (pre-synonym)",
    ),
    (
        "RESEARCH METHOD",
        "research method",
        "Methodology research method all-caps (pre-synonym)",
    ),
    ("Research design", "research design", "Methodology research design (pre-synonym)"),
    (
        "Research Design",
        "research design",
        "Methodology research design title (pre-synonym)",
    ),
    (
        "Research method",
        "research method",
        "Methodology research method lc (pre-synonym)",
    ),
    ("research methods", "research methods", "Methodology all lowercase (pre-synonym)"),
    ("Methodologies", "methodologies", "Methodology plural (pre-synonym)"),
    # Statistical Analysis — surface normalization only
    ("Statistical analysis", "statistical analysis", "StatAnalysis base form"),
    ("Statistical Analysis", "statistical analysis", "StatAnalysis title case"),
    (
        "Statistical analyses",
        "statistical analyses",
        "StatAnalysis plural (pre-synonym)",
    ),
    (
        "Statistical Analyses",
        "statistical analyses",
        "StatAnalysis title plural (pre-synonym)",
    ),
    ("STATISTICAL ANALYSIS", "statistical analysis", "StatAnalysis all-caps"),
    ("statistical analysis", "statistical analysis", "StatAnalysis lowercase"),
    (
        "Statistical methods",
        "statistical methods",
        "StatAnalysis methods (pre-synonym)",
    ),
    (
        "Statistical Methods",
        "statistical methods",
        "StatAnalysis methods title (pre-synonym)",
    ),
    (
        "Statistical data analysis",
        "statistical data analysis",
        "StatAnalysis extended (pre-synonym)",
    ),
    (
        "Statistical Data Analysis",
        "statistical data analysis",
        "StatAnalysis extended title (pre-synonym)",
    ),
    ("Statistics", "statistics", "StatAnalysis statistics shorthand (pre-synonym)"),
    ("| Statistical analysis", "statistical analysis", "StatAnalysis pipe prefix"),
    (
        "| Statistical analyses",
        "statistical analyses",
        "StatAnalysis pipe plural (pre-synonym)",
    ),
    (
        "STATISTICAL ANALYSES",
        "statistical analyses",
        "StatAnalysis all-caps plural (pre-synonym)",
    ),
    # Data Analysis — surface normalization only
    ("Data analysis", "data analysis", "DataAnalysis base form"),
    ("Data Analysis", "data analysis", "DataAnalysis title case"),
    ("DATA ANALYSIS", "data analysis", "DataAnalysis all-caps"),
    ("Data analyses", "data analyses", "DataAnalysis plural (pre-synonym)"),
    ("Data Analyses", "data analyses", "DataAnalysis title plural (pre-synonym)"),
    ("| Data analysis", "data analysis", "DataAnalysis pipe prefix"),
    ("| Data analyses", "data analyses", "DataAnalysis pipe plural (pre-synonym)"),
    # Study Area — surface normalization only
    ("Study Area", "study area", "StudyArea base form"),
    ("Study area", "study area", "StudyArea lowercase"),
    ("STUDY AREA", "study area", "StudyArea all-caps"),
    ("Study site", "study site", "StudyArea site (pre-synonym)"),
    ("Study Site", "study site", "StudyArea site title (pre-synonym)"),
    ("STUDY SITE", "study site", "StudyArea site all-caps (pre-synonym)"),
    ("Study sites", "study sites", "StudyArea sites plural (pre-synonym)"),
    ("Study Sites", "study sites", "StudyArea sites title plural (pre-synonym)"),
    ("Study Areas", "study areas", "StudyArea plural (pre-synonym)"),
    ("Study area and data", "study area and data", "StudyArea compound (pre-synonym)"),
    ("Study Region", "study region", "StudyArea region (pre-synonym)"),
    ("Study region", "study region", "StudyArea region lc (pre-synonym)"),
    ("Site description", "site description", "StudyArea site desc (pre-synonym)"),
    ("Site Description", "site description", "StudyArea site desc title (pre-synonym)"),
    (
        "Description of the study area",
        "description of the study area",
        "StudyArea desc extended (pre-synonym)",
    ),
    (
        "Overview of the study area",
        "overview of the study area",
        "StudyArea overview (pre-synonym)",
    ),
    (
        "Study area description",
        "study area description",
        "StudyArea reordered (pre-synonym)",
    ),
    ("The study area", "the study area", "StudyArea article prefix (pre-synonym)"),
    ("| Study area", "study area", "StudyArea pipe prefix"),
    ("| Study site", "study site", "StudyArea site pipe prefix (pre-synonym)"),
    # Literature Review / Related Work — surface normalization only
    ("Literature Review", "literature review", "LitReview base form"),
    ("Literature review", "literature review", "LitReview lowercase"),
    ("LITERATURE REVIEW", "literature review", "LitReview all-caps"),
    ("Related Work", "related work", "RelatedWork base form"),
    ("Related work", "related work", "RelatedWork lowercase"),
    ("RELATED WORK", "related work", "RelatedWork all-caps"),
    ("Related Works", "related works", "RelatedWork plural (pre-synonym)"),
    ("Related works", "related works", "RelatedWork plural lc (pre-synonym)"),
    ("RELATED WORKS", "related works", "RelatedWork plural all-caps (pre-synonym)"),
    ("Literature search", "literature search", "LitReview search (pre-synonym)"),
    ("Literature Survey", "literature survey", "LitReview survey (pre-synonym)"),
    (
        "Review of Literature",
        "review of literature",
        "LitReview inverted (pre-synonym)",
    ),
    # Data and Methods — surface normalization only
    ("Data and methods", "data and methods", "DataMethods base form"),
    ("Data and Methods", "data and methods", "DataMethods title case"),
    ("DATA AND METHODS", "data and methods", "DataMethods all-caps"),
    ("Data and method", "data and method", "DataMethods singular (pre-synonym)"),
    (
        "Data and Methodology",
        "data and methodology",
        "DataMethods methodology (pre-synonym)",
    ),
    (
        "Data and methodology",
        "data and methodology",
        "DataMethods methodology lc (pre-synonym)",
    ),
    (
        "DATA AND METHODOLOGY",
        "data and methodology",
        "DataMethods methodology all-caps (pre-synonym)",
    ),
    # Summary — surface normalization only
    ("Summary", "summary", "Summary base form"),
    ("SUMMARY", "summary", "Summary all-caps"),
    (
        "Summary and conclusions",
        "summary and conclusions",
        "Summary+conclusions (pre-synonym)",
    ),
    (
        "Summary and Conclusions",
        "summary and conclusions",
        "Summary+conclusions title (pre-synonym)",
    ),
    (
        "SUMMARY AND CONCLUSIONS",
        "summary and conclusions",
        "Summary+conclusions all-caps (pre-synonym)",
    ),
    (
        "Summary and conclusion",
        "summary and conclusion",
        "Summary+conclusion singular (pre-synonym)",
    ),
    (
        "Summary and discussion",
        "summary and discussion",
        "Summary+discussion (pre-synonym)",
    ),
    ("Summary and outlook", "summary and outlook", "Summary+outlook (pre-synonym)"),
    # Experimental Design — surface normalization only
    ("Experimental design", "experimental design", "ExpDesign base form"),
    ("Experimental Design", "experimental design", "ExpDesign title case"),
    (
        "Design of experiments",
        "design of experiments",
        "ExpDesign inverted (pre-synonym)",
    ),
    ("Experiment design", "experiment design", "ExpDesign informal (pre-synonym)"),
    # Participants — surface normalization only
    ("Participants", "participants", "Participants base form"),
    ("Subjects", "subjects", "Participants subjects (pre-synonym)"),
    ("Study population", "study population", "Participants population (pre-synonym)"),
    ("Patients", "patients", "Participants patients (pre-synonym)"),
    ("Animals", "animals", "Participants animals (pre-synonym)"),
    ("Study subjects", "study subjects", "Participants study subjects (pre-synonym)"),
    # Limitations — surface normalization only
    ("Limitations", "limitations", "Limitations base form"),
    (
        "Limitations of the study",
        "limitations of the study",
        "Limitations extended (pre-synonym)",
    ),
    (
        "Limitations of this study",
        "limitations of this study",
        "Limitations this study (pre-synonym)",
    ),
    ("Study limitations", "study limitations", "Limitations reordered (pre-synonym)"),
    ("Limitation", "limitation", "Limitations singular (pre-synonym)"),
    (
        "Strengths and limitations",
        "strengths and limitations",
        "Limitations combined (pre-synonym)",
    ),
    # Defensive regression checks
    ("3.2.1 Discussion", "3.2.1. discussion", "Multi-level digit prefix (numeral retained)"),
    ("(2) Background", "2. background", "Parenthesized digit prefix (numeral retained)"),
    ("[III] Results", "iii. results", "Bracketed roman prefix (numeral retained)"),
    ("MIX Methods", "mix methods", "Roman-shaped real word NOT stripped"),
    ("DID Analysis", "did analysis", "Roman-shaped real word NOT stripped 2"),
]

# ---------------------------------------------------------------------------
# (raw_key, expected_after_normalize+synonyms, description)
# ---------------------------------------------------------------------------
SYNONYM_CASES = [
    # -- discussion ----------------------------------------------------------
    ("Discussions", "discussion", "Discussion plural → canonical"),
    ("DISCUSSIONS", "discussion", "Discussion all-caps plural → canonical"),
    # -- conclusion ----------------------------------------------------------
    ("Conclusions", "conclusion", "Conclusions → conclusion"),
    ("CONCLUSIONS", "conclusion", "CONCLUSIONS → conclusion"),
    ("| CONCLUSIONS", "conclusion", "Pipe conclusions → conclusion"),
    ("| CON CLUS IONS", "conclusion", "OCR conclusions → conclusion"),
    ("\u00e2 CONCLUSIONS", "conclusion", "Unicode conclusions → conclusion"),
    ("Concluding remarks", "conclusion", "Concluding remarks → conclusion"),
    ("Concluding Remarks", "conclusion", "Concluding Remarks → conclusion"),
    ("CONCLUDING REMARKS", "conclusion", "CONCLUDING REMARKS → conclusion"),
    ("Final remarks", "conclusion", "Final remarks → conclusion"),
    ("Final Remarks", "conclusion", "Final Remarks → conclusion"),
    ("Final considerations", "conclusion", "Final considerations → conclusion"),
    ("conclusions", "conclusion", "conclusions → conclusion"),
    # -- materials and methods -----------------------------------------------
    ("Material and methods", "materials and methods", "Material and methods → M&M"),
    ("Material and Methods", "materials and methods", "Material and Methods → M&M"),
    ("MATERIAL AND METHODS", "materials and methods", "MATERIAL AND METHODS → M&M"),
    ("Methods and Materials", "materials and methods", "Methods and Materials → M&M"),
    ("Methods and materials", "materials and methods", "Methods and materials → M&M"),
    ("METHODS AND MATERIALS", "materials and methods", "METHODS AND MATERIALS → M&M"),
    ("Materials & Methods", "materials and methods", "Materials & Methods → M&M"),
    ("Materials & methods", "materials and methods", "Materials & methods → M&M"),
    ("MATERIALS & METHODS", "materials and methods", "MATERIALS & METHODS → M&M"),
    ("Material and Method", "materials and methods", "Material and Method → M&M"),
    ("Materials and Method", "materials and methods", "Materials and Method → M&M"),
    ("Materials and method", "materials and methods", "Materials and method → M&M"),
    ("MATERIAL AND METHOD", "materials and methods", "MATERIAL AND METHOD → M&M"),
    ("Materials and Reagents", "materials and methods", "Materials and Reagents → M&M"),
    (
        "Materials and Chemicals",
        "materials and methods",
        "Materials and Chemicals → M&M",
    ),
    # -- methods (singular) --------------------------------------------------
    ("Method", "methods", "Method singular → methods"),
    ("METHOD", "methods", "METHOD → methods"),
    # -- results and discussion ----------------------------------------------
    ("Results and Discussions", "results and discussion", "R&D plural → canonical"),
    ("Results and discussions", "results and discussion", "R&D plural lc → canonical"),
    ("Result and Discussion", "results and discussion", "R&D singular → canonical"),
    ("Result and discussion", "results and discussion", "R&D singular lc → canonical"),
    (
        "RESULTS AND DISCUSSIONS",
        "results and discussion",
        "R&D all-caps plural → canonical",
    ),
    ("Results & Discussion", "results and discussion", "R&D ampersand → canonical"),
    ("Results & discussion", "results and discussion", "R&D ampersand lc → canonical"),
    (
        "RESULTS & DISCUSSION",
        "results and discussion",
        "R&D all-caps ampersand → canonical",
    ),
    (
        "Results and Analysis",
        "results and discussion",
        "R&D analysis synonym → canonical",
    ),
    (
        "Result and Analysis",
        "results and discussion",
        "R&D analysis singular → canonical",
    ),
    # -- discussion and conclusions ------------------------------------------
    (
        "Discussion and Conclusion",
        "discussion and conclusions",
        "D&C singular → canonical",
    ),
    (
        "DISCUSSION AND CONCLUSION",
        "discussion and conclusions",
        "D&C all-caps singular → canonical",
    ),
    (
        "Conclusions and Discussion",
        "discussion and conclusions",
        "D&C reversed → canonical",
    ),
    (
        "Conclusion and Discussion",
        "discussion and conclusions",
        "D&C singular reversed → canonical",
    ),
    (
        "Conclusions and discussion",
        "discussion and conclusions",
        "D&C reversed lc → canonical",
    ),
    (
        "Conclusion and discussion",
        "discussion and conclusions",
        "D&C singular reversed lc → canonical",
    ),
    (
        "Discussions and Conclusions",
        "discussion and conclusions",
        "D&C both plural → canonical",
    ),
    (
        "Discussions and conclusions",
        "discussion and conclusions",
        "D&C both plural lc → canonical",
    ),
    # -- methodology ---------------------------------------------------------
    ("Methodologies", "methodology", "Methodologies → methodology"),
    ("Research Methodology", "methodology", "Research Methodology → methodology"),
    ("Research methodology", "methodology", "Research methodology → methodology"),
    ("RESEARCH METHODOLOGY", "methodology", "RESEARCH METHODOLOGY → methodology"),
    ("Research Method", "methodology", "Research Method → methodology"),
    ("Research Methods", "methodology", "Research Methods → methodology"),
    ("RESEARCH METHODS", "methodology", "RESEARCH METHODS → methodology"),
    ("RESEARCH METHOD", "methodology", "RESEARCH METHOD → methodology"),
    ("Research design", "methodology", "Research design → methodology"),
    ("Research Design", "methodology", "Research Design → methodology"),
    ("Research method", "methodology", "Research method → methodology"),
    ("research methods", "methodology", "research methods → methodology"),
    # -- statistical analysis ------------------------------------------------
    (
        "Statistical analyses",
        "statistical analysis",
        "Statistical analyses → statistical analysis",
    ),
    (
        "Statistical Analyses",
        "statistical analysis",
        "Statistical Analyses → statistical analysis",
    ),
    (
        "STATISTICAL ANALYSES",
        "statistical analysis",
        "STATISTICAL ANALYSES → statistical analysis",
    ),
    (
        "Statistical methods",
        "statistical analysis",
        "Statistical methods → statistical analysis",
    ),
    (
        "Statistical Methods",
        "statistical analysis",
        "Statistical Methods → statistical analysis",
    ),
    (
        "Statistical data analysis",
        "statistical analysis",
        "Statistical data analysis → statistical analysis",
    ),
    (
        "Statistical Data Analysis",
        "statistical analysis",
        "Statistical Data Analysis → statistical analysis",
    ),
    ("Statistics", "statistical analysis", "Statistics → statistical analysis"),
    (
        "| Statistical analyses",
        "statistical analysis",
        "Pipe stat analyses → statistical analysis",
    ),
    # -- data analysis -------------------------------------------------------
    ("Data analyses", "data analysis", "Data analyses → data analysis"),
    ("Data Analyses", "data analysis", "Data Analyses → data analysis"),
    ("| Data analyses", "data analysis", "Pipe data analyses → data analysis"),
    # -- data and methods ----------------------------------------------------
    ("Data and method", "data and methods", "Data and method → data and methods"),
    (
        "Data and Methodology",
        "data and methods",
        "Data and Methodology → data and methods",
    ),
    (
        "Data and methodology",
        "data and methods",
        "Data and methodology → data and methods",
    ),
    (
        "DATA AND METHODOLOGY",
        "data and methods",
        "DATA AND METHODOLOGY → data and methods",
    ),
    # -- study area ----------------------------------------------------------
    ("Study site", "study area", "Study site → study area"),
    ("Study Site", "study area", "Study Site → study area"),
    ("STUDY SITE", "study area", "STUDY SITE → study area"),
    ("Study sites", "study area", "Study sites → study area"),
    ("Study Sites", "study area", "Study Sites → study area"),
    ("Study Areas", "study area", "Study Areas → study area"),
    ("Study area and data", "study area", "Study area and data → study area"),
    ("Study Region", "study area", "Study Region → study area"),
    ("Study region", "study area", "Study region → study area"),
    ("Site description", "study area", "Site description → study area"),
    ("Site Description", "study area", "Site Description → study area"),
    (
        "Description of the study area",
        "study area",
        "Description of the study area → study area",
    ),
    (
        "Overview of the study area",
        "study area",
        "Overview of the study area → study area",
    ),
    ("Study area description", "study area", "Study area description → study area"),
    ("The study area", "study area", "The study area → study area"),
    ("| Study site", "study area", "Pipe study site → study area"),
    # -- literature review ---------------------------------------------------
    ("Literature search", "literature review", "Literature search → literature review"),
    ("Literature Survey", "literature review", "Literature Survey → literature review"),
    (
        "Review of Literature",
        "literature review",
        "Review of Literature → literature review",
    ),
    # -- related work --------------------------------------------------------
    ("Related Works", "related work", "Related Works → related work"),
    ("Related works", "related work", "Related works → related work"),
    ("RELATED WORKS", "related work", "RELATED WORKS → related work"),
    # -- summary -------------------------------------------------------------
    ("Summary and conclusions", "summary", "Summary+conclusions → summary"),
    ("Summary and Conclusions", "summary", "Summary+Conclusions → summary"),
    ("SUMMARY AND CONCLUSIONS", "summary", "SUMMARY AND CONCLUSIONS → summary"),
    ("Summary and conclusion", "summary", "Summary+conclusion → summary"),
    ("Summary and discussion", "summary", "Summary+discussion → summary"),
    ("Summary and outlook", "summary", "Summary+outlook → summary"),
    # -- experimental design -------------------------------------------------
    (
        "Design of experiments",
        "experimental design",
        "Design of experiments → experimental design",
    ),
    (
        "Experiment design",
        "experimental design",
        "Experiment design → experimental design",
    ),
    # -- participants --------------------------------------------------------
    ("Subjects", "participants", "Subjects → participants"),
    ("Patients", "participants", "Patients → participants"),
    ("Animals", "participants", "Animals → participants"),
    ("Study population", "participants", "Study population → participants"),
    ("Study subjects", "participants", "Study subjects → participants"),
    # -- limitations ---------------------------------------------------------
    ("Limitation", "limitations", "Limitation → limitations"),
    (
        "Limitations of the study",
        "limitations",
        "Limitations of the study → limitations",
    ),
    (
        "Limitations of this study",
        "limitations",
        "Limitations of this study → limitations",
    ),
    ("Study limitations", "limitations", "Study limitations → limitations"),
    (
        "Strengths and limitations",
        "limitations",
        "Strengths and limitations → limitations",
    ),
]


def _run_suite(label: str, cases: list, fn) -> tuple[int, int]:
    passes = fails = 0
    print(f"\n{'=' * 70}")
    print(f"  {label}")
    print(f"{'=' * 70}")
    for raw, expected, note in cases:
        actual = fn(raw)
        ok = actual == expected
        status = "PASS" if ok else "FAIL"
        if ok:
            passes += 1
        else:
            fails += 1
        print(f"[{status}] {note!r:55s} {raw!r:42s} -> {actual!r} (expected {expected!r})")
    return passes, fails


def main() -> int:
    total_pass = total_fail = 0

    p, f = _run_suite("_normalize_header cases", NORMALIZE_CASES, _normalize_header)
    total_pass += p
    total_fail += f

    p, f = _run_suite("apply_synonyms cases (normalize + synonyms)", SYNONYM_CASES, _n)
    total_pass += p
    total_fail += f

    print(f"\nTotal: {total_pass + total_fail}, Passed: {total_pass}, Failed: {total_fail}")
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
