#!/usr/bin/env python3
import argparse, hashlib, json, re, tarfile
from pathlib import Path

FILES=("SHA256SUMS","sbom.cdx.json","install.sh","release-notes.md")
CHECKS=(
    "release_readiness",
    "exact_archive_qualification_codex",
    "exact_archive_qualification_claude",
    "codex_stage_runtime",
    "pretag_attestation_rehearsal",
    "release_notes_rendered",
)

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def require_hex(value,n,label):
    if not isinstance(value,str) or not re.fullmatch(rf"[0-9a-f]{{{n}}}",value):
        raise SystemExit(f"RELEASE_STAGE_BLOCKED:{label}")

def archive_version_fields(path: Path):
    with tarfile.open(path,"r:gz") as ar:
        members=[m for m in ar.getmembers() if m.isfile() and m.name.endswith("/VERSION")]
        if len(members)!=1:
            raise SystemExit("RELEASE_STAGE_BLOCKED:ARCHIVE_VERSION_COUNT")
        body=ar.extractfile(members[0]).read().decode("utf-8")
    fields={}
    for line in body.splitlines():
        if "=" in line:
            k,v=line.split("=",1); fields[k]=v
    return fields

def create(a):
    root=Path(a.root)
    artifact=root/a.artifact_name
    required=[artifact]+[root/n for n in FILES]+[
        Path(a.codex_stage),Path(a.codex_qualification),Path(a.claude_qualification),
        Path(a.pretag_provenance),Path(a.pretag_sbom),
    ]
    for p in required:
        if not p.is_file() or p.stat().st_size==0:
            raise SystemExit(f"RELEASE_STAGE_BLOCKED:MISSING:{p.name}")
    fields=archive_version_fields(artifact)
    if fields.get("version")!=a.version or fields.get("source_commit")!=a.source_head:
        raise SystemExit("RELEASE_STAGE_BLOCKED:ARCHIVE_IDENTITY")
    record={
      "schema_version":"clroom.release-stage.v1",
      "release_version":a.version,
      "source_head":a.source_head,
      "source_tree":a.source_tree,
      "reviewed_content_digest":a.reviewed_content_digest,
      "artifact_name":a.artifact_name,
      "files":{p.name:sha256(p) for p in [artifact]+[root/n for n in FILES]},
      "providers":{
        "codex":{"version":a.codex_version,"package_sha512":a.codex_sha512,"platform_sha512":a.codex_platform_sha512},
        "claude":{"version":a.claude_version,"package_sha512":a.claude_sha512,"platform_sha512":a.claude_platform_sha512},
      },
      "evidence":{
        "codex_stage":{"name":Path(a.codex_stage).name,"sha256":sha256(Path(a.codex_stage))},
        "codex_qualification":{"name":Path(a.codex_qualification).name,"sha256":sha256(Path(a.codex_qualification))},
        "claude_qualification":{"name":Path(a.claude_qualification).name,"sha256":sha256(Path(a.claude_qualification))},
        "pretag_provenance":{"name":Path(a.pretag_provenance).name,"sha256":sha256(Path(a.pretag_provenance))},
        "pretag_sbom":{"name":Path(a.pretag_sbom).name,"sha256":sha256(Path(a.pretag_sbom))},
      },
      "checks":{k:True for k in CHECKS},
    }
    require_hex(a.source_head,40,"SOURCE_HEAD")
    require_hex(a.source_tree,40,"SOURCE_TREE")
    require_hex(a.reviewed_content_digest,64,"REVIEW_DIGEST")
    Path(a.output).write_text(json.dumps(record,sort_keys=True,indent=2)+"\n",encoding="utf-8")

def verify(a):
    root=Path(a.root)
    path=root/"release-stage.json"
    if not path.is_file():
        raise SystemExit("RELEASE_STAGE_BLOCKED:MANIFEST_MISSING")
    r=json.loads(path.read_text(encoding="utf-8"))
    expected={
      "schema_version":"clroom.release-stage.v1",
      "release_version":a.version,
      "source_head":a.source_head,
    }
    for k,v in expected.items():
        if r.get(k)!=v:
            raise SystemExit(f"RELEASE_STAGE_BLOCKED:{k.upper()}")
    require_hex(r.get("source_tree"),40,"SOURCE_TREE")
    require_hex(r.get("reviewed_content_digest"),64,"REVIEW_DIGEST")
    artifact_name=r.get("artifact_name")
    if artifact_name!=f"clean-room-launcher-v{a.version}-aarch64-apple-darwin.tar.gz":
        raise SystemExit("RELEASE_STAGE_BLOCKED:ARTIFACT_NAME")
    files=r.get("files") or {}
    for name in (artifact_name,*FILES):
        p=root/name
        if not p.is_file() or files.get(name)!=sha256(p):
            raise SystemExit(f"RELEASE_STAGE_BLOCKED:FILE_DIGEST:{name}")
    fields=archive_version_fields(root/artifact_name)
    if fields.get("version")!=a.version or fields.get("source_commit")!=a.source_head:
        raise SystemExit("RELEASE_STAGE_BLOCKED:ARCHIVE_IDENTITY")
    for k in CHECKS:
        if (r.get("checks") or {}).get(k) is not True:
            raise SystemExit(f"RELEASE_STAGE_BLOCKED:CHECK:{k}")
    evidence=r.get("evidence") or {}
    for key in ("codex_stage","codex_qualification","claude_qualification","pretag_provenance","pretag_sbom"):
        item=evidence.get(key) or {}
        name=item.get("name")
        if not isinstance(name,str):
            raise SystemExit(f"RELEASE_STAGE_BLOCKED:EVIDENCE_NAME:{key}")
        p=root/name
        if not p.is_file() or item.get("sha256")!=sha256(p):
            raise SystemExit(f"RELEASE_STAGE_BLOCKED:EVIDENCE_DIGEST:{key}")
    print(f"RELEASE_STAGE_VERIFY_PASS version={a.version} source={a.source_head} artifact_sha256={files[artifact_name]}")

def main():
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest="cmd",required=True)
    c=sub.add_parser("create")
    for x in ("root","version","source-head","source-tree","reviewed-content-digest","artifact-name","codex-stage","codex-qualification","claude-qualification","pretag-provenance","pretag-sbom","codex-version","codex-sha512","codex-platform-sha512","claude-version","claude-sha512","claude-platform-sha512","output"):
        c.add_argument("--"+x,required=True)
    v=sub.add_parser("verify")
    v.add_argument("--root",required=True); v.add_argument("--version",required=True); v.add_argument("--source-head",required=True)
    a=p.parse_args()
    (create if a.cmd=="create" else verify)(a)
if __name__=="__main__":
    main()
