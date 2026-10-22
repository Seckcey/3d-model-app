#!/usr/bin/env python3
"""End-to-end smoke test through the real proxy, standard library only.

Runs inside a one-off API container (so it can read the outbox for sign-in codes):

  setup:  sign in by email code, create a project/part/revision, upload a drawing,
          wait for the intake check, download it back and compare the hash, run the
          geometry benchmark, and (optionally) prove a second shop sees nothing.
          Prints a JSON state line for the verify phase.
  verify: after a stack restart, sign in again and confirm the uploaded file,
          its hash and the job history are all still there.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.cookies import SimpleCookie
from pathlib import Path

CODE = re.compile(r"^\s{2,}(\d{6})\s*$", re.M)


def make_pdf(lines: list[str]) -> bytes:
    def esc(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    ops = ["BT", "/F1 14 Tf", "60 732 Td", "18 TL"] + [f"({esc(l)}) Tj T*" for l in lines]
    ops += ["ET", "2 w", "420 200 500 260 re S"]
    stream = "\n".join(ops).encode("latin-1")
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        4: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 1224 792] /Resources << /Font << /F1 3 0 R >> >> /Contents 5 0 R >>",
        5: b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    }
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for oid in sorted(objects):
        offsets[oid] = len(out)
        out += f"{oid} 0 obj\n".encode() + objects[oid] + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 6\n0000000000 65535 f \n".encode()
    for oid in range(1, 6):
        out += f"{offsets[oid]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


class Client:
    """Minimal browser: cookies (Secure ignored, we are behind TLS), CSRF, JSON."""

    def __init__(self, base: str, public_url: str):
        self.base = base.rstrip("/")
        public = urllib.parse.urlparse(public_url)
        self.public_url = public_url.rstrip("/")
        self.host = public.netloc
        self.scheme = public.scheme
        self.cookies: dict[str, str] = {}

    def request(self, method: str, path: str, body=None, *, headers=None, raw=False, expect=None):
        data = None
        hdrs = {"Host": self.host, "X-Forwarded-Proto": self.scheme, "Accept": "application/json"}
        if isinstance(body, (bytes, bytearray)):
            data = bytes(body)
        elif body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        if method not in ("GET", "HEAD"):
            if "bpcad_csrftoken" not in self.cookies:
                self.request("GET", "/api/v1/csrf/")
            hdrs["X-CSRFToken"] = self.cookies.get("bpcad_csrftoken", "")
            hdrs["Origin"] = self.public_url
            hdrs["Referer"] = self.public_url + "/"
        if self.cookies:
            hdrs["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        hdrs.update(headers or {})
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                status, payload, resp_headers = resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as err:
            status, payload, resp_headers = err.code, err.read(), err.headers
        for header in resp_headers.get_all("Set-Cookie") or []:
            jar = SimpleCookie()
            jar.load(header)
            for key, morsel in jar.items():
                if morsel["max-age"] == "0" or morsel.value == "":
                    self.cookies.pop(key, None)
                else:
                    self.cookies[key] = morsel.value
        if expect is not None and status not in (expect if isinstance(expect, tuple) else (expect,)):
            raise AssertionError(f"{method} {path} -> {status}: {payload[:400]!r}")
        if raw:
            return status, payload
        try:
            return status, json.loads(payload) if payload else None
        except ValueError:
            return status, payload


def latest_code(outbox: Path, email: str, since: float) -> str:
    for _ in range(30):
        for path in sorted(outbox.glob("*.json"), reverse=True):
            if path.stat().st_mtime < since - 1:
                break
            message = json.loads(path.read_text())
            if email in message["to"]:
                match = CODE.search(message["body"])
                if match:
                    return match.group(1)
        time.sleep(1)
    raise AssertionError(f"no sign-in code for {email} in {outbox}")


def sign_in(client: Client, email: str, outbox: Path) -> None:
    for attempt in range(8):
        since = time.time()
        status, body = client.request("POST", "/_allauth/browser/v1/auth/code/request", {"email": email})
        if status == 401:
            break
        if status == 400 and "too_many" in json.dumps(body):
            time.sleep(15)  # one code per address per minute
            continue
        raise AssertionError(f"code request failed: {status} {body}")
    else:
        raise AssertionError("could not request a code")
    code = latest_code(outbox, email, since)
    client.request("POST", "/_allauth/browser/v1/auth/code/confirm", {"code": code}, expect=200)
    status, me = client.request("GET", "/api/v1/me/", expect=200)
    assert me["email"] == email, me
    print(f"  signed in as {email}")


def multipart(field: str, filename: str, content: bytes, content_type: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def wait_job(client: Client, job_id: str, timeout: int = 300) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, job = client.request("GET", f"/api/v1/jobs/{job_id}/", expect=200)
        if job["state"] in ("succeeded", "failed", "unsupported", "canceled"):
            return job
        time.sleep(2)
    raise AssertionError(f"job {job_id} did not finish: {job['state']}")


def setup(args) -> dict:
    outbox = Path(args.outbox)
    client = Client(args.base, args.public_url)
    status, _ = client.request("GET", "/healthz")
    assert status == 200, "proxy/api not healthy"
    _, page = client.request("GET", "/", raw=True, expect=200)
    assert b'<div id="root">' in page, "SPA not served"
    sign_in(client, args.email, outbox)
    _, me = client.request("GET", "/api/v1/me/", expect=200)
    org = me["memberships"][0]["organization"]["id"]

    _, project = client.request("POST", "/api/v1/projects/", {"organization": org, "name": "Smoke test job",
                                                             "reference": "PO-SMOKE"}, expect=201)
    _, part = client.request("POST", "/api/v1/parts/", {"project": project["id"], "part_number": "SMOKE-1"},
                             expect=201)
    _, revision = client.request("POST", f"/api/v1/parts/{part['id']}/revisions/", {"drawing_revision": "A"},
                                 expect=201)
    pdf = make_pdf(["UNLESS OTHERWISE SPECIFIED DIMENSIONS ARE IN INCHES", "MATERIAL: 6061-T6",
                    "THIRD ANGLE PROJECTION", "PART NO. SMOKE-1 REV A", "4X 1/4-20 UNC-2B THRU"])
    body, ctype = multipart("file", "SMOKE-1_A.pdf", pdf, "application/pdf")
    _, source = client.request("POST", f"/api/v1/revisions/{revision['id']}/files/", body,
                               headers={"Content-Type": ctype}, expect=201)
    print(f"  uploaded drawing {source['id']}")
    _, jobs = client.request("GET", f"/api/v1/jobs/?source_file={source['id']}", expect=200)
    intake = wait_job(client, jobs["results"][0]["id"])
    assert intake["state"] == "succeeded", intake
    print("  intake check succeeded")
    _, data = client.request("GET", f"/api/v1/files/{source['id']}/download/", raw=True, expect=200)
    assert hashlib.sha256(data).hexdigest() == hashlib.sha256(pdf).hexdigest(), "download hash mismatch"
    print("  authenticated download returned the identical file (X-Accel-Redirect)")

    _, bench = client.request("POST", f"/api/v1/organizations/{org}/benchmark/", {},
                              headers={"Idempotency-Key": f"smoke-{uuid.uuid4()}"}, expect=(200, 202))
    bench = wait_job(client, bench["id"], timeout=600)
    assert bench["state"] == "succeeded", bench
    assert bench["result"]["passed"] is True, bench["result"]
    _, listing = client.request("GET", f"/api/v1/organizations/{org}/benchmark/", expect=200)
    steps = [a for a in listing["artifacts"] if a["kind"] == "step"]
    assert len(steps) >= 3, listing["artifacts"]
    _, step = client.request("GET", f"/api/v1/artifacts/{steps[0]['id']}/download/", raw=True, expect=200)
    assert step.startswith(b"ISO-10303-21"), step[:40]
    print(f"  geometry benchmark passed ({len(steps)} STEP files)")

    if args.other_email:
        other = Client(args.base, args.public_url)
        sign_in(other, args.other_email, outbox)
        for path in (f"/api/v1/projects/{project['id']}/", f"/api/v1/files/{source['id']}/download/",
                     f"/api/v1/jobs/{intake['id']}/", f"/api/v1/artifacts/{steps[0]['id']}/download/"):
            status, _ = other.request("GET", path)
            assert status == 404, f"second shop could reach {path}: {status}"
        print("  second shop cannot see the first shop's project, file, job or artifact")

    return {"project": project["id"], "source": source["id"], "sha256": hashlib.sha256(pdf).hexdigest(),
            "intake_job": intake["id"], "benchmark_job": bench["id"]}


def verify(args) -> None:
    state = json.loads(args.state)
    client = Client(args.base, args.public_url)
    sign_in(client, args.email, Path(args.outbox))
    client.request("GET", f"/api/v1/projects/{state['project']}/", expect=200)
    _, data = client.request("GET", f"/api/v1/files/{state['source']}/download/", raw=True, expect=200)
    assert hashlib.sha256(data).hexdigest() == state["sha256"], "file changed after restart"
    for key in ("intake_job", "benchmark_job"):
        _, job = client.request("GET", f"/api/v1/jobs/{state[key]}/", expect=200)
        assert job["state"] == "succeeded" and job["events"], job
    print("  after restart: project, original drawing (same SHA-256) and job history are intact")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["setup", "verify"])
    parser.add_argument("--base", default="http://proxy:8080")
    parser.add_argument("--public-url", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--other-email")
    parser.add_argument("--outbox", default="/data/outbox")
    parser.add_argument("--state")
    args = parser.parse_args()
    if args.phase == "setup":
        state = setup(args)
        print("STATE " + json.dumps(state))
    else:
        verify(args)
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
