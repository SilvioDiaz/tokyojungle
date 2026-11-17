# Classic in-game trophy notification

Original implementation by matymeatboy, MIT. The gray translucent plaque,
left-hand trophy badge and two-line message follow the user's classic PS3
notification reference. No Sony firmware font, sound, icon or notification
asset is distributed. The badge is read locally from the user's trophy catalog.

The notification is composed into the game's D3D12 backbuffer. It is not a
desktop notification or a separate overlay window. At 720p its logical size is
384x96, with proportional placement/scaling at 1440p and other output sizes.
The message is localized and the small cup reflects the actual trophy grade.
Events queue in order, fade in/out and remain visible for approximately five
seconds. Long titles use an ellipsis.

Only the existing successful, persisted original-game unlock callback enqueues
normal notifications. Loading saved unlocks does not replay them. The existing
RecompAchievements quiet-toast flag suppresses the native callback when the
launcher supplies its notification. This does not change trophy IDs or state.

Composition uses bounded PNG decoding through Windows Imaging Component. Missing
or corrupt badges fall back to an original procedural cup. GPU resources are
separate for each backbuffer and used only after the existing checked fence
drain. They are released after shutdown retirement. Guest display history is
copied before the notification; diagnostic backbuffer capture includes it.
Resource creation failure skips the notification and preserves the game frame.

`--trophy-popup-preview <catalog.bin> <synthetic-frame.tjrsx>` exercises the same
GPU composition path through the renderer-only diagnostic. It returns before
game/trophy/SDK initialization, never unlocks a trophy and does not write save
data. Preview badges/names remain private local data. Synthetic fixtures and
captures used during verification are not included as game content.

Validation: native queue/timing/bounds/Unicode/premultiplied-alpha tests; valid,
missing, corrupt and oversized PNG cases; backend compilation with the callback
enabled and disabled; shader diagnostics and actual GPU readback at 1280x720 and
2560x1440. The GPU preview uses no original guest instructions.

Research references: [RPCS3's overlay implementation](https://github.com/RPCS3/rpcs3/blob/master/rpcs3/Emu/RSX/Overlays/overlay_trophy_notification.cpp)
and [Finally Decky Achievements](https://github.com/otisabiburada/finally-decky-achievements).
RPCS3 uses GPL and the Decky plugin targets a different frontend. Their source
and assets are not incorporated; the native compositor extends this port's
existing MIT overlay mechanism.
