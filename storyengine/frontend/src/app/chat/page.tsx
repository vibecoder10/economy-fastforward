import { DirectorProvider } from "@/components/director/DirectorContext";
import { DirectorSurface } from "@/components/director/DirectorSurface";

export default function ChatPage() {
  // Same treatment as app/page.tsx (DIRECTOR-CHAT-PLAN.md Task 1.3 Step 4) —
  // see that file's comment for why `fixed inset-0` is needed to escape
  // AuthenticatedShell's padded, non-height-bound content box.
  return (
    <div className="fixed inset-0 z-50 bg-void">
      <DirectorProvider>
        <DirectorSurface />
      </DirectorProvider>
    </div>
  );
}
