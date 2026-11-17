/* SDL2's public stable C ABI is dynamically loaded from the executable's
 * directory. No SDL window/event loop replaces the game's Win32 controls.
 * The positional hint is essential for Nintendo: south must stay PS Cross.
 * ABI references: wiki.libsdl.org/SDL2/SDL_GameControllerButton and
 * SDL_HINT_GAMECONTROLLER_USE_BUTTON_LABELS. */
#include "lajungla_gamepads.h"
#include <string.h>

LjPromptFamily lj_prompt_choose(const char* setting, LjPromptFamily last) {
    if (!setting) return LJ_PROMPT_PLAYSTATION;
    if (!strcmp(setting,"auto")) return last;
    if (!strcmp(setting,"keyboard")) return LJ_PROMPT_KEYBOARD;
    if (!strcmp(setting,"xbox")) return LJ_PROMPT_XBOX;
    if (!strcmp(setting,"nintendo")) return LJ_PROMPT_NINTENDO;
    return LJ_PROMPT_PLAYSTATION;
}

const char* lj_prompt_label(LjPromptFamily family, int action) {
    static const char* ps[] = {"Cross","Circle","Square","Triangle","L1","R1","L2","R2","L3","R3","Start","Select"};
    static const char* xbox[] = {"A","B","X","Y","LB","RB","LT","RT","LS","RS","Menu","View"};
    static const char* nintendo[] = {"B","A","Y","X","L","R","ZL","ZR","LS","RS","+","-"};
    static const char* arrows[] = {"\xE2\x86\x91","\xE2\x86\x93","\xE2\x86\x90","\xE2\x86\x92"};
    if (action >=12 && action <24) return arrows[(action-12)%4];
    if (action<0 || action>=12) return "?";
    return family==LJ_PROMPT_NINTENDO ? nintendo[action] : family==LJ_PROMPT_XBOX ? xbox[action] : ps[action];
}

LjPromptFamily lj_sdl_family(int type) {
    if (type==3 || type==4 || type==7) return LJ_PROMPT_PLAYSTATION;
    if (type==5 || type==11 || type==12 || type==13) return LJ_PROMPT_NINTENDO;
    return LJ_PROMPT_XBOX;
}

uint16_t lj_sdl_button_mask(int button) {
    static const uint16_t masks[] = {0x1000,0x2000,0x4000,0x8000,0x20,0,0x10,0x40,0x80,0x100,0x200,1,2,4,8};
    return button>=0 && button<15 ? masks[button] : 0;
}

void lj_gamepad_sync_ids(int slots[4], const int* ids, int count) {
    int next[4]={-1,-1,-1,-1}, used=0;
    for(int old=0;old<4;++old)
        for(int i=0;i<count;++i)
            if(slots[old]>=0 && slots[old]==ids[i]) { next[used++]=slots[old]; break; }
    for(int i=0;i<count && used<4;++i) {
        int present=ids[i]<0;
        for(int j=0;j<used;++j) if(next[j]==ids[i]) present=1;
        if(!present) next[used++]=ids[i];
    }
    memcpy(slots,next,sizeof(next));
}

#if defined(_WIN32) && !defined(LAJUNGLA_GAMEPAD_PURE_ONLY)
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <wchar.h>
/* SDL2 enum/bool/int and opaque pointers have these exact public ABI widths.
 * SDL_VERSION_ATLEAST is not needed: every required symbol is checked. */
typedef struct SDL_GameController SDL_GameController;
static HMODULE s_sdl;
static int s_attempted, s_owns_init;
static SDL_GameController* s_handles[4];
static int s_ids[4]={-1,-1,-1,-1};
static int (__cdecl *pSDL_InitSubSystem)(uint32_t);
static void (__cdecl *pSDL_QuitSubSystem)(uint32_t);
static int (__cdecl *pSDL_SetHintWithPriority)(const char*,const char*,int);
static int (__cdecl *pSDL_NumJoysticks)(void);
static int (__cdecl *pSDL_IsGameController)(int);
static int (__cdecl *pSDL_JoystickGetDeviceInstanceID)(int);
static SDL_GameController* (__cdecl *pSDL_GameControllerOpen)(int);
static void (__cdecl *pSDL_GameControllerClose)(SDL_GameController*);
static int (__cdecl *pSDL_GameControllerGetAttached)(SDL_GameController*);
static int (__cdecl *pSDL_GameControllerGetType)(SDL_GameController*);
static uint8_t (__cdecl *pSDL_GameControllerGetButton)(SDL_GameController*,int);
static int16_t (__cdecl *pSDL_GameControllerGetAxis)(SDL_GameController*,int);
static void (__cdecl *pSDL_GameControllerUpdate)(void);
static int (__cdecl *pSDL_GameControllerEventState)(int);
static int (__cdecl *pSDL_JoystickEventState)(int);
static int (__cdecl *pSDL_GameControllerRumble)(SDL_GameController*,uint16_t,uint16_t,uint32_t);

static int lj_sdl_init(void) {
    if(s_attempted) return s_sdl!=NULL;
    s_attempted=1;
    wchar_t path[32768];
    DWORD n=GetModuleFileNameW(NULL,path,32768);
    if(!n || n>=32768) return 0;
    wchar_t* slash=wcsrchr(path,L'\\');
    if(!slash || slash-path+10>=32768) return 0;
    memcpy(slash+1,L"SDL2.dll",sizeof(L"SDL2.dll"));
    s_sdl=LoadLibraryExW(path,NULL,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_SYSTEM32);
    if(!s_sdl) { fprintf(stderr,"[cellPad] SDL2.dll unavailable; using XInput fallback\n"); return 0; }
#define LJ_SDL_REQUIRED(name) do { *(FARPROC*)&p##name=GetProcAddress(s_sdl,#name); if(!p##name) goto fail; } while(0)
    LJ_SDL_REQUIRED(SDL_InitSubSystem); LJ_SDL_REQUIRED(SDL_QuitSubSystem);
    LJ_SDL_REQUIRED(SDL_SetHintWithPriority); LJ_SDL_REQUIRED(SDL_NumJoysticks);
    LJ_SDL_REQUIRED(SDL_IsGameController); LJ_SDL_REQUIRED(SDL_JoystickGetDeviceInstanceID);
    LJ_SDL_REQUIRED(SDL_GameControllerOpen); LJ_SDL_REQUIRED(SDL_GameControllerClose);
    LJ_SDL_REQUIRED(SDL_GameControllerGetAttached); LJ_SDL_REQUIRED(SDL_GameControllerGetType);
    LJ_SDL_REQUIRED(SDL_GameControllerGetButton); LJ_SDL_REQUIRED(SDL_GameControllerGetAxis);
    LJ_SDL_REQUIRED(SDL_GameControllerUpdate); LJ_SDL_REQUIRED(SDL_GameControllerEventState);
    LJ_SDL_REQUIRED(SDL_JoystickEventState); LJ_SDL_REQUIRED(SDL_GameControllerRumble);
#undef LJ_SDL_REQUIRED
    /* SDL_HINT_OVERRIDE=2: positional binding is a game invariant, not a label preference. */
    if(!pSDL_SetHintWithPriority("SDL_GAMECONTROLLER_USE_BUTTON_LABELS","0",2)) goto fail;
    pSDL_SetHintWithPriority("SDL_JOYSTICK_HIDAPI","1",1);
    pSDL_SetHintWithPriority("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS","1",1);
    if(pSDL_InitSubSystem(0x2000u)!=0) goto fail; /* SDL_INIT_GAMECONTROLLER */
    s_owns_init=1;
    /* Poll directly. Avoid building an unconsumed SDL input-event queue. */
    pSDL_GameControllerEventState(0);
    pSDL_JoystickEventState(0);
    fprintf(stderr,"[cellPad] SDL2 controller polling ready (keyboard/F1 retained)\n");
    return 1;
fail:
    FreeLibrary(s_sdl); s_sdl=NULL;
    fprintf(stderr,"[cellPad] SDL2 controller initialization failed; using XInput fallback\n");
    return 0;
}

static int16_t invert_axis(int16_t value) { return value==-32768 ? 32767 : (int16_t)-value; }
int lj_gamepads_poll(LjGamepadState out[4]) {
    memset(out,0,4*sizeof(*out));
    if(!lj_sdl_init()) return 0;
    pSDL_GameControllerUpdate();
    int ids[128], indices[128], count=0, total=pSDL_NumJoysticks();
    for(int i=0;i<total && count<128;++i) if(pSDL_IsGameController(i)) {
        int id=pSDL_JoystickGetDeviceInstanceID(i);
        if(id>=0) { ids[count]=id; indices[count++]=i; }
    }
    int next[4]; memcpy(next,s_ids,sizeof(next));
    lj_gamepad_sync_ids(next,ids,count);
    SDL_GameController* handles[4]={0};
    for(int port=0;port<4;++port) {
        if(next[port]<0) continue;
        for(int old=0;old<4;++old) if(s_ids[old]==next[port]) {
            handles[port]=s_handles[old]; s_handles[old]=NULL; break;
        }
        if(!handles[port]) for(int i=0;i<count;++i) if(ids[i]==next[port]) {
            handles[port]=pSDL_GameControllerOpen(indices[i]); break;
        }
    }
    for(int old=0;old<4;++old) if(s_handles[old]) pSDL_GameControllerClose(s_handles[old]);
    memcpy(s_ids,next,sizeof(s_ids)); memcpy(s_handles,handles,sizeof(handles));
    int connected=0;
    for(int port=0;port<4;++port) {
        SDL_GameController* gc=s_handles[port];
        if(!gc || !pSDL_GameControllerGetAttached(gc)) {
            if(gc) pSDL_GameControllerClose(gc);
            s_handles[port]=NULL; s_ids[port]=-1; continue;
        }
        LjGamepadState* state=&out[port]; state->connected=1; state->instance_id=s_ids[port]; ++connected;
        state->family=lj_sdl_family(pSDL_GameControllerGetType(gc));
        for(int button=0;button<15;++button)
            if(pSDL_GameControllerGetButton(gc,button)) state->buttons|=lj_sdl_button_mask(button);
        state->lx=pSDL_GameControllerGetAxis(gc,0); state->ly=invert_axis(pSDL_GameControllerGetAxis(gc,1));
        state->rx=pSDL_GameControllerGetAxis(gc,2); state->ry=invert_axis(pSDL_GameControllerGetAxis(gc,3));
        int lt=pSDL_GameControllerGetAxis(gc,4),rt=pSDL_GameControllerGetAxis(gc,5);
        state->lt=(uint8_t)(lt>0 ? lt*255/32767 : 0); state->rt=(uint8_t)(rt>0 ? rt*255/32767 : 0);
    }
    /* One backend owns all physical snapshots. Never also poll XInput for
     * an SDL-reported device (SDL already deduplicates its HID/XInput drivers). */
    return connected!=0;
}
int lj_gamepads_rumble(unsigned port,uint16_t low,uint16_t high) {
    if(port>=4 || !s_handles[port] || !s_sdl) return 0;
    pSDL_GameControllerRumble(s_handles[port],low,high,100); return 1;
}
void lj_gamepads_shutdown(void) {
    if(!s_sdl) return;
    for(int i=0;i<4;++i) { if(s_handles[i]) pSDL_GameControllerClose(s_handles[i]); s_handles[i]=NULL; s_ids[i]=-1; }
    if(s_owns_init) pSDL_QuitSubSystem(0x2000u);
    FreeLibrary(s_sdl); s_sdl=NULL; s_owns_init=0; s_attempted=0;
}
#else
int lj_gamepads_poll(LjGamepadState out[4]) { memset(out,0,4*sizeof(*out)); return 0; }
int lj_gamepads_rumble(unsigned port,uint16_t low,uint16_t high) { (void)port;(void)low;(void)high;return 0; }
void lj_gamepads_shutdown(void) {}
#endif
