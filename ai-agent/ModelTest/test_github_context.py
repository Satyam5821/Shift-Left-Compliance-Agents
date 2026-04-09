import argparse
import os
import sys

AI_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if AI_AGENT_DIR not in sys.path:
    sys.path.insert(0, AI_AGENT_DIR)

from app.clients.github_context import build_context_snippet, read_github_file_lines


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test GitHub file fetch + snippet extraction for Shift-Left-Compliance-Agents ai-agent."
    )
    parser.add_argument(
        "--file",
        required=True,
        help="Repo-relative path, e.g. src/main/java/com/example/App.java",
    )
    parser.add_argument(
        "--line",
        type=int,
        default=1,
        help="1-based line number to center the snippet around",
    )
    parser.add_argument(
        "--radius",
        type=int,
        default=10,
        help="Lines of context above/below the target line",
    )
    args = parser.parse_args()

    lines = read_github_file_lines(args.file)
    if not lines:
        print("FAILED: Could not fetch file from GitHub.")
        print("Check: GITHUB_REPO_OWNER / GITHUB_REPO_NAME / GITHUB_REF / GITHUB_TOKEN in ai-agent/.env")
        return 2

    print(f"OK: fetched {len(lines)} lines from '{args.file}'")
    print("-" * 80)
    snippet = build_context_snippet(args.file, args.line, radius=args.radius)
    if not snippet.strip():
        print("FAILED: Could not build snippet (empty).")
        return 3

    print(snippet)
    print("-" * 80)
    print("SUCCESS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

