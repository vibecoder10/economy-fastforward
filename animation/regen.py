"""Regenerate scene prompts."""
import sys
import asyncio
sys.path.insert(0, "/home/clawd/projects/economy-fastforward")

from animation.airtable import AnimationAirtableClient
from animation.scene_planner import ScenePlanner

async def regen_scene(scene_num: int):
    client = AnimationAirtableClient()
    planner = ScenePlanner()
    
    # Get current project
    projects = client.project_table.all(max_records=1)
    if not projects:
        print("No projects found")
        return
    
    project_name = projects[0]["fields"].get("Project Name")
    
    records = client.scenes_table.all(
        formula=f'AND({{Project Name}} = "{project_name}", {{scene_order}} = {scene_num})',
    )
    
    if not records:
        print(f"Scene {scene_num} not found")
        return
    
    scene = {"id": records[0]["id"], **records[0]["fields"]}
    print(f"Found scene {scene_num}")
    
    # Regenerate prompts
    new_start = await planner.generate_start_prompt(scene)
    if new_start:
        client.scenes_table.update(scene["id"], {
            "start_image_prompt": new_start,
            "start prompt done": False,
        })
        print(f"✅ New start prompt generated")
    
    new_end = await planner.generate_end_prompt(scene)
    if new_end:
        client.scenes_table.update(scene["id"], {
            "end_image_prompt": new_end,
            "end prompt done": False,
        })
        print(f"✅ New end prompt generated")
    
    print(f"🔄 Scene {scene_num} prompts regenerated - review and approve in Airtable")

def main():
    if len(sys.argv) < 2:
        print("Usage: python -m animation.regen <scene_num>")
        return
    
    scene_num = int(sys.argv[1])
    asyncio.run(regen_scene(scene_num))

if __name__ == "__main__":
    main()
