# D3 Director Chat Surface and Spend Fixes

Last done: Live drive of prod video 686b4651 in Ryan's Chrome (2026-07-28) confirmed two new defects and filed them: D3-45 (chat cards crushed by flex-shrink, root cause measured: cards render 50/30/30/30px vs scrollHeights 122/58/227/182) and D3-46 (right-rail media thumbnails have no click handler). D3-39/D3-40 did NOT reproduce on this video - still open, seen on 67a87d3c. Ryan gave the timeline-unpacking vision, filed as D3-47.

Next chunk: D3-45 and D3-46 dispatched in parallel (own worktrees, dev ports 3000/3001), D3-47 recon dispatched read-only. After those land: D3-39/D3-40 on video 67a87d3c, then D3-32..34.
