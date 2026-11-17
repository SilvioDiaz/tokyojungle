// Original-game trophy HLE and optional game-only SDK bridge. Author: matymeatboy.
#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
// Call before guest boot. Catalog is privately extracted catalog.bin; state_directory
// is separate from mounted game content, normally <save_root>/trophies.
int lajungla_trophies_configure(const char* catalog, const char* state_directory);
void lajungla_trophies_register(void); // after ppu_hle_register_all()
void lajungla_trophies_frame(void);    // once per presented frame (SDK maintenance)
void lajungla_trophies_save_loaded(void); // every successful save load, not save writes
void lajungla_trophies_casual(const char* reason); // cheats/debug/save states
void lajungla_trophies_shutdown(void);
typedef void (*lajungla_trophy_notify_fn)(uint32_t id, const char* name, const char* description);
void lajungla_trophies_set_notify(lajungla_trophy_notify_fn notify);
typedef struct lajungla_trophy_view {
    uint32_t id, grade, hidden, unlocked;
    uint64_t timestamp;
    char name[128], description[1024], icon[128];
} lajungla_trophy_view;
// Read-only host view: 13 records, 0 if unconfigured, -1 on invalid state/buffer.
// Hidden locked records have no identifying text or icon. Never emits events.
// Committed state is cached before guest registration; live state is used after.
int lajungla_trophies_snapshot(lajungla_trophy_view* records, uint32_t capacity);
// Isolated viewer diagnostic: catalog/state only, no SDK or guest initialization.
int lajungla_trophies_configure_view(const char* catalog, const char* state_directory);
#ifdef __cplusplus
}
#endif
