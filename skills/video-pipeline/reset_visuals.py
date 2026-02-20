import os
from dotenv import load_dotenv
from pyairtable import Table
from pyairtable.formulas import match

def reset_visuals(video_title):
    print(f"🗑️ RESETTING VISUALS FOR: {video_title}")
    
    # Load env
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '.env'))
    api_key = os.getenv("AIRTABLE_API_KEY")
    base_id = os.getenv("AIRTABLE_BASE_ID")
    
    if not api_key or not base_id:
        print("❌ Missing Airtable credentials")
        return

    # Connect to Images table
    # ID from SKILL.md: tbl3luJ0zsWu0MYYz
    # But usually we use the name or ID. Let's trust .env if possible, but strict ID is safer.
    # checking airtable_client.py, it uses os.getenv("AIRTABLE_TABLE_IMAGES") or "Images"
    # let's try to load the client logic or just use the Table directly
    
    table = Table(api_key, base_id, "Images")
    
    # Find all records for this video
    print("🔍 Searching for records...")
    records = table.all(formula=match({"Video Title": video_title}))
    print(f"Found {len(records)} records.")
    
    if not records:
        print("✅ No records to delete.")
        return

    # Delete in batches
    ids = [r["id"] for r in records]
    print(f"🔥 Deleting {len(ids)} records...")
    
    batch_size = 10
    for i in range(0, len(ids), batch_size):
        batch = ids[i:i+batch_size]
        table.batch_delete(batch)
        print(f"   Deleted batch {i}-{i+len(batch)}")
        
    print("✅ Visuals reset complete!")

if __name__ == "__main__":
    title = "The 2030 Currency Collapse: Which Assets Will YOU Still Own?"
    reset_visuals(title)
