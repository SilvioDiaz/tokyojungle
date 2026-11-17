#ifndef LAJUNGLA_GAMEPADS_H
#define LAJUNGLA_GAMEPADS_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef enum LjPromptFamily {
    LJ_PROMPT_PLAYSTATION = 0, LJ_PROMPT_KEYBOARD = 1,
    LJ_PROMPT_XBOX = 2, LJ_PROMPT_NINTENDO = 3
} LjPromptFamily;
LjPromptFamily lj_prompt_choose(const char* setting, LjPromptFamily last);
const char* lj_prompt_label(LjPromptFamily family, int action);
LjPromptFamily lj_sdl_family(int type);
uint16_t lj_sdl_button_mask(int button);
void lj_gamepad_sync_ids(int slots[4], const int* ids, int count);
/* XInput-compatible positional snapshot, without requiring an SDL SDK. */
typedef struct LjGamepadState {
    int connected;
    int instance_id;
    LjPromptFamily family;
    uint16_t buttons;
    uint8_t lt, rt;
    int16_t lx, ly, rx, ry;
} LjGamepadState;
int lj_gamepads_poll(LjGamepadState out[4]);
int lj_gamepads_rumble(unsigned port, uint16_t low, uint16_t high);
void lj_gamepads_shutdown(void);
#ifdef __cplusplus
}
#endif
#endif
