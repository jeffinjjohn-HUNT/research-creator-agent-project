from __future__ import annotations


def report_markdown(job: dict) -> str:
    r = job.get("result") or {}
    lines = [f"# {job.get('name') or 'Research report'}", ""]
    if job.get("input_url"):
        lines += [f"Source: {job['input_url']}", ""]
    rep = r.get("report") or {}
    for s in rep.get("sections", []):
        cites = f" [{', '.join(s['citations'])}]" if s.get("citations") else ""
        label = "" if s.get("label") == "source_backed" else f" _({s['label']})_"
        lines += [f"## {s['title']}{label}", "", f"{s['body']}{cites}", ""]
    if rep.get("glossary"):
        lines += ["## Glossary", ""] + [f"- **{g['term']}**: {g['definition']}" for g in rep["glossary"]] + [""]
    if r.get("claims"):
        lines += ["## Claims and evidence", ""]
        for c in r["claims"]:
            lines.append(f"- **{c['id']}** ({c['status'].replace('_', ' ')}, confidence {c['confidence']:.2f}): "
                         f"{c['claim_text']} — {', '.join(c['evidence_ids']) or 'no evidence'}. {c['explanation']}")
        lines.append("")
    if r.get("evidence"):
        lines += ["## Bibliography", ""]
        for e in r["evidence"]:
            lines.append(f"- **{e['id']}** {e['title']} — {e['platform']}"
                         f"{', ' + e['author'] if e.get('author') else ''}"
                         f"{', ' + e['published_at'] if e.get('published_at') else ''}. {e['url']} "
                         f"(retrieved {str(e['retrieved_at'])[:10]})")
        lines.append("")
    q = r.get("quality")
    if q and q.get("issues"):
        lines += ["## Quality notes", ""] + [f"- [{i['severity']}] {i['message']}" for i in q["issues"]] + [""]
    return "\n".join(lines)


def drafts_markdown(job: dict) -> str:
    r = job.get("result") or {}
    lines = [f"# Content drafts — {job.get('name') or ''}", "", "_Review and publish manually; nothing is auto-posted._", ""]
    for d in r.get("drafts", []):
        lines += [f"## {d['format']} ({d['tone']}, rev {d['revision']})", "", d["draft_text"], "",
                  f"Based on claims: {', '.join(d['source_claim_ids']) or 'none'}", ""]
    return "\n".join(lines)
