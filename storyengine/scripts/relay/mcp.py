"""Tiny StoryEngine MCP client for relay work, so big prompts/answers never pass through chat.

  python3 mcp.py pending [video_id]        -> saves each pending request to req/<id>.json, prints a summary
  python3 mcp.py answer <request_id> <file> -> posts the file's text as the answer (code fences stripped;
                                              .json must parse, .txt is posted as plain text)
"""
import json, os, re, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.expanduser("~/.claude.json")))["mcpServers"]["storyengine"]


def call(tool, args):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": tool, "arguments": args}}).encode()
    req = urllib.request.Request(CFG["url"], data=body, headers={
        **CFG["headers"], "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
    raw = urllib.request.urlopen(req, timeout=120).read().decode()
    if raw.lstrip().startswith("event:") or "data:" in raw[:20]:
        raw = next(line[5:].strip() for line in raw.splitlines() if line.startswith("data:"))
    msg = json.loads(raw)
    if "error" in msg:
        raise SystemExit(json.dumps(msg["error"]))
    text = msg["result"]["content"][0]["text"]
    try:
        return json.loads(text)
    except ValueError:
        return text


def strip_fences(text):
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    return m.group(1) if m else text


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "pending":
        args = {"limit": 50}
        if len(sys.argv) > 2:
            args["video_id"] = sys.argv[2]
        res = call("list_pending_llm_requests", args)
        os.makedirs(os.path.join(HERE, "req"), exist_ok=True)
        print("pending_total", res.get("pending_total"))
        for r in res.get("requests", []):
            path = os.path.join(HERE, "req", r["request_id"] + ".json")
            json.dump(r, open(path, "w"))
            target = re.search(r"Target: (.*?)\. Aliases", r["prompt"])
            print(r["request_id"], r["stage"], target.group(1) if target else "", len(r["prompt"]))
    elif cmd == "answer":
        text = strip_fences(open(sys.argv[3]).read())
        if not sys.argv[3].endswith(".txt"):
            json.loads(text)  # must be valid JSON before it is posted (.txt = plain-text answer, e.g. vision QA)
        print(json.dumps(call("answer_llm_request", {"request_id": sys.argv[2], "response": text}))[:400])
