# In-game trophy browser

Original implementation by matymeatboy, MIT.

Open **F3** for the read-only trophy page in the existing in-game overlay. F1
continues to open Controls and F2 keeps the optional Options page. On a
controller, open the overlay with Back+Start and use the shoulder buttons
(L1/R1 or LB/RB) to change tabs. Use the directional buttons to select a trophy;
Circle/B or Escape closes the overlay. Gameplay input remains neutral while the
overlay is open and until the closing buttons have been released.
The overlay does not automatically pause the original simulation. During a run,
use the game's own pause first, then open the trophy page; the page includes this
reminder. It can also be browsed from the title screen.

The 13 original trophies keep their grades: 1 gold, 3 silver, 9 bronze, no
platinum. The **cup symbol** appears in its category color after unlocking and
gray while locked. The original game-specific badge is shown separately in the
details panel, also desaturated while locked. Secret locked trophies hide their
name, description and artwork. The page shows progress, the selected condition
and the unlock date where available. There are no unlock, reset or edit actions.

The browser takes a host snapshot under the existing trophy mutex. Before guest
registration it caches a private read of committed state; it does not consume
the original first-load signal or emit an SDK event. After registration it reads
live in-memory unlocks. Missing metadata and corrupt progress display explicit
unavailable/read-error messages rather than fabricated progress. Artwork is
decoded only on selection/unlock changes, with bounded files and image sizes.

Runtime page registration is optional and generic. Other titles that do not
register a page retain their existing F1/F2 behavior and can still bind F3.
The new page reuses the existing GPU overlay resources and input routing.

`--trophy-menu-preview <catalog.bin> <synthetic-frame.tjrsx>` opens a renderer-only
preview. `LAJUNGLA_TROPHY_DIR` can point to an isolated synthetic state for visual
tests. This path does not initialize trophy guest handlers or the achievements
SDK, and never writes progress. The synthetic three-unlock preview used to
verify gold/silver/bronze pixels is not evidence of real game unlocks.

Verified with native snapshot, UI, navigation and badge tests; actual GPU
readback at 2560x1440 confirms gold, silver, bronze and gray cup pixels. Real
save/trophy file hashes remain unchanged across preview. The source comparison
and broader gameplay limits in COMMUNITY-IMPROVEMENTS.md still apply.
