# Deferred verification — Anton DvsU launch-feedback refinement

Nothing is being treated as silently skipped. These checks require Ryan’s later approval because they spend money or change production.

- [ ] Paid three-view proof on one aircraft.
  - Proof reached now: local tests and a synthetic render prove the data, timing, overlay, and motion contract without external generation.
  - Later recipe: after deployment, open Anton’s DvsU video, choose one already researched aircraft, request **Redraw** in Pictures, review the displayed quote, then explicitly confirm. Expect 2–3 approved views grouped under that aircraft: three-quarter identification, elevated/top-oblique, and a detail view. A run with fewer than two approved views must stay incomplete.
  - Cross-reference: checklist C1, C3, C4.

- [ ] Production render and Anton visual review.
  - Proof reached now: a short local synthetic MP4 is rendered and frame-inspected for card content, multi-view rotation, and smooth full-duration motion.
  - Later recipe: deploy the reviewed branch with `storyengine/scripts/se.sh deploy anton-dvsu-feedback --with-frontend`, verify `http://localhost:8001/api/health` through the normal deployment smoke path, then render the regenerated one-aircraft proof. Expect one animated title card per aircraft, 2–3 rotating views, alternating slow push-in/pull-out moves, and no visible jump, lateral wander, freeze, or wobble. Do not upload to YouTube.
  - Cross-reference: checklist C2, C3, C4.
