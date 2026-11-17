# Community input, content and stability improvements

Author: matymeatboy. Based on SilvioDiaz/tokyojungle `bbb6f1a`.

This contribution keeps Tokyo Jungle Recompiled and its original launcher. It
adds independent changes rather than replacing the runtime with Drakengard 3's.
See [the source comparison](DRK3_PORTING_REVIEW.md) for features already present,
transfer candidates and changes that need their own game-specific validation.

## Installation and DLC

The launcher's **Install game / DLC** action accepts your own North American
base PKG and DLC PKGs plus a folder containing your RAP files. The first package
installation needs the base PKG too, even if you previously used the extracted
folder workflow. Subsequent additions can contain only new DLC.

The preparation tool authenticates each supported EDAT against a supplied RAP,
uses RPCS3 offline for decryption, verifies the exact supported base ELF, and
publishes a separate `content/mounted` tree only after preparation succeeds.
Original installed package files stay under `content/packages`. Existing
`engine/savedata` is not replaced. Source packages, licenses, generated code,
private trophy names/icons and save data must never be committed or distributed.

The tool requires the Python dependencies from `requirements.txt`. RPCS3 can be
selected with `-Rpcs3`, `TJ_RPCS3`, or `[paths] rpcs3=` in `launcher.ini`.
The command-line equivalent is:

```powershell
.\tools\content\tj_prepare_content.ps1 -Root $PWD `
  -Packages C:\MyDumps\Base.pkg,C:\MyDumps\DLC.pkg `
  -Licenses C:\MyDumps\licenses -Rpcs3 C:\Emulators\RPCS3\rpcs3.exe
```

Only the supported NPUA80523 1.00 executable is accepted. An update PKG with
different game code is deliberately rejected: code from another version must
be recompiled and its hooks verified. This does not claim support for 1.01.

## Controls and language

PlayStation is the default prompt family. Xbox, Nintendo, keyboard and automatic
selection are available. Family selection changes presentation; physical south,
east, west and north positions remain consistent. SDL2 handles recognized
gamepads, connection changes and rumble; XInput remains the Windows fallback.
The SDL runtime is pinned and verified before bundling. Existing key rebinding
remains available. Physical controller models still need device testing.

The launcher selects English, Spanish, French or Portuguese resources already
present in the supported dump. Restart the game after changing language.
Desktop shortcut and Steam actions are explicit buttons; the Steam action opens
the non-Steam-game dialog instead of editing Steam's shortcut database.

## Saves and trophies

See [save transactions](SAVEDATA-TRANSACTIONS.md) for staging, recovery, explicit
deletion, locking and the tested error cases. A failed callback must preserve
the previously committed generation; recovery must not resurrect an intentional
deletion. Recovery data stays outside the game's slot list.

The game extracts its original 13-trophy catalog locally. Gold trophy ID 0 is
preserved; there is no platinum. Unlocks come from original game calls and are
stored atomically. The launcher has a read-only viewer. The optional
RecompAchievements SDK is linked into the game only, under its own license;
the launcher uses an independently licensed JSON reader. Native definitions and
IDs are provided to RecompLauncher, and stored unlocks are not emitted as new
live events. Original trophy texts/icons are not part of this repository.

New unlocks also show a [classic PS3-style in-game popup](TROPHY-POPUP.md), with
the locally extracted badge, translated message and trophy grade. Preview mode
is isolated from game progress; the launcher's quiet-toast flag prevents duplicate
native notifications.

The [in-game trophy browser](TROPHY-MENU.md) opens with F3 or controller tab
navigation. It shows colored grade cups for unlocked trophies and gray cups for
locked ones, with separate original badges, progress and read-only details.

## Build and verification limits

Cached ELF input is checked even when decryption or compilation is skipped.
Runtime preparation recognizes only the pinned base and exact ordered patch
prefixes; it refuses unrelated modifications rather than resetting or cleaning
the checkout. The generation pipeline recovers the final import trampoline and
preserves the runtime bridge and function table.

Synthetic and native component tests cover content transactions, malformed
inputs, original trophy ABI, controller mapping and save failures. Local native
boot has opened all 20 supplied DLC EDATs and reached the title screen at a
2560x1440 render target. That is not a complete playthrough, a performance gain,
or proof that every DLC animal and mode is playable. Story mode, long sessions,
local co-op, physical gamepads and a suitable external save remain separate
validation items. No eligible public external save was obtained; the search
limits are recorded in the source-comparison document.
