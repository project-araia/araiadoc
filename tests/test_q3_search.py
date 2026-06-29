from __future__ import annotations

import json
from importlib import resources

from click.testing import CliRunner

from araiadoc.collection.s2orc import _count_q3_tagged_docs, _merge_q3_tag, get_from_local_s2orc
from araiadoc.searches import get_q3_groups


def test_q3_keyword_files_are_package_resources():
    files = resources.files("araiadoc.q3_keywords")

    assert (files / "File 3_Transportation_revised.txt").is_file()


def test_q3_groups_parse_expected_metadata():
    groups = get_q3_groups()

    assert len(groups) == 52
    assert not any("--" in group["query"] for group in groups)

    maritime = next(group for group in groups if group["file"] == 3 and group["group"] == 3)
    assert maritime["name"] == "Maritime Transportation"
    assert maritime["sector"] == "Transportation"
    assert maritime["subsectors"] == ["Maritime"]

    supply_chains = next(group for group in groups if group["file"] == 7 and group["group"] == 6)
    assert supply_chains["tag"] == "Supply Chains"
    assert "sector" not in supply_chains


def test_q3_tag_merge_matches_sector_and_cross_cutting_example():
    groups = get_q3_groups()
    maritime = next(group for group in groups if group["file"] == 3 and group["group"] == 3)
    resilience = next(group for group in groups if group["file"] == 7 and group["group"] == 3)
    supply_chains = next(group for group in groups if group["file"] == 7 and group["group"] == 6)

    doc = {"corpusid": 123}
    _merge_q3_tag(doc, maritime)
    _merge_q3_tag(doc, resilience)
    _merge_q3_tag(doc, supply_chains)
    _merge_q3_tag(doc, supply_chains)

    ci = doc["_araiadoc_tags"]["critical_infrastructure"]
    assert ci["sectors"] == [{"sector": "Transportation", "subsectors": ["Maritime"]}]
    assert ci["tags"] == ["Resilience (incl. Risk and Vulnerability)", "Supply Chains"]
    assert ci["matched_groups"] == [
        {
            "file": 3,
            "group": 3,
            "name": "Maritime Transportation",
            "sector": "Transportation",
            "subsectors": ["Maritime"],
        },
        {
            "file": 7,
            "group": 3,
            "name": "Resilience (incl. Risk and Vulnerability)",
            "tag": "Resilience (incl. Risk and Vulnerability)",
        },
        {"file": 7, "group": 6, "name": "Supply Chains", "tag": "Supply Chains"},
    ]


def test_count_q3_tagged_docs_recomputes_from_output(tmp_path):
    shard_dir = tmp_path / "45"
    shard_dir.mkdir()
    (shard_dir / "12345.json").write_text(
        json.dumps({"_araiadoc_tags": {"critical_infrastructure": {"tags": ["Supply Chains"]}}})
    )
    (shard_dir / "99945.json").write_text(json.dumps({"corpusid": 99945}))

    assert _count_q3_tagged_docs(tmp_path) == 1


def test_with_tags_is_q3_only(tmp_path):
    data_dir = tmp_path / "s2orc"
    data_dir.mkdir()

    runner = CliRunner()
    result = runner.invoke(get_from_local_s2orc, ["-d", str(data_dir), "--all-weather", "--with-tags"])

    assert result.exit_code != 0
    assert "--with-tags is only supported with --all-critical-infrastructure" in result.output
