from app.openapi_export import OUTPUT_PATH, export


def test_committed_spec_matches_fresh_export():
    # git checks the file out with CRLF on Windows while the export is always LF
    committed = OUTPUT_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert committed == export()
