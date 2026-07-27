# Lessons Learned

## 2026-07-27: git stash is shared across worktrees

`git stash` is shared across ALL worktrees of a repo. It is NOT per-worktree.

On 2026-07-27 two workers ran in separate worktrees at the same time. One did a stash/pop cycle and accidentally pulled the other worker's uncommitted work into its own tree. It was caught and restored, but it could have destroyed work silently.

The rule from now on: when parallel workers share a repo, never use `git stash`. To prove a fix (the "stash-proof"), use `git diff > /tmp/patch && git checkout -- <explicit paths>` and then reapply, or better, prove it on a scratch branch or with a test that fails before and passes after. Also always commit by explicit path, never `git add -A`.
