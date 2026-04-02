#!/usr/bin/env python3
"""
Import SonarQube prompts from Excel file to MongoDB database
"""
import pandas as pd
from pymongo import MongoClient
from datetime import datetime
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def import_excel_to_database():
    """Import prompts from Java_SONAR_Prompts.xlsx to MongoDB"""

    print("📊 Importing SonarQube Prompts from Excel to Database")
    print("=" * 60)

    try:
        # Connect to MongoDB
        mongo_client = MongoClient(os.getenv("MONGO_URI"))
        db = mongo_client[os.getenv("DB_NAME")]
        prompts_collection = db["prompts"]

        # Excel file path
        excel_file = "Java_SONAR_Prompts.xlsx"
        print(f"Reading Excel file: {excel_file}")

        # Read Excel file
        df = pd.read_excel(excel_file, engine='openpyxl')
        print(f"✅ Successfully read Excel file with {len(df)} rows")
        print(f"Columns found: {list(df.columns)}")

        # Display first few rows to understand structure
        print("\n📋 First 3 rows preview:")
        print(df.head(3))

        imported_count = 0
        skipped_count = 0

        # Process each row
        for index, row in df.iterrows():
            try:
                # Extract data from Excel row
                # Adjust column names based on actual Excel file structure
                rule_key = str(row.get("Rule ID", row.get("rule_key", row.get("Rule", "")))).strip()
                description = str(row.get("Description", row.get("Issue Description", ""))).strip()
                prompt_template = str(row.get("Prompt Template", row.get("Prompt", ""))).strip()

                # Skip if essential fields are missing
                if not rule_key or not prompt_template:
                    print(f"⚠️  Skipping row {index + 1}: Missing rule_key or prompt_template")
                    print(f"   Rule: '{rule_key}', Prompt length: {len(prompt_template)}")
                    skipped_count += 1
                    continue

                # Create prompt document
                prompt_doc = {
                    "rule_key": rule_key,
                    "description": description,
                    "prompt_template": prompt_template,
                    "category": str(row.get("Category", row.get("Type", "General"))).strip(),
                    "severity": str(row.get("Severity", row.get("Priority", ""))).strip(),
                    "language": "java",
                    "tags": str(row.get("Tags", "")).strip().split(",") if row.get("Tags") else [],
                    "created_at": datetime.now(),
                    "updated_at": datetime.now(),
                    "source": "excel_import"
                }

                # Insert/Update in database
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
                print(f"❌ Error processing row {index + 1}: {str(e)}")
                skipped_count += 1

        # Summary
        print(f"\n📈 Import Summary:")
        print(f"✅ Successfully imported: {imported_count}")
        print(f"⚠️  Skipped: {skipped_count}")
        print(f"📊 Total prompts in database: {prompts_collection.count_documents({})}")

        # Show sample of imported prompts
        print(f"\n🔍 Sample prompts in database:")
        sample_prompts = list(prompts_collection.find(
            {"source": "excel_import"},
            {"_id": 0, "rule_key": 1, "description": 1, "category": 1}
        ).limit(5))

        if sample_prompts:
            for prompt in sample_prompts:
                print(f"  - {prompt['rule_key']} ({prompt.get('category', 'General')}): {prompt['description'][:60]}...")
        else:
            print("  No prompts found with source 'excel_import'")

        return True

    except FileNotFoundError:
        print(f"❌ Error: Excel file '{excel_file}' not found in current directory")
        print("Make sure the file is in the ai-agent folder")
        return False

    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Make sure pandas and openpyxl are installed:")
        print("pip install pandas openpyxl")
        return False

    except Exception as e:
        print(f"❌ Unexpected error: {str(e)}")
        return False

def validate_excel_structure():
    """Check if Excel file has expected structure"""
    try:
        excel_file = "Java_SONAR_Prompts.xlsx"
        df = pd.read_excel(excel_file, engine='openpyxl')

        print("📋 Excel File Structure Analysis:")
        print(f"Total rows: {len(df)}")
        print(f"Columns: {list(df.columns)}")

        # Check for essential columns
        essential_cols = ["Rule ID", "rule_key", "Rule"]
        has_rule_col = any(col in df.columns for col in essential_cols)

        essential_cols = ["Prompt Template", "Prompt"]
        has_prompt_col = any(col in df.columns for col in essential_cols)

        print(f"Has Rule column: {'✅' if has_rule_col else '❌'}")
        print(f"Has Prompt column: {'✅' if has_prompt_col else '❌'}")

        if has_rule_col and has_prompt_col:
            print("✅ Excel structure looks good for import")
            return True
        else:
            print("❌ Excel missing essential columns. Expected:")
            print("  - Rule ID/rule_key/Rule")
            print("  - Prompt Template/Prompt")
            return False

    except Exception as e:
        print(f"❌ Cannot validate Excel structure: {e}")
        return False

def test_database_connection():
    """Test MongoDB connection"""
    try:
        mongo_client = MongoClient(os.getenv("MONGO_URI"))
        db = mongo_client[os.getenv("DB_NAME")]

        # Test connection
        db.command('ping')
        print("✅ MongoDB connection successful")

        # Check existing collections
        collections = db.list_collection_names()
        print(f"📁 Existing collections: {collections}")

        return True
    except Exception as e:
        print(f"❌ MongoDB connection failed: {str(e)}")
        return False

def main():
    """Main import function"""
    print("🚀 SonarQube Prompts Excel Import Tool")
    print("=" * 50)

    # Step 1: Test database connection
    if not test_database_connection():
        print("❌ Cannot proceed without database connection")
        return False

    # Step 2: Validate Excel structure
    if not validate_excel_structure():
        print("❌ Cannot proceed with invalid Excel structure")
        return False

    # Step 3: Import data
    print("\n" + "=" * 50)
    success = import_excel_to_database()

    if success:
        print("\n🎉 Excel import completed successfully!")
        print("You can now test the /fixes endpoint with rule-specific prompts from your Excel file.")
    else:
        print("\n❌ Excel import failed. Check the errors above.")

    return success

if __name__ == "__main__":
    main()