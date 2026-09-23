import os
import re
from pathlib import Path

HOME = Path(os.path.expanduser('~'))
GIT_LOG = HOME / 'Pi_Music_Console' / 'git_log.txt'

def extract_path(line: str) -> str:
    # Try to find a path-like component (contains / or \\)
    tokens = line.strip().split()
    for token in reversed(tokens):
        # Remove surrounding quotes if any
        token = token.strip('"\'')
        if '/' in token or '\\' in token:
            # Expand user tilde if present
            p = os.path.expanduser(token)
            # If path is relative, make it absolute based on HOME
            if not os.path.isabs(p):
                p = os.path.join(str(HOME), p)
            return p
    return ''

def clean_git_log():
    if not GIT_LOG.exists():
        print(f"[!] {GIT_LOG} not found, nothing to clean.")
        return
    with open(GIT_LOG, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    kept = []
    removed = 0
    for line in lines:
        path = extract_path(line)
        if path and not os.path.exists(path):
            removed += 1
            continue
        kept.append(line)
    with open(GIT_LOG, 'w', encoding='utf-8') as f:
        f.writelines(kept)
    print(f"[+] Cleaned git_log.txt: {removed} stale entries removed, {len(kept)} entries remain.")

if __name__ == '__main__':
    clean_git_log()
