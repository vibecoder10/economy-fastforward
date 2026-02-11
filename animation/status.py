"""Show scene approval status."""
import sys
sys.path.insert(0, "/home/clawd/projects/economy-fastforward")

from animation.airtable import AnimationAirtableClient

def main():
    client = AnimationAirtableClient()
    
    # Get current project
    projects = client.project_table.all(max_records=1)
    if not projects:
        print("No projects found")
        return
    
    project_name = projects[0]["fields"].get("Project Name", "Unknown")
    print(f"📋 Scene Status: {project_name}\n")
    
    records = client.scenes_table.all(
        formula=f'{{Project Name}} = "{project_name}"',
        sort=["scene_order"],
    )
    
    pending_start = []
    pending_end = []
    ready = []
    
    for r in records:
        f = r["fields"]
        scene = f.get("scene_order", "?")
        start_ok = f.get("start prompt done", False)
        end_ok = f.get("end prompt done", False)
        has_start_img = bool(f.get("start_image"))
        has_end_img = bool(f.get("end_image"))
        
        if not start_ok:
            pending_start.append(scene)
        elif not end_ok and not has_end_img:
            pending_end.append(scene)
        elif start_ok and (end_ok or has_end_img):
            ready.append(scene)
    
    if pending_start:
        print(f"⏸️ Awaiting START prompt approval: {pending_start}")
    if pending_end:
        print(f"⏸️ Awaiting END prompt approval: {pending_end}")
    if ready:
        print(f"✅ Ready for image generation: {ready}")
    if not pending_start and not pending_end:
        print("✅ All prompts approved!")

if __name__ == "__main__":
    main()
