#!/usr/bin/env python3
import pandas as pd
import json
from pymongo import MongoClient
from datetime import datetime
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def import_excel_prompts():
    """Import prompts from Java_SONAR_Prompts.xlsx to MongoDB"""

    print("📊 Importing Sonar Prompts from Excel to Database")
    print("=" * 60)

    try:
        # Connect to MongoDB
        mongo_client = MongoClient(os.getenv("MONGO_URI"))
        db = mongo_client[os.getenv("DB_NAME")]
        prompts_collection = db["prompts"]

        # Read Excel file
        excel_file = "Java_SONAR_Prompts.xlsx"
        print(f"Reading {excel_file}...")

        df = pd.read_excel(excel_file)
        print(f"✅ Found {len(df)} rows in Excel file")

        # Display columns found
        print(f"Columns: {list(df.columns)}")

        imported_count = 0
        skipped_count = 0

        # Import each row
        for index, row in df.iterrows():
            try:
                # Assuming Excel has these columns (adjust based on actual file)
                rule_key = str(row.get("Rule ID", row.get("rule_key", ""))).strip()
                description = str(row.get("Description", row.get("description", ""))).strip()
                prompt_template = str(row.get("Prompt Template", row.get("prompt_template", ""))).strip()

                if not rule_key or not prompt_template:
                    print(f"⚠️  Skipping row {index + 1}: Missing rule_key or prompt_template")
                    skipped_count += 1
                    continue

                # Create prompt document
                prompt_doc = {
                    "rule_key": rule_key,
                    "description": description,
                    "prompt_template": prompt_template,
                    "category": str(row.get("Category", "General")).strip(),
                    "severity": str(row.get("Severity", "")).strip(),
                    "language": "java",  # Assuming Java prompts
                    "created_at": datetime.now(),
                    "updated_at": datetime.now()
                }

                # Save to database
                result = prompts_collection.update_one(
                    {"rule_key": rule_key},
                    {"$set": prompt_doc},
                    upsert=True
                )

                if result.upserted_id or result.modified_count > 0:
                    imported_count += 1
                    print(f"✅ Imported: {rule_key}")
                else:
                    print(f"ℹ️  No changes: {rule_key}")

            except Exception as e:
                print(f"❌ Error importing row {index + 1}: {str(e)}")
                skipped_count += 1

        print(f"\n📈 Import Summary:")
        print(f"✅ Successfully imported: {imported_count}")
        print(f"⚠️  Skipped: {skipped_count}")
        print(f"📊 Total prompts in database: {prompts_collection.count_documents({})}")

        # Show sample prompts
        print(f"\n🔍 Sample prompts in database:")
        sample_prompts = list(prompts_collection.find({}, {"_id": 0, "rule_key": 1, "description": 1}).limit(3))
        for prompt in sample_prompts:
            print(f"  - {prompt['rule_key']}: {prompt['description'][:50]}...")

    except FileNotFoundError:
        print(f"❌ Error: {excel_file} not found in current directory")
        print("Make sure the Excel file is in the ai-agent folder")
    except Exception as e:
        print(f"❌ Import failed: {str(e)}")

def create_sample_prompts():
    """Create sample prompts if Excel import fails"""
    print("\n🔧 Creating sample prompts for testing...")

    mongo_client = MongoClient(os.getenv("MONGO_URI"))
    db = mongo_client[os.getenv("DB_NAME")]
    prompts_collection = db["prompts"]

    sample_prompts = [
        {
            "rule_key": "java:S106",
            "description": "System.out.println should be replaced with logger",
            "prompt_template": """You are a senior Java developer. Replace System.out.println with SLF4J logger.

Issue: {message}
File: {file}
Line: {line}

Provide a structured fix with:
1. Required imports
2. Logger declaration
3. Code replacements

Format as JSON:
{{
  "imports": ["import org.slf4j.Logger;", "import org.slf4j.LoggerFactory;"],
  "logger_declaration": "private static final Logger logger = LoggerFactory.getLogger(ClassName.class);",
  "replacements": [
    {{
      "old_code": "System.out.println(\\"message\\");",
      "new_code": "logger.info(\\"message\\");"
    }}
  ]
}}""",
            "category": "Logging",
            "language": "java"
        },
        {
            "rule_key": "java:S120",
            "description": "Package name doesn't match regex",
            "prompt_template": """Fix Java package naming convention violation.

Issue: {message}
File: {file}
Line: {line}

The package name should follow: ^[a-z_]+(\\.[a-z_][a-z0-9_]*)*$

Provide the fix as JSON:
{{
  "problem": "Package name contains uppercase letters",
  "solution": "Convert to lowercase",
  "code_changes": [
    {{
      "file": "{file}",
      "old_code": "package current.package.name;",
      "new_code": "package corrected.package.name;",
      "line": {line}
    }}
  ],
  "directory_rename": "OldName/ → newname/"
}}""",
            "category": "Naming",
            "language": "java"
        }
    ]

    for prompt in sample_prompts:
        prompt["created_at"] = datetime.now()
        prompt["updated_at"] = datetime.now()

        prompts_collection.update_one(
            {"rule_key": prompt["rule_key"]},
            {"$set": prompt},
            upsert=True
        )

    print(f"✅ Created {len(sample_prompts)} sample prompts")

def test_database_connection():
    """Test MongoDB connection"""
    try:
        mongo_client = MongoClient(os.getenv("MONGO_URI"))
        db = mongo_client[os.getenv("DB_NAME")]

        # Test connection
        db.command('ping')
        print("✅ MongoDB connection successful")

        # Check collections
        collections = db.list_collection_names()
        print(f"📁 Collections: {collections}")

        return True
    except Exception as e:
        print(f"❌ MongoDB connection failed: {str(e)}")
        return False

if __name__ == "__main__":
    # Test database connection first
    if not test_database_connection():
        exit(1)

    # Try to import from Excel
    try:
        import_excel_prompts()
    except Exception as e:
        print(f"❌ Excel import failed: {str(e)}")
        print("Falling back to sample prompts...")
        create_sample_prompts()

    print("\n🎉 Prompt import process completed!")
    print("You can now test the /fixes endpoint with database-driven prompts.")