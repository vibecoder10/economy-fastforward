# Deferred verification — reference-lookup fix

- [ ] Deploy: code fix reaches prod only after Ryan runs `scripts/se.sh deploy` (push to
      main does NOT restart the backend). Recipe: `se deploy` from the Mac, then
      `se health`. Cross-ref: checklist C3.
- [ ] Post-deploy live proof: re-run `images(fc73860c-a9af-444f-95a5-7f86d60503e0, scene=8)`
      (XB-35, ~$0.03, quote→confirm) and visually verify the render is a FLYING WING.
      Expected: image-to-image from a real XB-35 photo; asset prompt carries "[ref: ...]".
- [ ] Fail-closed proof on prod: attempt images for a machine with no reference anywhere
      (or temporarily empty cache row) → scene must persist status='blocked_no_reference'
      and NO image generated / no spend.
