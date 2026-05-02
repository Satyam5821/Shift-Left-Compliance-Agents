from typing import Any, Dict, List

from fastapi.responses import RedirectResponse

from ..core.config import (
    GITHUB_APP_ID,
    GITHUB_APP_PRIVATE_KEY_PEM,
    GITHUB_APP_SLUG,
    GITHUB_INSTALLATION_ID,
    GITHUB_WEBHOOK_SECRET,
)


def register_github_install_routes(app, github_app_installations_collection=None):
    @app.get("/github/install")
    def github_install():
        """
        Redirect users to GitHub App installation page.
        Configure GITHUB_APP_SLUG like: "shiftleft-bot" (from https://github.com/apps/<slug>).
        """
        if not GITHUB_APP_SLUG:
            return {
                "ok": False,
                "error": "GITHUB_APP_SLUG not configured",
                "hint": "Set GITHUB_APP_SLUG to your GitHub App slug (https://github.com/apps/<slug>)",
            }

        url = f"https://github.com/apps/{GITHUB_APP_SLUG}/installations/new"
        return RedirectResponse(url=url, status_code=302)

    @app.get("/github/status")
    def github_status() -> Dict[str, Any]:
        """
        Safe diagnostics for onboarding (no secrets returned).
        """
        active_installs = 0
        total_installs = 0
        if github_app_installations_collection is not None:
            try:
                total_installs = int(github_app_installations_collection.count_documents({}))
                active_installs = int(github_app_installations_collection.count_documents({"active": True}))
            except Exception:
                total_installs = 0
                active_installs = 0

        return {
            "ok": True,
            "github_app": {
                "slug_configured": bool(GITHUB_APP_SLUG),
                "app_id_configured": bool(GITHUB_APP_ID),
                "private_key_configured": bool(GITHUB_APP_PRIVATE_KEY_PEM),
                "webhook_secret_configured": bool(GITHUB_WEBHOOK_SECRET),
                "default_installation_id_configured": isinstance(GITHUB_INSTALLATION_ID, int) and GITHUB_INSTALLATION_ID > 0,
            },
            "installations": {
                "tracked_total": total_installs,
                "tracked_active": active_installs,
                "mongo_configured": github_app_installations_collection is not None,
            },
            "hints": {
                "connect": "Open GET /github/install in the browser to install the GitHub App on an org/user account.",
                "webhook": "GitHub App must send installation + installation_repositories events to POST /webhook/github to track repos per installation.",
            },
        }

    @app.get("/github/installations")
    def list_github_installations(limit: int = 50) -> Dict[str, Any]:
        """
        Lists installations persisted from GitHub webhooks (metadata only).
        """
        if github_app_installations_collection is None:
            return {"ok": False, "error": "MongoDB not configured for installations collection"}

        lim = max(1, min(int(limit or 50), 200))
        try:
            cur = (
                github_app_installations_collection.find({"active": True}, {"_id": 0})
                .sort("updated_at", -1)
                .limit(lim)
            )
            items: List[Dict[str, Any]] = []
            for doc in cur:
                if isinstance(doc, dict):
                    items.append(doc)
            return {"ok": True, "count": len(items), "installations": items}
        except Exception as e:
            return {"ok": False, "error": str(e)}

