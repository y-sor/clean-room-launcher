#!/usr/bin/env python3
"""Read-only upstream signals. Never qualifies, updates, or publishes CLROOM."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

BASE = Path(__file__).resolve().parents[2]
PROVIDERS = (
 ("codex","https://api.github.com/repos/openai/codex/releases/latest","CODEX_VERSION",r"rust-v(\d+\.\d+\.\d+)"),
 ("claude","https://api.github.com/repos/anthropics/claude-code/releases/latest","CLAUDE_VERSION",r"v(\d+\.\d+\.\d+)"),
)
STANDARDS = (
 ("agent-plugins","https://api.github.com/repos/agentplugins/agent-plugins-spec/commits/main"),
 ("agent-skills","https://api.github.com/repos/agentskills/agentskills/commits/main"),
 ("mcp","https://api.github.com/repos/modelcontextprotocol/modelcontextprotocol/commits/main"),
)

def pins(text):
    out={}
    for key in ("CODEX_VERSION","CLAUDE_VERSION"):
        values=re.findall(r"^"+key+r"=(\d+\.\d+\.\d+)$",text,re.M)
        if len(values)!=1:
            raise ValueError("ambiguous-provider-pin:"+key)
        out[key]=values[0]
    return out

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise ValueError("redirect-not-allowed-for-authenticated-source")


def get_json(url):
    token=os.getenv("GH_TOKEN","")
    hdr={"Accept":"application/vnd.github+json","User-Agent":"CLROOM-upstream-watch/1"}
    if token:
        hdr["Authorization"]="Bearer "+token
    request=urllib.request.Request(url,headers=hdr)
    with urllib.request.build_opener(NoRedirect()).open(request,timeout=15) as response:
        if response.status!=200:
            raise ValueError("unexpected HTTP status")
        body=response.read(131073)
        if len(body)>131072:
            raise ValueError("oversized response")
        return json.loads(body)

def inspect_release(name,url,pin,tag_pattern,raw):
    result={"source":name,"kind":"provider","url":url,"qualified_pin":pin,"state":"UNKNOWN"}
    if not isinstance(raw,dict) or raw.get("draft") is not False or raw.get("prerelease") is not False:
        result["reason"]="unconfirmed-stable-release"
        return result
    tag=raw.get("tag_name")
    match=re.fullmatch(tag_pattern,tag) if isinstance(tag,str) else None
    if match is None:
        result["reason"]="unexpected-stable-tag"
        return result
    result["latest"]=match.group(1)
    result["state"]="UNCHANGED" if result["latest"]==pin else "REVIEW_NEEDED"
    result["reason"]="same-pin" if result["state"]=="UNCHANGED" else "drift-needs-human-qualification"
    return result

def inspect_standard(name,url,raw):
    result={"source":name,"kind":"standard-source","url":url,"state":"UNKNOWN"}
    if isinstance(raw,dict) and isinstance(raw.get("sha"),str) and re.fullmatch(r"[0-9a-f]{40}",raw["sha"]):
        result.update({"state":"OBSERVED_UNTRIAGED","revision":raw["sha"],"reason":"main-head-not-published-standard"})
    else:
        result["reason"]="invalid-source-sha"
    return result

def source_error_reason(error):
    if isinstance(error, urllib.error.HTTPError):
        return "http-" + str(error.code)
    if isinstance(error, ValueError) and str(error) == "redirect-not-allowed-for-authenticated-source":
        return "redirect-denied"
    if isinstance(error, json.JSONDecodeError):
        return "invalid-json"
    return "source-transport-or-invalid"


def collect(pin_text,getter):
    qualified=pins(pin_text)
    results=[]
    for name,url,key,pattern in PROVIDERS:
        try:
            results.append(inspect_release(name,url,qualified[key],pattern,getter(url)))
        except (OSError,ValueError,urllib.error.URLError,json.JSONDecodeError) as error:
            results.append({"source":name,"kind":"provider","url":url,"state":"UNKNOWN","reason":source_error_reason(error)})
    for name,url in STANDARDS:
        try:
            results.append(inspect_standard(name,url,getter(url)))
        except (OSError,ValueError,urllib.error.URLError,json.JSONDecodeError) as error:
            results.append({"source":name,"kind":"standard-source","url":url,"state":"UNKNOWN","reason":source_error_reason(error)})
    status="UNKNOWN" if any(x["state"]=="UNKNOWN" for x in results) else (
        "REVIEW_NEEDED" if any(x["state"]=="REVIEW_NEEDED" for x in results) else "NO_PROVIDER_PIN_DRIFT_OBSERVED"
    )
    return {
      "schema":"clroom.advisory-watch.v1",
      "observed_at":dt.datetime.now(dt.timezone.utc).isoformat(),
      "source_commit":os.getenv("WATCH_SOURCE_HEAD",os.getenv("GITHUB_SHA","LOCAL")),
      "overall":status,
      "release_decision":"NOT_AUTHORIZED",
      "signals":results,
      "nonclaims":[
        "This checks source release metadata and standard repository heads, not a CVE feed or exploitability.",
        "An upstream main commit is not a newly published normative Agent Plugins, MCP, or Agent Skills version.",
        "Security advisories, dependency alerts, native Mac qualification and release checks remain separate.",
        "No new version, unsafe capability, merge, tag, publish or user notification is authorized.",
      ]
    }

def self_test():
    text="CODEX_VERSION=0.161.0\nCLAUDE_VERSION=2.1.293\n"
    fixtures={PROVIDERS[0][1]:{"tag_name":"rust-v0.161.0","draft":False,"prerelease":False},
      PROVIDERS[1][1]:{"tag_name":"v2.1.293","draft":False,"prerelease":False}}
    fixtures.update({url:{"sha":"a"*40} for name,url in STANDARDS})
    assert collect(text,fixtures.__getitem__)["overall"]=="NO_PROVIDER_PIN_DRIFT_OBSERVED"
    fixtures[PROVIDERS[0][1]]["tag_name"]="rust-v0.162.0"
    assert collect(text,fixtures.__getitem__)["overall"]=="REVIEW_NEEDED"
    assert collect(text,fixtures.__getitem__)["release_decision"]=="NOT_AUTHORIZED"
    fixtures[PROVIDERS[0][1]]["draft"]=True
    assert collect(text,fixtures.__getitem__)["overall"]=="UNKNOWN"
    fixtures[PROVIDERS[0][1]]["draft"]=False
    fixtures[STANDARDS[1][1]]={"sha":"../../invalid"}
    assert collect(text,fixtures.__getitem__)["overall"]=="UNKNOWN"
    try:
        pins(text+"CODEX_VERSION=0.161.0\n")
        raise AssertionError("duplicate pin accepted")
    except ValueError:
        pass
    try:
        NoRedirect().redirect_request(None,None,302,"",{},"https://example.invalid/")
        raise AssertionError("redirect accepted")
    except ValueError:
        pass
    print("ADVISORY_WATCH_SELF_TEST_PASS: unchanged, drift, draft, bad source, ambiguous pin, denied redirect")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.output:
        parser.error("--output is required")
    report=collect((BASE/"scripts/release/provider-pins.sh").read_text(),get_json)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    lines=["### CLROOM daily upstream signals (advisory only)","",
       "Overall: "+report["overall"]+"; release: NOT_AUTHORIZED.","",
       "| Source | State | Latest / SHA | Frozen pin |",
       "| --- | --- | --- | --- |"]
    for x in report["signals"]:
        lines.append("| "+x["source"]+" | "+x["state"]+" | "+x.get("latest",x.get("revision","unknown"))+" | "+x.get("qualified_pin","n/a")+" |")
    lines+=["","NOT a vulnerability verdict, provider qualification or release approval.",""]
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a") as f:
            f.write("\n".join(lines))
    else:
        print("\n".join(lines))
    # UNKNOWN never turns into a false clean verdict, but intermittent network
    # failure does not generate noisy CI failure notifications.
    return 0

if __name__=="__main__":
    sys.exit(main())
