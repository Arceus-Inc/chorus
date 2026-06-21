"""Parse HARD_TASKS.md → manifest of (n, name, lang, brief) for the 15 goals."""
import json
import re
from pathlib import Path

md = Path("standup-app/HARD_TASKS.md").read_text()
# Match: ### N. Title — `name` [· **Lang** emoji]\n> brief line(s)\n\n
goals = []
# split on headings
blocks = re.split(r"\n### (\d+)\. ", md)
# blocks[0] is preamble; then pairs (num, body)
for i in range(1, len(blocks), 2):
    num = int(blocks[i])
    body = blocks[i + 1]
    head, *_ = body.split("\n", 1)
    # name is the first `backtick` token in the heading
    m = re.search(r"`([a-z0-9_-]+)`", head)
    name = m.group(1) if m else f"goal{num}"
    langm = re.search(r"\*\*([A-Za-z]+)\*\*", head)
    lang = langm.group(1) if langm else "Python"
    # brief = the blockquote lines (>) immediately after heading
    quote = []
    for line in body.split("\n"):
        if line.startswith("> "):
            quote.append(line[2:].rstrip())
        elif quote and not line.startswith(">"):
            break
    brief = " ".join(quote).strip()
    goals.append({"n": num, "name": name, "lang": lang, "brief": brief})

Path("standup-app/hard-task-report/_manifest.json").write_text(json.dumps(goals, indent=2))
print(f"extracted {len(goals)} goals")
for g in goals:
    print(f"  {g['n']:>2}. {g['name']:<14} [{g['lang']:<10}] {g['brief'][:60]}...")
