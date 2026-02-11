"""Approve scene prompts."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from animation.airtable import AnimationAirtableClient

def main():
    client = AnimationAirtableClient()
    
    # Get current project
    projects = client.project_table.all(max_records=1)
    if not projects:
        print("No projects found")
        return
    
    project_name = projects[0]["fields"].get("Project Name")
    
    if len(sys.argv) < 2:
        print("Usage: python -m animation.approve <scene_num|all>")
        return
    
    arg = sys.argv[1]
    
    if arg == "all":
        records = client.scenes_table.all(
            formula=f'{{Project Name}} = "{project_name}"',
        )
        count = 0
        for r in records:
            client.scenes_table.update(r["id"], {
                "start prompt done": True,
                "end prompt done": True,
            })
            count += 1
        print(f"✅ Approved all prompts for {count} scenes")
    else:
        scene_num = int(arg)
        records = client.scenes_table.all(
            formula=f'AND({{Project Name}} = "{project_name}", {{scene_order}} = {scene_num})',
        )
        if not records:
            print(f"Scene {scene_num} not found")
            return
        
        client.scenes_table.update(records[0]["id"], {
            "start prompt done": True,
            "end prompt done": True,
        })
        print(f"✅ Scene {scene_num} prompts approved")

if __name__ == "__main__":
    main()
