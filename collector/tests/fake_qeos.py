"""A stand-in QEOS for CI's collector-action job: `python fake_qeos.py PORT SUGGESTED_JSON UPLOADS_FILE`.

POST /api/v1/collect/impact answers with the suggestion in SUGGESTED_JSON (a JSON list of [suite, uri, name]);
POST /api/v1/collect/runs appends the body to UPLOADS_FILE (one JSON line each) and answers 201;
POST /api/v1/collect/token grants an import token for project 1, and POST /api/v1/projects/1/cases/import
appends the import body to UPLOADS_FILE as well and answers as a dry run would (every file created).
Binds 127.0.0.1 only, so the collector's http:// localhost rule applies."""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT, SUGGESTED, UPLOADS = int(sys.argv[1]), sys.argv[2], sys.argv[3]


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path == "/api/v1/collect/impact":
            with open(SUGGESTED, encoding="utf-8") as handle:
                tests = json.load(handle)
            answer = {"state": "ok", "model_version": "stats-v1", "history_runs": 30, "needed_runs": 20,
                      "statistical_total": len(tests),
                      "tests": [{"test_key": f"{i:064d}", "suite": suite, "class_name": uri, "name": name,
                                 "kind": "statistical", "evidence": {"path_unit": "collector/", "changed_runs": 5,
                                                                     "new_failures": 3}}
                                for i, (suite, uri, name) in enumerate(tests)]}
            status = 200
        elif self.path == "/api/v1/collect/runs":
            with open(UPLOADS, "a", encoding="utf-8") as handle:
                handle.write(body.decode("utf-8") + "\n")
            results = json.loads(body)["results"]
            failed = sum(1 for r in results if r["status"] == "failed")
            answer = {"id": 1, "project_id": 1, "total": len(results), "passed": len(results) - failed,
                      "failed": failed, "skipped": 0, "errored": 0, "quarantined": 0, "blocking": failed,
                      "created_at": "2026-10-13T10:00:00Z"}
            status = 201
        elif self.path == "/api/v1/collect/token":
            answer, status = {"project_id": 1, "token": "fake-import-token"}, 200
        elif self.path.startswith("/api/v1/projects/1/cases/import"):
            with open(UPLOADS, "a", encoding="utf-8") as handle:
                handle.write(body.decode("utf-8") + "\n")
            files = json.loads(body)["files"]
            answer = {"summary": {"created": len(files), "updated": 0, "moved": 0, "reactivated": 0,
                                  "archived": 0, "unchanged": 0, "skipped": 0},
                      "items": [{"action": "created", "path": f["path"], "scenario": None} for f in files],
                      "errors": [], "warnings": []}
            status = 200
        else:
            answer, status = {"detail": "Not Found"}, 404
        data = json.dumps(answer).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
