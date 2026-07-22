from scripts.rebuild_evidence_vectors import backup_vector_store_path


def test_backup_vector_store_path_copies_lancedb_directory(tmp_path):
    source_path = tmp_path / "lancedb"
    source_path.mkdir()
    (source_path / "marker.txt").write_text("before-rebuild", encoding="utf-8")

    backup_path = backup_vector_store_path(source_path)

    assert backup_path is not None and backup_path.exists()
    assert (backup_path / "marker.txt").read_text(encoding="utf-8") == "before-rebuild"
