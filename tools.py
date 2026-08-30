from pathlib import Path


def _path(root, relative):
    candidate = (Path(root) / relative).resolve()
    workspace = Path(root).resolve()
    if candidate != workspace and workspace not in candidate.parents:
        raise ValueError("path escapes workspace")
    return candidate


def list_files(root, args):
    entries = []
    for path in sorted(Path(root).iterdir(), key=lambda item: item.name):
        entries.append(path.name + ("/" if path.is_dir() else ""))
    return "\n".join(entries) or "(empty workspace)"


def read_file(root, args):
    path = _path(root, args["path"])
    if not path.is_file():
        raise ValueError(f"not a file: {args['path']}")
    lines = path.read_text(encoding="utf-8").splitlines()
    start = max(1, int(args.get("start", 1)))
    end = int(args.get("end", len(lines)))
    return "\n".join(f"{number}: {lines[number - 1]}" for number in range(start, min(end, len(lines)) + 1))
