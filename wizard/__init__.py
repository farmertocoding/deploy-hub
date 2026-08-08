"""wizard: scan report + human answers -> a frozen deployment manifest.

§D4 AMENDMENT (2026-08-09). The pinned app layout had no home for this code, and both
obvious candidates are wrong:

  * deploys/ would have to import scanner -> violates ARCH-V6-DEPLOYS-NO-SCANNER-IMPORT
    directly.
  * core/ is worse. core is the shared kernel every app imports, so `core -> scanner`
    makes `deploys -> core -> scanner` true transitively. The V6 grep test only looked
    for direct imports, so the gate would have stayed green while the invariant it
    exists to protect was gone. (Found in the 2026-08-09 design debate; the test now
    walks the import graph.)

So: wizard/ imports scanner, writes deploys.Manifest, and deploys/ imports neither.
The dependency arrow points one way only:

    scanner  <--  wizard  -->  deploys  (manifest rows)
"""
