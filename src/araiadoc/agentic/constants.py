DEFAULT_MODEL = "openai/gpt-oss-20b"
DEFAULT_BASE_URL = "https://inference-api.alcf.anl.gov/resource_server/sophia/vllm/v1"
VALID_DECISIONS = {"relevant", "maybe", "irrelevant"}
SKIP_JSON_FILENAMES = {
    "batch_checkpoint.json",
    "duckdb_checkpoint.json",
    "failures.json",
    "filter_report.json",
    "judge_checkpoint.json",
    "judge_summary.json",
    "sectionization_report.json",
}
PRIORITY_SECTION_MARKERS = (
    "introduction",
    "intro",
    "background",
    "overview",
    "summary",
    "conclusion",
    "discussion",
)
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
