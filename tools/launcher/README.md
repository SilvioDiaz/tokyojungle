# Native launcher additions

Community additions by matymeatboy, retaining Tokyo Jungle's name and existing
port credits. The launcher remains Windows-native.

- The game-language selector persists `[language] locale=es/en/fr/pt` in
  `launcher.ini` (Spanish initially) and sets `LAJUNGLA_LANGUAGE` for the
  game's system-language helper. This does not translate the launcher itself.
- Controller symbols use the existing `[controls] prompt_family` contract.
  The combo and asynchronous content-install controls are created in the
  settings window alongside their handlers.
- Create desktop shortcut uses Known Folders and IShellLink with the absolute
  launcher executable, `-play`, its working directory and executable icon.
  It writes a temporary file, then moves without replacing an existing link.
- Add to Steam opens `steam://AddNonSteamGame` and explains Browse, confirm
  and `-play`. The user completes Steam's own dialog. No `shortcuts.vdf`
  edits, automatic account selection or library-overwrite claims.
  [Steam's documented manual flow](https://help.steampowered.com/en/faqs/view/4B8B-9697-2338-40EC)
  is the fallback when the URI dialog does not appear. No Steam GUI was opened
  during verification.
- Trophies opens a read-only local viewer. Catalog:
  `<paths/game>/.lajungla/trophies/<locale>/catalog.json`; state:
  `<engine>/savedata/trophies/NPWR01344_00.json`. Hidden locked names and
  descriptions are obscured. Existing corrupt state errors rather than
  fabricating progress; absent state means a new profile. The viewer never
  writes unlocks and contains no RecompAchievements SDK or APIs.

The viewer uses unmodified MIT cJSON v1.7.19 from
[DaveGamble/cJSON revision c859b25da02955fef659d658b8f324b5cde87be3](https://github.com/DaveGamble/cJSON/tree/c859b25da02955fef659d658b8f324b5cde87be3).
Its license is retained in `third_party/cjson/LICENSE`. No original-game
catalog, icon or save data is committed.

Build the launcher with `launcher.c`, `trophy_view.c` and
`third_party/cjson/cJSON.c`; link user32, gdi32, comdlg32, shell32, ole32,
uuid and comctl32. Define `CJSON_HIDE_SYMBOLS` for cJSON. Existing resource
branding and the game's engine build remain separate.

`TokyoJungle.exe --self-test` performs language mapping, in-memory COM
shortcut property checks and synthetic trophy JSON checks without UI, saves
or desktop writes. Trophy fixtures cover 13 unique IDs, hidden-state masking,
duplicate/out-of-range unlocks, invalid timestamps, corrupt JSON, duplicate
keys, wrong communication IDs and unchanged output after a failed parse.

`TokyoJungle.exe --check-settings "C:\Recomp Library\tokyojungle\launcher.ini"`
reads and prints resolved settings without launching the game or writing the
INI. Validation on 17 November 2026: /W4 compilation clean; self-test exit 0;
destination INI resolved to Spanish, PlayStation, 1440p and windowed.
