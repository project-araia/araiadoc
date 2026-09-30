from click.testing import CliRunner

from araiadoc.collection.s2orc import get_from_local_s2orc


def test_get_from_local_s2orc_uses_bounded_duckdb_threads_by_default(tmp_path, monkeypatch):
    data_dir = tmp_path / "s2orc"
    data_dir.mkdir()
    (data_dir / "shard.gz").write_bytes(b"")
    captured = {}

    def fake_query(gz_files, query_text, output_dir, label, duckdb_threads, duckdb_memory_limit):
        captured["gz_files"] = gz_files
        captured["duckdb_threads"] = duckdb_threads
        captured["duckdb_memory_limit"] = duckdb_memory_limit
        return 0

    monkeypatch.setattr("araiadoc.collection.s2orc.os.cpu_count", lambda: 48)
    monkeypatch.setattr("araiadoc.collection.s2orc._query_with_duckdb", fake_query)

    result = CliRunner().invoke(get_from_local_s2orc, ["-d", str(data_dir), "--all-utility"])

    assert result.exit_code == 0
    assert captured["duckdb_threads"] == 8
    assert captured["duckdb_memory_limit"] is None


def test_get_from_local_s2orc_duckdb_resource_overrides(tmp_path, monkeypatch):
    data_dir = tmp_path / "s2orc"
    data_dir.mkdir()
    (data_dir / "shard.gz").write_bytes(b"")
    captured = {}

    def fake_query(gz_files, query_text, output_dir, label, duckdb_threads, duckdb_memory_limit):
        captured["duckdb_threads"] = duckdb_threads
        captured["duckdb_memory_limit"] = duckdb_memory_limit
        return 0

    monkeypatch.setattr("araiadoc.collection.s2orc._query_with_duckdb", fake_query)

    result = CliRunner().invoke(
        get_from_local_s2orc,
        [
            "-d",
            str(data_dir),
            "--all-utility",
            "--duckdb-threads",
            "4",
            "--duckdb-memory-limit",
            "32GB",
        ],
    )

    assert result.exit_code == 0
    assert captured == {"duckdb_threads": 4, "duckdb_memory_limit": "32GB"}
