import hmac
import json
from hashlib import sha256
from typing import Any, Dict, Optional

from fastapi import Header, HTTPException, Request

from ..clients.github_app import GitHubRef, create_branch, create_pull_request, get_installation_token
from ..clients.sonar import fetch_sonar_issues
from ..core.config import GITHUB_WEBHOOK_SECRET, SHIFTLEFT_FIX_LIMIT
from ..services.fixes_service import generate_fix_for_issue
from ..services.github_apply import apply_code_changes_via_github_api


def _verify_sig(body: bytes, sig_header: Optional[str]) -> None:
    if not GITHUB_WEBHOOK_SECRET:
        # If no secret configured, do not allow webhook in production accidentally
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    if not sig_header or not isinstance(sig_header, str) or not sig_header.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing signature")

    expected = hmac.new(GITHUB_WEBHOOK_SECRET.encode("utf-8"), body, sha256).hexdigest()
    got = sig_header.split("=", 1)[1].strip()
    if not hmac.compare_digest(expected, got):
        raise HTTPException(status_code=401, detail="Bad signature")


def _extract_workflow_run(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    wr = payload.get("workflow_run")
    if isinstance(wr, dict):
        return wr
    return None


def register_webhook_routes(app, fixes_collection, prompts_collection):
    @app.post("/webhook/github")
    async def github_webhook(
        request: Request,
        x_hub_signature_256: Optional[str] = Header(default=None, alias="X-Hub-Signature-256"),
        x_github_event: Optional[str] = Header(default=None, alias="X-GitHub-Event"),
    ):
        body = await request.body()
        _verify_sig(body, x_hub_signature_256)

        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON")

        # We recommend webhook event = workflow_run (Sonar workflow completion)
        if x_github_event != "workflow_run":
            return {"ok": True, "ignored": True, "reason": f"event {x_github_event} not handled"}

        workflow_run = _extract_workflow_run(payload)
        if not workflow_run:
            raise HTTPException(status_code=400, detail="Missing workflow_run payload")

        if workflow_run.get("conclusion") != "success":
            return {"ok": True, "ignored": True, "reason": "workflow_run not successful"}

        repo_obj = (payload.get("repository") or {}) if isinstance(payload.get("repository"), dict) else {}
        full_name = repo_obj.get("full_name") or ""
        if "/" not in full_name:
            raise HTTPException(status_code=400, detail="Missing repository.full_name")
        owner, repo_name = full_name.split("/", 1)
        repo = GitHubRef(owner=owner, repo=repo_name)

        installation = payload.get("installation") or {}
        installation_id = installation.get("id")
        if not isinstance(installation_id, int):
            raise HTTPException(status_code=400, detail="Missing installation.id")

        token = get_installation_token(installation_id)

        base_branch = "main"
        head_branch = f"shiftleft/fixes-{workflow_run.get('head_sha','')[:8] or 'latest'}"
        create_branch(repo, token, new_branch=head_branch, base_branch=base_branch)

        sonar_issues = fetch_sonar_issues()
        fixes_payload: Dict[str, Any] = {"results": []}

        # Generate fixes (reuse existing caching collection data if possible)
        for issue in (sonar_issues or [])[:SHIFTLEFT_FIX_LIMIT]:
            issue_key = issue.get("key")
            cached = fixes_collection.find_one({"issue_key": issue_key}, {"_id": 0}) if issue_key else None
            if cached and cached.get("fix_json"):
                fix_json = cached.get("fix_json")
                fixes_payload["results"].append({"issue": issue, "fix_json": fix_json, "source": "cache"})
                continue

            gen = generate_fix_for_issue(issue, prompts_collection)
            fix_json = gen.get("fix_json")
            fix_record = {
                "issue_key": issue_key,
                "issue_rule": issue.get("rule"),
                "fix": gen.get("fix_string"),
                "fix_raw": gen.get("fix_text"),
                "fix_json": fix_json,
            }
            if issue_key:
                fixes_collection.update_one({"issue_key": issue_key}, {"$set": fix_record}, upsert=True)
            fixes_payload["results"].append({"issue": issue, "fix_json": fix_json, "source": "generated"})

        # Flatten all changes
        all_changes = []
        for item in fixes_payload["results"]:
            fj = item.get("fix_json") or {}
            if isinstance(fj, dict) and isinstance(fj.get("code_changes"), list):
                all_changes.extend(list(fj.get("code_changes") or []))

        counters, report = apply_code_changes_via_github_api(
            repo=repo,
            token=token,
            base_ref=base_branch,
            branch=head_branch,
            code_changes=all_changes,
        )

        pr_title = "chore(shiftleft): auto fixes"
        pr_body = (
            "## Shift-Left automated fixes\n\n"
            + f"- Applied: {counters.applied}\n"
            + f"- Skipped: {counters.skipped}\n"
            + f"- Errors: {counters.errors}\n\n"
            + "## Report\n"
            + "```json\n"
            + json.dumps(report, ensure_ascii=False, indent=2)
            + "\n```\n"
        )

        pr = create_pull_request(
            repo=repo,
            token=token,
            title=pr_title,
            body=pr_body,
            head=head_branch,
            base=base_branch,
        )

        return {"ok": True, "branch": head_branch, "pr": pr.get("html_url"), "counters": counters.__dict__}

