from datetime import datetime


def register_prompt_routes(app, prompts_collection):
    @app.get("/prompts")
    def get_all_prompts():
        prompts = list(prompts_collection.find({}, {"_id": 0}))
        return {"prompts": prompts, "count": len(prompts)}

    @app.post("/prompts")
    def create_or_update_prompt(prompt_data: dict):
        rule_key = prompt_data.get("rule_key")
        description = prompt_data.get("description")
        prompt_template = prompt_data.get("prompt_template")
        category = prompt_data.get("category", "General")

        if not rule_key or not prompt_template:
            return {"error": "rule_key and prompt_template are required"}

        prompts_collection.update_one(
            {"rule_key": rule_key},
            {
                "$set": {
                    "rule_key": rule_key,
                    "description": description,
                    "prompt_template": prompt_template,
                    "category": category,
                    "language": "java",
                    "created_at": datetime.now(),
                    "updated_at": datetime.now(),
                }
            },
            upsert=True,
        )
        return {"status": "Prompt saved", "rule_key": rule_key}

    @app.get("/prompts/{rule_key}")
    def get_prompt(rule_key: str):
        prompt_doc = prompts_collection.find_one({"rule_key": rule_key}, {"_id": 0})
        if prompt_doc:
            return prompt_doc
        return {"error": "Prompt not found"}

    @app.delete("/prompts/{rule_key}")
    def delete_prompt(rule_key: str):
        result = prompts_collection.delete_one({"rule_key": rule_key})
        if result.deleted_count > 0:
            return {"status": "Prompt deleted", "rule_key": rule_key}
        return {"error": "Prompt not found"}

