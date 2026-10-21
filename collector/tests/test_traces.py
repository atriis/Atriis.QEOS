"""Traces (spec 2026-10-21 §4.2, collector 0.14.0): Playwright `application/zip` attachments and Cucumber reference
attachments (`application/vnd.qeos.artifact+json`) become `artifacts` on the result; the zip files are read only
inside the working directory (0.13.0 rules), at most 100 MB, `PK\\x03\\x04` first, and go up before the run with HEAD
then a streaming PUT on /collect/artifacts/{sha256}, best effort, never costing the run."""
import base64
import hashlib
import json
import os

import pytest

from qeos_collector import traces, upload
from qeos_collector.cli import main
from qeos_collector.formats import parse_file
from qeos_collector.payload import build_parts
from qeos_collector.traces import TraceFile
from qeos_collector.upload import MAX_ARTIFACTS_PER_RUN, upload_artifacts

KEY = "qeos_test_key_123"
ZIP_A = b"PK\x03\x04" + b"\x01" * 64
ZIP_B = b"PK\x03\x04" + b"\x02" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
RECEIPT = {"id": 42, "project_id": 1, "total": 1, "passed": 0, "failed": 1, "skipped": 0, "errored": 0,
           "created_at": "2026-10-21T12:00:00Z"}
TRACES_ON = {"project_id": 1, "name": "ci", "screenshots": True, "artifacts": True}
REFERENCE = "application/vnd.qeos.artifact+json"


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "test-results").mkdir()
    return tmp_path


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# --- Playwright ---------------------------------------------------------------------------------------------------


def playwright_report(folder, attachments, name="results.json"):
    data = {"config": {"version": "1.47.0"}, "suites": [{
        "title": "checkout.spec.ts", "file": "checkout.spec.ts", "suites": [],
        "specs": [{"title": "pays", "file": "checkout.spec.ts", "tests": [{"projectName": "chromium", "results": [
            {"status": "failed", "duration": 10, "retry": 0, "steps": [], "attachments": attachments}]}]}]}]}
    path = folder / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def zip_attachment(path, name="trace"):
    return {"name": name, "contentType": "application/zip", "path": str(path)}


def test_a_playwright_trace_becomes_an_artifact_read_by_streaming(workdir):
    trace = write(workdir / "test-results" / "pays" / "trace.zip", ZIP_A)
    parsed = parse_file(playwright_report(workdir, [zip_attachment(trace)]))
    (row,) = parsed.results
    assert row["artifacts"] == [{"sha256": sha(ZIP_A), "kind": "trace", "name": "trace"}]
    ref = row["_artifacts"][sha(ZIP_A)]
    assert isinstance(ref, TraceFile) and ref.size == len(ZIP_A) and ref.sha256 == sha(ZIP_A)
    assert ref.path == os.path.realpath(trace)
    assert b"".join(ref.chunks()) == ZIP_A
    assert "screenshots" not in row
    assert not any("trace" in warning for warning in parsed.warnings)  # no longer "not sent yet"
    assert parsed.artifact_skips == {}


def test_a_playwright_video_is_still_counted_as_not_sent_yet(workdir):
    trace = write(workdir / "test-results" / "trace.zip", ZIP_A)
    parsed = parse_file(playwright_report(workdir, [zip_attachment(trace),
                                                    {"name": "video", "contentType": "video/webm",
                                                     "path": str(workdir / "test-results" / "v.webm")}]))
    warning = next(w for w in parsed.warnings if "Playwright" in w)
    assert "1 video (not sent yet)" in warning and "trace" not in warning
    assert len(parsed.results[0]["artifacts"]) == 1


def test_a_relative_playwright_trace_path_resolves_from_the_report_folder(workdir):
    write(workdir / "out" / "trace.zip", ZIP_A)
    reports = workdir / "reports"
    reports.mkdir()
    path = playwright_report(reports, [zip_attachment("../out/trace.zip")])
    assert parse_file(path).results[0]["artifacts"][0]["sha256"] == sha(ZIP_A)


def test_unsafe_or_unusable_traces_are_skipped_and_counted(workdir, tmp_path_factory, monkeypatch):
    monkeypatch.setattr(traces, "MAX_TRACE_BYTES", 1024)
    outside = write(tmp_path_factory.mktemp("elsewhere") / "secret.zip", ZIP_B)
    link = workdir / "test-results" / "link.zip"
    try:
        os.symlink(outside, link)
        has_link = True
    except (OSError, NotImplementedError):  # Windows without symlink rights
        has_link = False
    big = write(workdir / "test-results" / "big.zip", b"PK\x03\x04" + b"\x00" * 2000)
    not_zip = write(workdir / "test-results" / "fake.zip", b"not a zip at all")
    good = write(workdir / "test-results" / "good.zip", ZIP_A)
    attachments = [
        zip_attachment(outside),
        zip_attachment(workdir / "test-results" / "gone.zip"),
        zip_attachment(workdir / "test-results"),  # a folder, not a file
        zip_attachment(big),
        zip_attachment(not_zip),
        {"name": "trace", "contentType": "application/zip", "body": base64.b64encode(ZIP_A).decode()},
        zip_attachment(good),
    ]
    if has_link:
        attachments.append(zip_attachment(link))
    parsed = parse_file(playwright_report(workdir, attachments))
    (row,) = parsed.results
    assert [a["sha256"] for a in row["artifacts"]] == [sha(ZIP_A)]  # only good.zip
    assert parsed.artifact_skips == {"outside": 2 if has_link else 1, "missing": 2, "large": 1, "not_zip": 1,
                                     "inline": 1}
    assert not any("trace" in warning for warning in parsed.warnings)  # said once, in the trace phase


def test_at_most_five_traces_per_result_and_each_once(workdir):
    files = [write(workdir / "test-results" / f"t{n}.zip", b"PK\x03\x04" + bytes([n]) * 8) for n in range(7)]
    attachments = [zip_attachment(f) for f in files] + [zip_attachment(files[0])]
    parsed = parse_file(playwright_report(workdir, attachments))
    (row,) = parsed.results
    assert len(row["artifacts"]) == 5 and len(row["_artifacts"]) == 5
    assert parsed.artifact_skips == {"over": 2}


def test_a_long_attachment_name_is_cut_to_200(workdir):
    trace = write(workdir / "test-results" / "trace.zip", ZIP_A)
    parsed = parse_file(playwright_report(workdir, [zip_attachment(trace, name="x" * 300)]))
    assert parsed.results[0]["artifacts"][0]["name"] == "x" * 200


# --- Cucumber -----------------------------------------------------------------------------------------------------


def reference(content, identity=False):
    text = content if isinstance(content, str) else json.dumps(content)
    if identity:  # cucumber's message formats: the text itself
        return {"body": text, "mediaType": REFERENCE, "contentEncoding": "IDENTITY"}
    return {"data": base64.b64encode(text.encode()).decode(), "mime_type": REFERENCE}  # the classic JSON


def cucumber_report(folder, embeddings, after=None, name="cucumber.json"):
    steps = [{"keyword": "Given ", "name": "a cart", "line": 3, "result": {"status": "passed", "duration": 1}},
             {"keyword": "When ", "name": "I pay", "line": 4, "result": {"status": "failed", "duration": 1,
                                                                            "error_message": "boom"},
              "embeddings": [{"data": base64.b64encode(b"paying").decode(), "mime_type": "text/plain"}]},
             {"keyword": "After", "hidden": True, "result": {"status": "passed", "duration": 1},
              "embeddings": embeddings}]
    feature = {"uri": "f.feature", "name": "F", "elements": [
        {"type": "scenario", "name": "pays", "line": 2, "steps": steps, **({"after": after} if after else {})}]}
    path = folder / name
    path.write_text(json.dumps([feature]), encoding="utf-8")
    return str(path)


def test_a_cucumber_reference_becomes_an_artifact_never_a_log_line_or_screenshot(workdir):
    write(workdir / "test-results" / "traces" / "pays.zip", ZIP_A)
    write(workdir / "test-results" / "traces" / "again.zip", ZIP_B)
    parsed = parse_file(cucumber_report(workdir, [
        reference({"kind": "trace", "path": "test-results/traces/pays.zip"}),
        reference({"kind": "trace", "path": "test-results/traces/again.zip"}, identity=True),
    ]))
    (row,) = parsed.results
    assert row["artifacts"] == [{"sha256": sha(ZIP_A), "kind": "trace", "name": "pays.zip"},
                                {"sha256": sha(ZIP_B), "kind": "trace", "name": "again.zip"}]
    assert set(row["_artifacts"]) == {sha(ZIP_A), sha(ZIP_B)}
    assert row["log"] == "paying" and "screenshots" not in row
    assert parsed.artifact_skips == {}


def test_a_cucumber_reference_on_cucumber_jvm_after_hooks_counts_too(workdir):
    write(workdir / "test-results" / "pays.zip", ZIP_A)
    after = [{"result": {"status": "passed"},
              "embeddings": [reference({"kind": "trace", "path": "test-results/pays.zip"})]}]
    parsed = parse_file(cucumber_report(workdir, [], after=after))
    assert parsed.results[0]["artifacts"][0]["sha256"] == sha(ZIP_A)


def test_a_cucumber_reference_path_resolves_from_the_report_folder_then_the_working_directory(workdir):
    write(workdir / "reports" / "beside.zip", ZIP_A)
    write(workdir / "test-results" / "cwd.zip", ZIP_B)
    parsed = parse_file(cucumber_report(workdir / "reports", [
        reference({"kind": "trace", "path": "beside.zip"}),
        reference({"kind": "trace", "path": "test-results/cwd.zip"}),
    ]))
    assert [a["sha256"] for a in parsed.results[0]["artifacts"]] == [sha(ZIP_A), sha(ZIP_B)]


def test_video_and_invalid_cucumber_references_are_skipped_and_counted(workdir, tmp_path_factory):
    outside = write(tmp_path_factory.mktemp("elsewhere") / "x.zip", ZIP_A)
    parsed = parse_file(cucumber_report(workdir, [
        reference({"kind": "video", "path": "test-results/v.webm"}),
        reference("{not json"),
        reference({"kind": "trace"}),
        reference({"kind": "trace", "path": ""}),
        reference(["a", "list"]),
        reference({"kind": "trace", "path": str(outside)}),
        reference({"kind": "trace", "path": "test-results/gone.zip"}),
    ]))
    (row,) = parsed.results
    assert "artifacts" not in row and "_artifacts" not in row
    assert parsed.artifact_skips == {"video": 1, "bad_reference": 4, "outside": 1, "missing": 1}
    assert row["log"] == "paying"  # no reference text in the log
    assert not any("trace" in warning or "reference" in warning for warning in parsed.warnings)


# --- TraceFile ----------------------------------------------------------------------------------------------------


def test_trace_chunks_are_one_megabyte_and_a_changed_file_is_never_sent(workdir):
    data = b"PK\x03\x04" + os.urandom(traces.CHUNK_BYTES * 2 + 10)
    path = write(workdir / "test-results" / "big.zip", data)
    ref = TraceFile(str(path), len(data), sha(data), "trace")
    chunks = list(ref.chunks())
    assert [len(c) for c in chunks] == [traces.CHUNK_BYTES, traces.CHUNK_BYTES, 14]
    path.write_bytes(data[:-1] + b"!")  # same size, other bytes
    sent = []
    with pytest.raises(traces.TraceChanged):
        for chunk in ref.chunks():
            sent.append(chunk)
    assert len(b"".join(sent)) < len(data)  # the last chunk is held back until the hash matched
    path.write_bytes(data + b"more")
    with pytest.raises(traces.TraceChanged):
        list(ref.chunks())
    path.unlink()
    with pytest.raises(traces.TraceChanged):
        list(ref.chunks())


# --- upload_artifacts ---------------------------------------------------------------------------------------------


def trace_file(folder, data, name="trace.zip"):
    path = write(folder / name, data)
    return TraceFile(str(path), len(data), sha(data), name)


def test_head_then_a_streaming_put_with_content_length(platform, tmp_path):
    big = b"PK\x03\x04" + os.urandom(traces.CHUNK_BYTES + 100)
    files = {sha(big): trace_file(tmp_path, big, "a.zip"), sha(ZIP_B): trace_file(tmp_path, ZIP_B, "b.zip")}
    platform.stored.add(sha(ZIP_B))
    assert upload_artifacts(platform.url, KEY, files) == {sha(big), sha(ZIP_B)}
    requests = sorted((r["method"], r["sha"]) for r in platform.blob_requests)
    assert requests == sorted([("HEAD", sha(big)), ("HEAD", sha(ZIP_B)), ("PUT", sha(big))])  # stored: no PUT
    put = next(r for r in platform.blob_requests if r["method"] == "PUT")
    assert put["path"] == f"/api/v1/collect/artifacts/{sha(big)}"
    assert put["body"] == big
    assert put["headers"]["Content-Length"] == str(len(big))
    assert put["headers"]["Content-Type"] == "application/zip"
    assert put["headers"].get("Transfer-Encoding") is None
    assert put["headers"]["Authorization"] == f"Bearer {KEY}"


def test_a_trace_that_changed_since_the_report_is_left_out(platform, tmp_path):
    ref = trace_file(tmp_path, ZIP_A)
    write(tmp_path / "trace.zip", ZIP_B)
    notes = []
    assert upload_artifacts(platform.url, KEY, {ref.sha256: ref}, warn=notes.append) == set()
    # the request is cut before its body is complete (the fake answers anyway; QEOS checks size and hash)
    assert all(len(r["body"]) < len(ZIP_B) for r in platform.blob_requests if r["method"] == "PUT")
    assert notes == ["1 changed since the report was read"]


@pytest.mark.parametrize("statuses", [[429, 201], [503, 201]])
def test_a_put_429_or_5xx_is_retried_with_the_file_streamed_again(platform, tmp_path, statuses):
    ref = trace_file(tmp_path, ZIP_A)
    platform.put_status[ref.sha256] = list(statuses)
    assert upload_artifacts(platform.url, KEY, {ref.sha256: ref}, sleep=lambda s: None) == {ref.sha256}
    puts = [r for r in platform.blob_requests if r["method"] == "PUT"]
    assert len(puts) == 2 and all(r["body"] == ZIP_A for r in puts)


def test_a_refused_trace_is_left_out_alone(platform, tmp_path):
    a, b = trace_file(tmp_path, ZIP_A, "a.zip"), trace_file(tmp_path, ZIP_B, "b.zip")
    platform.put_status[a.sha256] = 413
    notes = []
    assert upload_artifacts(platform.url, KEY, {a.sha256: a, b.sha256: b}, warn=notes.append) == {b.sha256}
    assert notes == ["1 refused by the platform"]


def test_a_403_stops_the_phase(platform, tmp_path):
    files = {}
    for n in range(4):
        ref = trace_file(tmp_path, b"PK\x03\x04" + bytes([n]) * 8, f"{n}.zip")
        files[ref.sha256] = ref
        platform.put_status[ref.sha256] = 403
    notes = []
    assert upload_artifacts(platform.url, KEY, files, warn=notes.append) == set()
    assert [r["method"] for r in platform.blob_requests] == ["HEAD", "PUT"]  # the first goes alone
    assert notes == ["traces are off for this project (403)"]


def test_the_budget_ends_the_phase(platform, tmp_path):
    platform.blob_delay = 0.3
    files = {}
    for n in range(8):
        ref = trace_file(tmp_path, b"PK\x03\x04" + bytes([n]) * 8, f"{n}.zip")
        files[ref.sha256] = ref
    notes = []
    stored = upload_artifacts(platform.url, KEY, files, budget_seconds=0.5, warn=notes.append)
    assert len(stored) < len(files)
    assert notes == ["out of time after 0.5 s"]


def test_at_most_500_traces_per_run(monkeypatch):
    calls = []
    monkeypatch.setattr(upload, "_store_artifact", lambda url, *args, **kwargs: calls.append(url) or True)
    many = {f"{n:064x}": TraceFile("x", 1, f"{n:064x}", "t") for n in range(MAX_ARTIFACTS_PER_RUN + 2)}
    notes = []
    stored = upload_artifacts("http://127.0.0.1:1", KEY, many, warn=notes.append)
    assert MAX_ARTIFACTS_PER_RUN == 500 and upload.ARTIFACT_WORKERS == 2 and upload.ARTIFACT_BUDGET_SECONDS == 300
    assert len(stored) == 500 and len(calls) == 500
    assert notes == ["2 beyond 500 per run"]


# --- the run upload -----------------------------------------------------------------------------------------------


@pytest.fixture
def traced_report(workdir):
    write(workdir / "test-results" / "traces" / "pays.zip", ZIP_A)
    return cucumber_report(workdir, [reference({"kind": "trace", "path": "test-results/traces/pays.zip"}),
                                     reference({"kind": "video", "path": "test-results/v.webm"})])


def upload_run(platform, report, *argv, **env):
    platform.reply(201, RECEIPT)
    code = main(["upload", str(report), "--no-changes", *argv],
                {"QEOS_URL": platform.url, "QEOS_API_KEY": KEY, **env}, sleep=lambda seconds: None)
    run = [r for r in platform.requests if r["path"] == "/api/v1/collect/runs"]
    assert code == 0 and len(run) == 1
    return json.loads(run[0]["body"])["results"]


def trace_lines(capsys):
    return [line for line in capsys.readouterr().err.splitlines() if line.startswith("qeos: traces")]


def test_traces_go_up_before_the_run_and_the_run_references_them(platform, traced_report, capsys):
    platform.key_check = TRACES_ON
    (row,) = upload_run(platform, traced_report)
    assert row["artifacts"] == [{"sha256": sha(ZIP_A), "kind": "trace", "name": "pays.zip"}]
    assert "_artifacts" not in row
    assert [(r["method"], r["path"]) for r in platform.blob_requests] == [
        ("HEAD", f"/api/v1/collect/artifacts/{sha(ZIP_A)}"), ("PUT", f"/api/v1/collect/artifacts/{sha(ZIP_A)}")]
    assert trace_lines(capsys) == ["qeos: traces: 1 stored (0.0 MB), 1 skipped (1 video (not sent yet))"]


def test_screenshots_and_traces_each_have_their_phase(platform, workdir, capsys):
    shot = write(workdir / "test-results" / "shot.png", PNG)
    trace = write(workdir / "test-results" / "trace.zip", ZIP_A)
    report = playwright_report(workdir, [{"name": "screenshot", "contentType": "image/png", "path": str(shot)},
                                         zip_attachment(trace)])
    platform.key_check = TRACES_ON
    (row,) = upload_run(platform, report)
    assert [r["path"].rsplit("/", 2)[1] for r in platform.blob_requests] == ["blobs", "blobs", "artifacts",
                                                                             "artifacts"]
    assert row["screenshots"][0]["sha256"] == sha(PNG) and row["artifacts"][0]["sha256"] == sha(ZIP_A)
    err = capsys.readouterr().err
    assert "qeos: screenshots: 1 stored, 0 skipped" in err and "qeos: traces: 1 stored (0.0 MB), 0 skipped" in err


@pytest.mark.parametrize("key_check, note", [
    ({"project_id": 1, "name": "ci", "artifacts": False}, "off for this project"),
    ({"project_id": 1, "name": "ci"}, "older than this collector"),
])
def test_traces_off_or_unknown_on_the_platform_send_none(platform, traced_report, capsys, key_check, note):
    platform.key_check = key_check
    (row,) = upload_run(platform, traced_report)
    assert platform.blob_requests == [] and "artifacts" not in row
    (line,) = trace_lines(capsys)
    assert line.startswith("qeos: traces: 0 stored (0.0 MB), 2 skipped (") and note in line
    assert "video" not in line  # off: one line, no reasons per file


def test_a_failed_key_check_sends_no_traces(platform, traced_report, capsys):
    platform.reply(401, {"detail": "no"})  # the key check; the run's reply is scripted after it
    (row,) = upload_run(platform, traced_report)
    assert platform.blob_requests == [] and "artifacts" not in row
    (line,) = trace_lines(capsys)
    assert "key check failed" in line


def test_a_403_on_put_skips_the_rest_and_the_run_goes_without_traces(platform, traced_report, capsys):
    platform.key_check = TRACES_ON  # turned off between the key check and the PUT
    platform.put_status[sha(ZIP_A)] = 403
    (row,) = upload_run(platform, traced_report)
    assert "artifacts" not in row
    (line,) = trace_lines(capsys)
    assert "0 stored" in line and "(403)" in line


def test_an_unexpected_error_in_the_trace_phase_never_costs_the_run(platform, traced_report, monkeypatch, capsys):
    def broken(*args, **kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr("qeos_collector.cli.upload_artifacts", broken)
    platform.key_check = TRACES_ON
    (row,) = upload_run(platform, traced_report)
    assert "artifacts" not in row
    (line,) = trace_lines(capsys)
    assert "RuntimeError: disk on fire" in line


@pytest.mark.parametrize("argv, env, yml", [
    (["--no-artifacts"], {}, None),
    ([], {"QEOS_NO_ARTIFACTS": "1"}, None),
    ([], {}, "no-artifacts: true\n"),
])
def test_no_artifacts_turns_traces_off_with_one_line(platform, traced_report, workdir, capsys, argv, env, yml):
    if yml:
        (workdir / ".qeos.yml").write_text(yml, encoding="utf-8")
    platform.key_check = TRACES_ON
    (row,) = upload_run(platform, traced_report, *argv, **env)
    assert platform.blob_requests == []
    assert [r["path"] for r in platform.requests] == ["/api/v1/collect/runs"]  # no key check either
    assert "artifacts" not in row
    (line,) = trace_lines(capsys)
    assert line.startswith("qeos: traces: 2 skipped (turned off")


def test_a_dry_run_keeps_the_references_and_uploads_nothing(traced_report, capsys):
    assert main(["upload", traced_report, "--no-changes", "--dry-run"], {}) == 0
    out = capsys.readouterr().out
    assert sha(ZIP_A) in out and "_artifacts" not in out


def test_the_run_body_never_carries_the_private_trace_files(tmp_path):
    ref = trace_file(tmp_path, ZIP_A)
    row = {"suite": "", "class_name": "", "name": "t", "status": "failed", "duration_ms": 1,
           "artifacts": [{"sha256": ref.sha256, "kind": "trace", "name": "trace"}], "_artifacts": {ref.sha256: ref}}
    (part,) = build_parts({"ci_provider": "local"}, [row], "k")
    result = json.loads(part.body)["results"][0]
    assert "_artifacts" not in result and result["artifacts"][0]["sha256"] == ref.sha256
    assert "_artifacts" in row  # the caller's row is left alone
