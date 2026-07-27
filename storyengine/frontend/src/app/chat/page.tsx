import { DirectorProvider } from "@/components/director/DirectorContext";
import { DirectorSurface } from "@/components/director/DirectorSurface";

export default function ChatPage() {
  // Same treatment as app/page.tsx (DIRECTOR-CHAT-PLAN.md Task 1.3 Step 4,
  // full-bleed fix 2026-07-27) — see that file's comment for the history.
  // `h-full w-full` (not `fixed inset-0`): AuthenticatedShell recognizes
  // `/chat` as a "full bleed" route and gives it an unpadded `flex-1 min-h-0`
  // box next to the sidebar, so this fills that box while the sidebar and
  // its Collapse control keep working.
  return (
    <div className="h-full w-full bg-void">
      <DirectorProvider>
        <DirectorSurface />
      </DirectorProvider>
    </div>
  );
}
