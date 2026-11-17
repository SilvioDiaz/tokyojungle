"""Native fixture exercises positional mappings, family choice, and hotplug IDs."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def test_gamepad_families_and_hotplug():
    source = r'''
#include "lajungla_gamepads.h"
#include <assert.h>
#include <string.h>
int main(void) {
    assert(lj_prompt_choose(NULL, LJ_PROMPT_KEYBOARD) == LJ_PROMPT_PLAYSTATION);
    assert(lj_prompt_choose("auto", LJ_PROMPT_NINTENDO) == LJ_PROMPT_NINTENDO);
    assert(lj_prompt_choose("keyboard", LJ_PROMPT_XBOX) == LJ_PROMPT_KEYBOARD);
    assert(lj_prompt_choose("bad", LJ_PROMPT_XBOX) == LJ_PROMPT_PLAYSTATION);
    const char *ps[] = {"Cross", "Circle", "Square", "Triangle"};
    const char *xbox[] = {"A", "B", "X", "Y"};
    const char *nintendo[] = {"B", "A", "Y", "X"};
    for (int i=0; i<4; ++i) {
        assert(!strcmp(lj_prompt_label(LJ_PROMPT_PLAYSTATION,i),ps[i]));
        assert(!strcmp(lj_prompt_label(LJ_PROMPT_XBOX,i),xbox[i]));
        assert(!strcmp(lj_prompt_label(LJ_PROMPT_NINTENDO,i),nintendo[i]));
    }
    assert(lj_sdl_button_mask(0) == 0x1000); /* south -> Cross */
    assert(lj_sdl_button_mask(1) == 0x2000); /* east -> Circle */
    assert(lj_sdl_button_mask(2) == 0x4000); /* west -> Square */
    assert(lj_sdl_button_mask(3) == 0x8000); /* north -> Triangle */
    assert(lj_sdl_button_mask(5) == 0); /* Guide is never a guest button */
    assert(lj_sdl_family(3) == LJ_PROMPT_PLAYSTATION); /* PS3 */
    assert(lj_sdl_family(4) == LJ_PROMPT_PLAYSTATION); /* PS4 */
    assert(lj_sdl_family(7) == LJ_PROMPT_PLAYSTATION); /* PS5 */
    assert(lj_sdl_family(5) == LJ_PROMPT_NINTENDO);
    int slots[4] = {-1,-1,-1,-1};
    int connect[] = {41,73}; lj_gamepad_sync_ids(slots,connect,2);
    assert(slots[0]==41 && slots[1]==73 && slots[2]==-1);
    int reordered[] = {73,41}; lj_gamepad_sync_ids(slots,reordered,2);
    assert(slots[0]==41 && slots[1]==73); /* indices are not identities */
    int remove[] = {73}; lj_gamepad_sync_ids(slots,remove,1);
    assert(slots[0]==73 && slots[1]==-1); /* player one reconnect */
    int duplicates[] = {73,73,99}; lj_gamepad_sync_ids(slots,duplicates,3);
    assert(slots[0]==73 && slots[1]==99 && slots[2]==-1);
    lj_gamepad_sync_ids(slots,NULL,0);
    assert(slots[0]==-1 && slots[1]==-1);
    return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='lj-gamepad-test-') as directory:
        test = Path(directory) / 'test.c'
        exe = Path(directory) / 'test.exe'
        test.write_text(source)
        subprocess.run(['C:/Program Files/LLVM/bin/clang.exe', '-std=c11',
                        '-DLAJUNGLA_GAMEPAD_PURE_ONLY', '-I', str(ROOT/'src'),
                        str(test), str(ROOT/'src/lajungla_gamepads.c'), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)

def test_dynamic_sdl_hotplug_and_snapshot():
    # Fake public SDL ABI allows deterministic lifecycle/input tests without
    # touching physical controllers or depending on SDL2.dll being installed.
    fake = r'''
#include <stdint.h>
#include <string.h>
#define API __declspec(dllexport)
static int mode=1, closed=0;
API void FakeMode(int value) { mode=value; }
API int FakeClosed(void) { return closed; }
API int SDL_InitSubSystem(uint32_t flags) { return flags==0x2000 ? 0:-1; }
API void SDL_QuitSubSystem(uint32_t flags) { (void)flags; }
API int SDL_SetHintWithPriority(const char* name,const char* value,int priority) {
 if(!strcmp(name,"SDL_GAMECONTROLLER_USE_BUTTON_LABELS")) return !strcmp(value,"0")&&priority==2;
 return 1;
}
API int SDL_NumJoysticks(void) { return mode==0?0:1; }
API int SDL_IsGameController(int index) { return index==0; }
API int SDL_JoystickGetDeviceInstanceID(int index) { (void)index;return mode==2?73:41; }
API void* SDL_GameControllerOpen(int index) { (void)index;return (void*)(uintptr_t)(mode==2?73:41); }
API void SDL_GameControllerClose(void* gc) { (void)gc;++closed; }
API int SDL_GameControllerGetAttached(void* gc) { (void)gc;return mode!=0; }
API int SDL_GameControllerGetType(void* gc) { return (uintptr_t)gc==73?7:5; }
API uint8_t SDL_GameControllerGetButton(void* gc,int button) { (void)gc;return button==0; }
API int16_t SDL_GameControllerGetAxis(void* gc,int axis) { (void)gc;return axis==1?-32768:axis==4?32767:0; }
API void SDL_GameControllerUpdate(void) {}
API int SDL_GameControllerEventState(int state) { return state; }
API int SDL_JoystickEventState(int state) { return state; }
API int SDL_GameControllerRumble(void* gc,uint16_t low,uint16_t high,uint32_t ms) { (void)gc;(void)low;(void)high;return ms==100?0:-1; }
'''
    app = r'''
#include <windows.h>
#include "lajungla_gamepads.h"
#include <assert.h>
int main(void) {
 HMODULE dll=LoadLibraryA("SDL2.dll");assert(dll);
 void(*mode)(int)=(void(*)(int))GetProcAddress(dll,"FakeMode");
 int(*closed)(void)=(int(*)(void))GetProcAddress(dll,"FakeClosed");
 LjGamepadState pads[4];
 assert(lj_gamepads_poll(pads)==1);
 assert(pads[0].connected && !pads[1].connected);
 assert(pads[0].family==LJ_PROMPT_NINTENDO && pads[0].buttons==0x1000);
 assert(pads[0].lt==255 && pads[0].rt==0 && pads[0].ly==32767);
 assert(lj_gamepads_rumble(0,100,100)==1);
 mode(0); assert(lj_gamepads_poll(pads)==0);
 assert(!pads[0].connected && closed()==1);
 mode(2); assert(lj_gamepads_poll(pads)==1);
 assert(pads[0].family==LJ_PROMPT_PLAYSTATION && !pads[1].connected);
 lj_gamepads_shutdown(); assert(closed()==2);
 FreeLibrary(dll); return 0;
}
'''
    compiler = 'C:/Program Files/LLVM/bin/clang.exe'
    with tempfile.TemporaryDirectory(prefix='lj-sdl-abi-') as directory:
        directory = Path(directory)
        (directory/'fake.c').write_text(fake)
        (directory/'test.c').write_text(app)
        subprocess.run([compiler,'-shared',str(directory/'fake.c'),'-o',str(directory/'SDL2.dll')],check=True)
        subprocess.run([compiler,'-std=c11','-D_CRT_SECURE_NO_WARNINGS','-I',str(ROOT/'src'),
                        str(directory/'test.c'),str(ROOT/'src/lajungla_gamepads.c'),
                        '-o',str(directory/'test.exe')],check=True)
        subprocess.run([str(directory/'test.exe')],cwd=directory,check=True)


def test_controller_prompt_rendering_uses_family_labels():
    source = r'''
#include "pad_prompt_art.h"
#include <assert.h>
#include <string.h>
int main(void) {
 int keys[24]={-2}; PadPromptLabels xbox,nintendo,keyboard;
 pad_prompt_labels_from_vks(&xbox,keys);
 keys[0]=-3;pad_prompt_labels_from_vks(&nintendo,keys);
 keys[0]=0x20;pad_prompt_labels_from_vks(&keyboard,keys);
 assert(!strcmp(xbox.full[0],"A") && !strcmp(nintendo.full[0],"B"));
 assert(!strcmp(nintendo.full[1],"A") && !strcmp(nintendo.full[2],"Y") && !strcmp(nintendo.full[3],"X"));
 assert(!strcmp(xbox.full[4],"LB") && !strcmp(nintendo.full[6],"ZL"));
 assert(!strcmp(keyboard.full[0],"Space"));
 unsigned char a[48*48*4],b[48*48*4],k[48*48*4];
 PadPromptArtSpec spec={PAD_PROMPT_STYLE_KEY,PAD_PROMPT_CROSS,0,0};
 assert(pad_prompt_art_render(&spec,&xbox,48,48,a)==0);
 assert(pad_prompt_art_render(&spec,&nintendo,48,48,b)==0);
 assert(pad_prompt_art_render(&spec,&keyboard,48,48,k)==0);
 assert(memcmp(a,b,sizeof(a)) && memcmp(a,k,sizeof(a)));
 int covered=0;
 for(int i=0;i<48*48;++i) covered+=a[i*4+3]!=0;
 assert(covered>100 && covered<48*48); /* actual transparent glyph sprite */
 return 0;
}
'''
    runtime = Path(os.environ.get('PS3RECOMP_DIR', ROOT.parent/'ps3recomp'))
    with tempfile.TemporaryDirectory(prefix='lj-prompt-art-') as directory:
        directory=Path(directory)
        (directory/'test.c').write_text(source)
        subprocess.run(['C:/Program Files/LLVM/bin/clang.exe','-std=c11','-D_CRT_SECURE_NO_WARNINGS',
                        '-DPS3RECOMP_PROMPT_ART','-DLAJUNGLA_GAMEPAD_PURE_ONLY',
                        '-I',str(ROOT/'src'),'-I',str(runtime/'libs/input'),str(directory/'test.c'),
                        str(runtime/'libs/input/pad_prompt_art.c'),str(ROOT/'src/lajungla_gamepads.c'),
                        '-lgdi32','-o',str(directory/'test.exe')],check=True)
        subprocess.run([str(directory/'test.exe')],check=True)
